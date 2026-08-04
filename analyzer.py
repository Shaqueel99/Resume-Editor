"""analyzer.py

Orchestrates the résumé-analysis pipeline: calls extraction and evaluation
functions in sequence, each via llm.ask_json() or llm.ask_text(), and
computes a final weighted score.
"""
import json
import sys
from llm import ask_json, ask_text
from prompts import (
    DEGREE_ALIGNMENT_PROMPT,
    RESUME_PROFILE_PROMPT,
    JD_PROFILE_PROMPT,
    KEYWORD_MATCH_PROMPT,
    BULLET_QUALITY_PROMPT,
    JARGON_AUDIT_PROMPT,
    STRUCTURE_AUDIT_PROMPT,
    BACKGROUND_FIT_PROMPT,
    OVERALL_SUMMARY_PROMPT,
)

# Bullet quality is scored 1-3 by BULLET_QUALITY_PROMPT; normalize to 0-100
# so it's on the same scale as the other three component scores before
# weighting in compute_overall_score.
BULLET_SCALE_MIN = 1
BULLET_SCALE_MAX = 3


def analyse_degree_alignment(jd_profile: dict, degree_program: str) -> dict:
    """JD profile + degree -> degree alignment dict."""
    user = (
        f"DEGREE PROGRAM: {degree_program}\n\n"
        f"JD PROFILE:\n{json.dumps(jd_profile, indent=2)}"
    )
    return ask_json(DEGREE_ALIGNMENT_PROMPT, user, max_tokens=600)


def extract_resume_profile(resume_text: str) -> dict:
    """Extract structured candidate info from résumé text.

    Uses RESUME_PROFILE_PROMPT as the system prompt (extraction,
    temperature 0.0-0.1) and the raw résumé text as the user message.
    """
    return ask_json(
        RESUME_PROFILE_PROMPT,
        resume_text,
        temperature=0.0,
        max_tokens=2000,
    )


def extract_jd_profile(jd_text: str) -> dict:
    """Extract structured role requirements from JD text.

    Uses JD_PROFILE_PROMPT as the system prompt (extraction,
    temperature 0.0-0.1) and the raw JD text as the user message.
    """
    return ask_json(
        JD_PROFILE_PROMPT,
        jd_text,
        temperature=0.0,
        max_tokens=1000,
    )


def analyse_keyword_match(resume_profile: dict, jd_profile: dict) -> dict:
    """Compare résumé profile keywords against JD profile keywords.

    Uses KEYWORD_MATCH_PROMPT as the system prompt (evaluation,
    temperature 0.2-0.3). Both profiles are serialised into the user
    message as JSON so the model can compare them directly.
    """
    user_message = json.dumps({
        "resume_profile": resume_profile,
        "jd_profile": jd_profile,
    })
    return ask_json(
        KEYWORD_MATCH_PROMPT,
        user_message,
        temperature=0.2,
        max_tokens=4000,
    )

def analyse_structure(resume_text: str) -> dict:
    """Assess ATS-parseability and structural conventions.

    Uses STRUCTURE_AUDIT_PROMPT as the system prompt (evaluation,
    temperature 0.2-0.3). Takes the raw résumé text directly (not the
    parsed profile), per the function signature.
    """
    return ask_json(
        STRUCTURE_AUDIT_PROMPT,
        resume_text,
        temperature=0.2,
        max_tokens=1000,
    )

def analyse_bullets(resume_profile: dict) -> dict:
    return ask_json(
        BULLET_QUALITY_PROMPT,
        json.dumps(resume_profile),
        temperature=0.2,
        max_tokens=2500,
    )

def analyse_jargon(resume_profile: dict, jd_profile: dict) -> dict:
    user_message = json.dumps({
        "resume_profile": resume_profile,
        "jd_profile": jd_profile,
    })
    return ask_json(
        JARGON_AUDIT_PROMPT,
        user_message,
        temperature=0.2,
        max_tokens=1500,
    )

def analyse_background_fit(resume_profile: dict, jd_profile: dict) -> dict:
    user_message = json.dumps({
        "resume_profile": resume_profile,
        "jd_profile": jd_profile,
    })
    return ask_json(
        BACKGROUND_FIT_PROMPT,
        user_message,
        temperature=0.2,
        max_tokens=1000,
    )


def summarise_overall(report: dict) -> str:
    """Write a three-bullet executive summary of the full report.

    Uses OVERALL_SUMMARY_PROMPT as the system prompt (synthesis,
    temperature 0.3-0.6) and ask_text() since the output is plain
    Markdown, not JSON.
    """
    return ask_text(
        OVERALL_SUMMARY_PROMPT,
        str(report),
        temperature=0.4,
        max_tokens=400,
    )

def _normalize_to_100(value, label: str) -> float:
    """
    Best-effort guard against a component score arriving on the wrong scale.
    Assumes all scores should be 0-100. If a value looks like it's still on
    a 1-3 rubric scale (i.e. <= 3), scale it up. Otherwise clamp to [0, 100].

    This is a safety net, not a substitute for fixing the source prompt —
    it can misfire if a score legitimately belongs in the 0-3 range for
    some other reason, so the print below makes every correction visible.
    """
    if value is None:
        print(f"WARNING: {label} is None, treating as 0", file=sys.stderr)
        return 0.0

    if 0 <= value <= 3:
        scaled = value / 3 * 100
        print(
            f"WARNING: {label}={value!r} looks like a 1-3 scale value; "
            f"normalizing to {scaled!r}",
            file=sys.stderr,
        )
        return scaled

    return max(0.0, min(100.0, float(value)))

def compute_overall_score(report: dict) -> int:
    keyword_score = _normalize_to_100(report["keyword_match"]["keyword_match_score"], "keyword_score")
    bullet_score = _normalize_to_100(report["bullets"]["bullet_quality_avg"], "bullet_score")
    structure_score = _normalize_to_100(report["structure"]["structure_score"], "structure_score")
    jargon_score = _normalize_to_100(report["jargon"]["jargon_score"], "jargon_score")
    degree_score = _normalize_to_100(report["degree_alignment"]["degree_alignment_score"], "degree_score")

    print("---- score breakdown ----")
    print(f"keyword_score  = {keyword_score!r}  (weight 0.40 -> {keyword_score * 0.40})")
    print(f"bullet_score   = {bullet_score!r}  (weight 0.25 -> {bullet_score * 0.25})")
    print(f"structure_score = {structure_score!r}  (weight 0.15 -> {structure_score * 0.15})")
    print(f"jargon_score   = {jargon_score!r}  (weight 0.10 -> {jargon_score * 0.10})")
    print(f"degree_score   = {degree_score!r}  (weight 0.10 -> {degree_score * 0.10})")

    total = (
        keyword_score * 0.40
        + bullet_score * 0.25
        + structure_score * 0.15
        + jargon_score * 0.10
        + degree_score * 0.10
    )
    total = max(0.0, min(100.0, total))
    print(f"total (pre-round) = {total!r}")
    print("--------------------------")

    return int(round(total))