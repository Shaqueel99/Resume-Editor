"""prompts.py

System prompts for the Résumé ATS Optimizer.

LLM calls:
  1. JD_SKILLS_PROMPT         — extracts required/preferred skills from a
                                 JD. Used to drive a deterministic,
                                 rule-based ATS score (see scoring.py),
                                 computed before and after edits with zero
                                 LLM involvement — the score is never
                                 self-graded by the model that wrote the
                                 rewrites.
  2. SKILL_GAPS_PROMPT        — lists JD-required/preferred skills (incl.
                                 soft skills) the résumé doesn't evidence.
  3. BULLET_REWRITES_PROMPT   — finds verbatim-anchored bullet rewrite
                                 opportunities that surface the JD's own
                                 terminology.
  4. REGENERATE_BULLET_PROMPT — regenerates a single bullet on request,
                                 honoring specific user feedback, for the
                                 follow-up refinement step.

SKILL_GAPS_PROMPT and BULLET_REWRITES_PROMPT used to be one combined
ASSISTANT_PROMPT call. Split into two focused calls (app.py merges their
results into the same {"skill_gaps": [...], "bullet_rewrites": [...]}
shape the rest of the app expects) because asking one call to reason
about two different things AND produce one large nested JSON object at
once made a smaller/cheaper model's output both less reliable (more
prone to stopping mid-JSON) and shallower (generic "why_it_matters"
text, bullet rewrites dropped entirely) — trimming the combined prompt's
wording made the reliability problem worse in the other direction, not
better. Two smaller, single-purpose prompts fix both: each can be as
detailed as the task needs without competing for the model's attention
or output budget with the other task.

All prompts follow ICCO structure (Instruction -> Context -> Constraints
-> Output). No placeholders — dynamic content (résumé text, JD text,
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

SKILL_GAPS_PROMPT = """\
INSTRUCTION
Compare a candidate's résumé against a job description and list every \
skill or competency the JD requires or prefers that the résumé does \
not evidence anywhere — technical (a technology, tool, language, or \
framework) and soft/interpersonal (e.g. teamwork, communication, \
problem-solving) alike — as a single JSON object matching the schema \
below.

CONTEXT
You will receive résumé text and JD text as JSON with keys "resume_text" \
and "jd_text". JDs often state soft skills as a full sentence rather \
than a named term (e.g. "Excellent communication and collaboration \
skills") — condense each distinct competency named in that sentence to \
a short standard term (e.g. "Communication", "Collaboration"), one \
entry per competency, the same way you would a technical requirement. \
It is common, and expected, for a résumé that has already been through \
a prior optimization pass to have few gaps left, or none at all.

CONSTRAINTS
- List a skill only where the JD explicitly requires or prefers it, AND \
the résumé text does not evidence it anywhere — including after \
considering implied phrasing (e.g. a bullet that clearly describes an \
automated build/test/release pipeline evidences "CI/CD" even without \
using that exact term). If the résumé evidences it, do not list it.
- "skill" must be a short noun phrase (1-4 words): the JD's own term \
for a technical skill, or a condensed standard name for a soft skill.
- "why_it_matters" must be specific to THIS résumé and THIS JD — name \
what the JD requires and briefly confirm why it's genuinely absent \
from the résumé's actual content, not a generic restatement of the \
skill name that would read the same for any résumé.
- If there are no genuine gaps, return an empty array — that is a \
correct result, not an incomplete one.

OUTPUT
Return a JSON object with exactly this schema:
{
  "skill_gaps": [
    {
      "skill": string,
      "why_it_matters": string
    }
  ]
}

Output ONLY a valid JSON object matching the schema above. No prose. No \
markdown fences. No commentary.\
"""

BULLET_REWRITES_PROMPT = """\
INSTRUCTION
You analyse a candidate's résumé against a job description, looking \
specifically for bullets where the candidate's wording describes \
something the JD asks for using DIFFERENT words than the JD itself \
uses. For each such bullet, and ONLY for such bullets, you suggest a \
rewrite that surfaces the JD's own terminology. On most résumés, \
especially ones that have already been through a prior optimization \
pass, this will apply to few bullets or none at all — that is the \
expected, normal outcome, not a failure. Return any genuine rewrite \
opportunities as a single JSON object matching the schema below.

CONTEXT
You will receive résumé text and JD text as JSON with keys "resume_text" \
and "jd_text". This tool's value is narrow and specific: it is NOT a \
general résumé-improvement tool, and it does not rewrite bullets for \
tone, concision, or persuasiveness. Its only job is terminology \
alignment — finding a genuine wording mismatch between what the résumé \
says and what the JD calls the same thing. The résumé you receive may \
already be the product of a previous round of edits, so most or all of \
its bullets may already use the JD's terminology, or may simply have no \
connection to any missing JD term at all. Producing a rewrite for a \
bullet that has no real, defensible connection to a missing JD term — \
just to have an answer — is a worse outcome than returning no \
suggestion for that bullet.

CONSTRAINTS
- Before suggesting a rewrite for a bullet, ask: "does this bullet's \
CURRENT wording already contain the JD term I would be surfacing, or \
does the bullet have NO genuine, defensible connection to any missing \
JD term?" In either case, do not suggest a rewrite for that bullet.
- A genuine connection means the bullet already describes the same \
underlying action, tool, or concept the JD term refers to — not merely a \
loose thematic association. "Deployment workflows" does not genuinely \
imply "CI/CD" unless the bullet actually describes an automated \
build/test/release pipeline. When in doubt, do not suggest — a missed \
opportunity costs nothing; a fabricated connection damages the \
candidate's credibility if they use it.
- Only suggest a rewrite for a bullet if doing so causes at least one \
specific JD required or preferred term (or a very close variant) to \
newly appear in the bullet's text, where it was genuinely implied but \
not literally present before.
- Once a bullet qualifies for a rewrite, surface EVERY missing JD term \
it genuinely, defensibly implies — not just the first one you find. A \
bullet already describing work with a specific database, for example, \
also genuinely implies querying it; if the JD separately lists both the \
database technology and something like "SQL queries" as missing terms, \
a rewrite that names the database but leaves the querying term out is \
an incomplete rewrite. Apply the same genuine-connection test from the \
constraint above to each additional term individually — stack terms \
that each pass it on their own, never one to justify another.
- "original_text" must be copied VERBATIM from the résumé text, \
character-for-character — it is used as a find-and-replace anchor.
- "suggested_text" must preserve the same underlying claim, technology, \
and outcome as the original. Do not invent metrics, technologies, \
architectural claims (e.g. microservices, distributed systems, CI/CD \
pipelines), or outcomes not stated or clearly implied in the original.
- "reason" must name every specific JD term the rewrite newly surfaces \
(there may be more than one), and briefly state what in the original \
bullet already implies each.
- It is common and expected for "bullet_rewrites" to be an empty array, \
including when the résumé has already been through a prior edit round. \
Returning an empty array when no genuine opportunity exists is a correct \
result, not an incomplete one.

OUTPUT
Return a JSON object with exactly this schema:
{
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