"""Continue evaluation from checkpoint."""

import sys, os, json, time, re, asyncio
from pathlib import Path

sys.path.insert(0, "backend")
os.environ["GROQ_API_KEY"] = "gsk_test"
import httpx

CHECKPOINT = Path("backend/benchmarks/eval_reports/checkpoint.json")
cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
results = cp["results"]
start_idx = cp["done"]
BASE = "http://127.0.0.1:8000"
TOTAL = 142
BATCH = 4

# Same question definitions
QUESTIONS = []


def add_en():
    for c, q in [
        ("departments", "What departments are available at BCREC?"),
        ("departments", "Which branches are offered for B.Tech?"),
        ("departments", "Does BCREC offer MCA and MBA programs?"),
        ("departments", "Is there a Data Science program?"),
        ("departments", "Tell me about the CSE department"),
        ("fees", "What is the fee for B.Tech CSE?"),
        ("fees", "AIML course fee"),
        ("fees", "How much does MBA cost?"),
        ("fees", "MCA total fee"),
        ("fees", "What is the admission fee for CSE?"),
        ("fees", "Fee structure for Mechanical Engineering"),
        ("fees", "Is there any hidden charge in fees?"),
        ("hostel", "Hostel fee details"),
        ("hostel", "Is hostel compulsory?"),
        ("hostel", "What is the mess charge per month?"),
        ("hostel", "How many hostels are there in BCREC?"),
        ("placement", "What is the placement rate at BCREC?"),
        ("placement", "Which companies visit BCREC for placement?"),
        ("placement", "Highest package offered last year"),
        ("placement", "CSE placement percentage"),
        ("admission", "How can I apply for B.Tech admission?"),
        ("admission", "What is the eligibility for B.Tech?"),
        ("admission", "Documents required for admission"),
        ("admission", "Can I track my application status?"),
        ("faculty", "How many faculty members are there?"),
        ("faculty", "Who is the principal of BCREC?"),
        ("faculty", "Who is the vice principal?"),
        ("faculty", "Who is the HOD of CSE?"),
        ("faculty", "Who is the HOD of AIML?"),
        ("faculty", "HOD of IT department"),
        ("campus", "What is the campus size?"),
        ("campus", "Is Wi-Fi available in the campus?"),
        ("scholarship", "What scholarships are available?"),
        ("scholarship", "Do you offer Tuition Fee Waiver?"),
        ("why_bcrec", "Why should I choose BCREC?"),
        ("why_bcrec", "Is BCREC NBA accredited?"),
        ("international", "Can international students apply?"),
        ("policies", "What happens if I fail a semester?"),
        ("policies", "Is laptop compulsory?"),
        ("refund", "Is caution money refundable?"),
        ("unknown", "What is the weather like in Durgapur?"),
        ("unknown", "Can you book a cab for me?"),
        ("unknown", "Who won the 2024 T20 World Cup?"),
        ("unknown", "Tell me a joke"),
        ("unknown", "What is the stock price of Apple?"),
        ("campus", "Does BCREC have a library?"),
        ("campus", "Tell me about the laboratories"),
        ("facilities", "What facilities are available on campus?"),
        ("placement", "Top recruiters at BCREC"),
        ("placement", "Average package at BCREC"),
        ("admission", "Is there lateral entry for B.Tech?"),
        ("admission", "What is the management quota percentage?"),
        ("admission", "Do you accept JEE Main scores?"),
        ("refund", "What is the refund policy?"),
        ("policies", "What is the dress code?"),
        ("contact", "What is the college portal?"),
        ("contact", "How can I contact the admission office?"),
        ("why_bcrec", "When was BCREC established?"),
        ("why_bcrec", "What is the NAAC grade of BCREC?"),
        ("courses", "Does BCREC offer B.Tech in Cyber Security?"),
        ("courses", "Is there a B.Tech in CS and Design?"),
        ("eligibility", "What rank is needed for CSE?"),
        ("eligibility", "Can I get CSE with 80,000 rank?"),
        ("hostel", "What is the hostel capacity?"),
        ("hostel", "Are there separate hostels for boys and girls?"),
        ("online", "Does BCREC have online classes?"),
    ]:
        QUESTIONS.append(("EN", c, q))


