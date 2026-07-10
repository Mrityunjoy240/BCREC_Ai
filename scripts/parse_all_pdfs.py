from pypdf import PdfReader
from pathlib import Path
import json, re

downloads = Path(__file__).resolve().parent.parent / "downloads"
output = {}

for pdf_name in sorted(downloads.glob("*.pdf")):
    name = pdf_name.stem
    reader = PdfReader(str(pdf_name))
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    
    output[name] = {
        "size": pdf_name.stat().st_size,
        "pages": len(reader.pages),
        "text_preview": text[:3000]
    }
    
    # Try to extract total fee amounts
    amounts = re.findall(r'(?:Rs\.|Rs)\s*([\d,]+)=?00', text)
    totals = [a for a in amounts if len(a.replace(",","")) >= 5]
    if totals:
        output[name]["extracted_amounts"] = totals[:20]
    
    print(f"\n{'='*60}")
    print(f"{name} ({pdf_name.stat().st_size} bytes, {len(reader.pages)} pages)")
    print(f"{'='*60}")
    print(text[:2500])
    if len(text) > 2500:
        print(f"... ({len(text)} total chars)")

Path("downloads/parsed_data.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
print("\n\nSaved to downloads/parsed_data.json")
