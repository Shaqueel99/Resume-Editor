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
     number of times — regeneration feeds the CURRENT draft back in, not
     the résumé's original text, so feedback compounds instead of
     resetting. The displayed "reason" caption tracks whichever version is
     showing (original suggestion or mid-regeneration draft). Each
     bullet's Skip / Use suggestion / Write my own radio choice is the
     final decision — collect_replacements() reads it live at apply time,
     there is no separate "Accept" step.
  6. For skill gaps, user can optionally describe relevant experience;
     DRAFT_NEW_BULLET_PROMPT turns it into a new bullet, shown directly in
     the description box (editable, re-draftable). The user picks where it
     goes: a new "Additional Skills / Experience" section, or an existing
     Work Experience / Project entry — entries are found deterministically
     via docx_editor.list_bullet_entries(), no LLM involved.
  7. Chosen rewrites + drafted skill-gap bullets are applied to the .docx
     via docx_editor.py.
  8. "Apply and rescore": compute_ats_score() re-runs on the edited text,
     against the SAME skill list used for "before", so the before/after
     comparison stays trustworthy — this is deterministic and does not
     call the LLM. Separately, ASSISTANT_PROMPT is re-run against the
     edited résumé to refresh suggestions for another round of edits.
  9. Download button for the edited .docx.