def add_hi():
    for c, q in [
        (
            "departments",
            "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u092e\u0947\u0902 \u0915\u094c\u0928-\u0915\u094c\u0928 \u0938\u0947 \u0935\u093f\u092d\u093e\u0917 \u0939\u0948\u0902?",
        ),
        (
            "fees",
            "\u092c\u0940.\u091f\u0947\u0915 \u0938\u0940\u090f\u0938\u0908 \u0915\u0940 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
        ),
        (
            "fees",
            "\u090f\u092e\u092c\u0940\u090f \u0915\u0940 \u0915\u0941\u0932 \u092b\u0940\u0938 \u092c\u0924\u093e\u090f\u0902",
        ),
        (
            "fees",
            "\u090f\u0921\u092e\u093f\u0936\u0928 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
        ),
        (
            "hostel",
            "\u0939\u0949\u0938\u094d\u091f\u0932 \u0915\u0940 \u092b\u0940\u0938 \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
        ),
        (
            "hostel",
            "\u0915\u094d\u092f\u093e \u0939\u0949\u0938\u094d\u091f\u0932 \u0905\u0928\u093f\u0935\u093e\u0930\u094d\u092f \u0939\u0948?",
        ),
        (
            "placement",
            "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u092e\u0947\u0902 \u092a\u094d\u0932\u0947\u0938\u092e\u0947\u0902\u091f \u0915\u093f\u0924\u0928\u093e \u0939\u0948?",
        ),
        (
            "admission",
            "\u092e\u0941\u091d\u0947 \u090f\u0921\u092e\u093f\u0936\u0928 \u0932\u0947\u0928\u093e \u0939\u0948\u0964 \u0915\u094d\u092f\u093e \u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u093e \u0939\u0948?",
        ),
        (
            "admission",
            "\u092c\u0940.\u091f\u0947\u0915 \u092e\u0947\u0902 \u090f\u0921\u092e\u093f\u0936\u0928 \u0915\u0947 \u0932\u093f\u090f \u0915\u094d\u092f\u093e \u092f\u094b\u0917\u094d\u092f\u0924\u093e \u0939\u0948?",
        ),
        (
            "faculty",
            "\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
        ),
        (
            "faculty",
            "\u0909\u092a-\u092a\u094d\u0930\u093f\u0902\u0938\u093f\u092a\u0932 \u0915\u094c\u0928 \u0939\u0948\u0902?",
        ),
        (
            "faculty",
            "\u0938\u0940\u090f\u0938\u0908 \u0935\u093f\u092d\u093e\u0917 \u0915\u0947 \u090f\u091a\u0913\u0921\u0940 \u0915\u094c\u0928 \u0939\u0948\u0902?",
        ),
        (
            "campus",
            "\u0915\u0948\u0902\u092a\u0938 \u092e\u0947\u0902 \u0935\u093e\u0908-\u092b\u093e\u0908 \u0909\u092a\u0932\u092c\u094d\u0927 \u0939\u0948?",
        ),
        (
            "scholarship",
            "\u0915\u094d\u092f\u093e \u091b\u093e\u0924\u094d\u0930\u0935\u0943\u0924\u094d\u0924\u093f \u092e\u093f\u0932\u0924\u0940 \u0939\u0948?",
        ),
        (
            "why_bcrec",
            "\u092c\u0940\u0938\u0940\u0906\u0930\u0908\u0938\u0940 \u090f\u0928\u092c\u0940\u090f \u092e\u093e\u0928\u094d\u092f\u0924\u093e \u092a\u094d\u0930\u093e\u092a\u094d\u0924 \u0939\u0948?",
        ),
        (
            "admission",
            "\u0915\u094d\u092f\u093e \u0932\u0947\u091f\u0930\u0932 \u090f\u0902\u091f\u094d\u0930\u0940 \u092e\u093f\u0932\u0924\u0940 \u0939\u0948?",
        ),
        (
            "hostel",
            "\u0932\u0921\u093c\u0915\u093f\u092f\u094b\u0902 \u0915\u0947 \u0932\u093f\u090f \u0939\u0949\u0938\u094d\u091f\u0932 \u0939\u0948?",
        ),
    ]:
        QUESTIONS.append(("HI", c, q))


