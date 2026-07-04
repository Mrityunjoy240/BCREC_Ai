"""
Task 3: Latency Analysis
=========================
Computes percentiles (avg, median, P90, P95, P99) per pipeline component
and identifies outliers.
"""

from collections import defaultdict
from .loader import percentile, safe_avg, safe_median, safe_stdev, detect_outliers


def analyze_latency(events_by_session: dict) -> dict:
    """Analyze latency for all pipeline components."""
    retrieval_lats = []
    llm_ttfts = []
    llm_gen = []
    llm_post = []
    llm_total = []
    tts_lats = []
    overall_lats = []  # per-turn composite: retrieval + llm + tts

    slow_turns = []  # (latency, session, turn, component)
    session_latencies = defaultdict(list)

    # Collect per-turn component latencies to compute composite overall_turn
    turn_components = defaultdict(lambda: {"retrieval": 0, "llm_total": 0, "tts": 0})

    for sid, evts in events_by_session.items():
        for ev in evts:
            etype = ev.get("type", "")
            data = ev.get("data", {})
            tn = ev.get("turn_number", 0)
            ts = ev.get("timestamp_unix", 0)

            if etype == "TURN_RETRIEVAL":
                lat = data.get("latency_ms", 0)
                if lat > 0:
                    retrieval_lats.append(lat)
                    slow_turns.append((lat, sid, tn, "retrieval"))
                    turn_components[(sid, tn)]["retrieval"] = lat

            elif etype == "TURN_LLM_LIFECYCLE":
                ttft = data.get("ttft_ms", 0)
                gen = data.get("generation_duration_ms", 0)
                post = data.get("postprocessing_duration_ms", 0)
                total = data.get("total_llm_duration_ms", 0)
                if ttft > 0:
                    llm_ttfts.append(ttft)
                if gen > 0:
                    llm_gen.append(gen)
                if post > 0:
                    llm_post.append(post)
                if total > 0:
                    llm_total.append(total)
                    slow_turns.append((total, sid, tn, "llm_total"))
                    session_latencies[sid].append(total)
                    turn_components[(sid, tn)]["llm_total"] = total

            elif etype == "TURN_VOICE":
                lat = data.get("tts_latency_ms", 0)
                if lat > 0:
                    tts_lats.append(lat)
                    turn_components[(sid, tn)]["tts"] = lat

    # Compute composite overall_turn as sum of available components per turn
    for key, comps in turn_components.items():
        total = comps["retrieval"] + comps["llm_total"] + comps["tts"]
        if total > 0:
            overall_lats.append(total)

    # Sort for percentile computation
    def _pct(vals):
        s = sorted(vals)
        return {
            "count": len(vals),
            "avg_ms": round(safe_avg(vals), 1),
            "median_ms": round(safe_median(s), 1),
            "p90_ms": round(percentile(s, 90), 1),
            "p95_ms": round(percentile(s, 95), 1),
            "p99_ms": round(percentile(s, 99), 1),
            "min_ms": round(s[0], 1) if s else 0,
            "max_ms": round(s[-1], 1) if s else 0,
            "stdev_ms": round(safe_stdev(vals), 1),
        }

    # Top slowest turns
    slow_turns.sort(key=lambda x: -x[0])

    # Per-session average latencies
    session_avgs = {sid: safe_avg(vals) for sid, vals in session_latencies.items() if vals}
    slow_sessions = sorted(session_avgs.items(), key=lambda x: -x[1])[:20]

    # Outliers
    outlier_indices = set(detect_outliers(overall_lats, 2))
    outlier_turns = []
    for i, lat in enumerate(overall_lats):
        if i in outlier_indices:
            # Find the session/turn that corresponds
            for sid, evts in events_by_session.items():
                for ev in evts:
                    if ev.get("type") == "TURN_LLM_LIFECYCLE":
                        d = ev.get("data", {})
                        if d.get("total_llm_duration_ms", 0) == lat:
                            outlier_turns.append(
                                {
                                    "latency_ms": round(lat, 1),
                                    "session_id": sid,
                                    "turn": ev.get("turn_number", 0),
                                }
                            )
                            break

    return {
        "retrieval": _pct(retrieval_lats),
        "llm_ttft": _pct(llm_ttfts),
        "llm_generation": _pct(llm_gen),
        "llm_postprocessing": _pct(llm_post),
        "llm_total": _pct(llm_total),
        "tts": _pct(tts_lats),
        "overall_turn": _pct(overall_lats),
        "slowest_turns": [
            {"latency_ms": round(r[0], 1), "session_id": r[1], "turn": r[2], "component": r[3]}
            for r in slow_turns[:20]
        ],
        "slowest_sessions": [
            {"session_id": sid, "avg_latency_ms": round(avg, 1)} for sid, avg in slow_sessions[:20]
        ],
        "outliers_gt_2sigma": outlier_turns[:20],
        "outlier_count": len(outlier_turns),
    }


def print_latency_report(report: dict):
    """Pretty-print latency analysis."""
    print(f"\n{'=' * 60}")
    print("  LATENCY ANALYSIS")
    print(f"{'=' * 60}")
    print(
        f"  {'Component':<22} {'Count':>6} {'Avg':>10} {'P50':>10} {'P90':>10} {'P95':>10} {'P99':>10} {'Max':>10}"
    )
    print("  " + "-" * 90)
    for component, label in [
        ("retrieval", "Retrieval"),
        ("llm_ttft", "LLM TTFT"),
        ("llm_generation", "LLM Generation"),
        ("llm_postprocessing", "LLM Post-proc"),
        ("llm_total", "LLM Total"),
        ("tts", "TTS"),
        ("overall_turn", "Overall Turn"),
    ]:
        c = report.get(component, {})
        print(
            f"  {label:<22} {c.get('count', 0):>6} {c.get('avg_ms', 0):>9.0f}ms "
            f"{c.get('median_ms', 0):>9.0f}ms {c.get('p90_ms', 0):>9.0f}ms "
            f"{c.get('p95_ms', 0):>9.0f}ms {c.get('p99_ms', 0):>9.0f}ms "
            f"{c.get('max_ms', 0):>9.0f}ms"
        )

    print(f"\n  Outliers (>2σ): {report['outlier_count']}")
    print(f"\n  Top 10 Slowest Turns:")
    for t in report["slowest_turns"][:10]:
        print(
            f"    {t['latency_ms']:>8.0f}ms  [{t['session_id'][:24]}] turn={t['turn']} ({t['component']})"
        )

    print(f"\n  Top 10 Slowest Sessions (avg LLM latency):")
    for s in report["slowest_sessions"][:10]:
        print(f"    {s['avg_latency_ms']:>8.0f}ms  {s['session_id'][:40]}")
