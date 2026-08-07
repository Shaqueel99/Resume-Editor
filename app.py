"""app.py

Entry point. Sets page config once (must happen before any other
Streamlit call) and wires up the sidebar navigation between the app's
two tools:
  - fit_checker_page.py    — the résumé fit checker (score, bullet
                              rewrites, skill-gap bullets).
  - cover_letter_page.py   — the cover letter generator (analyse ->
                              identify gaps -> generate draft, with
                              follow-up revisions).

Both pages keep their own st.session_state keys (fit_checker_page.py's
are unprefixed, cover_letter_page.py's are prefixed cl_), so switching
tabs doesn't lose either one's in-progress state.
"""

import streamlit as st

import cover_letter_page
import fit_checker_page

st.set_page_config(page_title="Résumé editor", layout="wide")

pages = [
    st.Page(fit_checker_page.render, title="Résumé editor", icon="📄",
            url_path="fit-checker", default=True),
    st.Page(cover_letter_page.render, title="Cover letter generator", icon="✉️",
            url_path="cover-letter"),
]

nav = st.navigation(pages)
nav.run()
