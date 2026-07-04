"""
Task 1: Telemetry Coverage Audit
=================================
Validates telemetry completeness for every session.
"""

from collections import defaultdict

REQUIRED_EVENT_TYPES = [
    "SESSION_START",
    "SESSION_SUMMARY",
    "TURN_INPUT",
    "TURN_RETRIEVAL",
    "TURN_LLM_LIFECYCLE",
    "TURN_VALIDATION",
    "TURN_VOICE",
    "TURN_ERROR",
]

TURN_EVENT_TYPES = {
    "TURN_INPUT",
    "TURN_RETRIEVAL",
    "TURN_LLM_LIFECYCLE",
    "TURN_VALIDATION",
    "TURN_VOICE",
    "TURN_ERROR",
    "TURN_PROMPT",
    "TURN_LLM_COMPLETE",
    "TURN_LLM_START",
}


def analyze_coverage(events_by_session: dict) -> list:
    """Produce per-session coverage report.

    Returns list of dicts with: session_id, expected_turns, actual_turns,
    missing_events, extra_events, coverage_pct, notes.
    """
    results = []

    for sid, evts in events_by_session.items():
        types_present = defaultdict(int)
        turn_numbers = set()
        has_start = False
        has_summary = False
        start_ts = None
        last_turn_event_ts = None

        for ev in evts:
            etype = ev.get("type", "")
            types_present[etype] += 1
            tn = ev.get("turn_number")
            if tn is not None:
                turn_numbers.add(tn)

            if etype == "SESSION_START":
                has_start = True
                start_ts = ev.get("timestamp_unix", 0)
            elif etype == "SESSION_SUMMARY":
                has_summary = True

        expected_turns = types_present.get("TURN_INPUT", 0)
        actual_turns = len(turn_numbers)
        missing = []
        extra = []

        for rt in REQUIRED_EVENT_TYPES:
            if types_present.get(rt, 0) == 0:
                missing.append(rt)

        # Check for extra turn-related events beyond TURN_INPUT
        turn_event_counts = {t: types_present.get(t, 0) for t in TURN_EVENT_TYPES}
        max_turn_events = max(turn_event_counts.values()) if turn_event_counts else 0
        for t, c in turn_event_counts.items():
            if c > expected_turns and expected_turns > 0:
                extra.append(f"{t}(count={c},expected~={expected_turns})")

        coverage_pct = round((1 - len(missing) / max(len(REQUIRED_EVENT_TYPES), 1)) * 100, 1)

        # Generate explanatory notes
        notes = []
        if not has_start:
            notes.append("SESSION_START missing — session may have been created by old code")
        if not has_summary:
            notes.append("SESSION_SUMMARY missing — session may have crashed or not ended properly")
        if expected_turns == 0 and not has_start:
            notes.append("No turns at all — possible file corruption or empty session")
        if expected_turns != actual_turns:
            notes.append(
                f"Turn numbers non-contiguous ({actual_turns} unique / {expected_turns} expected)"
            )
        if types_present.get("TURN_ERROR", 0) > 0:
            notes.append(
                f"{types_present['TURN_ERROR']} error(s) detected — see root cause analysis"
            )
        if types_present.get("TURN_RETRIEVAL", 0) == 0 and expected_turns > 0:
            notes.append("Retrieval never fired — possible pre-LLM failure or cached response")
        if types_present.get("TURN_LLM_LIFECYCLE", 0) == 0 and expected_turns > 0:
            notes.append(
                "LLM lifecycle events missing — may use older sync path without detailed telemetry"
            )
        if types_present.get("TURN_VALIDATION", 0) == 0 and expected_turns > 0:
            notes.append(
                "Validation events missing — possibly skipped due to error or early return"
            )
        if types_present.get("TURN_VOICE", 0) == 0 and expected_turns > 0:
            notes.append("Voice output missing — TTS may have failed or been skipped")
        if types_present.get("TURN_INPUT", 0) > 0 and types_present.get("SESSION_SUMMARY", 0) == 0:
            notes.append("Session has turns but no summary — abnormal termination")
        if types_present.get("SESSION_SUMMARY", 0) > 0 and has_start and start_ts:
            # Check if session ran very briefly
            for ev in reversed(evts):
                if ev.get("type") == "SESSION_SUMMARY":
                    dur = ev.get("duration_seconds", 0)
                    if dur < 1 and expected_turns > 0:
                        notes.append(
                            f"Very short session ({dur}s for {expected_turns} turns) — may have crashed"
                        )
                    break

        results.append(
            {
                "session_id": sid,
                "expected_turns": expected_turns,
                "actual_turns": actual_turns,
                "missing_events": "; ".join(missing) if missing else "None",
                "extra_events": "; ".join(extra[:3]) if extra else "None",
                "coverage_pct": coverage_pct,
                "notes": "; ".join(notes) if notes else "OK",
            }
        )

    return results


def print_coverage_report(results: list):
    """Pretty-print the coverage report."""
    sep = "-" * 100
    print(f"\n{'=' * 60}")
    print("  TELEMETRY COVERAGE AUDIT")
    print(f"{'=' * 60}")
    print(
        f"{'Session ID':<30} {'Exp':>3} {'Act':>3} {'Cov%':>5}  {'Missing Events':<30}  {'Notes'}"
    )
    print(sep)
    for r in sorted(results, key=lambda x: x["coverage_pct"]):
        sid = r["session_id"][:28]
        missing = r["missing_events"]
        if len(missing) > 28:
            missing = missing[:26] + "..."
        notes = r["notes"][:40]
        print(
            f"{sid:<30} {r['expected_turns']:>3} {r['actual_turns']:>3} {r['coverage_pct']:>4.0f}%  "
            f"{missing:<30}  {notes}"
        )

    full_coverage = sum(1 for r in results if r["coverage_pct"] >= 90)
    print(sep)
    print(
        f"  Total sessions: {len(results)}  |  Full coverage (>=90%): {full_coverage}  |  "
        f"Avg coverage: {sum(r['coverage_pct'] for r in results) / max(len(results), 1):.1f}%"
    )
