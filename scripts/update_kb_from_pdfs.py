"""
Update all 3 KB files with PDF-verified fee data from official BCREC website.
Usage: python scripts/update_kb_from_pdfs.py
"""
import json, os, sys
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parent.parent

# PDF-verified values from B.Tech Fee Structure 2026-30
# CSE/IT/ECE: per sem recurring = 73,925
# EE/AIML/DS/CY/CSD: per sem recurring = 67,600
# ME/CE: per sem recurring = 50,350
# One-time fees (all groups): admission 10,000 + caution 5,000 + MAKAUT SDF 2,200 + MAKAUT regn 500 + prospectus 1,000 + dress kit 6,600 = 25,300
# 8th sem extra: degree cert 1,000

def compute_total(per_sem, admission, caution, sdf, regn, prospectus, dress_kit, degree_cert):
    """Compute total fee = 8 sems recurring + one-time fees + degree cert"""
    recurring = per_sem * 8
    one_time = admission + caution + sdf + regn + prospectus + dress_kit
    return recurring + one_time + degree_cert

# Fee group definitions from PDF
fee_groups = {
    "CSE": {"per_sem": 73925, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 60500, "devt": 9075},
    "IT": {"per_sem": 73925, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 60500, "devt": 9075},
    "ECE": {"per_sem": 73925, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 60500, "devt": 9075},
    "EE": {"per_sem": 67600, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 55000, "devt": 8250},
    "AIML": {"per_sem": 67600, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 55000, "devt": 8250},
    "DS": {"per_sem": 67600, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 55000, "devt": 8250},
    "CY": {"per_sem": 67600, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 55000, "devt": 8250},
    "CSD": {"per_sem": 67600, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 55000, "devt": 8250},
    "ME": {"per_sem": 50350, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 40000, "devt": 6000},
    "CE": {"per_sem": 50350, "admission": 10000, "caution": 5000, "sdf": 2200, "regn": 500, "prospectus": 1000, "dress_kit": 6600, "degree_cert": 1000, "tuition": 40000, "devt": 6000},
}

for code, g in fee_groups.items():
    g["total"] = compute_total(g["per_sem"], g["admission"], g["caution"], g["sdf"], g["regn"], g["prospectus"], g["dress_kit"], g["degree_cert"])
    print(f"{code}: per_sem={g['per_sem']}, total={g['total']}, admission_first_sem={g['per_sem'] + g['admission'] + g['caution'] + g['sdf'] + g['regn'] + g['prospectus'] + g['dress_kit']}")

# MCA from PDF: Tuition 90,000/yr, Library 2,000/yr, Welfare 2,000/yr, Exam 1,600/sem
# 2 years = 4 sems
# Per sem (college fee): 45,000
# Admission: 5,000, Caution: 5,000 (without hostel), Regn: 500, MAKAUT SDF: 1,100, Degree Cert: 1,000/yr, Prospectus: 1,000, Dress Kit: 6,600
# Total without hostel: 67,800 (1st sem) + subsequent sems
# MCA total without hostel over 2 years:
mca_per_sem = 45000 + 1000 + 1000 + 1600  # college fee + library + welfare + exam = 48,600
mca_one_time = 5000 + 500 + 1100 + 1000 + 1000 + 6600  # admission + regn + sdf + degree + prospectus + dress = 15,200
mca_caution = 5000  # refundable
mca_total = mca_per_sem * 4 + mca_one_time  # 48600*4 + 15200 = 209,600
print(f"\nMCA: per_sem={mca_per_sem}, total={mca_total}")

# MBA from PDF: Tuition 1,86,000/yr, Library 4,000/yr, Student Activity 2,000/yr, Prof Training 5,000/yr, Exam 1,600/sem
# Per sem (college fee): 93,000
# Admission: 10,000, Caution: 5,000, Regn: 1,100, Journal: 1,200, MAKAUT SDF: 1,100, Dress Kit: 7,200
mba_admission_total = 10000 + 5000 + 1100 + 1200 + 1100 + 7200  # = 25,600
mba_per_sem = 93000 + 2000 + 1000 + 2500 + 1600  # college + library + activity + training + exam
# Actually from PDF: first sem without hostel = 1,21,400
# Total for 2 years = 1st sem total + subsequent sems
print(f"\nMBA: admission total (1st sem without hostel)={121400}")

print("\n=== UPDATING KB FILES ===")

# 1. Update knowledge_base.json
kb_path = ROOT / "backend" / "data" / "knowledge_base.json"
with open(kb_path, encoding="utf-8") as f:
    kb = json.load(f)

