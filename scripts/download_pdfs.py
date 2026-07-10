import requests, os

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
s.get("https://bcrec.ac.in", timeout=30)

base = "https://bcrec.ac.in/public/pdf"
pdfs = {
    "BTech_Fee_2026_2030": "B.Tech-Fee-Structure-2026-2030-1.pdf",
    "BTech_Lateral_Fee": "B-Tech-Lat-N-1.pdf",
    "MTech_Fee_2026": "M-Tech-Fees-2026-1.pdf",
    "MCA_Fee_2026": "MCA-Fee-2026-1.pdf",
    "MBA_Fee_2026_2028": "Fee%20Structure%20MBA%202026-2028.pdf",
    "MBA_HM_Fee": "MBA-%28HM%29-1.pdf",
    "NIRF_2026": "NIRF2026_Dr.%20B.C.%20Roy%20Engineering%20College,%20Durgapur20260316.pdf",
    "AICTE_Approval_2026_27": "EOA%20Report%202026-2027.PDF",
}

out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads")
os.makedirs(out_dir, exist_ok=True)

for name, fname in pdfs.items():
    url = f"{base}/{fname}"
    try:
        r = s.get(url, timeout=60)
        is_pdf = r.content[:4] == b"%PDF"
        ct = r.headers.get("Content-Type", "")
        print(f"{name}: status={r.status_code}, size={len(r.content)} bytes, is_pdf={is_pdf}, type={ct}")
        if is_pdf:
            fp = os.path.join(out_dir, f"{name}.pdf")
            with open(fp, "wb") as f:
                f.write(r.content)
            print(f"  -> Saved: {fp}")
        else:
            print(f"  -> NOT a PDF - first bytes: {r.content[:50]}")
    except Exception as e:
        print(f"{name}: FAILED - {e}")
