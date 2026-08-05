"""app.py

Résumé fit checker — Streamlit UI.

Flow:
  1. User uploads a .docx résumé and pastes a JD.
  2. JD_SKILLS_PROMPT extracts required/preferred skills (LLM call 1).
  3. compute_ats_score() scores the résumé as-is — deterministic, no LLM.
  4. ASSISTANT_PROMPT generates skill gaps + bullet rewrite suggestions
     that surface JD terminology already implied by a bullet's wording.
     Output passes through validate_rewrites() first — a code-level check
     that the rewrite kept the original's content words and didn't invent
     new technical terms, since prompt instructions alone did not reliably
     prevent either.
  5. Per bullet, the user picks one of three options via a single radio:
     Skip, Use suggestion, or Write my own. The radio makes the choices
     mutually exclusive structurally, so there is no separate "accepted"
     dict to drift out of sync — widget state IS the source of truth,
     read back at apply time by collect_replacements(). Within "Use
     suggestion", the user can regenerate with feedback repeatedly;
     regeneration feeds the CURRENT draft back in, not the résumé's
     original text, so feedback compounds instead of resetting.
  6. For skill gaps, the user can describe relevant experience they have;
     DRAFT_NEW_BULLET_PROMPT phrases it into a new bullet for a new
     "Additional Skills / Experience" section. Facts come from the user,
     not the model.
  7. Chosen rewrites + new bullets are applied to the .docx via
     docx_editor.py.
  8. "Apply and rescore": compute_ats_score() re-runs on the edited text
     against the SAME skill list used for "before", so the comparison
     stays trustworthy — deterministic, no LLM. Separately,
     ASSISTANT_PROMPT re-runs against the edited résumé to refresh
     suggestions for another round.
  9. Download button for the edited .docx.

Widget keys are hashed from the item's own text rather than its list
index, so state follows the item across rounds where the suggestion list
changes length or order.
"""

import hashlib
import json
import os
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

# set_page_config must be the first Streamlit call in the script.
st.set_page_config(page_title="Résumé fit checker", layout="wide")

load_dotenv(override=True)

if st.session_state.get("pending_scroll"):
    st.session_state.pending_scroll = False
    scroll_to_here(0, key="top")

st.title("Résumé fit checker")
st.caption("Upload your résumé, paste a job post, see exactly what to change")
st.caption(f"Model: {os.getenv('MODEL')}")  # remove before presenting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def bullet_key(text: str) -> str:
    """Stable per-item widget key derived from the item's own text, so
    widget state follows the item rather than its position in a list that
    changes between rounds.
    """
    return hashlib.md5(text.encode()).hexdigest()[:8]


PER_ITEM_KEY_PREFIXES = (
    "choice_", "manual_", "feedback_", "regen_", "has_exp_", "exp_input_", "draft_",
)


def reset_suggestion_state():
    """Clear per-item working state and the widget state backing it.

    Called after a fresh analysis and after every apply-and-rescore round:
    old entries are keyed by bullet text that may no longer exist verbatim
    in the current document, and leftover widget state would otherwise
    re-apply a stale choice to a newly suggested bullet.
    """
    st.session_state.current_suggestions = {}
    st.session_state.current_reasons = {}
    st.session_state.new_bullets = []
    for k in [k for k in st.session_state.keys() if k.startswith(PER_ITEM_KEY_PREFIXES)]:
        del st.session_state[k]