for dept_key, dept_data in kb.get("courses", {}).get("btech", {}).items():
    if dept_key in fee_groups:
        g = fee_groups[dept_key]
        dept_data["fees"]["total"] = g["total"]
        dept_data["fees"]["admission"] = g["admission"]
        old_per_sem = dept_data["fees"].get("per_semester", 0)
        dept_data["fees"]["per_semester"] = g["per_sem"]
        dept_data["fees"]["tuition_per_sem"] = g["tuition"]
        dept_data["fees"]["development_fee_per_sem"] = g["devt"]
        dept_data["fees"]["caution_money_refundable"] = g["caution"]
        print(f"  Updated {dept_key}: total {dept_data['fees']['total']} (was {old_per_sem} per_sem)")

# Update fee summary
if "fees_summary" in kb:
    fs = kb["fees_summary"]
    g1 = fee_groups["CSE"]
    g2 = fee_groups["EE"]
    g3 = fee_groups["ME"]
    fs["btech_cse_it_ece"]["total"] = f"Rs. {g1['total']:,}"
    fs["btech_cse_it_ece"]["per_semester"] = f"Rs. {g1['per_sem']:,}"
    fs["btech_ee_aiml_ds_cy_csd"]["total"] = f"Rs. {g2['total']:,}"
    fs["btech_ee_aiml_ds_cy_csd"]["per_semester"] = f"Rs. {g2['per_sem']:,}"
    fs["btech_me_ce"]["total"] = f"Rs. {g3['total']:,}"
    fs["btech_me_ce"]["per_semester"] = f"Rs. {g3['per_sem']:,}"
    print("  Updated fees_summary section")

# Update MCA fee
if "courses" in kb and "mca" in kb["courses"]:
    kb["courses"]["mca"]["fees"]["total"] = mca_total
    print(f"  Updated MCA total to {mca_total}")

# Update caution money in hostel
if "hostel" in kb:
    h = kb["hostel"]
    h["caution_money"]["hostel_caution_deposit"] = 2000
    h["caution_money"]["admission_caution_without_hostel"] = 5000
    h["caution_money"]["admission_caution_with_hostel"] = 7000
    h["mess"]["monthly_charge"] = 5500
    print("  Updated hostel caution money and mess charge")

# Update placements - add NIRF verified placement data
if "placements" in kb:
    p = kb["placements"]
    # NIRF 2026 data: Median salary for 2024-25 batch = 386000
    p["nirf_median_salary_2025"] = "Rs. 3,86,000"
    p["nirf_students_placed_2025"] = 503
    p["nirf_higher_studies_2025"] = 42
    print("  Added NIRF 2026 placement data")

kb["meta"]["last_updated"] = "2026-07-08"
kb["meta"]["version"] = "1.0.2"
kb["meta"]["data_source"] = "Official BCREC website + fee structure PDFs (2026-30)"

with open(kb_path, "w", encoding="utf-8") as f:
    json.dump(kb, f, indent=2, ensure_ascii=False)
print(f"  Saved {kb_path}")

# 2. Update combined_kb.json
combined_path = ROOT / "backend" / "data" / "knowledge_base" / "combined_kb.json"
with open(combined_path, encoding="utf-8") as f:
    combined = json.load(f)

for dept_key, dept_data in combined.get("courses", {}).get("btech", {}).items():
    if dept_key in fee_groups:
        g = fee_groups[dept_key]
        dept_data["fees"]["total"] = g["total"]
        dept_data["fees"]["admission"] = g["admission"]
        dept_data["fees"]["per_semester"] = g["per_sem"]
        dept_data["fees"]["tuition_per_sem"] = g["tuition"]
        dept_data["fees"]["development_fee_per_sem"] = g["devt"]
        dept_data["fees"]["caution_money_refundable"] = g["caution"]

# Update fee summary
if "fees_summary" in combined:
    fs = combined["fees_summary"]
    g1 = fee_groups["CSE"]
    g2 = fee_groups["EE"]
    g3 = fee_groups["ME"]
    fs["btech_cse_it_ece"]["total"] = f"Rs. {g1['total']:,}"
    fs["btech_cse_it_ece"]["per_semester"] = f"Rs. {g1['per_sem']:,}"
    fs["btech_ee_aiml_ds_cy_csd"]["total"] = f"Rs. {g2['total']:,}"
    fs["btech_ee_aiml_ds_cy_csd"]["per_semester"] = f"Rs. {g2['per_sem']:,}"
    fs["btech_me_ce"]["total"] = f"Rs. {g3['total']:,}"
    fs["btech_me_ce"]["per_semester"] = f"Rs. {g3['per_sem']:,}"

