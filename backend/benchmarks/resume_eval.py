"""
Continue evaluation from checkpoint. Processes remaining questions one by one.
"""

import sys, os, json, time, re, asyncio
from pathlib import Path

sys.path.insert(0, "backend")
os.environ["GROQ_API_KEY"] = "gsk_test"
import httpx

CHECKPOINT = Path("backend/benchmarks/eval_reports/checkpoint.json")
cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
results = cp["results"]
start_idx = cp["done"]
total = 142

BASE = "http://127.0.0.1:8000"

# Full question list (same order as eval_demo_readiness.py)
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
    (
        "HI",
        "departments",
        "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u092e\u0947\u0902 \u0915\u094c\u0928-\u0915\u094c\u0928 \u0938\u0947 \u0935\u093f\u092d\u093e\u0917 \u0939\u0948\u0902?",
    ),
    (
        "HI",
        "fees",
        "\u092c\u0940.\u091f\u0947\u0915 \u0938\u0940\u090f\u0938\u0908 \u0915\u0940 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
    ),
    (
        "HI",
        "fees",
        "\u090f\u092e\u092c\u0940\u090f \u0915\u0940 \u0915\u0941\u0932 \u092b\u0940\u0938 \u092c\u0924\u093e\u090f\u0902",
    ),
    (
        "HI",
        "fees",
        "\u090f\u0921\u092e\u093f\u0936\u0928 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
    ),
    (
        "HI",
        "hostel",
        "\u0939\u0949\u0938\u094d\u091f\u0932 \u0915\u0940 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
    ),
    (
        "HI",
        "hostel",
        "\u0915\u094d\u092f\u093e \u0939\u0949\u0938\u094d\u091f\u0932 \u0905\u0928\u093f\u0935\u093e\u0930\u094d\u092f \u0939\u0948?",
    ),
    (
        "HI",
        "placement",
        "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u092e\u0947\u0902 \u092a\u094d\u0932\u0947\u0938\u092e\u0947\u0902\u091f \u0915\u093f\u0924\u0928\u093e \u0939\u0948?",
    ),
    (
        "HI",
        "admission",
        "\u092e\u0941\u091d\u0947 \u090f\u0921\u092e\u093f\u0936\u0928 \u0932\u0947\u0928\u093e \u0939\u0948\u0964 \u0915\u094d\u092f\u093e \u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u093e \u0939\u0948?",
    ),
    (
        "HI",
        "admission",
        "\u092c\u0940.\u091f\u0947\u0915 \u092e\u0947\u0902 \u090f\u0921\u092e\u093f\u0936\u0928 \u0915\u0947 \u0932\u093f\u090f \u0915\u094d\u092f\u093e \u092f\u094b\u0917\u094d\u092f\u0924\u093e \u0939\u0948?",
    ),
    (
        "HI",
        "faculty",
        "\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
    ),
    (
        "HI",
        "faculty",
        "\u0909\u092a-\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
    ),
    (
        "HI",
        "faculty",
        "\u0938\u0940\u090f\u0938\u0908 \u0935\u093f\u092d\u093e\u0917 \u0915\u0947 \u090f\u091a\u0913\u0921\u0940 \u0915\u094c\u0928 \u0939\u0948\u0902?",
    ),
    (
        "HI",
        "campus",
        "\u0915\u0948\u0902\u092a\u0938 \u092e\u0947\u0902 \u0935\u093e\u0908-\u092b\u093e\u0908 \u0909\u092a\u0932\u092c\u094d\u0927 \u0939\u0948?",
    ),
    (
        "HI",
        "scholarship",
        "\u0915\u094d\u092f\u093e \u091b\u093e\u0924\u094d\u0930\u0935\u0943\u0924\u094d\u0924\u093f \u092e\u093f\u0932\u0924\u0940 \u0939\u0948?",
    ),
    (
        "HI",
        "why_bcrec",
        "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u090f\u0928\u092c\u0940\u090f \u092e\u093e\u0928\u094d\u092f\u0924\u093e \u092a\u094d\u0930\u093e\u092a\u094d\u0924 \u0939\u0948?",
    ),
    (
        "HI",
        "admission",
        "\u0915\u094d\u092f\u093e \u0932\u0947\u091f\u0930\u0932 \u090f\u0902\u091f\u094d\u0930\u0940 \u092e\u093f\u0932\u0924\u0940 \u0939\u0948?",
    ),
    (
        "HI",
        "hostel",
        "\u0932\u0921\u093c\u0915\u093f\u092f\u094b\u0902 \u0915\u0947 \u0932\u093f\u090f \u0939\u0949\u0938\u094d\u091f\u0932 \u0939\u0948?",
    ),
]
QUESTIONS.extend(HI)
BN = [
    (
        "BN",
        "departments",
        "\u09ac\u09bf\u09b8\u09bf\u0986\u09b0\u0987\u09b8\u09bf-\u09a4\u09c7 \u0995\u09cb\u09a8 \u0995\u09cb\u09a8 \u09a1\u09bf\u09aa\u09be\u09b0\u09cd\u099f\u09ae\u09c7\u09a8\u09cd\u099f \u0986\u099b\u09c7?",
    ),
    (
        "BN",
        "departments",
        "\u09ac\u09bf.\u099f\u09c7\u0995 \u098f \u0995\u09c0 \u0995\u09c0 \u09b6\u09be\u0996\u09be \u0986\u099b\u09c7?",
    ),
    (
        "BN",
        "fees",
        "\u09ac\u09bf.\u099f\u09c7\u0995 \u09b8\u09bf\u098f\u09b8\u0987 \u098f\u09b0 \u09ab\u09bf \u0995\u09a4?",
    ),
    (
        "BN",
        "fees",
        "\u098f\u0986\u0987\u098f\u09ae\u098f\u09b2 \u0995\u09cb\u09b0\u09cd\u09b8\u09c7\u09b0 \u09ab\u09bf \u0995\u09a4?",
    ),
    (
        "BN",
        "fees",
        "\u098f\u09ae\u09ac\u09bf\u098f \u098f\u09b0 \u09ae\u09cb\u099f \u09ab\u09bf \u0995\u09a4?",
    ),
    ("BN", "hostel", "\u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u09ab\u09bf \u0995\u09a4?"),
    (
        "BN",
        "hostel",
        "\u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u0995\u09bf \u09ac\u09be\u09a7\u09cd\u09af\u09a4\u09be\u09ae\u09c2\u09b2\u0995?",
    ),
    (
        "BN",
        "placement",
        "\u09ac\u09bf\u09b8\u09bf\u0986\u09b0\u0987\u09b8\u09bf \u098f\u09b0 \u09aa\u09cd\u09b2\u09c7\u09b8\u09ae\u09c7\u09a8\u09cd\u099f \u09b0\u09c7\u099f \u0995\u09a4?",
    ),
    (
        "BN",
        "admission",
        "\u09ad\u09b0\u09cd\u09a4\u09bf\u09b0 \u09aa\u09cd\u09b0\u0995\u09cd\u09b0\u09bf\u09af\u09bc\u09be \u0995\u09c0?",
    ),
    (
        "BN",
        "admission",
        "\u09ad\u09b0\u09cd\u09a4\u09bf\u09b0 \u099c\u09a8\u09cd\u09af \u0995\u09c0 \u0995\u09c0 \u09a1\u0995\u09c1\u09ae\u09c7\u09a8\u09cd\u099f \u09b2\u09be\u0997\u09c7?",
    ),
    (
        "BN",
        "faculty",
        "\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u09b8\u09bf\u09aa\u09be\u09b2 \u0995\u09c7?",
    ),
    (
        "BN",
        "faculty",
        "\u0989\u09aa-\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u09b8\u09bf\u09aa\u09be\u09b2 \u0995\u09c7?",
    ),
    (
        "BN",
        "faculty",
        "\u09b8\u09bf\u098f\u09b8\u0987 \u09ac\u09bf\u09ad\u09be\u0997\u09c7\u09b0 \u09aa\u09cd\u09b0\u09a7\u09be\u09a8 \u0995\u09c7?",
    ),
    (
        "BN",
        "campus",
        "\u0995\u09cd\u09af\u09be\u09ae\u09cd\u09aa\u09be\u09b8\u09c7 \u0993\u09df\u09be\u0987-\u09ab\u09be\u0987 \u0986\u099b\u09c7?",
    ),
    (
        "BN",
        "scholarship",
        "\u09b8\u09cd\u0995\u09b2\u09be\u09b0\u09b6\u09bf\u09aa \u0995\u09c0 \u0995\u09c0 \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df?",
    ),
    (
        "BN",
        "admission",
        "\u09b2\u09cd\u09af\u09be\u099f\u09be\u09b0\u09be\u09b2 \u098f\u09a8\u09cd\u099f\u09cd\u09b0\u09bf \u0995\u09bf \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df?",
    ),
    (
        "BN",
        "hostel",
        "\u099b\u09c7\u09b2\u09c7\u09a6\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u0986\u09b2\u09be\u09a6\u09be \u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u0986\u099b\u09c7?",
    ),
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
QUESTIONS.extend(
    [
        ("EN", "ambiguous", "What is the fee?"),
        ("EN", "ambiguous", "Who is the HOD?"),
        ("EN", "followup", "Tell me more about fees"),
        ("EN", "followup", "What about placements?"),
        ("EN", "ambiguous", "Is it good?"),
        ("HI", "ambiguous", "\u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?"),
        ("BN", "ambiguous", "\u09ab\u09bf \u0995\u09a4?"),
        ("EN", "ambiguous", "How many departments?"),
        ("EN", "multi_turn", "What is the fee for CSE?"),
        ("EN", "multi_turn", "What about AIML?"),
        ("EN", "multi_turn", "What documents do I need for admission?"),
        ("EN", "multi_turn", "Where can I track my application?"),
        ("EN", "multi_turn", "Who is the principal?"),
        ("EN", "multi_turn", "And the vice principal?"),
        (
            "HI",
            "multi_turn",
            "\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
        ),
        (
            "HI",
            "multi_turn",
            "\u0909\u092a-\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
        ),
        ("EN", "policies", "Are there any rules about attendance?"),
        ("EN", "why_bcrec", "What accreditation does BCREC have?"),
    ]
)


def check_hallucination(answer, context):
    if not context:
        return True
    ans_numbers = set(re.findall(r"\b\d+[\d,]*\b", answer.replace(",", "")))
    ctx_numbers = set(re.findall(r"\b\d+[\d,]*\b", context.replace(",", "")))
    return bool(ans_numbers - ctx_numbers)


def check_kb_has_answer(query, kb):
    q = query.lower()
    topics = {
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
        "fee": ["fee", "fees", "cost", "price", "tuition", "scholarship"],
        "hostel": ["hostel", "mess", "room", "capacity"],
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
        "faculty": ["faculty", "teacher", "professor", "hod", "principal"],
        "campus": ["campus", "acre", "wifi", "library", "laboratory"],
        "scholarship": ["scholarship", "tfw", "kanyashree"],
        "document": ["document", "marksheet", "certificate"],
        "why_bcrec": ["nba", "naac", "accredited", "established"],
        "policy": ["fail", "backlog", "laptop", "dress code", "attendance", "refund", "caution"],
        "contact": ["contact", "portal", "website", "phone"],
        "online": ["online", "virtual", "remote"],
        "international": ["international", "foreign", "visa", "dasa"],
        "refund": ["refund", "caution money"],
    }
    return any(any(kw in q for kw in kws) for kws in topics.values())


with open("backend/data/knowledge_base/combined_kb.json", "r", encoding="utf-8") as f:
    kb = json.load(f)


async def run():
    async with httpx.AsyncClient(timeout=300) as client:
        for idx in range(start_idx, len(QUESTIONS)):
            lf, cat, q = QUESTIONS[idx]
            try:
                t0 = time.monotonic()
                r1 = await client.post(
                    f"{BASE}/qa/debug",
                    json={"message": q, "session_id": f"eval-{idx}"},
                    timeout=120,
                )
                r2 = await client.post(
                    f"{BASE}/qa/query",
                    json={"message": q, "session_id": f"eval-{idx}"},
                    timeout=180,
                )
                lat = (time.monotonic() - t0) * 1000
                d, a = r1.json(), r2.json()
                ctx = d.get("context_preview", "")
                ans = a.get("answer", "")
                results.append(
                    {
                        "num": idx + 1,
                        "lang": lf,
                        "category": cat,
                        "query": q,
                        "context_len": len(ctx),
                        "answer": ans[:400],
                        "source": a.get("source", ""),
                        "model": a.get("model", ""),
                        "latency_ms": round(lat, 1),
                        "hallucination": "YES" if check_hallucination(ans, ctx) else "NO",
                        "kb_has_answer": "YES" if check_kb_has_answer(q, kb) else "NO",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "num": idx + 1,
                        "lang": lf,
                        "category": cat,
                        "query": q,
                        "context_len": 0,
                        "answer": f"ERROR: {e}",
                        "source": "error",
                        "model": "",
                        "latency_ms": 0,
                        "hallucination": "YES",
                        "kb_has_answer": "YES" if check_kb_has_answer(q, kb) else "NO",
                    }
                )
            done = len(results)
            ctx_ok = sum(1 for r in results if r["context_len"] > 0)
            errs = sum(1 for r in results if r["source"] == "error")
            print(f"  [{done}/{len(QUESTIONS)}] ctx={ctx_ok} err={errs}", flush=True)
            if done % 5 == 0 or done == len(QUESTIONS):
                with open(CHECKPOINT, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "done": done,
                            "total": len(QUESTIONS),
                            "with_context": ctx_ok,
                            "results": results,
                        },
                        f,
                        ensure_ascii=False,
                    )


asyncio.run(run())
