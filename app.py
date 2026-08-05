"""app.py

Résumé ATS Optimizer — Streamlit UI.

Flow:
  1. User uploads a .docx résumé and pastes a JD.
  2. JD_SKILLS_PROMPT extracts required/preferred skills (LLM call 1).
  3. compute_ats_score() scores the résumé as-is — deterministic, no LLM.
  4. ASSISTANT_PROMPT generates skill gaps + bullet rewrite suggestions
     (LLM call 2).
  5. User reviews suggestions, checks which to accept, and can ask for a
     single bullet to be regenerated with feedback (LLM call: 
     REGENERATE_BULLET_PROMPT) before accepting.
  6. For skill gaps, user can optionally describe relevant experience;
     DRAFT_NEW_BULLET_PROMPT turns it into a new bullet for a new
     "Additional Skills / Experience" section (LLM call).
  7. Accepted rewrites + new bullets are applied to the .docx via
     docx_editor.py.
  8. compute_ats_score() re-runs on the edited text — same function,
     no new LLM call — to show the after score.
  9. Download button for the edited .docx.
"""

import json
import tempfile
import traceback
from pathlib import Path

import streamlit as st
from docx import Document
from dotenv import load_dotenv

from llm import ask_json
from prompts import (
    JD_SKILLS_PROMPT,
    ASSISTANT_PROMPT,
    REGENERATE_BULLET_PROMPT,
    DRAFT_NEW_BULLET_PROMPT,
)
from scoring import compute_ats_score
from docx_editor import replace_bullets, append_new_section

load_dotenv()

st.set_page_config(page_title="Résumé ATS Optimizer", layout="wide")
st.title("Résumé ATS Optimizer")


def safe_call(label, fn, *args):
    """Run an LLM-calling function, surfacing the real error in the UI."""
    try:
        return fn(*args)
    except Exception as e:
        st.error(f"{label} failed: {e}")
        st.code(traceback.format_exc())
        st.stop()


def extract_docx_text(path: str) -> str:
    """Flatten a .docx's paragraph text into a single string for LLM input."""
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