def add_bn():
    for c, q in [
        (
            "departments",
            "\u09ac\u09bf\u09b8\u09bf\u0986\u09b0\u0987\u09b8\u09bf-\u09a4\u09c7 \u0995\u09cb\u09a8 \u0995\u09cb\u09a8 \u09a1\u09bf\u09aa\u09be\u09b0\u09cd\u099f\u09ae\u09c7\u09a8\u09cd\u099f \u0986\u099b\u09c7?",
        ),
        (
            "departments",
            "\u09ac\u09bf.\u099f\u09c7\u0995 \u098f \u0995\u09c0 \u0995\u09c0 \u09b6\u09be\u0996\u09be \u0986\u099b\u09c7?",
        ),
        (
            "fees",
            "\u09ac\u09bf.\u099f\u09c7\u0995 \u09b8\u09bf\u098f\u09b8\u0987 \u098f\u09b0 \u09ab\u09bf \u0995\u09a4?",
        ),
        (
            "fees",
            "\u098f\u0986\u0987\u098f\u09ae\u098f\u09b2 \u0995\u09cb\u09b0\u09cd\u09b8\u09c7\u09b0 \u09ab\u09bf \u0995\u09a4?",
        ),
        (
            "fees",
            "\u098f\u09ae\u09ac\u09bf\u098f \u098f\u09b0 \u09ae\u09cb\u099f \u09ab\u09bf \u0995\u09a4?",
        ),
        ("hostel", "\u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u09ab\u09bf \u0995\u09a4?"),
        (
            "hostel",
            "\u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u0995\u09bf \u09ac\u09be\u09a7\u09cd\u09af\u09a4\u09be\u09ae\u09c2\u09b2\u0995?",
        ),
        (
            "placement",
            "\u09ac\u09bf\u09b8\u09bf\u0986\u09b0\u0987\u09b8\u09bf \u098f\u09b0 \u09aa\u09cd\u09b2\u09c7\u09b8\u09ae\u09c7\u09a8\u09cd\u099f \u09b0\u09c7\u099f \u0995\u09a4?",
        ),
        (
            "admission",
            "\u09ad\u09b0\u09cd\u09a4\u09bf\u09b0 \u09aa\u09cd\u09b0\u0995\u09cd\u09b0\u09bf\u09af\u09bc\u09be \u0995\u09c0?",
        ),
        (
            "admission",
            "\u09ad\u09b0\u09cd\u09a4\u09bf\u09b0 \u099c\u09a8\u09cd\u09af \u0995\u09c0 \u0995\u09c0 \u09a1\u0995\u09c1\u09ae\u09c7\u09a8\u09cd\u099f \u09b2\u09be\u0997\u09c7?",
        ),
        (
            "faculty",
            "\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u09b8\u09bf\u09aa\u09be\u09b2 \u0995\u09c7?",
        ),
        (
            "faculty",
            "\u0989\u09aa-\u09aa\u09cd\u09b0\u09bf\u09a8\u09cd\u09b8\u09bf\u09aa\u09be\u09b2 \u0995\u09c7?",
        ),
        (
            "faculty",
            "\u09b8\u09bf\u098f\u09b8\u0987 \u09ac\u09bf\u09ad\u09be\u0997\u09c7\u09b0 \u09aa\u09cd\u09b0\u09a7\u09be\u09a8 \u0995\u09c7?",
        ),
        (
            "campus",
            "\u0995\u09cd\u09af\u09be\u09ae\u09cd\u09aa\u09be\u09b8\u09c7 \u0993\u09df\u09be\u0987-\u09ab\u09be\u0987 \u0986\u099b\u09c7?",
        ),
        (
            "scholarship",
            "\u09b8\u09cd\u0995\u09b2\u09be\u09b0\u09b6\u09bf\u09aa \u0995\u09c0 \u0995\u09c0 \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df?",
        ),
        (
            "admission",
            "\u09b2\u09cd\u09af\u09be\u099f\u09be\u09b0\u09be\u09b2 \u098f\u09a8\u09cd\u099f\u09cd\u09b0\u09bf \u0995\u09bf \u09aa\u09be\u0993\u09df\u09be \u09af\u09be\u09df?",
        ),
        (
            "hostel",
            "\u099b\u09c7\u09b2\u09c7\u09a6\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u0986\u09b2\u09be\u09a6\u09be \u09b9\u09cb\u09b8\u09cd\u099f\u09c7\u09b2 \u0986\u099b\u09c7?",
        ),
    ]:
        QUESTIONS.append(("BN", c, q))


