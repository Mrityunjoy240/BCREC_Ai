#!/usr/bin/env python3
"""Red-team test framework entry point.

Usage:
    python run_red_team.py                          # Run all non-voice, non-mock tests
    python run_red_team.py --p0                     # P0 only
    python run_red_team.py --group A                # Group A only
    python run_red_team.py --with-mocks             # Include LLM-mock tests
    python run_red_team.py --with-voice             # Include voice tests
    python run_red_team.py --json                   # JSON output
    python run_red_team.py --output report.json     # Save to file
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path for backend.app imports
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("red_team")


def main() -> None:
    parser = argparse.ArgumentParser(description="BCREC Red-Team Test Framework")
    parser.add_argument("--p0", action="store_true", help="Run P0 tests only")
    parser.add_argument("--p1", action="store_true", help="Run P1 tests only")
    parser.add_argument("--group", type=str, help="Filter by group (e.g., A, B, CS)")
    parser.add_argument("--with-mocks", action="store_true", help="Include LLM-mock tests")
    parser.add_argument("--with-voice", action="store_true", help="Include voice-specific tests")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--output", type=str, help="Save report to file")
    parser.add_argument("--generate-only", action="store_true", help="Run generate path only")
    parser.add_argument("--stream-only", action="store_true", help="Run stream path only")
    parser.add_argument("--list", action="store_true", help="List all test cases and exit")
    args = parser.parse_args()

    # Import framework
    from backend.tests.red_team import (
        ALL_CASES,
        P0_CASES,
        P1_CASES,
        SUMMARY,
        RedTeamRunner,
        RedTeamReport,
    )

    # List mode
    if args.list:
        print(f"{'ID':<12} {'Pri':<4} {'Grp':<4} {'Category':<25} Description")
        print("-" * 90)
        for c in ALL_CASES:
            print(f"{c.id:<12} {c.priority:<4} {c.group:<4} {c.category:<25} {c.description[:60]}")
        print(f"\nTotal: {len(ALL_CASES)} cases ({SUMMARY['P0']} P0, {SUMMARY['P1']} P1)")
        return

    # Select cases
    if args.p0 and args.p1:
        cases = ALL_CASES
    elif args.p0:
        cases = P0_CASES
    elif args.p1:
        cases = P1_CASES
    else:
        cases = ALL_CASES

    # Filter group
    if args.group:
        cases = [c for c in cases if c.group.upper() == args.group.upper()]

    # Filter mocks/voice
    if not args.with_mocks:
        cases = [c for c in cases if not c.requires_llm_mock]
    if not args.with_voice:
        cases = [c for c in cases if not c.requires_voice]

    if not cases:
        logger.warning("No test cases matched the filter criteria.")
        return

    logger.info(f"Loading GroqService...")
    from backend.app.services.llm.groq_service import get_groq_service

    service = get_groq_service()

    logger.info(
        f"Running {len(cases)} tests "
        f"(generate={not args.stream_only}, stream={not args.generate_only})"
    )

    runner = RedTeamRunner(
        service=service,
        run_generate=not args.stream_only,
        run_stream=not args.generate_only,
    )

    results = runner.run_all(
        cases=cases,
    )

    report = RedTeamReport().compute(results)

    if args.json or args.output:
        json_str = report.to_json()
        if args.output:
            out_path = Path(args.output)
            out_path.write_text(json_str, encoding="utf-8")
            logger.info(f"Report saved to {out_path}")
        else:
            print(json_str)
    else:
        print(report.to_text_table())

    # Summary
    summary = report.summary_dict()
    print(
        f"\nSummary: {summary['passed']}/{summary['total']} passed "
        f"({summary['pass_rate']}%) in {summary['elapsed_seconds']}s"
    )


if __name__ == "__main__":
    main()
