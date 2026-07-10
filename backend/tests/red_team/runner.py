"""Red-team test runner — executes each test case against generate and stream paths."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .cases import ALL_CASES, TestCase, Turn
from .pipeline_hooks import PipelineCapture, stage_capture_context

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    turn_index: int
    query: str
    generate_source: str | None
    stream_source: str | None
    generate_stages: list[str]
    stream_stages: list[str]
    generate_response: str
    stream_response: str
    handler_detected: str | None
    generate_passed: bool
    stream_passed: bool
    parity_passed: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    test_case: TestCase
    sid: str
    turn_results: list[TurnResult]
    passed: bool
    overall_parity_passed: bool
    total_elapsed_ms: float
    errors: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.test_case.id

    @property
    def priority(self) -> str:
        return self.test_case.priority


class RedTeamRunner:
    """Executes red-team test cases against a GroqService instance."""

    def __init__(
        self,
        service: Any,
        run_generate: bool = True,
        run_stream: bool = True,
        session_prefix: str = "rt",
    ):
        self.service = service
        self.run_generate = run_generate
        self.run_stream = run_stream
        self.session_prefix = session_prefix
        self.results: list[TestResult] = []

    def _make_sid(self, case_id: str) -> str:
        return f"{self.session_prefix}-{case_id}-{uuid.uuid4().hex[:8]}"

    def _check_stages_contain(self, actual_stages: list[str], expected: list[str] | None) -> bool:
        if expected is None:
            return True
        return all(e in actual_stages for e in expected)

    def _check_response_contains(self, response: str, expected: list[str] | None) -> bool:
        if expected is None:
            return True
        r_lower = response.lower()
        return all(e.lower() in r_lower for e in expected)

    def _run_single_turn(self, turn: Turn, sid: str, turn_idx: int) -> TurnResult:
        errors: list[str] = []
        query = turn.query

        # Execute generate path
        gen_source = None
        gen_stages: list[str] = []
        gen_response = ""

        if self.run_generate and query:
            try:
                with stage_capture_context(self.service) as gen_cap:
                    result = self.service.generate_response(query, sid)
                gen_response = (
                    str(result.get("answer", result)) if isinstance(result, dict) else str(result)
                )
                gen_source = gen_cap.generate_source
                gen_stages = gen_cap.stage_names()
            except Exception as e:
                errors.append(f"generate: {type(e).__name__}: {e}")
                gen_response = f"ERROR: {e}"

        # Execute stream path
        stream_source = None
        stream_stages: list[str] = []
        stream_response = ""

        if self.run_stream and query:
            try:
                with stage_capture_context(self.service) as stream_cap:

                    async def _run_stream():
                        tokens: list[str] = []
                        async for token in self.service.stream_response(query, sid):
                            if isinstance(token, dict):
                                t = (
                                    token.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                            else:
                                t = str(token)
                            tokens.append(t)
                        return "".join(tokens)

                    stream_response = asyncio.run(_run_stream())
                stream_source = stream_cap.stream_source
                stream_stages = stream_cap.stage_names()
            except Exception as e:
                errors.append(f"stream: {type(e).__name__}: {e}")
                stream_response = f"ERROR: {e}"

        # Determine detected handler from stages
        handler_detected = turn.expected_handler
        if gen_stages:
            # Check last non-validation stage for handler hint
            for stage in reversed(gen_stages):
                if stage in ("_structured_lookup",):
                    handler_detected = "structured_lookup"
                    break
                if stage in ("_detect_on_topic_arithmetic",):
                    handler_detected = "structured_arithmetic"
                    break

        # Evaluate pass/fail
        gen_pass = True
        if turn.expected_source and gen_source:
            gen_pass = gen_source == turn.expected_source
        if turn.expected_response_contains and gen_response:
            gen_pass = gen_pass and self._check_response_contains(
                gen_response, turn.expected_response_contains
            )

        stream_pass = True
        stream_expected = turn.expected_stream_response_contains or turn.expected_response_contains
        if turn.expected_source and stream_source:
            stream_pass = stream_source == turn.expected_source
        if stream_expected and stream_response:
            stream_pass = stream_pass and self._check_response_contains(
                stream_response, stream_expected
            )

        parity_pass = True
        if self.run_generate and self.run_stream:
            if gen_source and stream_source:
                parity_pass = gen_source == stream_source
            else:
                parity_pass = (gen_source is None) == (stream_source is None)

        return TurnResult(
            turn_index=turn_idx,
            query=query,
            generate_source=gen_source,
            stream_source=stream_source,
            generate_stages=gen_stages,
            stream_stages=stream_stages,
            generate_response=gen_response[:200],
            stream_response=stream_response[:200],
            handler_detected=handler_detected,
            generate_passed=gen_pass,
            stream_passed=stream_pass,
            parity_passed=parity_pass,
            errors=errors,
        )

    def run_case(self, case: TestCase) -> TestResult:
        t0 = time.monotonic()
        sid = self._make_sid(case.id)
        errors: list[str] = []
        turn_results: list[TurnResult] = []

        for i, turn in enumerate(case.turns):
            if not turn.query:
                continue
            tr = self._run_single_turn(turn, sid, i)
            turn_results.append(tr)
            errors.extend(tr.errors)

        # Overall pass: all turns pass generate AND stream (if expected)
        all_gen_pass = all(tr.generate_passed for tr in turn_results)
        all_stream_pass = all(tr.stream_passed for tr in turn_results)
        all_parity_pass = all(tr.parity_passed for tr in turn_results)

        overall_parity = all_parity_pass or not case.expected_generate_stream_parity
        passed = all_gen_pass and all_stream_pass and overall_parity
        elapsed = (time.monotonic() - t0) * 1000

        result = TestResult(
            test_case=case,
            sid=sid,
            turn_results=turn_results,
            passed=passed,
            overall_parity_passed=all_parity_pass,
            total_elapsed_ms=elapsed,
            errors=errors,
        )
        self.results.append(result)
        return result

    def run_all(
        self,
        cases: list[TestCase] | None = None,
        filter_priority: str | None = None,
        filter_group: str | None = None,
        filter_requires_llm_mock: bool | None = None,
    ) -> list[TestResult]:
        target = cases or ALL_CASES
        if filter_priority:
            target = [c for c in target if c.priority == filter_priority]
        if filter_group:
            target = [c for c in target if c.group == filter_group]
        if filter_requires_llm_mock is False:
            target = [c for c in target if not c.requires_llm_mock]

        results: list[TestResult] = []
        for case in target:
            r = self.run_case(case)
            results.append(r)
        return results

    def clear_session(self, sid: str) -> None:
        if hasattr(self.service, "clear_session"):
            self.service.clear_session(sid)

    def reset(self) -> None:
        self.results.clear()
