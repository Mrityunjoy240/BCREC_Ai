#!/usr/bin/env python3
"""
Telemetry Analytics CLI
=======================
Runs all 9 analyses against telemetry JSONL logs and produces reports.

Usage:
    python scripts/analytics/run_all.py --input <log_dir> --output <report_dir>
    python scripts/analytics/run_all.py --task coverage --input <log_dir>
    python scripts/analytics/run_all.py --task timeline --session <session_id>
"""

import argparse
import json
import os
import sys
import csv
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR.parent / "backend"))

from analytics.loader import load_events, index_by_session, _DEFAULT_INPUT, _DEFAULT_OUTPUT
from analytics.coverage import analyze_coverage, print_coverage_report
from analytics.root_cause import analyze_root_cause, print_root_cause_report
from analytics.latency import analyze_latency, print_latency_report
from analytics.quality import analyze_quality, print_quality_report
from analytics.retrieval import analyze_retrieval, print_retrieval_report
from analytics.llm_analysis import analyze_llm, print_llm_report
from analytics.timeline import generate_all_timelines
from analytics.regression import analyze_regression, print_regression_report
from analytics.summary import generate_summary


def write_csv(filename: str, data: list, fieldnames: list):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(data)


def write_json(filename: str, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def run_all(input_dir: str, output_dir: str, session_filter: str = ""):
    """Run all analyses and produce reports."""
    print(f"Loading events from {input_dir}...")
    events = load_events(input_dir, session_filter=session_filter if session_filter else None)
    print(f"Loaded {len(events)} events.\n")

    if not events:
        print("No events loaded. Exiting.")
        return

    by_session = index_by_session(events)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_reports = {}

    # Task 1: Coverage
    print("=" * 60)
    print("TASK 1: Telemetry Coverage Audit")
    coverage = analyze_coverage(by_session)
    print_coverage_report(coverage)
    write_csv(
        str(out / "coverage_audit.csv"),
        coverage,
        [
            "session_id",
            "expected_turns",
            "actual_turns",
            "coverage_pct",
            "missing_events",
            "extra_events",
            "notes",
        ],
    )
    write_json(str(out / "coverage_audit.json"), coverage)
    all_reports["coverage"] = coverage
    print()

    # Task 2: Root Cause
    print("=" * 60)
    print("TASK 2: Root Cause Analysis")
    root_cause = analyze_root_cause(by_session)
    print_root_cause_report(root_cause)
    write_json(str(out / "root_cause.json"), root_cause)
    all_reports["root_cause"] = root_cause
    print()

    # Task 3: Latency
    print("=" * 60)
    print("TASK 3: Latency Analysis")
    latency = analyze_latency(by_session)
    print_latency_report(latency)
    write_json(str(out / "latency.json"), latency)

    # Flatten latency for CSV
    latency_rows = []
    for comp, label in [
        ("retrieval", "Retrieval"),
        ("llm_ttft", "LLM TTFT"),
        ("llm_generation", "LLM Generation"),
        ("llm_postprocessing", "LLM Post-proc"),
        ("llm_total", "LLM Total"),
        ("tts", "TTS"),
        ("overall_turn", "Overall Turn"),
    ]:
        c = latency.get(comp, {})
        c["component"] = label
        latency_rows.append(c)
    write_csv(
        str(out / "latency.csv"),
        latency_rows,
        [
            "component",
            "count",
            "avg_ms",
            "median_ms",
            "p90_ms",
            "p95_ms",
            "p99_ms",
            "min_ms",
            "max_ms",
            "stdev_ms",
        ],
    )
    all_reports["latency"] = latency
    print()

    # Task 4: Quality
    print("=" * 60)
    print("TASK 4: Conversation Quality Dashboard")
    quality = analyze_quality(by_session, events)
    print_quality_report(quality)
    write_json(str(out / "quality.json"), quality)

    quality_rows = [
        {"metric": k, "count": v, "rate_per_turn_pct": quality["rates_per_turn_pct"].get(k, 0)}
        for k, v in quality["raw_counts"].items()
    ]
    write_csv(str(out / "quality.csv"), quality_rows, ["metric", "count", "rate_per_turn_pct"])
    all_reports["quality"] = quality
    print()

    # Task 5: Retrieval
    print("=" * 60)
    print("TASK 5: Retrieval Analysis")
    retrieval = analyze_retrieval(by_session, events)
    print_retrieval_report(retrieval)
    write_json(str(out / "retrieval.json"), retrieval)
    all_reports["retrieval"] = retrieval
    print()

    # Task 6: LLM Analysis
    print("=" * 60)
    print("TASK 6: LLM Analysis")
    llm_result = analyze_llm(by_session, events)
    print_llm_report(llm_result)
    write_json(str(out / "llm_analysis.json"), llm_result)
    all_reports["llm"] = llm_result
    print()

    # Task 7: Timelines
    print("=" * 60)
    print("TASK 7: Session Timelines")
    timeline_dir = out / "timelines"
    generated = generate_all_timelines(by_session, str(timeline_dir), max_sessions=20)
    print(f"  Generated {len(generated)} timeline HTML files in {timeline_dir}")
    print()

    # Task 9: Engineering Summary
    print("=" * 60)
    print("TASK 9: Engineering Summary")
    summary_path = str(out / "engineering_summary.md")
    generate_summary(all_reports, summary_path)
    print(f"  Summary written to {summary_path}")

    print(f"\n{'=' * 60}")
    print(f"  ALL REPORTS WRITTEN TO: {out.resolve()}")
    print(f"{'=' * 60}")


def run_task_coverage(input_dir: str, output_dir: str):
    events = load_events(input_dir)
    by_session = index_by_session(events)
    coverage = analyze_coverage(by_session)
    print_coverage_report(coverage)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(
        str(out / "coverage_audit.csv"),
        coverage,
        [
            "session_id",
            "expected_turns",
            "actual_turns",
            "coverage_pct",
            "missing_events",
            "extra_events",
            "notes",
        ],
    )
    write_json(str(out / "coverage_audit.json"), coverage)


def run_task_timeline(input_dir: str, output_dir: str, session_id: str = ""):
    from analytics.timeline import generate_timeline_html

    events = load_events(input_dir, session_filter=session_id if session_id else None)
    by_session = index_by_session(events)
    out = Path(output_dir) / "timelines"
    out.mkdir(parents=True, exist_ok=True)

    if session_id:
        evts = by_session.get(session_id, [])
        if not evts:
            print(f"Session '{session_id}' not found in {input_dir}")
            return
        path = str(out / f"timeline_{session_id.replace('/', '_')}.html")
        generate_timeline_html(session_id, evts, path)
        print(f"Timeline: {path}")
    else:
        generated = generate_all_timelines(by_session, str(out), max_sessions=20)
        print(f"Generated {len(generated)} timelines in {out}")


def run_task_regression(input_dir: str, output_dir: str, baseline_dir: str):
    events_current = load_events(input_dir)
    events_baseline = load_events(baseline_dir)
    report = analyze_regression(
        events_current, events_baseline, current_label="current", previous_label="baseline"
    )
    print_regression_report(report)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(str(out / "regression.json"), report)


def main():
    parser = argparse.ArgumentParser(description="BCREC Telemetry Analytics")
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=str(_DEFAULT_INPUT),
        help=f"Input directory with JSONL files (default: {_DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(_DEFAULT_OUTPUT),
        help=f"Output directory for reports (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--task",
        "-t",
        type=str,
        default="all",
        choices=[
            "all",
            "coverage",
            "root_cause",
            "latency",
            "quality",
            "retrieval",
            "llm",
            "timeline",
            "regression",
            "summary",
        ],
        help="Analysis task to run (default: all)",
    )
    parser.add_argument(
        "--session", "-s", type=str, default="", help="Session ID filter (for timeline)"
    )
    parser.add_argument(
        "--baseline", "-b", type=str, default="", help="Baseline directory for regression detection"
    )
    parser.add_argument(
        "--filter", "-f", type=str, default="", help="Session ID prefix filter (e.g., 'sim_')"
    )

    args = parser.parse_args()

    if args.task == "all":
        run_all(args.input, args.output, args.filter)
    elif args.task == "coverage":
        run_task_coverage(args.input, args.output)
    elif args.task == "timeline":
        run_task_timeline(args.input, args.output, args.session)
    elif args.task == "regression":
        if not args.baseline:
            print("ERROR: --baseline is required for regression detection")
            sys.exit(1)
        run_task_regression(args.input, args.output, args.baseline)
    else:
        # Run single task
        events = load_events(args.input, session_filter=args.filter if args.filter else None)
        by_session = index_by_session(events)
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)

        if args.task == "root_cause":
            report = analyze_root_cause(by_session)
            print_root_cause_report(report)
            write_json(str(out / "root_cause.json"), report)
        elif args.task == "latency":
            report = analyze_latency(by_session)
            print_latency_report(report)
            write_json(str(out / "latency.json"), report)
        elif args.task == "quality":
            report = analyze_quality(by_session, events)
            print_quality_report(report)
            write_json(str(out / "quality.json"), report)
        elif args.task == "retrieval":
            report = analyze_retrieval(by_session, events)
            print_retrieval_report(report)
            write_json(str(out / "retrieval.json"), report)
        elif args.task == "llm":
            report = analyze_llm(by_session, events)
            print_llm_report(report)
            write_json(str(out / "llm_analysis.json"), report)
        elif args.task == "summary":
            all_reports = {}
            all_reports["latency"] = analyze_latency(by_session)
            all_reports["root_cause"] = analyze_root_cause(by_session)
            all_reports["quality"] = analyze_quality(by_session, events)
            all_reports["retrieval"] = analyze_retrieval(by_session, events)
            all_reports["llm"] = analyze_llm(by_session, events)
            summary_path = str(out / "engineering_summary.md")
            generate_summary(all_reports, summary_path)
            print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