Anywhere the score row is shown, a "Preview résumé" expander renders the
current résumé (original or edited, tracking st.session_state.resume_path)
inline via mammoth's docx-to-HTML conversion — a semantic approximation
(headings/bold/bullets), not a pixel-perfect Word render, in a sandboxed
iframe so its CSS can't leak into the page.
"""

import json
import tempfile
import traceback
from pathlib import Path

import mammoth
import streamlit as st
import streamlit.components.v1 as components
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
from docx_editor import (
    replace_bullets,
    append_new_section,
    list_bullet_entries,
    insert_bullets_into_entries,
)
import hashlib

NEW_SECTION_OPTION = 'New "Additional Skills / Experience" section'


def gap_target_options(resume_path: str) -> tuple[list[dict], list[str]]:
    """Existing Work Experience / Project entries a drafted skill-gap
    bullet could be inserted into, plus the default of appending it to a
    brand new section. Recomputed fresh each call rather than cached in
    session state, since it's a cheap deterministic parse and must stay in
    sync with whichever file resume_path currently points to."""
    entries = list_bullet_entries(resume_path)
    labels = [
        f"{e['section']} — {e['title']}" if e["section"] else e["title"]
        for e in entries
    ]
    return entries, [NEW_SECTION_OPTION] + labels

def bullet_key(original: str) -> str:
    """Stable per-bullet key derived from its text, so widget state follows
    the bullet rather than its position in a list that changes between rounds."""
    return hashlib.md5(original.encode()).hexdigest()[:8]

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


def collect_replacements() -> list[dict]:
    """Build the replacement list by reading current widget state, so there
    is exactly one source of truth and no dict/widget drift."""
    replacements = []
    for item in st.session_state.assistant_output["bullet_rewrites"]:
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

def reset_suggestion_state():
    st.session_state.current_suggestions = {}
    st.session_state.current_reasons = {}
    st.session_state.drafted_gaps = set()
    st.session_state.pending_drafts = {}
    for k in [k for k in st.session_state.keys()
              if k.startswith(("choice_", "manual_", "feedback_", "regen_",
                                "has_exp_", "exp_input_", "target_"))]:
        del st.session_state[k]

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


MAMMOTH_STYLE_MAP = """
p[style-name='Title'] => h1.resume-name:fresh
p[style-name='Subtitle'] => p.resume-contact:fresh
"""

RESUME_PREVIEW_CSS = """
body { margin: 0; padding: 20px; background: #eef0f3; font-family: 'Segoe UI', Arial, sans-serif; }
.page { background: #ffffff; max-width: 800px; margin: 0 auto; padding: 40px 48px;
        border-radius: 4px; box-shadow: 0 2px 12px rgba(0,0,0,0.12); color: #1a1a1a; line-height: 1.5; }
.page h1 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px;
           border-bottom: 2px solid #333; padding-bottom: 4px; margin: 20px 0 8px; }
.page h1.resume-name { font-size: 26px; text-transform: none; letter-spacing: normal;
                        border-bottom: none; margin-top: 0; }
.page h2 { font-size: 14px; margin: 14px 0 2px; }
.page p.resume-contact { color: #555; font-size: 13px; margin: 0 0 8px; }
.page p { font-size: 13.5px; margin: 4px 0; }
.page ul { margin: 4px 0 12px; padding-left: 20px; }
.page li { font-size: 13.5px; margin-bottom: 3px; }
.page strong { font-weight: 600; }
.page a { color: #2563eb; }
"""


def render_resume_preview(docx_path: str, height: int = 900) -> None:
    """Render a résumé .docx inline via mammoth's docx-to-HTML conversion,
    so the user can see roughly how it looks without downloading it. This
    is a semantic HTML approximation (headings/bold/bullets/paragraphs
    mapped from Word styles) — not a pixel-perfect render of the original
    Word layout, since that would require an external tool like LibreOffice.
    Rendered inside a sandboxed iframe (components.html) so its CSS can't
    leak into the rest of the page."""
    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(f, style_map=MAMMOTH_STYLE_MAP)

    components.html(
        f"<html><head><style>{RESUME_PREVIEW_CSS}</style></head>"
        f'<body><div class="page">{result.value}</div></body></html>',
        height=height,
        scrolling=True,
    )
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
    ("drafted_gaps", set()),
    ("pending_drafts", {}),
    ("edited_path", None),
    ("after_score", None),
    ("pending_scroll", False),
    ("preview_expanded", False),
    ("preview_key_version", 0),
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

    with st.expander(
        "Preview résumé",
        expanded=st.session_state.preview_expanded,
        key=f"preview_expander_{st.session_state.preview_key_version}",
    ):
        render_resume_preview(st.session_state.resume_path)

    st.divider()
    st.subheader("Bullet suggestions")

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
                                "Bullet regeneration", ask_json, REGENERATE_BULLET_PROMPT,
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
                    st.caption("Enter your version above, or it will be skipped.")

    if st.session_state.assistant_output["skill_gaps"]:
        st.divider()
        st.subheader("Skill gaps")

        _, gap_target_choices = gap_target_options(st.session_state.resume_path)

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
                    input_key = f"exp_input_{gap['skill']}"
                    if gap["skill"] in st.session_state.pending_drafts:
                        st.session_state[input_key] = st.session_state.pending_drafts.pop(gap["skill"])
                    candidate_input = st.text_area(
                        "Briefly describe it",
                        key=input_key,
                        label_visibility="collapsed",
                        placeholder=f"What did you do with {gap['skill']}?",
                    )
                    st.selectbox(
                        "Add this bullet to",
                        gap_target_choices,
                        key=f"target_{gap['skill']}",
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
                                st.session_state.drafted_gaps.add(gap["skill"])
                                st.session_state.pending_drafts[gap["skill"]] = result["new_bullet"]
                                st.rerun()
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

            replacements = collect_replacements()

            out_path = str(Path(tempfile.gettempdir()) / "resume_edited.docx")

            entries, target_choices = gap_target_options(st.session_state.resume_path)
            new_section_bullets = []
            entry_bullets: dict[int, list[str]] = {}
            for skill in st.session_state.drafted_gaps:
                text = st.session_state.get(f"exp_input_{skill}", "").strip()
                if not text:
                    continue
                choice = st.session_state.get(f"target_{skill}", NEW_SECTION_OPTION)
                try:
                    choice_idx = target_choices.index(choice)
                except ValueError:
                    choice_idx = 0
                if choice_idx == 0:
                    new_section_bullets.append(text)
                else:
                    anchor_index = entries[choice_idx - 1]["anchor_index"]
                    entry_bullets.setdefault(anchor_index, []).append(text)

            result = replace_bullets(st.session_state.resume_path, out_path, replacements)
            if entry_bullets:
                insert_bullets_into_entries(out_path, out_path, entry_bullets)
            if new_section_bullets:
                append_new_section(out_path, out_path, new_section_bullets)

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
            st.session_state.preview_expanded = True
            st.session_state.preview_key_version += 1
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