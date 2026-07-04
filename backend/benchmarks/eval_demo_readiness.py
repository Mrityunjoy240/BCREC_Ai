"""
Demo Readiness Evaluation — incremental output, resumes from checkpoint.
"""

import sys, os, json, time, re, asyncio
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["GROQ_API_KEY"] = "gsk_test"

import httpx

BASE = "http://127.0.0.1:8000"
REPORT_DIR = Path(__file__).resolve().parent / "eval_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT = REPORT_DIR / "checkpoint.json"

# ── 100+ Questions ──

QUESTIONS = []

EN = [
    ("EN", "departments", "What departments are available at BCREC?"),
    ("EN", "departments", "Which branches are offered for B.Tech?"),
    ("EN", "departments", "Does BCREC offer MCA and MBA programs?"),
    ("EN", "departments", "Is there a Data Science program?"),
    ("EN", "departments", "Tell me about the CSE department"),
    ("EN", "fees", "What is the fee for B.Tech CSE?"),
    ("EN", "fees", "AIML course fee"),
    ("EN", "fees", "How much does MBA cost?"),
    ("EN", "fees", "MCA total fee"),
    ("EN", "fees", "What is the admission fee for CSE?"),
    ("EN", "fees", "Fee structure for Mechanical Engineering"),
    ("EN", "fees", "Is there any hidden charge in fees?"),
    ("EN", "hostel", "Hostel fee details"),
    ("EN", "hostel", "Is hostel compulsory?"),
    ("EN", "hostel", "What is the mess charge per month?"),
    ("EN", "hostel", "How many hostels are there in BCREC?"),
    ("EN", "placement", "What is the placement rate at BCREC?"),
    ("EN", "placement", "Which companies visit BCREC for placement?"),
    ("EN", "placement", "Highest package offered last year"),
    ("EN", "placement", "CSE placement percentage"),
    ("EN", "admission", "How can I apply for B.Tech admission?"),
    ("EN", "admission", "What is the eligibility for B.Tech?"),
    ("EN", "admission", "Documents required for admission"),
    ("EN", "admission", "Can I track my application status?"),
    ("EN", "faculty", "How many faculty members are there?"),
    ("EN", "faculty", "Who is the principal of BCREC?"),
    ("EN", "faculty", "Who is the vice principal?"),
    ("EN", "faculty", "Who is the HOD of CSE?"),
    ("EN", "faculty", "Who is the HOD of AIML?"),
    ("EN", "faculty", "HOD of IT department"),
    ("EN", "campus", "What is the campus size?"),
    ("EN", "campus", "Is Wi-Fi available in the campus?"),
    ("EN", "scholarship", "What scholarships are available?"),
    ("EN", "scholarship", "Do you offer Tuition Fee Waiver?"),
    ("EN", "why_bcrec", "Why should I choose BCREC?"),
    ("EN", "why_bcrec", "Is BCREC NBA accredited?"),
    ("EN", "international", "Can international students apply?"),
    ("EN", "policies", "What happens if I fail a semester?"),
    ("EN", "policies", "Is laptop compulsory?"),
    ("EN", "refund", "Is caution money refundable?"),
    ("EN", "unknown", "What is the weather like in Durgapur?"),
    ("EN", "unknown", "Can you book a cab for me?"),
    ("EN", "unknown", "Who won the 2024 T20 World Cup?"),
    ("EN", "unknown", "Tell me a joke"),
    ("EN", "unknown", "What is the stock price of Apple?"),
    ("EN", "campus", "Does BCREC have a library?"),
    ("EN", "campus", "Tell me about the laboratories"),
    ("EN", "facilities", "What facilities are available on campus?"),
    ("EN", "placement", "Top recruiters at BCREC"),
    ("EN", "placement", "Average package at BCREC"),
    ("EN", "admission", "Is there lateral entry for B.Tech?"),
    ("EN", "admission", "What is the management quota percentage?"),
    ("EN", "admission", "Do you accept JEE Main scores?"),
    ("EN", "refund", "What is the refund policy?"),
    ("EN", "policies", "What is the dress code?"),
    ("EN", "contact", "What is the college portal?"),
    ("EN", "contact", "How can I contact the admission office?"),
    ("EN", "why_bcrec", "When was BCREC established?"),
    ("EN", "why_bcrec", "What is the NAAC grade of BCREC?"),
    ("EN", "courses", "Does BCREC offer B.Tech in Cyber Security?"),
    ("EN", "courses", "Is there a B.Tech in CS and Design?"),
    ("EN", "eligibility", "What rank is needed for CSE?"),
    ("EN", "eligibility", "Can I get CSE with 80,000 rank?"),
    ("EN", "hostel", "What is the hostel capacity?"),
    ("EN", "hostel", "Are there separate hostels for boys and girls?"),
    ("EN", "online", "Does BCREC have online classes?"),
]
QUESTIONS.extend(EN)

