"""common.py

Small helpers shared by the app's Streamlit pages (fit_checker_page.py,
cover_letter_page.py). Kept separate from app.py so app.py can stay a
thin st.navigation() entry point and neither page module has to import
the other.
"""

import traceback

import streamlit as st
from docx import Document
from dotenv import load_dotenv

load_dotenv()


def safe_call(label, fn, *args, **kwargs):
    """Run an LLM-calling function, surfacing the real error in the UI."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        st.error(f"{label} failed: {e}")
        st.code(traceback.format_exc())
        st.stop()


def extract_docx_text(path: str) -> str:
    """Flatten a .docx's paragraph text into a single string for LLM input."""
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def truncate_for_prompt(text: str, max_chars: int = 12000) -> tuple[str, bool]:
    """Cap text at max_chars on a whitespace boundary, so a very long
    pasted résumé or job description can't blow the model's context
    budget or push a JSON response past max_tokens mid-object. Returns
    (possibly-truncated text, whether it was truncated) so callers can
    warn the user their input was cut down."""
    if len(text) <= max_chars:
        return text, False
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.8:
        cut = cut[:last_space]
    return cut.rstrip() + " …", True


def dedupe_skill_gaps(skill_gaps: list[dict]) -> list[dict]:
    """Drop skill gaps that repeat a skill name already seen earlier in
    the list — every skill-gap widget/key downstream is keyed off
    gap['skill'] directly, and a duplicate skill name collides on that
    key."""
    seen = set()
    deduped = []
    for gap in skill_gaps:
        skill = gap["skill"]
        if skill in seen:
            continue
        seen.add(skill)
        deduped.append(gap)
    return deduped


def render_overlay(placeholder, message: str, progress: int) -> None:
    """(Re)render a full-page dimmed overlay with a spinner, a message,
    and a progress bar into an EXISTING st.empty() placeholder — call
    once per step of a multi-step operation so the same overlay updates
    in place instead of flashing a new box per step. progress is 0-100."""
    theme_base = st.get_option("theme.base") or "light"
    if theme_base == "dark":
        bg, text, track = "#1e1e1e", "#f0f0f0", "#3a3a3a"
    else:
        bg, text, track = "#ffffff", "#111111", "#e2e5e9"

    placeholder.markdown(
        f"""
        <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                    background: rgba(0,0,0,0.5); z-index: 9999;
                    display: flex; align-items: center; justify-content: center;">
            <div style="background: {bg}; color: {text};
                        padding: 24px 32px; border-radius: 12px; font-size: 15px;
                        min-width: 320px;">
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px;">
                    <div style="width: 18px; height: 18px; border: 2px solid {text};
                                border-top-color: transparent; border-radius: 50%;
                                animation: spin 0.8s linear infinite; flex-shrink: 0;"></div>
                    <div>{message}</div>
                </div>
                <div style="width: 100%; height: 6px; background: {track};
                            border-radius: 3px; overflow: hidden;">
                    <div style="width: {progress}%; height: 100%; background: #ff4b4b;
                                border-radius: 3px; transition: width 0.3s ease;"></div>
                </div>
            </div>
        </div>
        <style>
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def start_progress_overlay(steps: list[str]):
    """Show a full-page dimmed overlay that steps through `steps`, one at
    a time, with a proportional progress bar. Returns (placeholder,
    advance) — call advance(i) right before starting step i (0-indexed);
    the bar reflects i / len(steps) steps already completed. Call
    placeholder.empty() once the whole operation finishes."""
    placeholder = st.empty()
    total = len(steps)

    def advance(i: int) -> None:
        render_overlay(placeholder, steps[i], int(i / total * 100))

    advance(0)
    return placeholder, advance