def validate_rewrites(output: dict) -> tuple[list[dict], list[dict]]:
    """Split rewrites into ones that look safe and ones to drop.

    Checks content preservation rather than trusting the model's own
    account of what it changed. Two failures observed in testing: a
    rewrite that silently dropped "Aurora" and "security groups" from the
    original, and one that invented "Dockerized" outright. Retention
    catches the first, the introduced-term cap catches the second.

    Thresholds are tunable — watch the dropped count in the UI and adjust.
    """
    FILLER = (
        "demonstrating proficiency", "showcasing expertise",
        "leveraging", "utilizing best practices", "best practices",
        "highlighting experience", "ensuring efficient and secure",
    )

    def content_words(text: str) -> set[str]:
        stop = {
            "a", "an", "the", "and", "or", "for", "to", "of", "in", "on", "with",
            "as", "at", "by", "from", "into", "using", "part", "project", "data",
        }
        return {
            w.strip(".,()").lower()
            for w in text.split()
            if len(w.strip(".,()")) > 3 and w.strip(".,()").lower() not in stop
        }

    kept, dropped = [], []

    for item in output.get("bullet_rewrites", []):
        original = item.get("original_text", "")
        suggested = item.get("suggested_text", "")

        if not original or not suggested or suggested == original:
            dropped.append(item)
            continue

        orig_words = content_words(original)
        sugg_words = content_words(suggested)

        retained = len(orig_words & sugg_words) / len(orig_words) if orig_words else 0
        introduced = sugg_words - orig_words

        keeps_content = retained >= 0.7
        modest_addition = len(introduced) <= 3
        filler_ok = not any(f in suggested.lower() for f in FILLER)

        if keeps_content and modest_addition and filler_ok:
            kept.append(item)
        else:
            dropped.append(item)

    return kept, dropped


def run_assistant_analysis(resume_text: str, jd_text: str) -> dict:
    """Call ASSISTANT_PROMPT and filter its rewrites through
    validate_rewrites. Records the dropped count so the UI can show it.
    """
    user_msg = json.dumps({"resume_text": resume_text, "jd_text": jd_text})
    raw_output = safe_call("Résumé analysis", ask_json, ASSISTANT_PROMPT, user_msg)
    kept, dropped = validate_rewrites(raw_output)
    raw_output["bullet_rewrites"] = kept
    st.session_state.dropped_count = len(dropped)
    return raw_output


def collect_replacements() -> list[dict]:
    """Build the replacement list by reading current widget state.

    Single source of truth for what gets applied. Nothing is tracked
    incrementally as the user clicks, so there is no parallel "accepted"
    dict that can disagree with what the UI shows.
    """
    replacements = []
    output = st.session_state.assistant_output
    if not output:
        return replacements

    for item in output["bullet_rewrites"]:
        original = item["original_text"]
        bk = bullet_key(original)
        choice = st.session_state.get(f"choice_{bk}", "Skip")

        if choice == "Use suggestion":
            new_text = st.session_state.current_suggestions.get(original, item["suggested_text"])
        elif choice == "Write my own":
            new_text = st.session_state.get(f"manual_{bk}", "").strip()
        else:
            continue

        if new_text and new_text != original:
            replacements.append({"original_text": original, "suggested_text": new_text})

    return replacements


