"""Red-team results aggregation and summary metrics."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from .cases import SUMMARY
from .runner import TestResult

logger = logging.getLogger(__name__)


@dataclass
class GroupSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    parity_failures: int = 0
    total_elapsed_ms: float = 0.0


@dataclass
class CategoryBreakdown:
    risk_id: str
    total: int
    passed: int
    failed: int

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0


@dataclass
class StageBreakdown:
    stage_name: str
    call_count: int = 0
    total_elapsed_ms: float = 0.0
    avg_elapsed_ms: float = 0.0
    error_count: int = 0


@dataclass
class HandlerBreakdown:
    handler: str
    total: int
    passed: int
    failed: int

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0.0


@dataclass
class RedTeamReport:
    run_timestamp: str = ""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    total_elapsed_ms: float = 0.0
    priority_p0: GroupSummary = field(default_factory=GroupSummary)
    priority_p1: GroupSummary = field(default_factory=GroupSummary)
    groups: dict[str, GroupSummary] = field(default_factory=dict)
    risk_breakdown: list[CategoryBreakdown] = field(default_factory=list)
    handler_breakdown: list[HandlerBreakdown] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    parity_failures: list[dict[str, Any]] = field(default_factory=list)
    stage_performance: dict[str, StageBreakdown] = field(default_factory=dict)

    def compute(self, results: list[TestResult]) -> RedTeamReport:
        self.run_timestamp = datetime.now().isoformat()
        self.total_cases = len(results)
        self.total_elapsed_ms = sum(r.total_elapsed_ms for r in results)

        for r in results:
            if r.passed:
                self.passed += 1
            else:
                self.failed += 1

            # Priority breakdown
            target = self.priority_p0 if r.priority == "P0" else self.priority_p1
            target.total += 1
            if r.passed:
                target.passed += 1
            else:
                target.failed += 1
            target.total_elapsed_ms += r.total_elapsed_ms
            if not r.overall_parity_passed:
                target.parity_failures += 1

            # Group breakdown
            g = r.test_case.group
            if g not in self.groups:
                self.groups[g] = GroupSummary()
            self.groups[g].total += 1
            if r.passed:
                self.groups[g].passed += 1
            else:
                self.groups[g].failed += 1
            self.groups[g].total_elapsed_ms += r.total_elapsed_ms
            if not r.overall_parity_passed:
                self.groups[g].parity_failures += 1

            # Failures detail
            if not r.passed:
                fail_entry = {
                    "id": r.id,
                    "priority": r.priority,
                    "group": r.test_case.group,
                    "category": r.test_case.category,
                    "description": r.test_case.description,
                    "elapsed_ms": round(r.total_elapsed_ms, 1),
                    "errors": r.errors,
                    "turn_results": [
                        {
                            "turn": t.turn_index,
                            "query": t.query[:80],
                            "gen_source": t.generate_source,
                            "stream_source": t.stream_source,
                            "gen_passed": t.generate_passed,
                            "stream_passed": t.stream_passed,
                            "parity_passed": t.parity_passed,
                        }
                        for t in r.turn_results
                    ],
                }
                self.failures.append(fail_entry)

            # Parity failures
            for tr in r.turn_results:
                if not tr.parity_passed:
                    self.parity_failures.append(
                        {
                            "test_id": r.id,
                            "turn": tr.turn_index,
                            "query": tr.query[:80],
                            "gen_source": tr.generate_source,
                            "stream_source": tr.stream_source,
                        }
                    )

        # Risk breakdown
        risk_map: dict[str, dict[str, int]] = {}
        for r in results:
            for rid in r.test_case.risk_ids:
                if rid not in risk_map:
                    risk_map[rid] = {"total": 0, "passed": 0, "failed": 0}
                risk_map[rid]["total"] += 1
                if r.passed:
                    risk_map[rid]["passed"] += 1
                else:
                    risk_map[rid]["failed"] += 1
        self.risk_breakdown = [
            CategoryBreakdown(rid, v["total"], v["passed"], v["failed"])
            for rid, v in sorted(risk_map.items())
        ]

        # Handler breakdown
        handler_map: dict[str, dict[str, int]] = {}
        for r in results:
            h = r.test_case.expected_handler or "unknown"
            if h not in handler_map:
                handler_map[h] = {"total": 0, "passed": 0, "failed": 0}
            handler_map[h]["total"] += 1
            if r.passed:
                handler_map[h]["passed"] += 1
            else:
                handler_map[h]["failed"] += 1
        self.handler_breakdown = [
            HandlerBreakdown(h, v["total"], v["passed"], v["failed"])
            for h, v in sorted(handler_map.items())
        ]

        return self

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, default=str)

    def to_text_table(self) -> str:
        lines = [
            "=" * 70,
            "RED-TEAM TEST REPORT",
            f"Run: {self.run_timestamp}",
            "=" * 70,
            "",
            f"Total: {self.total_cases}  |  PASS: {self.passed}  |  FAIL: {self.failed}  |  Skipped: {self.skipped}",
            f"Total elapsed: {self.total_elapsed_ms / 1000:.1f}s",
            "",
            "--- Priority Breakdown ---",
            f"  P0: {self.priority_p0.total} tests, {self.priority_p0.passed} passed, "
            f"{self.priority_p0.failed} failed, {self.priority_p0.parity_failures} parity failures",
            f"  P1: {self.priority_p1.total} tests, {self.priority_p1.passed} passed, "
            f"{self.priority_p1.failed} failed, {self.priority_p1.parity_failures} parity failures",
            "",
            "--- Group Breakdown ---",
        ]
        for gid, gs in sorted(self.groups.items()):
            lines.append(
                f"  {gid}: {gs.total} tests, {gs.passed} passed, "
                f"{gs.failed} failed, {gs.parity_failures} parity failures"
            )
        lines.extend(
            [
                "",
                "--- Risk Breakdown ---",
            ]
        )
        for rb in self.risk_breakdown:
            lines.append(
                f"  {rb.risk_id}: {rb.total} tests, pass={rb.passed} ({rb.pass_rate:.0f}%)"
            )
        lines.extend(
            [
                "",
                "--- Handler Breakdown ---",
            ]
        )
        for hb in self.handler_breakdown:
            lines.append(
                f"  {hb.handler}: {hb.total} tests, pass={hb.passed} ({hb.pass_rate:.0f}%)"
            )
        if self.parity_failures:
            lines.extend(
                [
                    "",
                    f"--- Parity Failures ({len(self.parity_failures)}) ---",
                ]
            )
            for pf in self.parity_failures[:20]:
                lines.append(
                    f"  {pf['test_id']} turn {pf['turn']}: "
                    f"gen={pf['gen_source']} stream={pf['stream_source']}"
                )
            if len(self.parity_failures) > 20:
                lines.append(f"  ... and {len(self.parity_failures) - 20} more")
        if self.failures:
            lines.extend(
                [
                    "",
                    f"--- Failures ({len(self.failures)}) ---",
                ]
            )
            for f in self.failures[:10]:
                lines.append(f"  [{f['priority']}] {f['id']}: {f['description'][:80]}")
            if len(self.failures) > 10:
                lines.append(f"  ... and {len(self.failures) - 10} more")
        lines.append("=" * 70)
        return "\n".join(lines)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.run_timestamp,
            "total": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.passed / max(self.total_cases, 1) * 100, 1),
            "elapsed_seconds": round(self.total_elapsed_ms / 1000, 1),
            "by_priority": {
                "p0": {
                    "total": self.priority_p0.total,
                    "passed": self.priority_p0.passed,
                    "failed": self.priority_p0.failed,
                },
                "p1": {
                    "total": self.priority_p1.total,
                    "passed": self.priority_p1.passed,
                    "failed": self.priority_p1.failed,
                },
            },
        }
