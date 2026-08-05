"""scoring.py

Deterministic, rule-based ATS keyword scoring.

This is intentionally NOT an LLM call. The required/preferred skills list
comes from an LLM extraction (JD_SKILLS_PROMPT in prompts.py), but the
score itself is computed here with plain substring matching, so the
same LLM that suggests bullet rewrites can never be the one grading
whether those rewrites "worked." The before/after score comparison is
only meaningful if scoring is independent of generation.
"""


def compute_ats_score(resume_text: str, required_skills: list[str], preferred_skills: list[str] | None = None) -> dict:
    """Score résumé text against a JD's required/preferred skill lists.

    Args:
        resume_text: Full plain text of the résumé (from the .docx).
        required_skills: Skills the JD_SKILLS_PROMPT marked as required.
        preferred_skills: Skills the JD_SKILLS_PROMPT marked as preferred.
            Optional — included in the report but not the score itself.

    Returns:
        A dict with the score (0-100) and which skills were found/missing,
        so the UI can show exactly what changed between two calls.
    """
    preferred_skills = preferred_skills or []
    resume_lower = resume_text.lower()

    found_required = [s for s in required_skills if s.lower() in resume_lower]
    missing_required = [s for s in required_skills if s.lower() not in resume_lower]

    found_preferred = [s for s in preferred_skills if s.lower() in resume_lower]
    missing_preferred = [s for s in preferred_skills if s.lower() not in resume_lower]

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