"""cover_letter_page.py

Cover letter generator — Streamlit page.

Flow (a 3-step LLM pipeline, mirroring how fit_checker_page.py splits
its own analysis into focused calls rather than one do-everything call):
  1. COVER_LETTER_ANALYSIS_PROMPT — finds the résumé's strongest, most
     concrete points of alignment with the JD ("key_alignments"), so the
     draft has real evidence to build its case on instead of generic
     self-praise.
  2. SKILL_GAPS_PROMPT (reused as-is from prompts.py / fit_checker_page.py
     — same "what does the JD ask for that the résumé doesn't evidence"
     analysis the fit checker already does) — finds gaps the letter may
     need to address honestly.
  3. COVER_LETTER_DRAFT_PROMPT — combines both into a draft, returned as
     six clearly labelled sections (greeting / opening / alignment body /
     gap mitigation / closing / sign-off) rather than one blob of text,
     so the UI can show — and later revise — each part on its own.

Both the résumé and JD text can be long (a multi-page résumé, a sprawling
JD), so before either goes into a prompt they're capped by
common.truncate_for_prompt() — a JD or résumé beyond that length gets cut
on a word boundary, with a one-line warning, rather than silently risking
a cut-off JSON response or an oversized/expensive request.

Follow-up refinement is a small chat: st.chat_input takes a revision
request, COVER_LETTER_REVISE_PROMPT applies it to the CURRENT draft (not
the original — feedback compounds across turns, same principle as the fit
checker's bullet regeneration), and the exchange is logged in
st.session_state.cl_chat_history so prior turns stay visible.
"""

import io
import json
import tempfile

import streamlit as st
from docx import Document

from common import (
    dedupe_skill_gaps,
    extract_docx_text,
    safe_call,
    start_progress_overlay,
    truncate_for_prompt,
)
from llm import ask_json
from prompts import (
    COVER_LETTER_ANALYSIS_PROMPT,
    COVER_LETTER_DRAFT_PROMPT,
    COVER_LETTER_REVISE_PROMPT,
    SKILL_GAPS_PROMPT,
)

SECTION_LABELS = [
    ("greeting", "Greeting"),
    ("opening", "Opening"),
    ("alignment_body", "Why you're a fit"),
    ("gap_mitigation_body", "Addressing the gaps"),
    ("closing", "Closing"),
    ("sign_off", "Sign-off"),
]


