"""parse.py

Utilities for extracting text content from a resume PDF and a job
description text file, for downstream processing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_RESUME_CHARS = 24_000
MIN_RESUME_CHARS = 200
MIN_JD_CHARS = 100
MAX_RESUME_PAGES = 2


def read_resume_pdf(path: str) -> str:
    """Extract text from a resume PDF.

    Args:
        path: Path to the PDF file.

    Returns:
        The extracted text, with excessive blank lines collapsed and
        long text truncated to MAX_RESUME_CHARS.

    Raises:
        ValueError: If the file cannot be found or opened, if the
            extracted text is too short (suggesting an image-based
            PDF with no real text layer), or if the file is otherwise
            invalid.
    """
    pdf_path = Path(path)

    if not pdf_path.is_file():
        raise ValueError(f"Resume PDF not found: {path}")

    try:
        reader = PdfReader(str(pdf_path))
    except (PdfReadError, OSError) as exc:
        raise ValueError(f"Could not open resume PDF '{path}': {exc}") from exc

    try:
        num_pages = len(reader.pages)
    except Exception as exc:
        raise ValueError(f"Could not read pages from resume PDF '{path}': {exc}") from exc

    if num_pages > MAX_RESUME_PAGES:
        print(
            f"Warning: resume PDF '{path}' has {num_pages} pages "
            f"(expected at most {MAX_RESUME_PAGES}).",
            file=sys.stderr,
        )

    try:
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ValueError(f"Could not extract text from resume PDF '{path}': {exc}") from exc

    text = "\n\n".join(page_texts)

    # Collapse runs of 3+ blank lines down to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)

    stripped_len = len(text.strip())
    if stripped_len < MIN_RESUME_CHARS:
        raise ValueError(
            f"Resume PDF '{path}' yielded only {stripped_len} characters of text "
            "(minimum 200 expected). The PDF may be image-based / scanned "
            "with no extractable text layer."
        )

    if len(text) > MAX_RESUME_CHARS:
        print(
            f"Warning: resume text from '{path}' is {len(text)} characters; "
            f"truncating to {MAX_RESUME_CHARS}.",
            file=sys.stderr,
        )
        text = text[:MAX_RESUME_CHARS]

    return text


def read_jd_text(path: str) -> str:
    """Read a job description from a UTF-8 plain text file.

    Args:
        path: Path to the text file.

    Returns:
        The file's text content.

    Raises:
        ValueError: If the file cannot be found, cannot be decoded as
            UTF-8, or has fewer than 100 characters after stripping
            whitespace.
    """
    jd_path = Path(path)

    if not jd_path.is_file():
        raise ValueError(f"Job description file not found: {path}")

    try:
        text = jd_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Job description file '{path}' is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read job description file '{path}': {exc}") from exc

    if len(text.strip()) < MIN_JD_CHARS:
        raise ValueError(
            f"Job description file '{path}' has fewer than {MIN_JD_CHARS} "
            "characters of content after stripping whitespace."
        )

    return text