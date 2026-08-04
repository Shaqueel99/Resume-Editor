"""
report.py — pure Python Markdown renderer; no LLM calls.
"""

from pathlib import Path


def render_markdown(report: dict, *, out_path: str) -> None:
    """Render the full analysis report dict to a Markdown file."""
    lines = _build_lines(report)
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------

def _tick(value: object) -> str:
    return "✓" if value else "✗"


def _build_lines(report: dict) -> list[str]:
    meta    = report.get("meta", {})
    rp      = report.get("resume_profile", {})
    jd      = report.get("jd_profile", {})
    km      = report.get("keyword_match", {})
    bullets = report.get("bullets", {})
    jargon  = report.get("jargon", {})
    struct  = report.get("structure", {})
    bg      = report.get("background_fit", {})
    score   = report.get("overall_score", 0)
    passes  = report.get("passes_ats_threshold", False)
    summary = report.get("summary", "")

    lines: list[str] = []

    # 1. Header
    candidate = rp.get("name", "Unknown Candidate")
    jd_title  = jd.get("job_title", "Unknown Role")
    company   = jd.get("company", "Unknown Company")
    verdict   = "PASS" if passes else "FAIL"
    lines += [
        f"# Résumé Analysis Report",
        f"",
        f"**Candidate:** {candidate}  ",
        f"**Target role:** {jd_title} @ {company}  ",
        f"**Generated:** {meta.get('generated_at', '')}  ",
        f"",
        f"## Overall Score: {score}/100  ({verdict} — 60% ATS threshold)",
        f"",
    ]

    # 2. Executive summary
    lines += [
        "## Executive Summary",
        "",
        summary.strip(),
        "",
    ]

    # 3. Keyword match
    present = km.get("present", [])
    missing = km.get("missing", [])
    km_score = km.get("keyword_match_score", 0)
    lines += [
        "## Keyword Match",
        "",
        f"**Score:** {km_score}/100",
        "",
        "| Present keywords (up to 20) | Missing keywords (up to 20) |",
        "|---|---|",
    ]
    max_rows = max(len(present), len(missing), 1)
    for i in range(min(max_rows, 20)):
        p_cell = present[i]["keyword"] if i < len(present) else ""
        m_item = missing[i] if i < len(missing) else {}
        imp    = m_item.get("importance", "")
        m_cell = f"**{m_item['keyword']}** ({imp})" if m_item else ""
        lines.append(f"| {p_cell} | {m_cell} |")
    lines.append("")

    # 4. Bullet audit
    bullet_list = bullets.get("bullets", [])
    bq_avg = bullets.get("bullet_quality_avg", 0)
    lines += [
        "## Bullet Quality Audit",
        "",
        f"**Average score:** {bq_avg}/100  (L1=OK, L2=Better, L3=Best)",
        "",
        "| Project / Role | Bullet (truncated to 80 chars) | Action | Tech | Impact | Level | What's Missing |",
        "|---|---|---|---|---|---|---|",
    ]
    for b in bullet_list:
        text     = b.get("bullet_text", "")[:80]
        parent   = b.get("parent_title", "")
        action   = _tick(b.get("has_action_verb"))
        tech     = _tick(b.get("has_specific_technology"))
        impact   = _tick(b.get("has_measurable_impact"))
        level    = b.get("level", "")
        missing_ = b.get("what_is_missing", "")
        lines.append(f"| {parent} | {text} | {action} | {tech} | {impact} | {level} | {missing_} |")
    lines.append("")

    # 5. Terminology mismatches
    flags      = jargon.get("flags", [])
    jargon_sc  = jargon.get("jargon_score", 0)
    lines += [
        "## Terminology & Keyword Mismatches",
        "",
        f"**Score:** {jargon_sc}/100",
        "",
    ]
    if flags:
        lines += [
            "| Term Used | Suggested Translation | Severity |",
            "|---|---|---|",
        ]
        for f in flags:
            lines.append(
                f"| {f.get('term_used', '')} "
                f"| {f.get('suggested_translation', '')} "
                f"| {f.get('severity', '')} |"
            )
    else:
        lines.append("No terminology mismatches raised. ✓")
    lines.append("")

    # 6. Structure audit
    ats_flags  = struct.get("ats_red_flags", [])
    struct_sc  = struct.get("structure_score", 0)
    headings_p = ", ".join(struct.get("section_headings_present", [])) or "none detected"
    headings_m = ", ".join(struct.get("section_headings_missing", [])) or "none missing"
    lines += [
        "## Resume Structure & ATS Formatting",
        "",
        f"**Score:** {struct_sc}/100  "
        f"| Pages (est.): {struct.get('page_count_estimate', '?')}  "
        f"| Single-column: {_tick(struct.get('single_column_likely'))}",
        "",
        f"**Headings present:** {headings_p}  ",
        f"**Headings missing:** {headings_m}",
        "",
        "**ATS parseability checklist:**",
        "",
        f"| Check | Status |",
        f"|---|---|",
        f"| Single-column layout        | {_tick(struct.get('single_column_likely'))} |",
        f"| Reverse-chronological order | {_tick(struct.get('reverse_chronological_likely'))} |",
        f"| Contact info at top         | {_tick(struct.get('contact_info_at_top'))} |",
        f"| Appropriate length          | {_tick(struct.get('length_appropriate'))} |",
        f"| No images / graphics        | {_tick(struct.get('no_images_or_graphics'))} |",
        "",
    ]
    if ats_flags:
        lines += [
            "**ATS red flags:**",
            "",
            "| Issue | Evidence |",
            "|---|---|",
        ]
        for flag in ats_flags:
            lines.append(f"| {flag.get('issue', '')} | {flag.get('evidence', '')} |")
    else:
        lines.append("No ATS red flags detected. ✓")
    lines.append("")

    # 7. Background fit
    lines += [
        "## Background Fit",
        "",
        f"**Score:** {bg.get('background_fit_score', 0)}/100",
        "",
        f"**Candidate background:** {bg.get('candidate_background_summary', '')}  ",
        f"**Role expects:** {bg.get('role_requirements_summary', '')}  ",
        f"**Commentary:** {bg.get('alignment_commentary', '')}",
        "",
    ]

    # 8. Score breakdown
    km_contrib  = round(km.get("keyword_match_score", 0) * 0.40, 1)
    bq_contrib  = round(bullets.get("bullet_quality_avg", 0) * 0.25, 1)
    st_contrib  = round(struct.get("structure_score", 0) * 0.15, 1)
    ja_contrib  = round(jargon.get("jargon_score", 0) * 0.10, 1)
    bg_contrib  = round(bg.get("background_fit_score", 0) * 0.10, 1)
    lines += [
        "## Score Breakdown",
        "",
        "| Component | Raw | Weight | Contribution |",
        "|---|---|---|---|",
        f"| Keyword match    | {km.get('keyword_match_score', 0)} | 40% | {km_contrib} |",
        f"| Bullet quality   | {bullets.get('bullet_quality_avg', 0)} | 25% | {bq_contrib} |",
        f"| Structure        | {struct.get('structure_score', 0)} | 15% | {st_contrib} |",
        f"| Jargon           | {jargon.get('jargon_score', 0)} | 10% | {ja_contrib} |",
        f"| Background fit   | {bg.get('background_fit_score', 0)} | 10% | {bg_contrib} |",
        f"| **Total**        |     |     | **{score}** |",
        "",
    ]

    return lines