HI = [
    ("HI", "departments", "बीसीआरईसी में कौन-कौन से विभाग हैं?"),
    ("HI", "fees", "बी.टेक सीएसई की फीस कितनी है?"),
    ("HI", "fees", "एमबीए की कुल फीस बताएं"),
    ("HI", "fees", "एडमिशन फीस कितनी है?"),
    ("HI", "hostel", "हॉस्टल की फीस कितनी है?"),
    ("HI", "hostel", "क्या हॉस्टल अनिवार्य है?"),
    ("HI", "placement", "बीसीआरईसी में प्लेसमेंट कितना है?"),
    ("HI", "admission", "मुझे एडमिशन लेना है। क्या प्रक्रिया है?"),
    ("HI", "admission", "बी.टेक में एडमिशन के लिए क्या योग्यता है?"),
    ("HI", "faculty", "प्रिंसिपल कौन हैं?"),
    ("HI", "faculty", "उप-प्रिंसिपल कौन हैं?"),
    ("HI", "faculty", "सीएसई विभाग के एचओडी कौन हैं?"),
    ("HI", "campus", "कैंपस में वाई-फाई उपलब्ध है?"),
    ("HI", "scholarship", "क्या छात्रवृत्ति मिलती है?"),
    ("HI", "why_bcrec", "बीसीआरईसी एनबीए मान्यता प्राप्त है?"),
    ("HI", "admission", "क्या लेटरल एंट्री मिलती है?"),
    ("HI", "hostel", "लड़कियों के लिए हॉस्टल है?"),
]
QUESTIONS.extend(HI)

BN = [
    ("BN", "departments", "বিসিআরইসি-তে কোন কোন ডিপার্টমেন্ট আছে?"),
    ("BN", "departments", "বি.টেক এ কী কী শাখা আছে?"),
    ("BN", "fees", "বি.টেক সিএসই এর ফি কত?"),
    ("BN", "fees", "এআইএমএল কোর্সের ফি কত?"),
    ("BN", "fees", "এমবিএ এর মোট ফি কত?"),
    ("BN", "hostel", "হোস্টেল ফি কত?"),
    ("BN", "hostel", "হোস্টেল কি বাধ্যতামূলক?"),
    ("BN", "placement", "বিসিআরইসি এর প্লেসমেন্ট রেট কত?"),
    ("BN", "admission", "ভর্তির প্রক্রিয়া কী?"),
    ("BN", "admission", "ভর্তির জন্য কী কী ডকুমেন্ট লাগে?"),
    ("BN", "faculty", "প্রিন্সিপাল কে?"),
    ("BN", "faculty", "উপ-প্রিন্সিপাল কে?"),
    ("BN", "faculty", "সিএসই বিভাগের প্রধান কে?"),
    ("BN", "campus", "ক্যাম্পাসে ওয়াই-ফাই আছে?"),
    ("BN", "scholarship", "স্কলারশিপ কী কী পাওয়া যায়?"),
    ("BN", "admission", "ল্যাটারাল এন্ট্রি কি পাওয়া যায়?"),
    ("BN", "hostel", "ছেলেদের জন্য আলাদা হোস্টেল আছে?"),
]
QUESTIONS.extend(BN)

