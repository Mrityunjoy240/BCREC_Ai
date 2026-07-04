"""
Performance Report Generator
============================
Reads telemetry JSONL files from data/logs/conversations/ and produces:
  - Latency statistics (avg, p95, p99) per pipeline component
  - Slowest conversations / retrievals / LLM calls / TTS calls
  - Failure breakdown by error type
  - Language distribution
  - Confidence histogram
  - CSV + JSON output files

Usage:
    python scripts/performance_report.py [--input DIR] [--output DIR]
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import stdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_DEFAULT_INPUT = _PROJECT_ROOT / "data" / "logs" / "conversations"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data" / "logs" / "reports"


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


def load_events(input_dir: Path) -> list:
    events = []
    if not input_dir.exists():
        print(f"[ERROR] Input directory not found: {input_dir}")
        return events
    jsonl_files = sorted(input_dir.glob("session_*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL files in {input_dir}")
    for fp in jsonl_files:
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  [WARN] JSON decode error in {fp.name}: {e}")
    print(f"Loaded {len(events)} total events")
    return events


def analyze(events: list) -> dict:
    # Per-component latencies
    retrieval_latencies = []
    llm_total_latencies = []
    llm_ttfts = []
    llm_gen = []
    llm_post = []
    llm_tokens_sec = []
    tts_latencies = []
    all_latencies = []

    # Slowest calls
    slow_retrievals = []
    slow_llm = []
    slow_tts = []

    # Failures
    errors = []

    # Quality
    languages: Counter = Counter()
    confidences = []
    special_events = Counter()
    total_turns = 0
    total_sessions = 0
    hallucination_guards = 0
    ambiguous_queries = 0

    # Session-level data
    session_latencies = defaultdict(list)

    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {})
        sid = ev.get("session_id", "?")
        turn = ev.get("turn_number", 0)

        if etype == "SESSION_START":
            total_sessions += 1

        elif etype == "TURN_RETRIEVAL":
            lat = data.get("latency_ms", 0)
            retrieval_latencies.append(lat)
            slow_retrievals.append((lat, sid, turn, data.get("retrieval_query", "")))
            conf = data.get("confidence_score", 0)
            confidences.append(conf)

        elif etype == "TURN_LLM_LIFECYCLE":
            total_lat = data.get("total_llm_duration_ms", 0)
            ttft = data.get("ttft_ms", 0)
            gen = data.get("generation_duration_ms", 0)
            post = data.get("postprocessing_duration_ms", 0)
            tok_sec = data.get("estimated_tokens_per_second", 0)
            llm_total_latencies.append(total_lat)
            llm_ttfts.append(ttft)
            llm_gen.append(gen)
            llm_post.append(post)
            llm_tokens_sec.append(tok_sec)
            slow_llm.append((total_lat, sid, turn, data.get("model", "")))
            all_latencies.append(total_lat)
            session_latencies[sid].append(total_lat)

        elif etype == "TURN_LLM_COMPLETE":
            lat = data.get("total_latency_ms", 0) or data.get("latency_ms", 0)
            all_latencies.append(lat)
            session_latencies[sid].append(lat)

        elif etype == "TURN_VOICE":
            lat = data.get("tts_latency_ms", 0)
            tts_latencies.append(lat)
            slow_tts.append((lat, sid, turn))

        elif etype == "TURN_INPUT":
            total_turns += 1
            lang = data.get("detected_language", "")
            if lang:
                languages[lang] += 1

        elif etype == "TURN_ERROR":
            err_data = ev.get("data", {})
            if isinstance(err_data, dict) and "error_type" in err_data:
                errors.append(err_data)
            elif "error_type" in ev:
                errors.append(ev)

        elif etype == "SPECIAL_EVENT":
            event_name = ev.get("event", "")
            special_events[event_name] += 1

        elif etype == "SESSION_SUMMARY":
            hallucination_guards += ev.get("hallucination_guards_triggered", 0)
            ambiguous_queries += ev.get("ambiguous_queries", 0)

    # Sort for percentile / top-N
    retrieval_latencies.sort()
    llm_total_latencies.sort()
    llm_ttfts.sort()
    tts_latencies.sort()
    confidences.sort()
    # Top 10 slowest
    slow_retrievals.sort(key=lambda x: -x[0])
    slow_llm.sort(key=lambda x: -x[0])
    slow_tts.sort(key=lambda x: -x[0])

    # Per-session avg latency
    session_avgs = {sid: sum(vals) / len(vals) for sid, vals in session_latencies.items() if vals}
    sorted_sessions = sorted(session_avgs.items(), key=lambda x: -x[1])
    slowest_sessions = [
        (sid, round(avg, 1), len(session_latencies[sid])) for sid, avg in sorted_sessions[:10]
    ]

    # Failure breakdown
    error_types = Counter(e.get("error_type", "UNKNOWN") for e in errors)
    failure_total = len(errors)

    # Confidence histogram (buckets of 0.1)
    conf_hist = defaultdict(int)
    for c in confidences:
        bucket = int(c * 10) / 10
        conf_hist[bucket] += 1
    confidence_histogram = dict(sorted(conf_hist.items()))

    report = {
        "total_events": len(events),
        "total_sessions": total_sessions,
        "total_turns": total_turns,
        "total_errors": failure_total,
        "retrieval": {
            "count": len(retrieval_latencies),
            "avg_ms": round(sum(retrieval_latencies) / max(len(retrieval_latencies), 1), 1),
            "p50_ms": round(percentile(retrieval_latencies, 50), 1),
            "p95_ms": round(percentile(retrieval_latencies, 95), 1),
            "p99_ms": round(percentile(retrieval_latencies, 99), 1),
            "min_ms": round(retrieval_latencies[0], 1) if retrieval_latencies else 0,
            "max_ms": round(retrieval_latencies[-1], 1) if retrieval_latencies else 0,
        },
        "llm": {
            "count": len(llm_total_latencies),
            "avg_ms": round(sum(llm_total_latencies) / max(len(llm_total_latencies), 1), 1),
            "p50_ms": round(percentile(llm_total_latencies, 50), 1),
            "p95_ms": round(percentile(llm_total_latencies, 95), 1),
            "p99_ms": round(percentile(llm_total_latencies, 99), 1),
            "min_ms": round(llm_total_latencies[0], 1) if llm_total_latencies else 0,
            "max_ms": round(llm_total_latencies[-1], 1) if llm_total_latencies else 0,
            "avg_ttft_ms": round(sum(llm_ttfts) / max(len(llm_ttfts), 1), 1),
            "p95_ttft_ms": round(percentile(llm_ttfts, 95), 1),
            "avg_generation_ms": round(sum(llm_gen) / max(len(llm_gen), 1), 1),
            "avg_postprocessing_ms": round(sum(llm_post) / max(len(llm_post), 1), 1),
            "avg_tokens_per_second": round(sum(llm_tokens_sec) / max(len(llm_tokens_sec), 1), 2),
        },
        "tts": {
            "count": len(tts_latencies),
            "avg_ms": round(sum(tts_latencies) / max(len(tts_latencies), 1), 1),
            "p95_ms": round(percentile(tts_latencies, 95), 1),
            "p99_ms": round(percentile(tts_latencies, 99), 1),
            "min_ms": round(tts_latencies[0], 1) if tts_latencies else 0,
            "max_ms": round(tts_latencies[-1], 1) if tts_latencies else 0,
        },
        "slowest_sessions": slowest_sessions,
        "slowest_retrievals": [
            {"latency_ms": round(r[0], 1), "session_id": r[1], "turn": r[2], "query": r[3][:80]}
            for r in slow_retrievals[:10]
        ],
        "slowest_llm_calls": [
            {"latency_ms": round(r[0], 1), "session_id": r[1], "turn": r[2], "model": r[3]}
            for r in slow_llm[:10]
        ],
        "slowest_tts_calls": [
            {"latency_ms": round(r[0], 1), "session_id": r[1], "turn": r[2]} for r in slow_tts[:10]
        ],
        "failure_breakdown": dict(error_types),
        "failure_rate_pct": round(failure_total / max(total_turns, 1) * 100, 2),
        "language_distribution": dict(languages),
        "confidence_histogram": confidence_histogram,
        "special_events": dict(special_events),
        "hallucination_guards_triggered": hallucination_guards,
        "ambiguous_queries": ambiguous_queries,
        "average_confidence": round(sum(confidences) / max(len(confidences), 1), 4)
        if confidences
        else 0,
    }
    return report


def write_csv(report: dict, path: Path):
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Component", "Metric", "Value"])
        for component in ("retrieval", "llm", "tts"):
            for k, v in report.get(component, {}).items():
                w.writerow([component, k, v])
        w.writerow([])
        w.writerow(["Failure Breakdown", "Error Type", "Count"])
        for etype, count in report.get("failure_breakdown", {}).items():
            w.writerow(["failure_breakdown", etype, count])
        w.writerow([])
        w.writerow(["Language Distribution", "Language", "Turns"])
        for lang, count in report.get("language_distribution", {}).items():
            w.writerow(["language_distribution", lang, count])
        w.writerow([])
        w.writerow(["Confidence Histogram", "Bucket", "Count"])
        for bucket, count in report.get("confidence_histogram", {}).items():
            w.writerow(["confidence_histogram", bucket, count])
    print(f"  CSV report: {path}")


def print_report(report: dict):
    print("\n" + "=" * 60)
    print("  PERFORMANCE REPORT")
    print("=" * 60)
    print(
        f"  Sessions: {report['total_sessions']}  |  Turns: {report['total_turns']}  |  Errors: {report['total_errors']}  |  Events: {report['total_events']}"
    )

    print(f"\n  --- Retieval ---")
    r = report["retrieval"]
    print(f"  Avg: {r['avg_ms']}ms  P95: {r['p95_ms']}ms  P99: {r['p99_ms']}ms  (n={r['count']})")

    print(f"\n  --- LLM ---")
    l = report["llm"]
    print(f"  Avg: {l['avg_ms']}ms  P95: {l['p95_ms']}ms  P99: {l['p99_ms']}ms  (n={l['count']})")
    print(
        f"  Avg TTFT: {l['avg_ttft_ms']}ms  Avg Gen: {l['avg_generation_ms']}ms  Avg Post: {l['avg_postprocessing_ms']}ms"
    )
    print(f"  Avg Tok/s: {l['avg_tokens_per_second']}")

    print(f"\n  --- TTS ---")
    t = report["tts"]
    print(f"  Avg: {t['avg_ms']}ms  P95: {t['p95_ms']}ms  P99: {t['p99_ms']}ms  (n={t['count']})")

    print(f"\n  --- Failures ---")
    for etype, count in report["failure_breakdown"].items():
        print(f"  {etype}: {count}")
    print(f"  Failure rate: {report['failure_rate_pct']}%")

    print(f"\n  --- Language Distribution ---")
    for lang, count in report["language_distribution"].items():
        print(f"  {lang}: {count}")

    print(f"\n  --- Confidence Histogram ---")
    for bucket, count in report["confidence_histogram"].items():
        bar = "#" * min(count, 40)
        print(f"  [{bucket:.1f}] {count:>4}  {bar}")

    print(f"\n  --- Quality ---")
    print(f"  Hallucination guards triggered: {report['hallucination_guards_triggered']}")
    print(f"  Ambiguous queries: {report['ambiguous_queries']}")
    for ev, count in report.get("special_events", {}).items():
        if count > 0:
            print(f"  {ev}: {count}")

    print(f"\n  --- Slowest Sessions ---")
    for sid, avg, n in report.get("slowest_sessions", []):
        print(f"  {sid}: avg={avg}ms over {n} turns")

    print(f"\n  --- Top 5 Slowest LLM Calls ---")
    for c in report.get("slowest_llm_calls", [])[:5]:
        print(
            f"  {c['latency_ms']}ms  [{c['session_id'][:20]}] turn={c['turn']} model={c['model']}"
        )

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Generate performance report from telemetry JSONL files"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=str(_DEFAULT_INPUT),
        help="Input directory containing JSONL files",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(_DEFAULT_OUTPUT),
        help="Output directory for reports",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    events = load_events(input_dir)
    if not events:
        print("[ERROR] No events loaded. Nothing to report.")
        sys.exit(1)

    report = analyze(events)
    write_csv(report, output_dir / "performance_report.csv")

    json_path = output_dir / "performance_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"  JSON report: {json_path}")

    print_report(report)


if __name__ == "__main__":
    main()
