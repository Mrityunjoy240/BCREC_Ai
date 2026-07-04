"""
Retrieval Validation Script
============================
Tests 100+ queries against ChromaDB to validate retrieval quality after KB changes.
Reports per-query: top chunks, confidence, correct doc rank #1, conflicts, duplicates.
"""

import sys, os, json, logging
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
logging.basicConfig(level=logging.ERROR)

from app.services.vector_store import get_vector_store

# Load knowledge_base.json for ground truth
kb_path = Path(__file__).resolve().parent.parent / "backend" / "data" / "knowledge_base.json"
combined_kb_path = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "data"
    / "knowledge_base"
    / "combined_kb.json"
)
canonical_kb_path = (
    Path(__file__).resolve().parent.parent / "backend" / "data" / "canonical" / "canonical_kb.json"
)

with open(kb_path, encoding="utf-8") as f:
    kb_data = json.load(f)
with open(combined_kb_path, encoding="utf-8") as f:
    combined_kb = json.load(f)

vs = get_vector_store()
if not vs.vector_store:
    print("ERROR: Vector store not initialized. Run ingestion first.")
    sys.exit(1)

count = vs.vector_store._collection.count()
print(f"Vector store has {count} documents.\n")

# Category-question pairs covering all required areas
test_queries = [
    # ---- Admissions ----
    ("admissions", "What is the eligibility for B.Tech admission?"),
    ("admissions", "How many seats are allocated through WBJEE?"),
    ("admissions", "What is the admission portal URL?"),
    ("admissions", "Is there lateral entry for B.Tech?"),
    ("admissions", "What documents are needed for admission?"),
    ("admissions", "What is the age limit for B.Tech?"),
    ("admissions", "Is there an NRI quota?"),
    ("admissions", "How do I apply online for B.Tech?"),
    ("admissions", "What is the management quota percentage?"),
    ("admissions", "When is the spot round for admission?"),
    ("admissions", "What is the JEE Main quota percentage?"),
    ("admissions", "Who do I contact for admission queries?"),
    # ---- Fees ----
    ("fees", "What is the total fee for B.Tech CSE?"),
    ("fees", "What is the fee for B.Tech ECE?"),
    ("fees", "How much is the B.Tech ME fee?"),
    ("fees", "What is the total fee for MBA?"),
    ("fees", "What is the total fee for MCA?"),
    ("fees", "What is the admission fee for B.Tech CSE?"),
    ("fees", "What is the per semester fee for B.Tech EE?"),
    ("fees", "Is there any hidden charges in fees?"),
    ("fees", "What is the refund policy?"),
    ("fees", "Can I pay fees in installments?"),
    ("fees", "What is the fee for B.Tech CSD?"),
    ("fees", "What payment modes are accepted?"),
    # ---- Hostel ----
    ("hostel", "Is hostel compulsory at BCREC?"),
    ("hostel", "How many hostels are there for boys?"),
    ("hostel", "What is the hostel caution money?"),
    ("hostel", "How much is the mess charge per month?"),
    ("hostel", "What are the hostel curfew timings?"),
    ("hostel", "What facilities are available in hostels?"),
    ("hostel", "How many hostels are there for girls?"),
    ("hostel", "What is the total hostel capacity?"),
    ("hostel", "What room types are available in hostel?"),
    ("hostel", "What meals are served in hostel mess?"),
    # ---- Placements ----
    ("placements", "What is the placement rate of BCREC?"),
    ("placements", "What is the highest placement package?"),
    ("placements", "Which companies visit BCREC for placements?"),
    ("placements", "What is the average placement package?"),
    ("placements", "What is the placement rate for CSE?"),
    ("placements", "Who is the head of Training and Placement?"),
    ("placements", "Does BCREC have internship opportunities?"),
    ("placements", "Which branch has the highest placements?"),
    ("placements", "How many companies visited in 2025?"),
    ("placements", "What training programs are offered for placements?"),
    # ---- Scholarships ----
    ("scholarships", "What scholarships are available at BCREC?"),
    ("scholarships", "What is the TFW scheme?"),
    ("scholarships", "What is the Swami Vivekananda scholarship amount?"),
    ("scholarships", "Who is eligible for Aikyashree scholarship?"),
    ("scholarships", "Is Kanyashree scholarship available?"),
    ("scholarships", "What is the eligibility for merit scholarship?"),
    # ---- Departments ----
    ("departments", "What departments are available at BCREC?"),
    ("departments", "How many B.Tech branches are there?"),
    ("departments", "Does BCREC offer CSE AI ML?"),
    ("departments", "Is there a Cyber Security program?"),
    ("departments", "Is there a Data Science program?"),
    ("departments", "Does BCREC have a Civil Engineering department?"),
    ("departments", "What is the intake for CSE department?"),
    ("departments", "What is the intake for IT department?"),
    ("departments", "Does BCREC offer M.Tech programs?"),
    ("departments", "Is there an MBA program?"),
    # ---- Faculty ----
    ("faculty", "How many faculty members are at BCREC?"),
    ("faculty", "What is the student-teacher ratio?"),
    ("faculty", "Who is the HOD of CSE department?"),
    ("faculty", "Who is the HOD of ECE department?"),
    ("faculty", "Who is the HOD of ME department?"),
    ("faculty", "Who is the HOD of CE department?"),
    ("faculty", "Who is the HOD of MBA department?"),
    ("faculty", "Who is the HOD of MCA department?"),
    # ---- Principal & Vice Principal ----
    ("principal", "Who is the principal of BCREC?"),
    ("principal", "Who is the vice principal of BCREC?"),
    ("principal", "What is the principal's email?"),
    ("principal", "What is the principal's phone number?"),
    # ---- Contact ----
    ("contact", "What is the college address?"),
    ("contact", "What is the college phone number?"),
    ("contact", "What is the college email?"),
    ("contact", "What is the college website?"),
    ("contact", "What is the women's safety helpline?"),
    ("contact", "What are the college timings?"),
    ("contact", "What is the Kolkata office address?"),
    ("contact", "What is the fax number of college?"),
    ("contact", "What is the mobile number of college?"),
    # ---- MAKAUT ----
    ("makaut", "Is BCREC affiliated to MAKAUT?"),
    ("makaut", "Is BCREC an autonomous institute?"),
    ("makaut", "Since when is BCREC autonomous?"),
    # ---- AICTE ----
    ("aicte", "Is BCREC approved by AICTE?"),
    ("aicte", "Does BCREC have AICTE IDEA Lab?"),
    ("aicte", "What is the AICTE IDEA Lab rank of BCREC?"),
    # ---- NBA ----
    ("nba", "Is BCREC NBA accredited?"),
    ("nba", "Which programs are NBA accredited at BCREC?"),
    ("nba", "How many NBA accredited branches are there?"),
    # ---- NAAC ----
    ("naac", "What is the NAAC grade of BCREC?"),
    ("naac", "What is the NAAC CGPA of BCREC?"),
    ("naac", "When is the NAAC grade valid from?"),
    # ---- Facilities ----
    ("facilities", "Does BCREC have WiFi on campus?"),
    ("facilities", "What sports facilities are available?"),
    ("facilities", "Is there a gym at BCREC?"),
    ("facilities", "What medical facilities are available?"),
    ("facilities", "Is there a library? How many books?"),
    ("facilities", "What e-resources are in the library?"),
    ("facilities", "Does BCREC have an auditorium?"),
    ("facilities", "Is there a canteen on campus?"),
    ("facilities", "Is there a guest house facility?"),
    ("facilities", "Does BCREC have a language lab?"),
    ("facilities", "Is NCC available at BCREC?"),
    ("facilities", "Are counselling services available?"),
    # ---- Courses ----
    ("courses", "What B.Tech courses are offered?"),
    ("courses", "Does BCREC offer MCA?"),
    ("courses", "Is branch change allowed?"),
    ("courses", "What is the duration of B.Tech?"),
    ("courses", "What is the duration of MBA?"),
    ("courses", "What is the duration of MCA?"),
    ("courses", "Does BCREC offer MBA in Hospital Management?"),
    ("courses", "What M.Tech programs are available?"),
    ("courses", "Does BCREC offer M.Tech Construction Technology and Management?"),
    # ---- Eligibility ----
    ("eligibility", "What are the eligibility criteria for B.Tech?"),
    ("eligibility", "What entrance exams are accepted?"),
    ("eligibility", "What is the cutoff rank for CSE?"),
    ("eligibility", "What is the cutoff rank for ECE?"),
    ("eligibility", "Is there any age limit for admission?"),
    ("eligibility", "What is the eligibility for MCA?"),
]