HINGLISH = [
    ("HINGLISH", "departments", "BCREC me kaun se departments hain?"),
    ("HINGLISH", "fees", "CSE ka fee kitna hai?"),
    ("HINGLISH", "fees", "MBA ki total fee kya hai?"),
    ("HINGLISH", "fees", "Admission fee kitni hai?"),
    ("HINGLISH", "hostel", "Hostel fee kitni hai bhai?"),
    ("HINGLISH", "hostel", "Kya hostel compulsory hai?"),
    ("HINGLISH", "placement", "Placement kitna percent hai BCREC mein?"),
    ("HINGLISH", "admission", "Admission ke liye kya karna padta hai?"),
    ("HINGLISH", "admission", "BTech ke liye kya eligibility hai?"),
    ("HINGLISH", "faculty", "Principal kaun hain?"),
    ("HINGLISH", "campus", "WiFi available hai campus mein?"),
    ("HINGLISH", "scholarship", "Scholarship milti hai kya?"),
]
QUESTIONS.extend(HINGLISH)

BANGLISH = [
    ("BANGLISH", "departments", "BCREC te ki ki department ache?"),
    ("BANGLISH", "fees", "CSE er fee koto?"),
    ("BANGLISH", "fees", "AIML er total fee koto?"),
    ("BANGLISH", "fees", "Admission fee koto?"),
    ("BANGLISH", "hostel", "Hostel er fee koto?"),
    ("BANGLISH", "hostel", "Hostel ki compulsory?"),
    ("BANGLISH", "placement", "Placement rate koto BCREC te?"),
    ("BANGLISH", "admission", "Vorti process ta ki?"),
    ("BANGLISH", "admission", "Btech e vortir jonno ki ki document lagbe?"),
    ("BANGLISH", "faculty", "Principal ke?"),
    ("BANGLISH", "faculty", "CSE department er HOD ke?"),
    ("BANGLISH", "campus", "Campus e WiFi ache?"),
]
QUESTIONS.extend(BANGLISH)

# Ambiguous/Follow-up/Multi-turn
QUESTIONS.extend(
    [
        ("EN", "ambiguous", "What is the fee?"),
        ("EN", "ambiguous", "Who is the HOD?"),
        ("EN", "followup", "Tell me more about fees"),
        ("EN", "followup", "What about placements?"),
        ("EN", "ambiguous", "Is it good?"),
        ("HI", "ambiguous", "फीस कितनी है?"),
        ("BN", "ambiguous", "ফি কত?"),
        ("EN", "ambiguous", "How many departments?"),
        ("EN", "multi_turn", "What is the fee for CSE?"),
        ("EN", "multi_turn", "What about AIML?"),
        ("EN", "multi_turn", "What documents do I need for admission?"),
        ("EN", "multi_turn", "Where can I track my application?"),
        ("EN", "multi_turn", "Who is the principal?"),
        ("EN", "multi_turn", "And the vice principal?"),
        ("HI", "multi_turn", "प्रिंसिपल कौन हैं?"),
        ("HI", "multi_turn", "उप-प्रिंसिपल कौन हैं?"),
        ("EN", "policies", "Are there any rules about attendance?"),
        ("EN", "why_bcrec", "What accreditation does BCREC have?"),
    ]
)


# ── Evaluation Logic ──


def check_hallucination(answer: str, context: str) -> bool:
    """Check if answer contains specific numbers not grounded in context."""
    if not context:
        return True
    ans_lower = answer.lower()
    ctx_lower = context.lower()
    ans_numbers = set(re.findall(r"\b\d+[\d,]*\b", answer.replace(",", "")))
    ctx_numbers = set(re.findall(r"\b\d+[\d,]*\b", context.replace(",", "")))
    suspicious = ans_numbers - ctx_numbers
    if suspicious and len(suspicious) > 0:
        return True
    return False


def check_kb_has_answer(query: str, kb: dict) -> bool:
    """Check if KB likely has the answer for this query."""
    vra = kb.get("voice_ready_answers", {})
    query_lower = query.lower()
    topic_keywords = {
        "admission": [
            "admission",
            "apply",
            "eligibility",
            "entrance",
            "wbjee",
            "jee",
            "application",
            "lateral",
            "quota",
        ],
        "fee": ["fee", "fees", "cost", "price", "tuition", "scholarship", "stipend"],
        "hostel": ["hostel", "mess", "room", "capacity", "boys", "girls"],
        "placement": ["placement", "job", "recruit", "company", "package", "career"],
        "department": [
            "department",
            "branch",
            "course",
            "program",
            "b.tech",
            "mca",
            "mba",
            "cse",
            "aiml",
        ],
        "faculty": ["faculty", "teacher", "professor", "hod", "principal", "vice principal"],
        "campus": ["campus", "acre", "wifi", "wi-fi", "library", "laboratory", "lab", "facility"],
        "scholarship": ["scholarship", "tfw", "kanyashree", "financial aid", "fee waiver"],
        "document": ["document", "marksheet", "certificate", "admit card", "allotment"],
        "why_bcrec": ["nba", "naac", "accredited", "established", "why"],
        "policy": ["fail", "backlog", "laptop", "dress code", "attendance", "refund", "caution"],
        "contact": ["contact", "portal", "website", "phone", "email"],
        "online": ["online", "virtual", "remote"],
        "international": ["international", "foreign", "visa", "dasa"],
        "refund": ["refund", "caution money", "security deposit", "cancellation"],
    }
    for topic, keywords in topic_keywords.items():
        if any(kw in query_lower for kw in keywords):
            return True
    return False