# Update MCA
if "courses" in combined and "mca" in combined["courses"]:
    combined["courses"]["mca"]["fees"]["total"] = mca_total

# Update hostel
if "hostel" in combined:
    combined["hostel"]["mess"]["monthly_charge"] = 5500
    combined["hostel"]["caution_money"] = "Rs. 2,000 (hostel caution deposit) / Rs. 5,000 (without hostel) / Rs. 7,000 (with hostel) as admission caution deposit. All refundable."

# Update quick_answers
if "quick_answers" in combined:
    qa = combined["quick_answers"]
    g1 = fee_groups["CSE"]
    g2 = fee_groups["EE"]
    g3 = fee_groups["ME"]
    qa["btech_fee"] = f"B.Tech total fees range from Rs. {g3['total']:,} to Rs. {g1['total']:,} depending on branch. CSE/IT/ECE: Rs. {g1['total']:,}. EE/AIML/DS/CY/CSD: Rs. {g2['total']:,}. ME/CE: Rs. {g3['total']:,}."
    qa["hostel_fee"] = "Hostel is optional. Seat rent: Rs. 10,000 per semester. Mess charges: Rs. 5,500 per month. Caution deposit: Rs. 2,000 (hostel) or Rs. 5,000 (without hostel) / Rs. 7,000 (with hostel), refundable."

# Update placements
if "placements" in combined:
    combined["placements"]["nirf_median_salary_2025"] = "Rs. 3,86,000"

combined["meta"]["last_updated"] = "July 2026"
combined["meta"]["version"] = "1.0.2"
combined["meta"]["data_source"] = "Official BCREC website + fee structure PDFs (2026-30)"

with open(combined_path, "w", encoding="utf-8") as f:
    json.dump(combined, f, indent=2, ensure_ascii=False)
print(f"  Saved {combined_path}")

# 3. Update canonical_kb.json
canon_path = ROOT / "backend" / "data" / "canonical" / "canonical_kb.json"
with open(canon_path, encoding="utf-8") as f:
    canon = json.load(f)

for dept_key, dept_data in canon.get("courses", {}).get("btech", {}).items():
    if dept_key in fee_groups:
        g = fee_groups[dept_key]
        fees = dept_data.get("fees", {})
        fees["total"] = {"value": g["total"], "provenance": {"source_type": "pdf", "source_url": "https://bcrec.ac.in/public/pdf/B.Tech-Fee-Structure-2026-2030-1.pdf", "date_verified": "2026-07-08", "confidence": "high"}}
        fees["admission"] = {"value": g["admission"], "provenance": {"source_type": "pdf", "date_verified": "2026-07-08", "confidence": "high"}}
        fees["per_semester"] = {"value": g["per_sem"], "provenance": {"source_type": "pdf", "date_verified": "2026-07-08", "confidence": "high"}}
        fees["caution_money"] = {"value": g["caution"], "provenance": {"source_type": "pdf", "date_verified": "2026-07-08", "confidence": "high"}}

# Update hostel in canonical
if "hostel" in canon:
    can_h = canon["hostel"]
    can_h["mess"] = can_h.get("mess", {})
    can_h["mess"]["monthly_charge"] = {"value": 5500, "provenance": {"source_type": "pdf", "source_url": "https://bcrec.ac.in/public/pdf/MBA-Fee-Structure-2026-2028.pdf", "date_verified": "2026-07-08", "confidence": "high", "notes": "Mess charge from MBA fee PDF: Rs. 5,500 per month"}}

# Update placements
if "placements" in canon:
    can_p = canon["placements"]
    can_p["nirf_median_salary_2025"] = {"value": "Rs. 3,86,000", "provenance": {"source_type": "pdf", "source_url": "https://bcrec.ac.in/public/pdf/NIRF2026.pdf", "date_verified": "2026-07-08", "confidence": "high"}}

canon["meta"]["version"] = "1.0.2"
canon["meta"]["last_updated"] = "2026-07-08"
canon["meta"]["_provenance"]["date_verified"] = "2026-07-08"
canon["meta"]["_provenance"]["notes"] = "All fee data verified from official BCREC fee structure PDFs (2026-30)"

with open(canon_path, "w", encoding="utf-8") as f:
    json.dump(canon, f, indent=2, ensure_ascii=False)
print(f"  Saved {canon_path}")

print("\n=== DONE ===")
