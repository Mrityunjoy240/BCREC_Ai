"""
Task 4: Conversation Quality Dashboard
=======================================
Computes quality metrics from SESSION_SUMMARY accumulators and special events.
"""

from collections import Counter
from .loader import safe_avg


def analyze_quality(events_by_session: dict, all_events: list) -> dict:
    """Compute conversation quality metrics."""
    total_sessions = len(events_by_session)
    total_errors = 0

    # Count total turns from TURN_INPUT events (not summaries, which may be missing)
    total_turns = sum(1 for ev in all_events if ev.get("type") == "TURN_INPUT")

    # Track per-session turn counts from input events
    session_turn_counts = Counter()
    for ev in all_events:
        if ev.get("type") == "TURN_INPUT":
            session_turn_counts[ev.get("session_id", "")] += 1

    accums = {
        "clarification_prompts": 0,
        "repeat_requests": 0,
        "language_switches": 0,
        "follow_up_queries": 0,
        "hallucination_guards_triggered": 0,
        "low_confidence_retrievals": 0,
        "confidence_rejections": 0,
        "empty_retrievals": 0,
        "out_of_kb": 0,
        "interruptions": 0,
        "ambiguous_queries": 0,
    }

    durations = []
    turns_per_session = list(session_turn_counts.values())

    # Read from SESSION_SUMMARY events (for accumulators and durations)
    for sid, evts in events_by_session.items():
        for ev in evts:
            if ev.get("type") == "SESSION_SUMMARY":
                dur = ev.get("duration_seconds", 0)
                durations.append(dur)
                total_errors += ev.get("total_errors", 0)
                for key in accums:
                    accums[key] += ev.get(key, 0)

    # Count hallucination guards from TURN_VALIDATION events
    # (SESSION_SUMMARY hallucination_guards_triggered may be inaccurate)
    hg_from_validation = 0
    for ev in all_events:
        if ev.get("type") == "TURN_VALIDATION":
            if ev.get("data", {}).get("hallucination_guard_result") == "blocked":
                hg_from_validation += 1
    if hg_from_validation > accums.get("hallucination_guards_triggered", 0):
        accums["hallucination_guards_triggered"] = hg_from_validation

    # Count special events from SPECIAL_EVENT log entries
    special_counts = Counter()
    for ev in all_events:
        if ev.get("type") == "SPECIAL_EVENT":
            special_counts[ev.get("event", "")] += 1

    # Compute rates
    n = max(total_turns, 1)
    rates = {k: round(v / n * 100, 2) for k, v in accums.items()}
    rates["special_events"] = {k: round(v / n * 100, 2) for k, v in special_counts.items()}

    avg_turns = safe_avg(turns_per_session)
    avg_duration = safe_avg(durations)

    report = {
        "total_sessions": total_sessions,
        "total_turns": total_turns,
        "total_errors": total_errors,
        "avg_turns_per_session": round(avg_turns, 1),
        "avg_session_duration_seconds": round(avg_duration, 1),
        "raw_counts": accums,
        "rates_per_turn_pct": rates,
        "special_events_raw": dict(special_counts),
    }
    return report


def print_quality_report(report: dict):
    """Pretty-print quality dashboard."""
    print(f"\n{'=' * 60}")
    print("  CONVERSATION QUALITY DASHBOARD")
    print(f"{'=' * 60}")
    print(
        f"  Sessions: {report['total_sessions']}  |  Turns: {report['total_turns']}  |  Errors: {report['total_errors']}"
    )
    print(
        f"  Avg turns/session: {report['avg_turns_per_session']}  |  Avg session duration: {report['avg_session_duration_seconds']}s"
    )
    print()
    print(f"  {'Metric':<35} {'Count':>8} {'Rate/Turn':>10}")
    print("  " + "-" * 55)
    for metric in [
        "clarification_prompts",
        "repeat_requests",
        "language_switches",
        "follow_up_queries",
        "hallucination_guards_triggered",
        "low_confidence_retrievals",
        "confidence_rejections",
        "empty_retrievals",
        "out_of_kb",
        "interruptions",
        "ambiguous_queries",
    ]:
        c = report["raw_counts"].get(metric, 0)
        r = report["rates_per_turn_pct"].get(metric, 0)
        print(f"  {metric:<35} {c:>8} {r:>9.2f}%")

    print(f"\n  Special Events:")
    for ev, c in sorted(report.get("special_events_raw", {}).items(), key=lambda x: -x[1]):
        r = report["rates_per_turn_pct"]["special_events"].get(ev, 0)
        print(f"    {ev:<30} {c:>6}  {r:>6.2f}%")