async def evaluate_single(client, kb, idx, lang_family, category, query):
    start = time.monotonic()
    try:
        resp = await client.post(
            f"{BASE}/qa/debug", json={"message": query, "session_id": f"eval-{idx}"}, timeout=120
        )
        debug = resp.json()
        resp2 = await client.post(
            f"{BASE}/qa/query", json={"message": query, "session_id": f"eval-{idx}"}, timeout=180
        )
        answer_data = resp2.json()
        latency = (time.monotonic() - start) * 1000
        context = debug.get("context_preview", "")
        answer = answer_data.get("answer", "")
        source = answer_data.get("source", "")
        model = answer_data.get("model", "")
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        context = ""
        answer = f"ERROR: {e}"
        source = "error"
        model = ""

    return {
        "num": idx + 1,
        "lang": lang_family,
        "category": category,
        "query": query,
        "context_len": len(context),
        "answer": answer[:400],
        "source": source,
        "model": model,
        "latency_ms": round(latency, 1),
        "hallucination": "YES" if check_hallucination(answer, context) else "NO",
        "kb_has_answer": "YES" if check_kb_has_answer(query, kb) else "NO",
    }


async def main():
    BATCH = 4  # concurrent queries (reduced from 5 to avoid timeout pileup)

    # load KB
    with open("backend/data/knowledge_base/combined_kb.json", "r", encoding="utf-8") as f:
        kb = json.load(f)

    # Resume from checkpoint
    results = []
    start_idx = 0
    if CHECKPOINT.exists():
        cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        results = cp["results"]
        start_idx = cp["done"]
        print(f"Resuming from checkpoint: {start_idx}/{len(QUESTIONS)} done")
    else:
        print(f"Starting fresh: {len(QUESTIONS)} questions")

    async with httpx.AsyncClient(timeout=300) as client:
        for batch_start in range(start_idx, len(QUESTIONS), BATCH):
            batch = QUESTIONS[batch_start : batch_start + BATCH]
            tasks = [
                evaluate_single(client, kb, idx, lf, cat, q)
                for idx, (lf, cat, q) in enumerate(batch, start=batch_start)
            ]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

            done = min(batch_start + BATCH, len(QUESTIONS))
            ctx = sum(1 for r in results if r["context_len"] > 0)
            errs = sum(1 for r in results if r["source"] == "error")
            with open(CHECKPOINT, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "done": done,
                        "total": len(QUESTIONS),
                        "with_context": ctx,
                        "results": results,
                    },
                    f,
                    ensure_ascii=False,
                )
            avg = sum(r["latency_ms"] for r in results if r["latency_ms"] > 0) / max(
                1, sum(1 for r in results if r["latency_ms"] > 0)
            )
            print(
                f"  [{done}/{len(QUESTIONS)}] ctx={ctx} err={errs} avg_lat={avg:.0f}ms", flush=True
            )

    generate_report(results)
    os.remove(CHECKPOINT)


