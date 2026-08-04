import streamlit as st
import tempfile
import traceback
from pathlib import Path
from dotenv import load_dotenv

from parse import read_resume_pdf
from analyzer import (
    extract_resume_profile, extract_jd_profile, analyse_keyword_match,
    analyse_bullets, analyse_jargon, analyse_structure,
    analyse_degree_alignment, summarise_overall, compute_overall_score,
)

load_dotenv()
VALID_DEGREES = ["RTIS", "IMGD", "UXGD", "BFA"]

st.set_page_config(page_title="Resume Analyzer", layout="wide")
st.title("📄 AI Resume Analyzer")

if "report" not in st.session_state:
    st.session_state.report = None

resume_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])
jd_text = st.text_area("Paste Job Description", height=250)
degree = st.selectbox("Select Degree", VALID_DEGREES)
run = st.button("Analyze Resume")


def safe_call(label, fn, *args):
    """Run an LLM-calling function, surfacing the real error in the UI on failure."""
    try:
        return fn(*args)
    except Exception as e:
        st.error(f"{label} failed: {e}")
        st.code(traceback.format_exc())
        st.stop()


if run:
    if not resume_file or not jd_text:
        st.error("Please upload resume and paste job description.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(resume_file.getvalue())
        tmp_path = tmp.name

    try:
        with st.spinner("Parsing résumé..."):
            resume_text = read_resume_pdf(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    with st.spinner("Extracting résumé profile..."):
        resume_profile = safe_call("Extract résumé profile", extract_resume_profile, resume_text)

    with st.spinner("Extracting JD profile..."):
        jd_profile = safe_call("Extract JD profile", extract_jd_profile, jd_text)

    with st.spinner("Matching keywords..."):
        keyword_match = safe_call("Keyword match", analyse_keyword_match, resume_profile, jd_profile)

    with st.spinner("Auditing bullets..."):
        bullets = safe_call("Bullet audit", analyse_bullets, resume_profile)

    with st.spinner("Checking jargon..."):
        jargon = safe_call("Jargon audit", analyse_jargon, resume_profile, jd_profile)

    with st.spinner("Checking structure..."):
        structure = safe_call("Structure audit", analyse_structure, resume_text)

    with st.spinner("Checking degree alignment..."):
        degree_alignment = safe_call("Degree alignment", analyse_degree_alignment, jd_profile, degree)

    report: dict[str, object] = {
        "resume_profile": resume_profile,
        "jd_profile": jd_profile,
        "keyword_match": keyword_match,
        "bullets": bullets,
        "jargon": jargon,
        "structure": structure,
        "degree_alignment": degree_alignment,
    }
    report["overall_score"] = compute_overall_score(report)
    report["passes_ats_threshold"] = report["overall_score"] >= 60

    with st.spinner("Generating summary..."):
        report["summary"] = safe_call("Summary", summarise_overall, report)

    st.session_state.report = report

if st.session_state.report:
    report = st.session_state.report
    score = report["overall_score"]
    verdict = "✅ PASS" if report["passes_ats_threshold"] else "❌ FAIL"

    col1, col2 = st.columns(2)
    col1.metric("Overall Score", f"{score}/100")
    col2.metric("ATS Threshold (60)", verdict)

    st.subheader("Summary")
    st.write(report["summary"])

    with st.expander("Keyword Match"):
        st.json(report["keyword_match"])
    with st.expander("Bullet Audit"):
        st.json(report["bullets"])
    with st.expander("Jargon Check"):
        st.json(report["jargon"])
    with st.expander("Structure"):
        st.json(report["structure"])
    with st.expander("Degree Alignment"):
        st.json(report["degree_alignment"])