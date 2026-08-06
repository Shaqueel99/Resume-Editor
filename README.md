# Resume Editor — Résumé Fit Checker & Cover Letter Generator

A Streamlit app that compares your résumé against a job description, scores how well it matches, rewrites weak spots to surface the job description's own terminology, and edits your résumé in place — preserving your original formatting, fonts, and layout, unlike most AI tools that regenerate the whole document from scratch. A second tool drafts a tailored cover letter from the same inputs.

## Problem Statement

Tailoring a résumé and cover letter to every job posting is tedious, and it's easy to miss required keywords that ATS (applicant tracking system) filters and recruiters scan for. This app automates that comparison: it tells you exactly which required skills your résumé is missing, suggests wording changes anchored to your real bullet points (never invented experience), applies accepted edits directly back into the original document without disturbing its formatting, and drafts a cover letter grounded in the same résumé-to-job-description analysis — saving the manual re-reading, re-writing, and re-formatting normally needed for each application.

## Technology Stack

- **Language:** Python
- **UI:** Streamlit (`streamlit`, `streamlit-scroll-to-top`)
- **AI API:** Google Gemini API, accessed through `litellm` (`litellm` also lets you swap in OpenAI, Anthropic Claude, or a local Ollama model by changing one environment variable — no code changes)
- **Document handling:** `python-docx` (read/write `.docx` résumés and cover letters), `mammoth` (résumé preview), `pypdf` (PDF input support)
- **Config:** `python-dotenv`

## Setup Instructions

1. Clone the repository:
   ```
   git clone <this-repo-url>
   cd Resume-Editor
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root and set which model to use. For Google Gemini:
   ```
   MODEL=gemini/gemini-3.5-flash
   GEMINI_API_KEY=your-gemini-api-key
   ```
   Other supported options (set `MODEL` and the matching key/host):
   - OpenAI: `MODEL=openai/gpt-4o-mini`, `OPENAI_API_KEY=...`
   - Anthropic: `MODEL=anthropic/claude-3-5-sonnet-20241022`, `ANTHROPIC_API_KEY=...`
   - Local Ollama (no API key, more consistent, requires `ollama serve` running): `MODEL=ollama/gemma4:e2b`, `OLLAMA_API_BASE=http://localhost:11434`
4. Run the application:
   ```
   streamlit run app.py
   ```
5. Open the URL Streamlit prints (default `http://localhost:8501`). Use the sidebar to switch between **Résumé fit checker** and **Cover letter generator**.

## Usage Examples

**Example 1 — Résumé fit checker**
- **Input:** Upload a `.docx` résumé that includes the bullet "Managed Linux servers and automated deployments with Bash scripts," and paste a job description requiring "Kubernetes" and "CI/CD."
- **Output:** A match score (e.g. `67/100`), a list of matched vs. missing required skills, a rewrite suggestion for the Bash-scripting bullet that surfaces "CI/CD" (only if genuinely implied by the original wording), and a "Kubernetes" skill gap card explaining why it's missing and offering to draft a new bullet from experience you describe.

**Example 2 — Cover letter generator**
- **Input:** The same résumé and job description, then a follow-up message: "make the opening shorter."
- **Output:** A draft cover letter broken into labelled sections (Greeting, Opening, Why you're a fit, Addressing the gaps, Closing, Sign-off), grounded in your actual résumé bullets. After the follow-up message, only the Opening section is rewritten (shorter), and a "Shortened the opening per feedback" note is logged in the revision chat — the rest of the letter carries over unchanged.

## Known Limitations

- **LLM rate limits and consistency:** the free tier of the Gemini API can rate-limit or slow down analysis, since each page makes several sequential calls (skill extraction, gap analysis, bullet rewrites, cover letter draft). Running a local model via Ollama avoids rate limits and gives more consistent results, but is slower and less capable than Gemini on typical hardware.
- **Skill gap detection is inconsistent between calls:** the deterministic match score and the LLM-generated "Skill gaps" list come from two independent code paths, so a skill the score row marks as missing doesn't always appear in the Skill gaps section on the first pass — it sometimes only shows up after running "Apply changes and rescore" a second time.

## Future Improvements

- Let the user pick which specific existing bullet point a suggestion should replace (or insert next to), with the new text automatically matching the surrounding formatting, instead of only auto-anchoring to text matches or appending to a detected entry.
- Support adding an entire new résumé entry — job title, company, and dates — with its own bullet points underneath, rather than only inserting bullets into an existing entry or a generic "Additional Skills" section.
