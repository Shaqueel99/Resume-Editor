# Résumé × JD Analyzer — Track B Starter

> **Track B** — you vibe-code with Claude. `main.py` is already working. You build the three modules (`parse.py`, `prompts.py`, `analyzer.py`) using Claude.ai as your AI coding tutor.

## Quick setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy .env.example and fill in your API key
cp .env.example .env
# Edit .env — defaults to a local Ollama model; see comments for OpenAI/Anthropic
```

## Run the analyzer

```bash
python main.py path/to/your_resume.pdf inputs/job_rtis_systems_engineer.txt
```

Reports are saved to `outputs/` as both `.json` and `.md`.

## File guide

| File | Your job |
|---|---|
| `parse.py` | ✏️ **Build with Claude** — Task 1 |
| `prompts.py` | ✏️ **Build with Claude** — Task 3 |
| `analyzer.py` | ✏️ **Build with Claude** — Task 4 |
| `main.py` | ✅ Pre-provided and complete — read it as your blueprint |
| `llm.py` | ✅ Pre-provided — read it, don't edit |
| `report.py` | ✅ Pre-provided — read it, don't edit |

## How to build each file

Open **Claude.ai** in your browser and use the paste-into-Claude prompts provided in your tutorial guide (Track B lab, Tasks 1, 3, 4).

Each prompt gives Claude:
- The function signature you need
- The behaviour it must have
- The exact output format
- What _not_ to do (never rewrite résumé content)

Paste Claude's output into the appropriate `.py` file, then run the checkpoint command from your tutorial to verify.

## Progress checkpoints

```bash
# Task 1 checkpoint — parse.py
python -c "from parse import read_jd_text; print(read_jd_text('inputs/job_rtis_systems_engineer.txt')[:200])"

# Task 3 checkpoint — prompts.py
python -c "from prompts import RESUME_PROFILE_PROMPT; print(RESUME_PROFILE_PROMPT[:100])"

# Task 4 checkpoint — analyzer.py
python -c "from analyzer import extract_jd_profile; from parse import read_jd_text; print(extract_jd_profile(read_jd_text('inputs/job_rtis_systems_engineer.txt')))"
```

## Stretch goals

- Change `MODEL=` in `.env` to use a local Ollama model — no code changes needed.
- Ask Claude to add a `--verbose` flag to `main.py` that prints each LLM response.
- Ask Claude to write a Streamlit UI wrapper around the analyzer.
