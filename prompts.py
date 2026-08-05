"""prompts.py

System prompts for the Résumé ATS Optimizer.

Three LLM calls:
  1. JD_SKILLS_PROMPT        — extracts required/preferred skills from a
                                JD. Used to drive a deterministic,
                                rule-based ATS score (see scoring.py),
                                computed before and after edits with zero
                                LLM involvement — the score is never
                                self-graded by the model that wrote the
                                rewrites.
  2. ASSISTANT_PROMPT         — generates skill gap commentary and
                                verbatim-anchored bullet rewrite
                                suggestions, in one JSON response.
  3. REGENERATE_BULLET_PROMPT — regenerates a single bullet on request,
                                honoring specific user feedback, for the
                                follow-up refinement step.

All three follow ICCO structure (Instruction -> Context -> Constraints ->
Output). No placeholders — dynamic content (résumé text, JD text,
feedback) is passed as the user message in llm.py's ask_json().
"""

# ---------------------------------------------------------------------------
# EXTRACTION (temperature 0.0-0.1)
# ---------------------------------------------------------------------------

JD_SKILLS_PROMPT = """\
INSTRUCTION
You extract a flat list of required and preferred skills, tools, and \
qualifications from a job description's plain text, for use in a \
downstream keyword-matching score. Return them as a single JSON object \
matching the schema below.

CONTEXT
You will receive the full text of a job description. Job descriptions \
typically separate "must-have" or "required" qualifications from \
"nice-to-have" or "preferred" ones, though the exact wording varies by \
company. Your output will be used to check, by exact and near-exact text \
matching, whether each skill literally appears in a résumé — so each \
entry must be a short, specific term, not a sentence. This applies \
equally to technical skills (a technology, tool, language, or named \
qualification) and to soft/interpersonal skills (e.g. problem-solving, \
teamwork, communication) — JDs routinely state the latter as a full \
sentence ("Strong problem-solving skills and ability to work \
effectively in a team-oriented environment"), and that sentence must \
still be condensed down to short terms rather than dropped, since a \
soft skill the JD explicitly requires is exactly as real a requirement \
as a named technology.

CONSTRAINTS
- Only extract skills, tools, qualifications, and soft/interpersonal \
competencies that are literally stated in the JD text. Never invent, \
infer, or add ones that are not mentioned.
- Each entry must be a short noun phrase (1-4 words) naming one specific \
skill, tool, language, framework, or competency — e.g. "React.js", \
"AWS RDS", "Spring Boot", "MySQL", "Problem-solving", "Teamwork", \
"Communication". Do not return full sentences or bullet-length phrases.
- For technical skills, preserve the JD's own terminology; do not \
substitute synonyms or expand abbreviations. For soft/interpersonal \
skills, the JD's phrasing is usually a full sentence rather than a term \
— condense it to the standard short name(s) for the competency it \
describes (e.g. "ability to work effectively in a team-oriented \
environment" -> "Teamwork", "excellent communication and collaboration \
skills" -> "Communication" and "Collaboration"). If one JD sentence \
names more than one distinct competency, extract each as its own entry \
rather than combining them into one.
- Classify a skill as "required" only if the JD's own language marks it \
as mandatory (e.g. "must have", "required", listed under a \
"Requirements" heading). Classify as "preferred" if the JD marks it as \
optional or desirable (e.g. "nice to have", "bonus", "a plus", \
"familiarity with").
- If the JD does not clearly distinguish required vs. preferred for a \
given skill, use your best judgment from context, but do not invent \
qualifications that are not mentioned anywhere.
- Deduplicate entries. Do not list the same skill twice, including \
near-duplicates (e.g. "JS" and "JavaScript" — pick the JD's own wording \
once; "Teamwork" mentioned twice in different sections — list it once).
- If either array would be empty, return an empty array [] rather than \
omitting the field or guessing content.

OUTPUT
Return a JSON object with exactly this schema:
{
  "required_skills": [string],
  "preferred_skills": [string]
}

Output ONLY a valid JSON object matching the schema above. No prose. No \
markdown fences. No commentary.\
"""

# ---------------------------------------------------------------------------
# GENERATION (temperature 0.3-0.5)
# ---------------------------------------------------------------------------