def generate_report(results):
    total = len(results)
    hallucinations = sum(1 for r in results if r["hallucination"] == "YES")
    total_with_context = sum(1 for r in results if r["context_len"] > 0)
    avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0
    kb_answered = sum(1 for r in results if r["kb_has_answer"] == "YES")
    errors = [r for r in results if r["source"] == "error"]

    categories = defaultdict(list)
    languages = defaultdict(list)
    for r in results:
        categories[r["category"]].append(r)
        languages[r["lang"]].append(r)

    correct = sum(
        1
        for r in results
        if r["hallucination"] == "NO" and r["context_len"] > 0 and r["kb_has_answer"] == "YES"
    )
    answerable = sum(1 for r in results if r["kb_has_answer"] == "YES")

    lines = []

    def w(s=""):
        lines.append(s)

    w("=" * 80)
    w("  DEMO READINESS EVALUATION REPORT")
    w(f"  Generated: {datetime.now().isoformat()}")
    w("=" * 80)
    w()
    w(f"  Total questions evaluated: {total}")
    w(
        f"  Questions with RAG context: {total_with_context}/{total} ({total_with_context / total * 100:.1f}%)"
    )
    w(f"  KB has answer for: {kb_answered}/{total} ({kb_answered / total * 100:.1f}%)")
    w(f"  Errors: {len(errors)}")
    w()
    w("-" * 80)
    w("  HALLUCINATION & RETRIEVAL ANALYSIS")
    w("-" * 80)
    w(f"  Hallucination detected: {hallucinations}/{total} ({hallucinations / total * 100:.1f}%)")
    w(f"  Average latency: {avg_latency:.0f}ms")
    w(
        f"  Retrieval Recall@30 (has context): {total_with_context}/{total} = {total_with_context / total * 100:.1f}%"
    )
    w(
        f"  Estimated accuracy (on KB-answerable): {correct}/{answerable} = {correct / answerable * 100:.1f}%"
    )
    w()
    w("-" * 80)
    w("  RESULTS BY CATEGORY")
    w("-" * 80)
    for cat in sorted(categories.keys()):
        items = categories[cat]
        cat_total = len(items)
        cat_hall = sum(1 for r in items if r["hallucination"] == "YES")
        cat_ctx = sum(1 for r in items if r["context_len"] > 0)
        cat_lat = sum(r["latency_ms"] for r in items) / cat_total
        cat_ka = sum(1 for r in items if r["kb_has_answer"] == "YES")
        w(
            f"  {cat:20s} n={cat_total:2d} ctx={cat_ctx:2d} hall={cat_hall:2d} ka={cat_ka:2d} lat={cat_lat:.0f}ms"
        )
    w()
    w("-" * 80)
    w("  RESULTS BY LANGUAGE")
    w("-" * 80)
    for lang in sorted(languages.keys()):
        items = languages[lang]
        lang_total = len(items)
        lang_hall = sum(1 for r in items if r["hallucination"] == "YES")
        lang_ctx = sum(1 for r in items if r["context_len"] > 0)
        lang_lat = sum(r["latency_ms"] for r in items) / lang_total
        w(
            f"  {lang:12s} n={lang_total:2d} ctx={lang_ctx:2d} hall={lang_hall:2d} lat={lang_lat:.0f}ms"
        )
    w()
    w("-" * 80)
    w("  FAILED / HALLUCINATED QUESTIONS")
    w("-" * 80)
    failed = [r for r in results if r["hallucination"] == "YES" or r["context_len"] == 0]
    if failed:
        for r in failed:
            w(
                f"  #{r['num']:3d} [{r['lang']:8s}/{r['category']:12s}] HALL={r['hallucination']:3s} CTX={r['context_len']:4d}"
            )
            w(f"       Q: {r['query'][:80]}")
            if r["hallucination"] == "YES":
                w(f"       A: {r['answer'][:120]}")
            w()
    else:
        w("  (none)")
    w()
    w("-" * 80)
    w("  LANGUAGE DISTRIBUTION")
    w("-" * 80)
    for lang in sorted(languages.keys()):
        items = languages[lang]
        w(f"  {lang:12s}: {len(items):2d} ({len(items) / total * 100:.0f}%)")
    w()
    if errors:
        w("-" * 80)
        w("  ERRORS")
        w("-" * 80)
        for e in errors:
            w(f"  #{e['num']}: {e['query'][:60]} -> {e['answer'][:100]}")
    w()
    w("=" * 80)
    w("  END OF REPORT")
    w("=" * 80)

    report = "\n".join(lines)
    report_path = REPORT_DIR / f"demo_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    json_path = report_path.with_suffix(".json")
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw results saved to: {json_path}")

    print(report)


if __name__ == "__main__":
    asyncio.run(main())
