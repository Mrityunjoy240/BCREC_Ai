import subprocess, sys, os, json, re
from pathlib import Path

# Try pdftotext first, fall back to pypdf
downloads = Path(__file__).resolve().parent.parent / "downloads"

def extract_with_pdftotext(pdf_path):
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except FileNotFoundError:
        pass
    return None

def extract_with_pypdf(pdf_path):
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"PYPDF_ERROR: {e}"

pdfs = [
    "BTech_Fee_2026_2030.pdf",
    "BTech_Lateral_Fee.pdf",
    "MTech_Fee_2026.pdf",
    "MCA_Fee_2026.pdf",
    "MBA_Fee_2026_2028.pdf",
    "MBA_HM_Fee.pdf",
    "NIRF_2026.pdf",
]

for pdf_name in pdfs:
    pdf_path = downloads / pdf_name
    print(f"\n{'='*60}")
    print(f"FILE: {pdf_name} ({pdf_path.stat().st_size} bytes)")
    print(f"{'='*60}")
    
    text = extract_with_pdftotext(pdf_path)
    if text is None:
        text = extract_with_pypdf(pdf_path)
    
    # Print first 2000 chars
    print(text[:2000])
    if len(text) > 2000:
        print(f"\n... (truncated, total {len(text)} chars)")
