"""
Task 8: Regression Detection
=============================
Compares two telemetry datasets to identify statistically significant changes.
"""

from collections import Counter
from .loader import safe_avg, percentile


def analyze_regression(
    current_events: list,
    previous_events: list,
    current_label: str = "current",
    previous_label: str = "previous",
) -> dict:
    """Compare two sets of telemetry events and report changes."""

    def _summarize(events):
        by_type = Counter(e.get("type", "") for e in events)

        # Latencies
        retrieval_lats = []
        llm_totals = []
        tts_lats = []
        confidences = []
        errors = []

        for e in events:
            data = e.get("data", {})
            et = e.get("type", "")
            if et == "TURN_RETRIEVAL":
                retrieval_lats.append(data.get("latency_ms", 0) or 0)
                confidences.append(data.get("confidence_score", 0) or 0)
            elif et == "TURN_LLM_LIFECYCLE":
                llm_totals.append(data.get("total_llm_duration_ms", 0) or 0)
            elif et == "TURN_VOICE":
                tts_lats.append(data.get("tts_latency_ms", 0) or 0)
            elif et == "TURN_ERROR":
                err_data = data if data else {}
                if not err_data:
                    err_data = e
                errors.append(err_data.get("error_type", "UNKNOWN"))

        retrieval_lats = [v for v in retrieval_lats if v > 0]
        llm_totals = [v for v in llm_totals if v > 0]
        tts_lats = [v for v in tts_lats if v > 0]

        return {
            "event_counts": dict(by_type),
            "total_events": len(events),
            "total_turns": by_type.get("TURN_INPUT", 0),
            "total_sessions": by_type.get("SESSION_START", 0),
            "avg_retrieval_latency_ms": safe_avg(retrieval_lats),
            "avg_llm_latency_ms": safe_avg(llm_totals),
            "avg_tts_latency_ms": safe_avg(tts_lats),
            "avg_confidence": safe_avg(confidences),
            "total_errors": len(errors),
            "error_types": dict(Counter(errors)),
        }

    current = _summarize(current_events)
    previous = _summarize(previous_events)

    # Compare
    changes = {}
    regression_flags = []

    numeric_keys = [
        ("avg_retrieval_latency_ms", "Retrieval Latency", "down"),
        ("avg_llm_latency_ms", "LLM Latency", "down"),
        ("avg_tts_latency_ms", "TTS Latency", "down"),
        ("avg_confidence", "Retrieval Confidence", "up"),
        ("total_errors", "Error Count", "down"),
    ]

    for key, label, improve_dir in numeric_keys:
        cur = current.get(key, 0)
        prv = previous.get(key, 0)
        if prv == 0:
            pct = 0
        else:
            pct = round((cur - prv) / prv * 100, 1)
        is_regression = False
        if improve_dir == "down" and pct > 5:
            is_regression = True
        elif improve_dir == "up" and pct < -5:
            is_regression = True
        changes[key] = {
            "label": label,
            current_label: cur,
            previous_label: prv,
            "change_pct": pct,
            "regression": is_regression,
        }
        if is_regression:
            direction = "increased" if pct > 0 else "decreased"
            regression_flags.append(f"{label} {direction} by {abs(pct)}%")

    # Error type changes
    cur_errors = current.get("error_types", {})
    prv_errors = previous.get("error_types", {})
    all_error_types = set(list(cur_errors.keys()) + list(prv_errors.keys()))
    error_changes = {}
    for et in sorted(all_error_types):
        cur_c = cur_errors.get(et, 0)
        prv_c = prv_errors.get(et, 0)
        diff = cur_c - prv_c
        if diff != 0:
            error_changes[et] = {"current": cur_c, "previous": prv_c, "diff": diff}
    changes["error_type_changes"] = error_changes

    changes["significant_regressions"] = regression_flags
    changes["summary"] = {
        "current_events": current["total_events"],
        "previous_events": previous["total_events"],
        "current_sessions": current["total_sessions"],
        "previous_sessions": previous["total_sessions"],
        "regression_count": len(regression_flags),
    }

    return changes


def print_regression_report(report: dict, current_label="current", previous_label="previous"):
    """Pretty-print regression analysis."""
    print(f"\n{'=' * 60}")
    print("  REGRESSION DETECTION")
    print(f"  {current_label} vs {previous_label}")
    print(f"{'=' * 60}")
    s = report["summary"]
    print(f"  {current_label}: {s['current_events']} events, {s['current_sessions']} sessions")
    print(f"  {previous_label}: {s['previous_events']} events, {s['previous_sessions']} sessions")

    print(f"\n  {'Metric':<35} {current_label:<12} {previous_label:<12} {'Change':>8}  {'Status'}")
    print("  " + "-" * 80)
    for key, info in report.items():
        if key in ("error_type_changes", "significant_regressions", "summary"):
            continue
        if isinstance(info, dict) and "change_pct" in info:
            cval = info.get(current_label, 0)
            pval = info.get(previous_label, 0)
            pct = info.get("change_pct", 0)
            status = "⚠ REGRESSION" if info.get("regression") else "✓"
            print(f"  {info['label']:<35} {cval:<12} {pval:<12} {pct:>+7.1f}%  {status}")

    if report.get("error_type_changes"):
        print(f"\n  Error Type Changes:")
        for et, ch in report["error_type_changes"].items():
            print(f"    {et:<25} {ch['current']} (was {ch['previous']}, diff={ch['diff']:+d})")

    if report.get("significant_regressions"):
        print(f"\n  ⚠ Significant Regressions:")
        for r in report["significant_regressions"]:
            print(f"    - {r}")
    else:
        print(f"\n  No significant regressions detected.")
