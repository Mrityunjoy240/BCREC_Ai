import requests, json, sys, os, re
from pathlib import Path

BASE = "https://bcrec.ac.in"

pages = {
    "overview": "/overview",
    "contact": "/contact-us",
    "admission": "/custom-page/62a71b1551f19",
    "scholarship": "/custom-page/62a7197e27fc1",
    "placement_info": "/custom-page/631436f1e689f",
    "placements": "/placements",
    "mission-vision": "/mission-vision",
}

print("=== CRAWLING OFFICIAL BCREC WEBSITE ===")
for name, path in pages.items():
    url = BASE + path
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        print(f"[{r.status_code}] {name}: {url} ({len(r.content)} bytes)")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")

# Try fee structure PDFs
pdf_urls = {
    "BTech_Fee": "https://bcrec.ac.in/display-pdf-download/B.Tech-Fee-Structure-2026-2030-1.pdf/Fee%20Structure%20B.Tech",
    "BTech_Lateral_Fee": "https://bcrec.ac.in/display-pdf-download/B-Tech-Lat-N-1.pdf/Fee%20Structure%20B.Tech%20Lateral",
    "MTech_Fee": "https://bcrec.ac.in/display-pdf-download/M-Tech-Fees-2026-1.pdf/Fee%20Structure%20M.Tech",
    "MCA_Fee": "https://bcrec.ac.in/display-pdf-download/MCA-Fee-2026-1.pdf/Fee%20Structure%20MCA",
    "MBA_Fee": "https://bcrec.ac.in/display-pdf-download/Fee%20Structure%20MBA%202026-2028.pdf/Fee%20Structure%20MBA",
    "MBA_HM_Fee": "https://bcrec.ac.in/display-pdf-download/MBA-%28HM%29-1.pdf/Fee%20Structure%20MBA%20%28Hospital%20Management%29",
}

out_dir = Path(__file__).resolve().parent.parent / "uploads"
out_dir.mkdir(exist_ok=True)

for name, url in pdf_urls.items():
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        if "text/html" in r.headers.get("Content-Type", "") and len(r.content) > 5000:
            out_path = out_dir / f"{name}.pdf"
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"[OK] {name}: {len(r.content)} bytes -> {out_path}")
        elif "application/pdf" in r.headers.get("Content-Type", ""):
            out_path = out_dir / f"{name}.pdf"
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"[OK] {name}: {len(r.content)} bytes (PDF) -> {out_path}")
        else:
            print(f"[SKIP] {name}: Content-Type={r.headers.get('Content-Type','')}, size={len(r.content)}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")

print("\nDone.")
