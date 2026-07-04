"""
Task 2: Root Cause Analysis
============================
Groups failures by error type and produces diagnostic statistics.
"""

from collections import Counter, defaultdict
from .loader import safe_avg


def analyze_root_cause(events_by_session: dict) -> dict:
    """Analyze all TURN_ERROR events grouped by error_type."""
    all_errors = []
    per_session_errors = defaultdict(list)

    for sid, evts in events_by_session.items():
        for ev in evts:
            if ev.get("type") == "TURN_ERROR":
                data = ev.get("data", {})
                err = {
                    "session_id": sid,
                    "turn_number": ev.get("turn_number", 0),
                    "error_type": data.get("error_type", "UNKNOWN"),
                    "exception_class": data.get("exception_class", ""),
                    "exception_message": data.get("exception_message", ""),
                    "stack_location": data.get("stack_location", ""),
                    "elapsed_ms": data.get("elapsed_ms", 0),
                }
                all_errors.append(err)
                per_session_errors[err["error_type"]].append(err)

    type_counts = Counter(e["error_type"] for e in all_errors)
    total = len(all_errors)

    categories = {}
    for etype in sorted(type_counts):
        group = per_session_errors[etype]
        sessions = list(set(e["session_id"] for e in group))
        categories[etype] = {
            "count": type_counts[etype],
            "percentage": round(type_counts[etype] / max(total, 1) * 100, 1),
            "affected_sessions": len(sessions),
            "session_list": sessions,
            "avg_elapsed_ms": round(safe_avg([e["elapsed_ms"] for e in group]), 1),
            "most_common_exception": Counter(e["exception_class"] for e in group).most_common(1)[0][
                0
            ]
            if group
            else "",
        }

    return {
        "total_errors": total,
        "categories": categories,
        "all_errors": all_errors,
    }


def print_root_cause_report(report: dict):
    """Pretty-print the root cause analysis."""
    print(f"\n{'=' * 60}")
    print("  ROOT CAUSE ANALYSIS")
    print(f"{'=' * 60}")
    print(f"  Total errors: {report['total_errors']}")
    print()
    print(
        f"  {'Error Type':<25} {'Count':>6} {'%':>6}  {'Sessions':>8}  {'Avg Elapsed':>11}  {'Top Exception'}"
    )
    print("  " + "-" * 90)
    for etype, cat in sorted(report["categories"].items(), key=lambda x: -x[1]["count"]):
        print(
            f"  {etype:<25} {cat['count']:>6} {cat['percentage']:>5.1f}%  "
            f"{cat['affected_sessions']:>8}  {cat['avg_elapsed_ms']:>8.0f}ms  "
            f"{cat['most_common_exception'][:25]}"
        )
    print()