ASSISTANT_PROMPT = """\
INSTRUCTION
From the given résumé and JD text, do two things: (1) for bullets that \
already say something the JD asks for but in different words, suggest \
a rewrite surfacing the JD's own term — only for genuine matches; \
(2) list every required/preferred skill or competency, technical or \
soft, that the résumé doesn't evidence, as skill gaps. Empty or \
near-empty results are normal and expected, not a failure. Return one \
JSON object per the schema below.

CONTEXT
Input is JSON: {"resume_text", "jd_text"}. Scope is narrow: \
terminology alignment only, never rewriting for tone or style, and \
never inventing a connection just to produce an answer — an \
already-edited résumé may genuinely have few or no rewrites left.

CONSTRAINTS
- Rewrite a bullet ONLY if it does NOT already contain the JD term, AND \
it has a genuine, defensible connection to that term — describes the \
same real action/tool/concept, not just a loose thematic link (e.g. \
"deployment workflows" ≠ "CI/CD" unless an actual build/test/release \
pipeline is described). Skip it when in doubt.
- The rewrite must cause at least one specific missing required/\
preferred JD term to newly, genuinely appear. Once a bullet qualifies, \
also surface any OTHER missing term it independently, genuinely \
implies — never stack a term that fails the connection test on its own.
- "original_text": copied VERBATIM, character-for-character (used as a \
find/replace anchor).
- "suggested_text": same underlying claim, technology, and outcome as \
the original — no invented metrics, technologies, or claims.
- "reason": name every term the rewrite surfaces and briefly state what \
implies each.
- "bullet_rewrites": [] is a common, correct result.
- "skill_gaps": every required/preferred skill — technical or soft \
(teamwork, communication, etc.) — not evidenced in the résumé, even by \
implication. Condense a soft-skill JD sentence to a short "skill" name \
(e.g. "Teamwork"); one entry per distinct competency.

OUTPUT
Return a JSON object with exactly this schema:
{
  "skill_gaps": [
    {
      "skill": string,
      "why_it_matters": string
    }
  ],
  "bullet_rewrites": [
    {
      "original_text": string,
      "suggested_text": string,
      "reason": string
    }
  ]
}

Output ONLY a valid JSON object matching the schema above. No prose. No \
markdown fences. No commentary.\
"""

REGENERATE_BULLET_PROMPT = """\
INSTRUCTION
You are given one résumé bullet, the job description it is being \
tailored against, and a short piece of user feedback describing how they \
want it changed. You produce exactly one new version of that bullet, \
honoring the feedback, and return it as a single JSON object.

CONTEXT
You will receive a JSON user message with three fields: "original_text" \
(the current version of the bullet, which may already be a rewrite from \
a previous turn, not necessarily the résumé's original wording), \
"jd_text" (the job description), and "feedback" (the user's instruction, \
e.g. "make it more concise", "lead with the impact instead", "remove the \
tool name, I don't want to claim that one"). The user has already seen a \
previous version and is asking for a different one — this is a \
refinement turn, not a first draft.

CONSTRAINTS
- The new version must preserve the same underlying claim as \
"original_text" — do not invent metrics, technologies, tools, \
architectural claims (e.g. microservices, distributed systems), or \
outcomes that were not stated or clearly implied in the original bullet.
- Follow the user's feedback as the primary instruction for HOW to \
change the bullet. If the feedback conflicts with the no-invention rule \
above (e.g. asks you to add a metric or technology that was never \
there), follow the no-invention rule and note the conflict in "note" \
instead of complying.
- Keep the bullet to a single line, in the same general style as a \
résumé bullet (action-oriented, no first-person pronouns).
- "reason" must state in 20 words or fewer what changed and why, from \
the user's own feedback (e.g. "shortened per feedback, kept the same \
tools and outcome").
- "note" should be an empty string in the normal case. Only populate it \
per the constraint above.

OUTPUT
Return a JSON object with exactly this schema:
{
  "new_text": string,
  "reason": string,
  "note": string
}

Output ONLY a valid JSON object matching the schema above. No prose. No \
markdown fences. No commentary.\
"""

DRAFT_NEW_BULLET_PROMPT = """\
INSTRUCTION
You are given a skill gap identified between a résumé and a job \
description, and the candidate's own account of relevant experience \
they have but had not included on their résumé. You phrase their account \
into a single, well-formed résumé bullet, and return it as a JSON object.

CONTEXT
You will receive a JSON user message with three fields: "skill" (the gap \
identified), "jd_text" (the job description), and "candidate_input" (the \
candidate's own plain-language description of relevant experience they \
have). The candidate_input is the ONLY source of factual content for the \
new bullet — you are a phrasing assistant, not a source of facts.

CONSTRAINTS
- Every technology, tool, action, and outcome in the new bullet must \
come directly from "candidate_input". Do not add any fact, number, \
technology, or outcome that the candidate did not state.
- If "candidate_input" is too vague or short to support a concrete \
bullet (e.g. just "yes" or "a little"), do not invent detail to fill the \
gap — instead return an empty "new_bullet" and explain in "note" that \
more detail is needed, naming what kind of detail would help (e.g. what \
they built, what tool, what outcome).
- Phrase the bullet in the same action-verb-led style as a typical \
résumé bullet. No first-person pronouns.
- "note" should be an empty string in the normal case; only populate it \
per the constraint above.

OUTPUT
Return a JSON object with exactly this schema:
{
  "new_bullet": string,
  "note": string
}

Output ONLY a valid JSON object matching the schema above. No prose. No \
markdown fences. No commentary.\
"""