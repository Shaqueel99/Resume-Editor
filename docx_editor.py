"""docx_editor.py

Applies LLM-suggested changes to a résumé .docx file:
  1. replace_bullets()          — find-and-replace existing bullets with
                                   accepted rewrite suggestions.
  2. append_new_section()       — add a new "Additional Skills/Experience"
                                   section at the end of the document, with
                                   one or more newly drafted bullets.
  3. list_bullet_entries()      — deterministically parse the existing
                                   Work Experience / Project entries (and
                                   their bullet lists) out of the .docx, so
                                   the caller can offer them as insertion
                                   targets.
  4. insert_bullets_into_entries() — insert new bullets after a specific
                                   existing entry's last bullet, instead of
                                   only ever appending a new section.

All operations work on python-docx Document objects and save a new
file, leaving the original untouched.
"""

from copy import deepcopy

from docx import Document
from docx.oxml.ns import qn
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


def _is_bullet_paragraph(paragraph: Paragraph) -> bool:
    """Heuristically detect a résumé bullet-list item, since templates vary
    in how they mark one: a named list style, direct Word list formatting
    (numPr), or a manually-typed bullet character."""
    style_name = paragraph.style.name if paragraph.style else ""
    if "List Bullet" in style_name or "List Paragraph" in style_name:
        return True

    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:numPr")) is not None:
        return True

    text = paragraph.text.strip()
    return bool(text) and text[0] in "•‣▪◦-*"


def _copy_paragraph_format(source: Paragraph, target: Paragraph) -> None:
    """Copy list numbering (bullet/indent) from an existing bullet
    paragraph onto a newly created one, for templates where bullets come
    from direct list formatting rather than a named paragraph style."""
    src_pPr = source._p.find(qn("w:pPr"))
    if src_pPr is None:
        return
    src_numPr = src_pPr.find(qn("w:numPr"))
    if src_numPr is None:
        return
    target._p.get_or_add_pPr().append(deepcopy(src_numPr))


def _manual_bullet_prefix(paragraph: Paragraph) -> str:
    """If a bullet's look comes from a literal leading character (no named
    list style, no Word list numbering — just typed "• text"), return that
    character plus one space, so a newly inserted bullet matches it. Real
    list-style/numPr bullets render their glyph automatically and need no
    prefix, so this returns "" for those."""
    style_name = paragraph.style.name if paragraph.style else ""
    if "List Bullet" in style_name or "List Paragraph" in style_name:
        return ""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None and pPr.find(qn("w:numPr")) is not None:
        return ""
    text = paragraph.text.strip()
    if text and text[0] in "•‣▪◦-*":
        return text[0] + " "
    return ""


def list_bullet_entries(doc_path: str) -> list[dict]:
    """Scan a résumé for existing Work Experience / Project entries that
    have their own bullet list, so the caller can offer "add this new
    bullet to an existing entry" as an alternative to appending a brand
    new section.

    An entry is a run of consecutive bullet paragraphs, labeled with the
    nearest preceding non-bullet line of text (its job/project title) and
    the nearest preceding heading-styled paragraph (its section, e.g.
    "WORK EXPERIENCE"), if the document uses named heading styles at all.

    Returns a list of dicts: {"section": str, "title": str,
    "anchor_index": int}, where "anchor_index" is the paragraph index of
    that entry's LAST bullet — the position insert_bullets_into_entries()
    inserts a new bullet after. Indices are only valid against the exact
    doc_path they were read from; re-read after any edit that adds or
    removes paragraphs.
    """
    doc = Document(doc_path)
    entries: list[dict] = []
    current_section = ""
    pending_title = ""
    in_entry = False

    for i, paragraph in enumerate(doc.paragraphs):
        style_name = paragraph.style.name if paragraph.style else ""
        text = paragraph.text.strip()

        if style_name.startswith("Heading"):
            current_section = text
            pending_title = ""
            in_entry = False
            continue

        if _is_bullet_paragraph(paragraph):
            if in_entry:
                entries[-1]["anchor_index"] = i
            else:
                entries.append({
                    "section": current_section,
                    "title": pending_title,
                    "anchor_index": i,
                })
                in_entry = True
            continue

        if text:
            pending_title = text
            in_entry = False

    return entries


def insert_bullets_into_entries(doc_path: str, out_path: str,
                                 entry_bullets: dict[int, list[str]]) -> None:
    """Insert new bullets after specific existing entries, e.g. adding a
    drafted skill-gap bullet into an existing Work Experience or Project
    entry instead of a brand-new section.

    Args:
        doc_path: Path to the .docx to edit.
        out_path: Path to save the result.
        entry_bullets: Maps an "anchor_index" (from list_bullet_entries(),
            read from THIS SAME doc_path before any other edit shifts
            paragraph positions) to the bullet strings to insert there, in
            order.
    """
    doc = Document(doc_path)
    paragraphs = doc.paragraphs

    for anchor_index, bullets in entry_bullets.items():
        if not (0 <= anchor_index < len(paragraphs)):
            continue
        anchor = paragraphs[anchor_index]
        for bullet_text in bullets:
            text = _manual_bullet_prefix(anchor) + bullet_text
            new_paragraph = doc.add_paragraph(text, style=anchor.style)
            _copy_paragraph_format(anchor, new_paragraph)
            anchor._p.addnext(new_paragraph._p)
            anchor = new_paragraph

    doc.save(out_path)