def add_hinglish():
    for c, q in [
        ("departments", "BCREC me kaun se departments hain?"),
        ("fees", "CSE ka fee kitna hai?"),
        ("fees", "MBA ki total fee kya hai?"),
        ("fees", "Admission fee kitni hai?"),
        ("hostel", "Hostel fee kitni hai bhai?"),
        ("hostel", "Kya hostel compulsory hai?"),
        ("placement", "Placement kitna percent hai BCREC mein?"),
        ("admission", "Admission ke liye kya karna padta hai?"),
        ("admission", "BTech ke liye kya eligibility hai?"),
        ("faculty", "Principal kaun hain?"),
        ("campus", "WiFi available hai campus mein?"),
        ("scholarship", "Scholarship milti hai kya?"),
    ]:
        QUESTIONS.append(("HINGLISH", c, q))


def add_banglish():
    for c, q in [
        ("departments", "BCREC te ki ki department ache?"),
        ("fees", "CSE er fee koto?"),
        ("fees", "AIML er total fee koto?"),
        ("fees", "Admission fee koto?"),
        ("hostel", "Hostel er fee koto?"),
        ("hostel", "Hostel ki compulsory?"),
        ("placement", "Placement rate koto BCREC te?"),
        ("admission", "Vorti process ta ki?"),
        ("admission", "Btech e vortir jonno ki ki document lagbe?"),
        ("faculty", "Principal ke?"),
        ("faculty", "CSE department er HOD ke?"),
        ("campus", "Campus e WiFi ache?"),
    ]:
        QUESTIONS.append(("BANGLISH", c, q))


def add_other():
    for lf, c, q in [
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
    ]:
        QUESTIONS.append((lf, c, q))


add_en()
add_hi()
add_bn()
add_hinglish()
add_banglish()
add_other()


def check_hallucination(answer, context):
    if not context:
        return True
    an = set(re.findall(r"\b\d+[\d,]*\b", answer.replace(",", "")))
    cn = set(re.findall(r"\b\d+[\d,]*\b", context.replace(",", "")))
    return bool(an - cn)


def check_kb_has_answer(query):
    q = query.lower()
    topics = [
        ["admission", "apply", "eligibility", "wbjee", "jee"],
        ["fee", "fees", "cost", "tuition"],
        ["hostel", "mess"],
        ["placement", "job", "recruit", "company"],
        ["department", "branch", "course", "b.tech", "mca", "mba", "cse", "aiml"],
        ["faculty", "teacher", "hod", "principal"],
        ["campus", "acre", "wifi", "library"],
        ["scholarship", "tfw"],
        ["document", "marksheet"],
        ["nba", "naac", "accredited"],
        ["fail", "backlog", "laptop", "dress code", "refund", "caution"],
        ["contact", "portal", "website"],
        ["online", "virtual"],
        ["international", "visa", "dasa"],
    ]
    return any(any(kw in q for kw in kws) for kws in topics)