def check_duplicates(chunks):
    """Check if any two chunks have near-identical content."""
    texts = [c["content"][:80] for c in chunks]
    seen = {}
    dups = []
    for i, t in enumerate(texts):
        for j, t2 in enumerate(texts):
            if i < j and t.strip() == t2.strip():
                dups.append((i, j, t))
    return dups


def check_conflicts(chunks, category):
    """Check if chunks contain contradictory information."""
    conflicts = []
    # Look for conflicting fee values or numerical data
    fee_values = {}
    for c in chunks:
        import re

        fees = re.findall(r"(?:Rs\.?\s*)?(\d[\d,]+)", c["content"])
        for f in fees:
            normalized = f.replace(",", "")
            if normalized not in fee_values:
                fee_values[normalized] = []
            fee_values[normalized].append(c["metadata"].get("source", "unknown"))
    # If we have multiple distinct fee values, flag
    if len(fee_values) > 1:
        conflicts.append(f"Multiple fee values found: {list(fee_values.keys())}")
    return conflicts


results = {
    "total_queries": len(test_queries),
    "by_category": {},
    "summary": {
        "correct_doc_rank1": 0,
        "above_threshold": 0,
        "below_threshold": 0,
        "with_conflicts": 0,
        "with_duplicates": 0,
        "total_confidence_sum": 0.0,
    },
    "details": [],
}

