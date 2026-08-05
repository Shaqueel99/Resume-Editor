"""app.py

Résumé fit checker — Streamlit UI.

Flow:
  1. User uploads a .docx résumé and pastes a JD.
  2. JD_SKILLS_PROMPT extracts required/preferred skills (LLM call 1).
  3. compute_ats_score() scores the résumé as-is — deterministic, no LLM.
  4. ASSISTANT_PROMPT generates skill gaps + bullet rewrite suggestions
     that specifically surface JD terminology (LLM call 2).
  5. User reviews suggestions in a working-draft state (current_suggestions
     / current_reasons) and can regenerate a bullet with feedback any
     number of times before explicitly accepting — regeneration feeds the
     CURRENT draft back in, not the résumé's original text, so feedback
     compounds instead of resetting. The displayed "reason" caption tracks
     whichever version is showing (original suggestion, mid-regeneration
     draft, or accepted). Nothing moves into accepted_rewrites until the
     user clicks Accept.
  6. For skill gaps, user can optionally describe relevant experience;
     DRAFT_NEW_BULLET_PROMPT turns it into a new bullet for a new
     "Additional Skills / Experience" section.
  7. Accepted rewrites + new bullets are applied to the .docx via
     docx_editor.py.
  8. "Apply and rescore": compute_ats_score() re-runs on the edited text,
     against the SAME skill list used for "before", so the before/after
     comparison stays trustworthy — this is deterministic and does not
     call the LLM. Separately, ASSISTANT_PROMPT is re-run against the
     edited résumé to refresh suggestions for another round of edits.
     After this completes, results are hidden (show_results=False) so
     the page renders short — just the upload box plus a "Show updated
     results" button — instead of leaving the user scrolled down to
     stale content with no way back to the top.
  9. Download button for the edited .docx.
"""

import json
import tempfile
import traceback
from pathlib import Path

import streamlit as st
from docx import Document
from dotenv import load_dotenv
from streamlit_scroll_to_top import scroll_to_here
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

st.set_page_config(page_title="Résumé fit checker", layout="wide")
if st.session_state.get("pending_scroll"):
    st.session_state.pending_scroll = False
    scroll_to_here(0, key="top")
st.title("Résumé fit checker")
st.caption("Upload your résumé, paste a job post, see exactly what to change")




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


def reset_suggestion_state():
    """Clear per-bullet working state. Called after a fresh analysis and
    after every apply-and-rescore round, since old entries are keyed by
    bullet text that may no longer exist verbatim in the current document.
    """
    st.session_state.current_suggestions = {}
    st.session_state.current_reasons = {}
    st.session_state.accepted_rewrites = {}
    st.session_state.accepted_reasons = {}
    st.session_state.new_bullets = []