def assemble_letter_text(draft: dict) -> str:
    """Join the labelled sections into one plain-text letter, in reading
    order, skipping any section the draft left empty (e.g. an empty
    gap_mitigation_body when there was nothing worth addressing)."""
    parts = []
    for key, _ in SECTION_LABELS:
        value = (draft.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n\n".join(parts)


def build_docx_bytes(letter_text: str) -> bytes:
    """Turn the assembled letter text into a minimal .docx (one paragraph
    per blank-line-separated block), for a download format that pairs
    naturally with the résumé's own .docx download on the other tab."""
    doc = Document()
    for line in letter_text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def run_cover_letter_pipeline(resume_text: str, jd_text: str, advance) -> dict:
    """Run the 3-step analyse -> identify gaps -> generate draft pipeline
    and return {"key_alignments": [...], "skill_gaps": [...], "draft": {...}}.
    advance(i) is called before step i (0-indexed) to move a shared
    progress overlay — see common.start_progress_overlay()."""
    resume_text, resume_truncated = truncate_for_prompt(resume_text)
    jd_text, jd_truncated = truncate_for_prompt(jd_text)
    if resume_truncated:
        st.warning("Your résumé was long, so only the first portion was used for the cover letter.")
    if jd_truncated:
        st.warning("The job description was long, so only the first portion was used for the cover letter.")

    combined = json.dumps({"resume_text": resume_text, "jd_text": jd_text})

    advance(0)
    analysis = safe_call(
        "Cover letter analysis", ask_json, COVER_LETTER_ANALYSIS_PROMPT, combined
    )

    advance(1)
    skill_gaps_result = safe_call(
        "Cover letter skill gaps", ask_json, SKILL_GAPS_PROMPT, combined
    )
    skill_gaps = dedupe_skill_gaps(skill_gaps_result["skill_gaps"])

    advance(2)
    draft = safe_call(
        "Cover letter draft",
        ask_json,
        COVER_LETTER_DRAFT_PROMPT,
        json.dumps({
            "resume_text": resume_text,
            "jd_text": jd_text,
            "key_alignments": analysis["key_alignments"],
            "skill_gaps": skill_gaps,
        }),
    )

    return {
        "key_alignments": analysis["key_alignments"],
        "skill_gaps": skill_gaps,
        "draft": draft,
    }


def render() -> None:
    st.title("Cover letter generator")
    st.caption("Paste a job description and your résumé — get a tailored draft, then ask for revisions")

    for key, default in [
        ("cl_resume_path", None),
        ("cl_jd_text", ""),
        ("cl_key_alignments", None),
        ("cl_skill_gaps", None),
        ("cl_draft", None),
        ("cl_chat_history", []),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # -------------------------------------------------------------------
    # Step 1: inputs + generate
    # -------------------------------------------------------------------

    with st.container(border=True):
        upload_col, jd_col = st.columns(2)
        with upload_col:
            resume_file = st.file_uploader(
                "Upload résumé (.docx)", type=["docx"], key="cl_resume_file"
            )
            if st.session_state.get("resume_path") and not resume_file:
                st.caption("Tip: you can also reuse the résumé already uploaded on the Fit checker tab below.")
                reuse = st.checkbox("Reuse résumé from the Fit checker tab", key="cl_reuse_resume")
            else:
                reuse = False
        with jd_col:
            jd_text = st.text_area("Paste job description", height=300, key="cl_jd_text")

        generate = st.button("Generate cover letter", type="primary")

    if generate:
        resume_path = None
        if resume_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(resume_file.getvalue())
                resume_path = tmp.name
        elif reuse and st.session_state.get("resume_path"):
            resume_path = st.session_state["resume_path"]

        if not resume_path or not jd_text.strip():
            st.error("Upload a résumé (or reuse one from the Fit checker tab) and paste a job description first.")
            st.stop()

        st.session_state.cl_resume_path = resume_path

        overlay, advance = start_progress_overlay([
            "Finding your strongest points of alignment with the role…",
            "Identifying skill gaps…",
            "Drafting your cover letter…",
        ])

        resume_text = extract_docx_text(resume_path)
        result = run_cover_letter_pipeline(resume_text, jd_text, advance)

        st.session_state.cl_key_alignments = result["key_alignments"]
        st.session_state.cl_skill_gaps = result["skill_gaps"]
        st.session_state.cl_draft = result["draft"]
        st.session_state.cl_chat_history = []

        overlay.empty()
        st.rerun()

    # -------------------------------------------------------------------
    # Step 2: skill gaps + draft
    # -------------------------------------------------------------------

    if st.session_state.cl_draft:
        draft = st.session_state.cl_draft

        if st.session_state.cl_skill_gaps:
            st.divider()
            with st.expander(f"Skill gaps considered ({len(st.session_state.cl_skill_gaps)})"):
                for gap in st.session_state.cl_skill_gaps:
                    st.write(f"**{gap['skill']}**")
                    st.caption(gap["why_it_matters"])

        st.divider()
        st.subheader("Your cover letter draft")

        for key, label in SECTION_LABELS:
            value = (draft.get(key) or "").strip()
            if not value:
                continue
            with st.container(border=True):
                st.caption(label)
                st.write(value)

        letter_text = assemble_letter_text(draft)

        st.text_area("Full text (for copying)", value=letter_text, height=300, disabled=True)

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "Download as .txt",
                letter_text,
                file_name="cover_letter.txt",
                use_container_width=True,
            )
        with dl_col2:
            st.download_button(
                "Download as .docx",
                build_docx_bytes(letter_text),
                file_name="cover_letter.docx",
                use_container_width=True,
            )

        # -------------------------------------------------------------------
        # Step 3: follow-up revisions
        # -------------------------------------------------------------------

        st.divider()
        st.subheader("Ask for revisions")

        for turn in st.session_state.cl_chat_history:
            with st.chat_message("user"):
                st.write(turn["feedback"])
            with st.chat_message("assistant"):
                st.write(turn["change_summary"])

        feedback = st.chat_input("e.g. \"make the tone warmer\" or \"shorten the opening\"")
        if feedback:
            with st.chat_message("user"):
                st.write(feedback)

            with st.spinner("Revising..."):
                jd_text_for_revision, _ = truncate_for_prompt(jd_text)
                revised = safe_call(
                    "Cover letter revision",
                    ask_json,
                    COVER_LETTER_REVISE_PROMPT,
                    json.dumps({
                        "current_draft": {k: draft.get(k, "") for k, _ in SECTION_LABELS},
                        "jd_text": jd_text_for_revision,
                        "feedback": feedback,
                    }),
                )

            change_summary = revised.pop("change_summary", "")
            st.session_state.cl_draft = revised
            st.session_state.cl_chat_history.append({
                "feedback": feedback,
                "change_summary": change_summary,
            })
            st.rerun()
