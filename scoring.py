"""scoring.py

Deterministic, rule-based ATS keyword scoring.

This is intentionally NOT an LLM call. The required/preferred skills list
comes from an LLM extraction (JD_SKILLS_PROMPT in prompts.py), but the
score itself is computed here with plain substring matching, so the
same LLM that suggests bullet rewrites can never be the one grading
whether those rewrites "worked." The before/after score comparison is
only meaningful if scoring is independent of generation.

Matching is done on normalized text (see _normalize) rather than raw
substrings, so minor wording variants like "React.js" vs "React" still
match — without needing an LLM judgment call in the scoring path itself.
"""

import re


def _normalize(text: str) -> str:
    """Lowercase, turn punctuation into spaces, strip standalone "js"
    tokens, and strip trailing version digits from words (e.g. "html5"
    -> "html", "css3" -> "css") — so "HTML5"/"HTML" and "CSS3"/"CSS"
    both normalize to the same token, alongside the existing
    "React.js"/"React" handling.
    """
    s = text.lower().strip()
    s = re.sub(r'[^\w\s]', ' ', s)        # punctuation -> space
    s = re.sub(r'\bjs\b', '', s)           # strip standalone "js" token
    s = re.sub(r'([a-z]+)\d+\b', r'\1', s)  # "html5" -> "html", "css3" -> "css"
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def compute_ats_score(resume_text: str, required_skills: list[str], preferred_skills: list[str] | None = None) -> dict:
    """Score résumé text against a JD's required/preferred skill lists.

    Args:
        resume_text: Full plain text of the résumé (from the .docx).
        required_skills: Skills the JD_SKILLS_PROMPT marked as required.
        preferred_skills: Skills the JD_SKILLS_PROMPT marked as preferred.
            Optional — included in the report but not the score itself.

    Returns:
        A dict with the score (0-100) and which skills were found/missing,
        so the UI can show exactly what changed between two calls. Found/
        missing lists report the ORIGINAL skill strings (not normalized),
        so the UI still shows the JD's own wording to the user.
    """
    preferred_skills = preferred_skills or []
    resume_normalized = _normalize(resume_text)

    def _is_present(skill: str) -> bool:
        return _normalize(skill) in resume_normalized

    found_required = [s for s in required_skills if _is_present(s)]
    missing_required = [s for s in required_skills if not _is_present(s)]

    found_preferred = [s for s in preferred_skills if _is_present(s)]
    missing_preferred = [s for s in preferred_skills if not _is_present(s)]

    score = (
        round(100 * len(found_required) / len(required_skills))
        if required_skills
        else 100
    )

    return {
        "score": score,
        "found_required": found_required,
        "missing_required": missing_required,
        "found_preferred": found_preferred,
        "missing_preferred": missing_preferred,
    }