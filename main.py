# """Résumé × JD Analyzer — CLI entry point."""

# import argparse
# import json
# import sys
# from datetime import datetime
# from pathlib import Path

# from dotenv import load_dotenv

# from parse import read_resume_pdf, read_jd_text
# from analyzer import (
#     extract_resume_profile,
#     extract_jd_profile,
#     analyse_keyword_match,
#     analyse_bullets,
#     analyse_jargon,
#     analyse_structure,
#     analyse_background_fit,
#     summarise_overall,
#     compute_overall_score,
# )
# from report import render_markdown


# def parse_args(argv: list[str]) -> tuple[str, str]:
#     parser = argparse.ArgumentParser(
#         prog="python main.py",
#         description=(
#             "Analyse a PDF résumé against a job description and produce "
#             "a scored report (0–100, 60 = ATS pass threshold)."
#         ),
#     )
#     parser.add_argument("resume", metavar="resume.pdf", help="Path to the PDF résumé")
#     parser.add_argument("job", metavar="job.txt", help="Path to the job description (plain text)")
#     args = parser.parse_args(argv[1:])
#     return args.resume, args.job


# def main() -> int:
#     resume_path, job_path = parse_args(sys.argv)

#     load_dotenv()
#     import os
#     model = os.getenv("MODEL", "openai/gpt-4o-mini")
#     print(f"Using model: {model}")

#     print(f"[1/8] Parsing résumé: {resume_path}")
#     try:
#         resume_text = read_resume_pdf(resume_path)
#     except ValueError as exc:
#         print(f"ERROR: {exc}", file=sys.stderr)
#         return 1

#     print(f"[2/8] Reading JD: {job_path}")
#     try:
#         jd_text = read_jd_text(job_path)
#     except ValueError as exc:
#         print(f"ERROR: {exc}", file=sys.stderr)
#         return 1

#     try:
#         print("[3/8] Extracting résumé profile (LLM)...")
#         resume_profile = extract_resume_profile(resume_text)

#         print("[4/8] Extracting JD profile (LLM)...")
#         jd_profile = extract_jd_profile(jd_text)

#         print("[5/8] Keyword match (LLM)...")
#         keyword_match = analyse_keyword_match(resume_profile, jd_profile)

#         print("[6/8] Bullet audit (LLM)...")
#         bullets = analyse_bullets(resume_profile)

#         print("[7/8] Jargon, structure, background fit (LLM x3)...")
#         jargon         = analyse_jargon(resume_profile, jd_profile)
#         structure      = analyse_structure(resume_text)
#         background_fit = analyse_background_fit(resume_profile, jd_profile)

#     except RuntimeError as exc:
#         print(f"ERROR: {exc}", file=sys.stderr)
#         return 1

#     report = {
#         "meta": {
#             "resume_path": resume_path,
#             "job_path": job_path,
#             "model": model,
#             "generated_at": datetime.now().isoformat(timespec="seconds"),
#         },
#         "resume_profile":  resume_profile,
#         "jd_profile":      jd_profile,
#         "keyword_match":   keyword_match,
#         "bullets":         bullets,
#         "jargon":          jargon,
#         "structure":       structure,
#         "background_fit":  background_fit,
#     }
#     report["overall_score"]       = compute_overall_score(report)
#     report["passes_ats_threshold"] = report["overall_score"] >= 60

#     try:
#         print("[8/8] Final summary (LLM)...")
#         report["summary"] = summarise_overall(report)
#     except RuntimeError as exc:
#         print(f"ERROR: {exc}", file=sys.stderr)
#         return 1

#     ts = datetime.now().strftime("%Y%m%d_%H%M%S")
#     Path("outputs").mkdir(exist_ok=True)
#     json_path = f"outputs/match_report_{ts}.json"
#     md_path   = f"outputs/match_report_{ts}.md"

#     Path(json_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
#     render_markdown(report, out_path=md_path)

#     verdict = "PASS" if report["passes_ats_threshold"] else "FAIL"
#     print()
#     print(
#         f"Score: {report['overall_score']}/100  "
#         f"({verdict} 60% ATS threshold)"
#     )
#     print(f"JSON:  {json_path}")
#     print(f"MD:    {md_path}")
#     print()
#     print(report["summary"])
#     return 0


# if __name__ == "__main__":
#     sys.exit(main())