async def run():
    async def query_one(idx, lf, cat, q):
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=300) as c:
                d = await c.post(
                    f"{BASE}/qa/debug",
                    json={"message": q, "session_id": f"eval-{idx}"},
                    timeout=120,
                )
                a = await c.post(
                    f"{BASE}/qa/query",
                    json={"message": q, "session_id": f"eval-{idx}"},
                    timeout=180,
                )
            lat = (time.monotonic() - t0) * 1000
            dj, aj = d.json(), a.json()
            ctx, ans = dj.get("context_preview", ""), aj.get("answer", "")
            return {
                "num": idx + 1,
                "lang": lf,
                "category": cat,
                "query": q,
                "context_len": len(ctx),
                "answer": ans[:400],
                "source": aj.get("source", ""),
                "model": aj.get("model", ""),
                "latency_ms": round(lat, 1),
                "hallucination": "YES" if check_hallucination(ans, ctx) else "NO",
                "kb_has_answer": "YES" if check_kb_has_answer(q) else "NO",
            }
        except Exception as e:
            return {
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
                "kb_has_answer": "YES" if check_kb_has_answer(q) else "NO",
            }

    for batch_start in range(start_idx, TOTAL, BATCH):
        tasks = [
            query_one(idx, lf, cat, q)
            for idx, (lf, cat, q) in enumerate(
                QUESTIONS[batch_start : batch_start + BATCH], start=batch_start
            )
        ]
        for r in await asyncio.gather(*tasks):
            results.append(r)
        done = len(results)
        ctx_ok = sum(1 for r in results if r["context_len"] > 0)
        errs = sum(1 for r in results if r["source"] == "error")
        avg = sum(r["latency_ms"] for r in results if r["latency_ms"] > 0) / max(
            1, sum(1 for r in results if r["latency_ms"] > 0)
        )
        print(f"  [{done}/{TOTAL}] ctx={ctx_ok} err={errs} avg={avg:.0f}ms", flush=True)
        with open(CHECKPOINT, "w", encoding="utf-8") as f:
            json.dump({"done": done, "total": TOTAL, "results": results}, f, ensure_ascii=False)

    # Generate final report
    halls = sum(1 for r in results if r["hallucination"] == "YES")
    ctxs = sum(1 for r in results if r["context_len"] > 0)
    errs = sum(1 for r in results if r["source"] == "error")
    avg = sum(r["latency_ms"] for r in results) / len(results)
    from collections import defaultdict

    cats, langs = defaultdict(list), defaultdict(list)
    for r in results:
        cats[r["category"]].append(r)
        langs[r["lang"]].append(r)
    correct = sum(
        1
        for r in results
        if r["hallucination"] == "NO" and r["context_len"] > 0 and r["kb_has_answer"] == "YES"
    )
    answerable = sum(1 for r in results if r["kb_has_answer"] == "YES")
    lines = []
    lines.append("=" * 80)
    lines.append(f"  DEMO READINESS EVALUATION REPORT")
    lines.append(
        f"  Questions: {TOTAL}, Hallucinations: {halls}, Errors: {errs}, With Context: {ctxs}"
    )
    lines.append(f"  Hallucination rate: {halls / max(1, TOTAL) * 100:.1f}%")
    lines.append(f"  Retrieval Recall@30: {ctxs / max(1, TOTAL) * 100:.1f}%")
    lines.append(
        f"  Estimated accuracy: {correct}/{answerable} = {correct / max(1, answerable) * 100:.1f}%"
    )
    lines.append(f"  Average latency: {avg:.0f}ms")
    lines.append(f"")
    lines.append(f"  By Category:")
    for cat in sorted(cats.keys()):
        it = cats[cat]
        lines.append(
            f"    {cat:15s} n={len(it):2d} ctx={sum(1 for r in it if r['context_len'] > 0):2d} hall={sum(1 for r in it if r['hallucination'] == 'YES'):2d} lat={sum(r['latency_ms'] for r in it) / len(it):.0f}ms"
        )
    lines.append(f"")
    lines.append(f"  By Language:")
    for lang in sorted(langs.keys()):
        it = langs[lang]
        lines.append(
            f"    {lang:10s} n={len(it):2d} ctx={sum(1 for r in it if r['context_len'] > 0):2d} hall={sum(1 for r in it if r['hallucination'] == 'YES'):2d} lat={sum(r['latency_ms'] for r in it) / len(it):.0f}ms"
        )
    lines.append(f"")
    lines.append(f"  Failed/Hallucinated:")
    for r in results:
        if r["hallucination"] == "YES" or r["context_len"] == 0:
            lines.append(
                f"    #{r['num']:3d} [{r['lang']:8s}/{r['category']:12s}] hall={r['hallucination']:3s} ctx={r['context_len']:4d}  Q: {r['query'][:60]}"
            )
            if r["hallucination"] == "YES":
                lines.append(f"      A: {r['answer'][:120]}")
    lines.append("=" * 80)
    report = "\n".join(lines)
    rp = Path("backend/benchmarks/eval_reports") / f"demo_eval_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    rp.write_text(report, encoding="utf-8")
    rp.with_suffix(".json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nReport: {rp}")
    print(report)


asyncio.run(run())