for idx, (category, query) in enumerate(test_queries):
    if idx % 20 == 0:
        print(f"  Processing query {idx + 1}/{len(test_queries)}: {query[:50]}...")
    docs, max_score = vs.search_with_scores(query, k=8)

    chunks = []
    for i, doc in enumerate(docs):
        content = doc.page_content[:200]
        metadata = doc.metadata
        chunks.append(
            {
                "rank": i + 1,
                "content": content,
                "score": round(metadata.get("_relevance_score", 0.5), 4) if i == 0 else 0.5,
                "metadata": {
                    "source": metadata.get("source", "unknown"),
                    "section": metadata.get("section", "unknown"),
                    "subsection": metadata.get("subsection", "unknown"),
                    "language": metadata.get("language", "unknown"),
                },
            }
        )

    # Overwrite scores from the actual similarity scores
    # (the metadata doesn't store scores, we need to re-query)
    docs_with_scores = vs.vector_store.similarity_search_with_relevance_scores(query, k=8)
    for i, (doc, score) in enumerate(docs_with_scores):
        if i < len(chunks):
            chunks[i]["score"] = round(score, 4)

    above_threshold = max_score >= 0.15 if docs else False

    dups = check_duplicates(chunks)
    conflicts = check_conflicts(chunks, category)

    entry = {
        "category": category,
        "query": query,
        "max_confidence": round(max_score, 4),
        "above_threshold": above_threshold,
        "num_chunks": len(chunks),
        "conflicts": conflicts[:3],
        "duplicates": dups[:3],
        "chunks": chunks[:5],
    }
    results["details"].append(entry)

    results["summary"]["total_confidence_sum"] += max_score
    if above_threshold:
        results["summary"]["above_threshold"] += 1
    else:
        results["summary"]["below_threshold"] += 1
    if conflicts:
        results["summary"]["with_conflicts"] += 1
    if dups:
        results["summary"]["with_duplicates"] += 1

    cat_key = category
    if cat_key not in results["by_category"]:
        results["by_category"][cat_key] = {"count": 0, "above": 0, "below": 0, "avg_conf": 0.0}
    results["by_category"][cat_key]["count"] += 1
    if above_threshold:
        results["by_category"][cat_key]["above"] += 1
    else:
        results["by_category"][cat_key]["below"] += 1
    results["by_category"][cat_key]["avg_conf"] += max_score

# Finalize averages
total = results["total_queries"]
results["summary"]["avg_confidence"] = (
    round(results["summary"]["total_confidence_sum"] / total, 4) if total else 0
)
for cat in results["by_category"]:
    c = results["by_category"][cat]
    c["avg_conf"] = round(c["avg_conf"] / c["count"], 4) if c["count"] else 0

# Print report
print("=" * 80)
print("RETRIEVAL VALIDATION REPORT")
print(f"Total queries: {results['total_queries']}")
print(f"Above threshold (>=0.15): {results['summary']['above_threshold']}/{total}")
print(f"Below threshold (<0.15): {results['summary']['below_threshold']}/{total}")
print(f"Average confidence: {results['summary']['avg_confidence']}")
print(f"Queries with conflicts: {results['summary']['with_conflicts']}")
print(f"Queries with duplicates: {results['summary']['with_duplicates']}")
print("=" * 80)

print("\n--- BY CATEGORY ---")
for cat, c in sorted(results["by_category"].items()):
    status = (
        "OK" if c["above"] == c["count"] else "WARN" if c["above"] >= c["count"] * 0.75 else "FAIL"
    )
    print(
        f"  {cat:20s} {c['above']:2d}/{c['count']:2d} above threshold  avg_conf={c['avg_conf']:.4f}  [{status}]"
    )

print("\n--- DETAILED RESULTS ---")
for entry in results["details"]:
    status = "OK" if entry["above_threshold"] else "LOW"
    dup_flag = " [DUP]" if entry["duplicates"] else ""
    conf_flag = " [CONFLICT]" if entry["conflicts"] else ""
    print(f"\n  [{entry['category']:15s}] {entry['query'][:70]}")
    print(f"    Confidence: {entry['max_confidence']:.4f} ({status}){dup_flag}{conf_flag}")
    for ci, chunk in enumerate(entry["chunks"][:3]):
        src = chunk["metadata"]["source"]
        sec = chunk["metadata"]["section"]
        print(
            f"    #{ci + 1} score={chunk['score']:.4f} src={src}/{sec}: {chunk['content'][:90]}..."
        )
    if entry["conflicts"]:
        print(f"    CONFLICTS: {'; '.join(entry['conflicts'])}")
    if entry["duplicates"]:
        print(f"    DUPLICATES: {entry['duplicates']}")

print("\n" + "=" * 80)
print("END OF REPORT")
print("=" * 80)