def show_overlay(message: str):
    """Full-page dimmed overlay with a centered message. Call before a
    long-running block, keep the returned placeholder open until the
    block finishes, then call .empty() on it."""
    theme_base = st.get_option("theme.base") or "light"
    if theme_base == "dark":
        bg, text = "#1e1e1e", "#f0f0f0"
    else:
        bg, text = "#ffffff", "#111111"

    placeholder = st.empty()
    placeholder.markdown(
        f"""
        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.5); z-index: 9999;
                    display: flex; align-items: center; justify-content: center;">
            <div style="background: {bg}; color: {text};
                        padding: 24px 32px; border-radius: 12px; font-size: 15px;
                        display: flex; align-items: center; gap: 12px;">
                <div style="width: 18px; height: 18px; border: 2px solid {text};
                            border-top-color: transparent; border-radius: 50%;
                            animation: spin 0.8s linear infinite;"></div>
                {message}
            </div>
        </div>
        <style>
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    return placeholder
# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

for key, default in [
    ("resume_path", None),
    ("jd_skills", None),
    ("before_score", None),
    ("assistant_output", None),
    ("current_suggestions", {}),
    ("current_reasons", {}),
    ("accepted_rewrites", {}),
    ("accepted_reasons", {}),
    ("new_bullets", []),
    ("edited_path", None),
    ("after_score", None),
    ("pending_scroll", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Step 1: upload + analyze
# ---------------------------------------------------------------------------

with st.container(border=True):
    upload_col, jd_col = st.columns(2)
    with upload_col:
        resume_file = st.file_uploader("Upload résumé (.docx)", type=["docx"])
    with jd_col:
        jd_text = st.text_area("Paste job description", height=120)

    run = st.button("Check fit", type="primary")

if run:
    if not resume_file or not jd_text.strip():
        st.error("Upload a résumé and paste a job description first.")
        st.stop()

    overlay = show_overlay("Checking your fit against this role…")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(resume_file.getvalue())
        st.session_state.resume_path = tmp.name

    resume_text = extract_docx_text(st.session_state.resume_path)
    jd_skills = safe_call("JD skill extraction", ask_json, JD_SKILLS_PROMPT, jd_text)
    st.session_state.jd_skills = jd_skills

    st.session_state.before_score = compute_ats_score(
        resume_text, jd_skills["required_skills"], jd_skills["preferred_skills"],
    )

    user_msg = json.dumps({"resume_text": resume_text, "jd_text": jd_text})
    st.session_state.assistant_output = safe_call(
        "Résumé analysis", ask_json, ASSISTANT_PROMPT, user_msg
    )

    reset_suggestion_state()
    st.session_state.edited_path = None
    st.session_state.after_score = None

    overlay.empty()
    st.session_state.pending_scroll = True
    st.rerun()


# ---------------------------------------------------------------------------
# Step 2: score row + suggestions
# ---------------------------------------------------------------------------

if st.session_state.assistant_output:
    before = st.session_state.before_score
    after = st.session_state.after_score

    st.divider()
    score_col1, score_col2, score_col3 = st.columns(3)
    score_col1.metric("Current match", f"{before['score']}/100")

    if after:
        delta = after["score"] - before["score"]
        score_col2.metric("After fixes", f"{after['score']}/100", delta=f"{delta:+d}")
    else:
        score_col2.metric("After fixes", "—")

    score_col3.metric("Missing skills", len((after or before)["missing_required"]))

    current = after if after else before
    if current["missing_required"]:
        label = "Still missing" if after else "Missing"
        st.caption(f"{label}: " + ", ".join(current["missing_required"]))

    st.divider()
    st.subheader("Bullet suggestions")

    for i, item in enumerate(st.session_state.assistant_output["bullet_rewrites"]):
        original = item["original_text"]
        is_accepted = original in st.session_state.accepted_rewrites

        if is_accepted:
            suggested = st.session_state.accepted_rewrites[original]
            reason = st.session_state.accepted_reasons.get(original, item["reason"])
        elif original in st.session_state.current_suggestions:
            suggested = st.session_state.current_suggestions[original]
            reason = st.session_state.current_reasons.get(original, item["reason"])
        else:
            suggested = item["suggested_text"]
            reason = item["reason"]

        with st.container(border=True):
            st.caption("original")
            st.write(original)
            st.caption("suggested")
            st.write(suggested)
            st.caption(reason)

            btn_col, fb_col, regen_col = st.columns([1, 3, 1])
            with btn_col:
                if is_accepted:
                    st.button("Accepted ✓", key=f"accept_{i}", disabled=True)
                else:
                    if st.button("Accept", key=f"accept_{i}"):
                        st.session_state.accepted_rewrites[original] = suggested
                        st.session_state.accepted_reasons[original] = reason
                        st.rerun()
            with fb_col:
                feedback = st.text_input(
                    "Ask for a different version",
                    key=f"feedback_{i}",
                    label_visibility="collapsed",
                    placeholder="e.g. make it more concise",
                    disabled=is_accepted,
                )
            with regen_col:
                if st.button("Regenerate", key=f"regen_{i}", disabled=is_accepted) and feedback.strip():
                    with st.spinner("Regenerating..."):
                        result = safe_call(
                            "Bullet regeneration",
                            ask_json,
                            REGENERATE_BULLET_PROMPT,
                            json.dumps({
                                "original_text": suggested,
                                "jd_text": jd_text,
                                "feedback": feedback,
                            }),
                        )
                    st.session_state.current_suggestions[original] = result["new_text"]
                    st.session_state.current_reasons[original] = result["reason"]
                    if result["note"]:
                        st.warning(result["note"])
                    st.rerun()

    if st.session_state.assistant_output["skill_gaps"]:
        st.divider()
        st.subheader("Skill gaps")

        for gap in st.session_state.assistant_output["skill_gaps"]:
            with st.container(border=True):
                st.write(f"**{gap['skill']}**")
                st.caption(gap["why_it_matters"])

                has_exp = st.radio(
                    "Do you have relevant experience?",
                    ["No", "Yes"],
                    key=f"has_exp_{gap['skill']}",
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if has_exp == "Yes":
                    candidate_input = st.text_area(
                        "Briefly describe it",
                        key=f"exp_input_{gap['skill']}",
                        label_visibility="collapsed",
                        placeholder=f"What did you do with {gap['skill']}?",
                    )
                    if st.button("Draft a bullet", key=f"draft_{gap['skill']}"):
                        if candidate_input.strip():
                            with st.spinner("Drafting..."):
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
                                st.success(result["new_bullet"])
                            else:
                                st.warning(result["note"])

    # -----------------------------------------------------------------------
    # Step 3: apply + rescore
    # -----------------------------------------------------------------------

    st.divider()
    apply_col, download_col = st.columns(2)

    with apply_col:
        if st.button("Apply changes and rescore", type="primary", use_container_width=True):
            overlay = show_overlay("Applying changes and rescoring…")

            replacements = [
                {"original_text": orig, "suggested_text": new}
                for orig, new in st.session_state.accepted_rewrites.items()
            ]

            out_path = str(Path(tempfile.gettempdir()) / "resume_edited.docx")

            result = replace_bullets(st.session_state.resume_path, out_path, replacements)
            if st.session_state.new_bullets:
                append_new_section(out_path, out_path, st.session_state.new_bullets)

            if result["not_found"]:
                st.warning(f"{len(result['not_found'])} suggestion(s) couldn't be located and were skipped.")

            st.session_state.edited_path = out_path
            edited_text = extract_docx_text(out_path)

            st.session_state.after_score = compute_ats_score(
                edited_text,
                st.session_state.jd_skills["required_skills"],
                st.session_state.jd_skills["preferred_skills"],
            )

            user_msg = json.dumps({"resume_text": edited_text, "jd_text": jd_text})
            st.session_state.assistant_output = safe_call(
                "Résumé re-analysis", ask_json, ASSISTANT_PROMPT, user_msg
            )

            st.session_state.resume_path = out_path
            reset_suggestion_state()

            overlay.empty()
            st.session_state.pending_scroll = True
            st.rerun()

    with download_col:
        if st.session_state.edited_path:
            with open(st.session_state.edited_path, "rb") as f:
                st.download_button(
                    "Download optimized résumé",
                    f,
                    file_name="resume_optimized.docx",
                    use_container_width=True,
                )
        else:
            st.button("Download optimized résumé", disabled=True, use_container_width=True)