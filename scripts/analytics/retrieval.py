"""
Task 5: Retrieval Analysis
===========================
Analyzes retrieval quality, confidence distribution, and empty contexts.
"""

from collections import Counter, defaultdict
from .loader import safe_avg, percentile


def analyze_retrieval(events_by_session: dict, all_events: list) -> dict:
    """Analyze retrieval quality from TURN_RETRIEVAL events."""
    confidences = []
    latencies = []
    queries = []  # (confidence, query, session, turn)
    empty_contexts = []
    hallucination_guard_triggers = set()
    lang_confidences = defaultdict(list)
    dept_confidences = defaultdict(list)

    # Two-pass approach for per-language/department confidence:
    # Pass 1: collect retrieval confidences keyed by (sid, tn)
    retrieval_conf_map = {}
    retrieval_turns_found = set()
    for sid, evts in events_by_session.items():
        for ev in evts:
            if ev.get("type") == "TURN_RETRIEVAL":
                data = ev.get("data", {})
                tn = ev.get("turn_number", 0)
                conf = data.get("confidence_score", 0)
                key = (sid, tn)
                if key not in retrieval_conf_map:
                    retrieval_conf_map[key] = conf
                retrieval_turns_found.add(key)

    for sid, evts in events_by_session.items():
        for ev in evts:
            etype = ev.get("type", "")
            data = ev.get("data", {})
            tn = ev.get("turn_number", 0)

            if etype == "TURN_RETRIEVAL":
                conf = data.get("confidence_score", 0)
                lat = data.get("latency_ms", 0)
                query = data.get("retrieval_query", "")
                confidences.append(conf)
                latencies.append(lat)
                queries.append((conf, query, sid, tn))

                # Detect empty contexts
                top_chunks = data.get("top_chunks", [])
                if not top_chunks or conf == 0.0:
                    empty_contexts.append(
                        {
                            "session_id": sid,
                            "turn": tn,
                            "query": query[:100],
                            "confidence": conf,
                        }
                    )

            elif etype == "TURN_VALIDATION":
                if data.get("hallucination_guard_result") == "blocked":
                    hallucination_guard_triggers.add((sid, tn))

            elif etype == "TURN_INPUT":
                lang = data.get("detected_language", "")
                query = data.get("raw_stt_transcript", "")
                dept = _detect_department(query)
                if lang:
                    key = (sid, tn)
                    if key in retrieval_conf_map:
                        c = retrieval_conf_map[key]
                        lang_confidences[lang].append(c)
                        dept_confidences[dept].append(c)

    confidences.sort()
    queries.sort(key=lambda x: -x[0])

    # Confidence histogram (buckets of 0.1)
    hist = Counter()
    for c in confidences:
        bucket = int(c * 10) / 10
        hist[bucket] += 1

    report = {
        "count": len(confidences),
        "avg_confidence": round(safe_avg(confidences), 4),
        "median_confidence": round(percentile(confidences, 50), 4),
        "p95_confidence": round(percentile(confidences, 95), 4),
        "min_confidence": round(confidences[0], 4) if confidences else 0,
        "max_confidence": round(confidences[-1], 4) if confidences else 0,
        "avg_latency_ms": round(safe_avg(latencies), 1),
        "confidence_histogram": {str(k): v for k, v in sorted(hist.items())},
        "lowest_confidence_queries": [
            {"confidence": round(q[0], 4), "query": q[1][:80], "session": q[2], "turn": q[3]}
            for q in queries[-10:]
        ],
        "highest_confidence_queries": [
            {"confidence": round(q[0], 4), "query": q[1][:80], "session": q[2], "turn": q[3]}
            for q in queries[:10]
        ],
        "empty_contexts": len(empty_contexts),
        "empty_context_list": empty_contexts[:20],
        "hallucination_guard_triggers": len(hallucination_guard_triggers),
        "avg_confidence_by_language": {
            lang: round(safe_avg(vals), 4) for lang, vals in sorted(lang_confidences.items())
        },
        "avg_confidence_by_department": {
            dept: round(safe_avg(vals), 4) for dept, vals in sorted(dept_confidences.items())
        },
    }
    return report


def _detect_department(query: str) -> str:
    """Simple heuristic to detect department mentions."""
    q = query.lower()
    if any(kw in q for kw in ("cse", "computer science", "computer_science")):
        return "CSE"
    if any(kw in q for kw in ("ece", "electronics", "electronics and communication")):
        return "ECE"
    if any(kw in q for kw in ("ee", "electrical")):
        return "EE"
    if any(kw in q for kw in ("me", "mechanical")):
        return "ME"
    if any(kw in q for kw in ("ce", "civil")):
        return "CE"
    if any(kw in q for kw in ("it", "information technology")):
        return "IT"
    if any(kw in q for kw in ("aiml", "ai ml", "artificial intelligence")):
        return "AIML"
    if any(kw in q for kw in ("csd", "computer science and design")):
        return "CSD"
    if any(
        kw in q for kw in ("fee", "admission", "hostel", "placement", "general", "hello", "hi ")
    ):
        return "General"
    return "Unknown"


def print_retrieval_report(report: dict):
    """Pretty-print retrieval analysis."""
    print(f"\n{'=' * 60}")
    print("  RETRIEVAL ANALYSIS")
    print(f"{'=' * 60}")
    print(f"  Total retrievals: {report['count']}")
    print(
        f"  Avg confidence: {report['avg_confidence']}  |  Median: {report['median_confidence']}  |  P95: {report['p95_confidence']}"
    )
    print(f"  Min: {report['min_confidence']}  |  Max: {report['max_confidence']}")
    print(f"  Avg latency: {report['avg_latency_ms']}ms")
    print(
        f"  Empty contexts: {report['empty_contexts']}  |  Hallucination guard triggers: {report['hallucination_guard_triggers']}"
    )

    print(f"\n  Confidence Histogram:")
    for bucket, count in report["confidence_histogram"].items():
        bar = "#" * min(count, 60)
        print(f"    [{float(bucket):.1f}] {count:>5}  {bar}")

    print(f"\n  Avg Confidence by Language:")
    for lang, avg in sorted(
        report.get("avg_confidence_by_language", {}).items(), key=lambda x: -x[1]
    ):
        print(f"    {lang:<8} {avg:.4f}")

    print(f"\n  Avg Confidence by Department:")
    for dept, avg in sorted(
        report.get("avg_confidence_by_department", {}).items(), key=lambda x: -x[1]
    ):
        print(f"    {dept:<10} {avg:.4f}")

    print(f"\n  Lowest Confidence Queries (bottom 5):")
    for q in report["lowest_confidence_queries"][-5:]:
        print(f'    {q["confidence"]:.4f}  [{q["session"][:20]}] "{q["query"][:60]}"')