for key, default in [
    ("resume_path", None),
    ("jd_skills", None),
    ("before_score", None),
    ("assistant_output", None),
    ("accepted_rewrites", {}),   # original_text -> suggested_text (possibly regenerated)
    ("new_bullets", []),
    ("edited_path", None),
    ("after_score", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Step 1: upload + analyze
# ---------------------------------------------------------------------------

resume_file = st.file_uploader("Upload Résumé (.docx)", type=["docx"])
jd_text = st.text_area("Paste Job Description", height=250)
run = st.button("Analyze")

if run:
    if not resume_file or not jd_text.strip():
        st.error("Please upload a résumé and paste a job description.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(resume_file.getvalue())
        st.session_state.resume_path = tmp.name

    resume_text = extract_docx_text(st.session_state.resume_path)

    with st.spinner("Extracting required skills from JD..."):
        jd_skills = safe_call("JD skill extraction", ask_json, JD_SKILLS_PROMPT, jd_text)
        st.session_state.jd_skills = jd_skills

    st.session_state.before_score = compute_ats_score(
        resume_text,
        jd_skills["required_skills"],
        jd_skills["preferred_skills"],
    )

    with st.spinner("Analyzing résumé against JD..."):
        user_msg = json.dumps({"resume_text": resume_text, "jd_text": jd_text})
        st.session_state.assistant_output = safe_call(
            "Résumé analysis", ask_json, ASSISTANT_PROMPT, user_msg
        )

    st.session_state.accepted_rewrites = {}
    st.session_state.new_bullets = []
    st.session_state.edited_path = None
    st.session_state.after_score = None


# ---------------------------------------------------------------------------
# Step 2: show before score + suggestions
# ---------------------------------------------------------------------------

if st.session_state.assistant_output:
    before = st.session_state.before_score
    st.subheader("Current ATS Score")
    st.metric("Before", f"{before['score']}/100")
    if before["missing_required"]:
        st.caption(f"Missing required skills: {', '.join(before['missing_required'])}")

    st.subheader("Suggested Bullet Rewrites")
    for i, item in enumerate(st.session_state.assistant_output["bullet_rewrites"]):
        original = item["original_text"]
        suggested = st.session_state.accepted_rewrites.get(original, item["suggested_text"])

        with st.expander(f"Bullet {i + 1}: {original[:70]}..."):
            st.markdown(f"**Original:** {original}")
            st.markdown(f"**Suggested:** {suggested}")
            st.caption(item["reason"])

            accept = st.checkbox("Accept this rewrite", key=f"accept_{i}")
            feedback = st.text_input("Ask for a different version (optional)", key=f"feedback_{i}")

            if st.button("Regenerate", key=f"regen_{i}") and feedback.strip():
                with st.spinner("Regenerating..."):
                    result = safe_call(
                        "Bullet regeneration",
                        ask_json,
                        REGENERATE_BULLET_PROMPT,
                        json.dumps({
                            "original_text": original,
                            "jd_text": jd_text,
                            "feedback": feedback,
                        }),
                    )
                st.session_state.accepted_rewrites[original] = result["new_text"]
                if result["note"]:
                    st.warning(result["note"])
                st.rerun()

            if accept:
                st.session_state.accepted_rewrites[original] = suggested

    st.subheader("Skill Gaps")
    for gap in st.session_state.assistant_output["skill_gaps"]:
        st.markdown(f"**{gap['skill']}** — {gap['why_it_matters']}")
        has_exp = st.radio(
            f"Do you have relevant experience with {gap['skill']}?",
            ["No", "Yes"],
            key=f"has_exp_{gap['skill']}",
            horizontal=True,
        )
        if has_exp == "Yes":
            candidate_input = st.text_area(
                f"Briefly describe your experience with {gap['skill']}",
                key=f"exp_input_{gap['skill']}",
            )
            if st.button(f"Draft bullet for {gap['skill']}", key=f"draft_{gap['skill']}"):
                if candidate_input.strip():
                    with st.spinner("Drafting bullet..."):
                        result = safe_call(
                            "Draft new bullet",
                            ask_json,
                            DRAFT_NEW_BULLET_PROMPT,
                            json.dumps({
                                "skill": gap["skill"],
                                "jd_text": jd_text,
                                "candidate_input": candidate_input,
                            }),
                        )
                    if result["new_bullet"]:
                        st.session_state.new_bullets.append(result["new_bullet"])
                        st.success(f"Added: {result['new_bullet']}")
                    else:
                        st.warning(result["note"])


    # -----------------------------------------------------------------------
    # Step 3: apply changes + rescore
    # -----------------------------------------------------------------------

    if st.button("Apply Changes & Rescore"):
        replacements = [
            {"original_text": orig, "suggested_text": new}
            for orig, new in st.session_state.accepted_rewrites.items()
        ]

        out_path = str(Path(tempfile.gettempdir()) / "resume_edited.docx")

        with st.spinner("Applying edits..."):
            result = replace_bullets(st.session_state.resume_path, out_path, replacements)
            if st.session_state.new_bullets:
                append_new_section(out_path, out_path, st.session_state.new_bullets)

        if result["not_found"]:
            st.warning(
                f"{len(result['not_found'])} rewrite(s) could not be located "
                "in the document and were skipped."
            )

        st.session_state.edited_path = out_path

        edited_text = extract_docx_text(out_path)
        st.session_state.after_score = compute_ats_score(
            edited_text,
            st.session_state.jd_skills["required_skills"],
            st.session_state.jd_skills["preferred_skills"],
        )


# ---------------------------------------------------------------------------
# Step 4: show after score + download
# ---------------------------------------------------------------------------

if st.session_state.after_score:
    col1, col2 = st.columns(2)
    col1.metric("Before", f"{st.session_state.before_score['score']}/100")
    col2.metric("After", f"{st.session_state.after_score['score']}/100")

    with open(st.session_state.edited_path, "rb") as f:
        st.download_button(
            "Download Edited Résumé (.docx)",
            f,
            file_name="resume_optimized.docx",
        )