def show_overlay(message: str):
    """Full-page dimmed overlay with a centered message. Call before a
    long-running block, then call .empty() on the returned placeholder
    once the block finishes.
    """
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
    ("new_bullets", []),
    ("edited_path", None),
    ("after_score", None),
    ("pending_scroll", False),
    ("dropped_count", 0),
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
        jd_text = st.text_area("Paste job description", height=300)

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
        resume_text,
        jd_skills["required_skills"],
        jd_skills["preferred_skills"],
    )

    st.session_state.assistant_output = run_assistant_analysis(resume_text, jd_text)

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

    if st.session_state.dropped_count:
        st.caption(
            f"{st.session_state.dropped_count} suggestion(s) filtered out for dropping or inventing content"
        )

    if not st.session_state.assistant_output["bullet_rewrites"]:
        st.info("No terminology gaps found in your existing bullets. Nothing to rewrite.")

    for item in st.session_state.assistant_output["bullet_rewrites"]:
        original = item["original_text"]
        bk = bullet_key(original)

        suggested = st.session_state.current_suggestions.get(original, item["suggested_text"])
        reason = st.session_state.current_reasons.get(original, item["reason"])

        with st.container(border=True):
            st.caption("original")
            st.write(original)
            st.caption("suggested")
            st.write(suggested)
            st.caption(reason)

            choice = st.radio(
                "What do you want to do with this bullet?",
                ["Skip", "Use suggestion", "Write my own"],
                key=f"choice_{bk}",
                horizontal=True,
                label_visibility="collapsed",
            )

            if choice == "Use suggestion":
                fb_col, regen_col = st.columns([4, 1])
                with fb_col:
                    feedback = st.text_input(
                        "Ask for a different version",
                        key=f"feedback_{bk}",
                        label_visibility="collapsed",
                        placeholder="e.g. make it more concise",
                    )
                with regen_col:
                    if st.button("Regenerate", key=f"regen_{bk}") and feedback.strip():
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

            elif choice == "Write my own":
                st.text_area(
                    "Your version",
                    key=f"manual_{bk}",
                    label_visibility="collapsed",
                    placeholder="Type your replacement bullet here",
                )
                if not st.session_state.get(f"manual_{bk}", "").strip():
                    st.caption("Enter your version above, or this bullet will be skipped.")

    if st.session_state.assistant_output["skill_gaps"]:
        st.divider()
        st.subheader("Skill gaps")

        for gap in st.session_state.assistant_output["skill_gaps"]:
            gk = bullet_key(gap["skill"])
            with st.container(border=True):
                st.write(f"**{gap['skill']}**")
                st.caption(gap["why_it_matters"])

                has_exp = st.radio(
                    "Do you have relevant experience?",
                    ["No", "Yes"],
                    key=f"has_exp_{gk}",
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if has_exp == "Yes":
                    candidate_input = st.text_area(
                        "Briefly describe it",
                        key=f"exp_input_{gk}",
                        label_visibility="collapsed",
                        placeholder=f"What did you do with {gap['skill']}?",
                    )
                    if st.button("Draft a bullet", key=f"draft_{gk}"):
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

        if st.session_state.new_bullets:
            st.caption(f"{len(st.session_state.new_bullets)} new bullet(s) queued to add")

    # -----------------------------------------------------------------------
    # Step 3: apply + rescore
    # -----------------------------------------------------------------------

    st.divider()

    pending = collect_replacements()
    st.caption(
        f"{len(pending)} bullet change(s) and "
        f"{len(st.session_state.new_bullets)} new bullet(s) ready to apply"
    )

    apply_col, download_col = st.columns(2)
    st.write(st.session_state.jd_skills)
    with apply_col:
        if st.button("Apply changes and rescore", type="primary", use_container_width=True):
            replacements = collect_replacements()

            if not replacements and not st.session_state.new_bullets:
                st.warning("Nothing selected to apply. Pick a suggestion or write your own first.")
            else:
                overlay = show_overlay("Applying changes and rescoring…")

                out_path = str(Path(tempfile.gettempdir()) / "resume_edited.docx")

                result = replace_bullets(st.session_state.resume_path, out_path, replacements)
                if st.session_state.new_bullets:
                    append_new_section(out_path, out_path, st.session_state.new_bullets)

                if result["not_found"]:
                    st.warning(
                        f"{len(result['not_found'])} change(s) couldn't be located in the document "
                        "and were skipped."
                    )

                st.session_state.edited_path = out_path
                edited_text = extract_docx_text(out_path)

                st.session_state.after_score = compute_ats_score(
                    edited_text,
                    st.session_state.jd_skills["required_skills"],
                    st.session_state.jd_skills["preferred_skills"],
                )

                delta = (
                    st.session_state.after_score["score"]
                    - st.session_state.before_score["score"]
                )
                if delta > 0:
                    st.toast(f"Score improved by {delta} points", icon="🎉")
 

                st.session_state.assistant_output = run_assistant_analysis(edited_text, jd_text)

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