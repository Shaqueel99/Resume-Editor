"""docx_editor.py

Applies LLM-suggested changes to a résumé .docx file:
  1. replace_bullets()      — find-and-replace existing bullets with
                               accepted rewrite suggestions.
  2. append_new_section()   — add a new "Additional Skills/Experience"
                               section at the end of the document, with
                               one or more newly drafted bullets.

Both operations work on python-docx Document objects and save a new
file, leaving the original untouched.
"""

from docx import Document
from docx.text.paragraph import Paragraph


def _replace_text_in_paragraph(paragraph: Paragraph, old_text: str, new_text: str) -> bool:
    """Replace old_text with new_text inside a single paragraph, handling
    the case where the target text is split across multiple runs.

    python-docx stores a paragraph's text as a list of "runs" (chunks
    with consistent formatting). A naive per-run string replace silently
    fails whenever the target text crosses a run boundary — which is
    common, since Word splits runs on any formatting change, spellcheck
    marker, or even sometimes with no visible reason at all.

    Strategy: concatenate all run texts to check for a match, then walk
    the runs, insert the new text as a single run in place of the first
    matched run, and clear the text of every run that is part of the
    original span (rather than deleting the runs, which is disruptive to
    other paragraph internals) so the paragraph keeps just one run
    carrying the correct new text.

    Returns True if a replacement was made, False if old_text was not
    found in this paragraph at all.
    """
    full_text = "".join(run.text for run in paragraph.runs)
    if old_text not in full_text:
        return False

    start = full_text.find(old_text)
    end = start + len(old_text)

    pos = 0
    replaced = False
    for run in paragraph.runs:
        run_start = pos
        run_end = pos + len(run.text)
        pos = run_end

        # Does this run overlap the target span at all?
        if run_end <= start or run_start >= end:
            continue  # run is entirely outside the target span

        if not replaced:
            # First overlapping run: put the new text here.
            run.text = new_text
            replaced = True
        else:
            # Any further overlapping run: clear it, its old content is
            # now represented by the first run's replacement.
            run.text = ""

    return replaced


def replace_bullets(doc_path: str, out_path: str, replacements: list[dict]) -> dict:
    """Apply accepted bullet rewrites to a résumé .docx.

    Args:
        doc_path: Path to the original .docx.
        out_path: Path to save the edited .docx.
        replacements: List of {"original_text": str, "suggested_text": str}
            dicts — typically the user-accepted subset of
            ASSISTANT_PROMPT's "bullet_rewrites" output.

    Returns:
        A dict reporting which replacements succeeded and which could not
        be located in the document (e.g. if the LLM's "original_text"
        did not exactly match the source, or matched text that spans
        multiple paragraphs).
    """
    doc = Document(doc_path)
    applied, not_found = [], []

    for item in replacements:
        old_text = item["original_text"]
        new_text = item["suggested_text"]
        found = False

        for paragraph in doc.paragraphs:
            if _replace_text_in_paragraph(paragraph, old_text, new_text):
                found = True
                break  # assume each bullet appears once; stop at first match

        (applied if found else not_found).append(item)

    doc.save(out_path)
    return {"applied": applied, "not_found": not_found}


def append_new_section(doc_path: str, out_path: str, new_bullets: list[str],
                        heading: str = "Additional Skills / Experience") -> None:
    """Append a new section with one or more bullets to the end of a résumé.

    Uses the document's existing "Heading 1" / "List Bullet" styles if
    present, so the new section visually matches the rest of the résumé.
    Falls back to plain paragraphs if those styles don't exist in this
    document's template.

    Args:
        doc_path: Path to the original .docx (or an already-edited one,
            if called after replace_bullets in the same session).
        out_path: Path to save the result.
        new_bullets: Plain bullet text strings to add, e.g. from
            DRAFT_NEW_BULLET_PROMPT's "new_bullet" field.
        heading: Section heading text.
    """
    doc = Document(doc_path)

    style_names = {s.name for s in doc.styles}
    heading_style = "Heading 1" if "Heading 1" in style_names else None
    bullet_style = "List Bullet" if "List Bullet" in style_names else None

    doc.add_paragraph(heading, style=heading_style) if heading_style else doc.add_paragraph(heading)

    for bullet_text in new_bullets:
        if bullet_style:
            doc.add_paragraph(bullet_text, style=bullet_style)
        else:
            doc.add_paragraph(f"• {bullet_text}")

    doc.save(out_path)