"""
Unit tests for the analytics package (scripts/analytics/)
=========================================================
Tests all analysis modules: loader, coverage, root_cause, latency,
quality, retrieval, llm_analysis, including edge cases.

Usage:
    python -m pytest tests/test_analytics.py -v
    python -m pytest tests/test_analytics.py -v --tb=short
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

from analytics.loader import (
    load_events,
    index_by_session,
    index_by_type,
    percentile,
    safe_avg,
    safe_median,
    safe_stdev,
    detect_outliers,
)
from analytics.coverage import analyze_coverage, REQUIRED_EVENT_TYPES
from analytics.root_cause import analyze_root_cause
from analytics.latency import analyze_latency
from analytics.quality import analyze_quality
from analytics.retrieval import analyze_retrieval
from analytics.llm_analysis import analyze_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(etype, sid="test", tn=0, data=None, **kw):
    ev = {"type": etype, "session_id": sid, "turn_number": tn}
    if data:
        ev["data"] = data
    ev.update(kw)
    return ev


def make_session_log(events):
    """Write events to a temp JSONL and return the loaded list."""
    lines = "\n".join(json.dumps(e) for e in events)
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = Path(tmpdir) / "session_test.jsonl"
        fpath.write_text(lines, encoding="utf-8")
        return load_events(str(tmpdir))


# ===================================================================
# LOADER TESTS
# ===================================================================


class TestLoader:
    def test_load_events_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evts = load_events(tmpdir)
        assert evts == []

    def test_load_events_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "session_empty.jsonl").write_text("", encoding="utf-8")
            evts = load_events(tmpdir)
        assert evts == []

    def test_load_events_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "session_blanks.jsonl").write_text(
                '\n\n{"type": "TURN_INPUT", "session_id": "s1", "turn_number": 1}\n\n',
                encoding="utf-8",
            )
            evts = load_events(tmpdir)
        assert len(evts) == 1

    def test_load_events_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "session_bad.jsonl").write_text(
                '{"type": "GOOD"}\nnot json\n{"type": "ALSO_GOOD"}\n',
                encoding="utf-8",
            )
            evts = load_events(tmpdir)
        assert len(evts) == 3
        assert evts[0]["type"] == "GOOD"
        assert evts[1]["type"] == "PARSE_ERROR"
        assert evts[2]["type"] == "ALSO_GOOD"

    def test_load_events_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "session_sim_abc.jsonl").write_text(
                '{"type": "A", "session_id": "sim_abc"}\n', encoding="utf-8"
            )
            Path(tmpdir, "session_live_def.jsonl").write_text(
                '{"type": "B", "session_id": "live_def"}\n', encoding="utf-8"
            )
            evts = load_events(tmpdir, session_filter="sim_")
        assert len(evts) == 1
        assert evts[0]["type"] == "A"

    def test_index_by_session(self):
        evts = [
            make_event("A", sid="s1"),
            make_event("B", sid="s2"),
            make_event("C", sid="s1"),
        ]
        idx = index_by_session(evts)
        assert set(idx.keys()) == {"s1", "s2"}
        assert len(idx["s1"]) == 2
        assert len(idx["s2"]) == 1

    def test_index_by_type(self):
        evts = [
            make_event("A"),
            make_event("B"),
            make_event("A"),
        ]
        idx = index_by_type(evts)
        assert set(idx.keys()) == {"A", "B"}
        assert len(idx["A"]) == 2
        assert len(idx["B"]) == 1

    # --- Stat helpers ---

    def test_percentile_empty(self):
        assert percentile([], 50) == 0.0

    def test_percentile_single(self):
        assert percentile([42], 50) == 42.0

    def test_percentile_values(self):
        vals = list(range(100))
        assert percentile(vals, 0) == 0
        assert percentile(vals, 50) == 49.5
        assert percentile(vals, 90) == 89.1
        assert percentile(vals, 95) == 94.05
        assert percentile(vals, 99) == 98.01
        assert percentile(vals, 100) == 99

    def test_safe_avg_empty(self):
        assert safe_avg([]) == 0.0

    def test_safe_avg_values(self):
        assert safe_avg([1, 2, 3, 4]) == 2.5
        assert safe_avg([10]) == 10.0

    def test_safe_median_empty(self):
        assert safe_median([]) == 0.0

    def test_safe_median_odd(self):
        assert safe_median(sorted([3, 1, 2])) == 2.0

    def test_safe_median_even(self):
        assert safe_median(sorted([1, 2, 3, 4])) == 2.5

    def test_safe_stdev_empty(self):
        assert safe_stdev([]) == 0.0

    def test_safe_stdev_single(self):
        assert safe_stdev([5]) == 0.0

    def test_safe_stdev_values(self):
        v = safe_stdev([1, 2, 3, 4, 5])
        assert round(v, 4) == 1.4142

    def test_detect_outliers_empty(self):
        assert detect_outliers([]) == []

    def test_detect_outliers_none(self):
        assert detect_outliers([1, 1, 1, 1, 1]) == []

    def test_detect_outliers_present(self):
        outliers = detect_outliers([1, 1, 1, 100], n_sigma=1.5)
        assert len(outliers) == 1

    def test_detect_outliers_too_few(self):
        assert detect_outliers([1]) == []


# ===================================================================
# COVERAGE TESTS
# ===================================================================


class TestCoverage:
    def test_full_coverage(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT"),
            make_event("TURN_RETRIEVAL"),
            make_event("TURN_LLM_LIFECYCLE"),
            make_event("TURN_VALIDATION"),
            make_event("TURN_VOICE"),
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert len(results) == 1
        assert results[0]["coverage_pct"] == 87.5  # only TURN_ERROR missing
        assert results[0]["missing_events"] == "TURN_ERROR"

    def test_empty_session(self):
        events = [make_event("SESSION_START"), make_event("SESSION_SUMMARY")]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert results[0]["coverage_pct"] < 50

    def test_missing_critical_events(self):
        events = [make_event("TURN_INPUT"), make_event("TURN_RETRIEVAL")]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert "SESSION_START" in results[0]["missing_events"]
        assert "SESSION_SUMMARY" in results[0]["missing_events"]

    def test_non_contiguous_turns(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event("TURN_RETRIEVAL", tn=1),
            make_event("TURN_LLM_LIFECYCLE", tn=1),
            make_event("TURN_VALIDATION", tn=1),
            make_event("TURN_VOICE", tn=1),
            make_event("TURN_INPUT", tn=3),
            make_event("TURN_RETRIEVAL", tn=3),
            make_event("TURN_LLM_LIFECYCLE", tn=3),
            make_event("TURN_VALIDATION", tn=3),
            make_event("TURN_VOICE", tn=3),
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert any("non-contiguous" in r["notes"] for r in results)

    def test_session_with_errors(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event("TURN_RETRIEVAL", tn=1),
            make_event("TURN_LLM_LIFECYCLE", tn=1),
            make_event("TURN_VALIDATION", tn=1),
            make_event("TURN_VOICE", tn=1),
            make_event("TURN_ERROR", tn=1, data={"error_type": "LLM_TIMEOUT"}),
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert any("error(s)" in r["notes"] for r in results)

    def test_missing_retrieval(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event("TURN_LLM_LIFECYCLE", tn=1),
            make_event("TURN_VALIDATION", tn=1),
            make_event("TURN_VOICE", tn=1),
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        results = analyze_coverage(idx)
        assert any("Retrieval never fired" in r["notes"] for r in results)


# ===================================================================
# ROOT CAUSE TESTS
# ===================================================================


class TestRootCause:
    def test_no_errors(self):
        events = [make_event("TURN_INPUT")]
        idx = index_by_session(events)
        report = analyze_root_cause(idx)
        assert report["total_errors"] == 0
        assert report["categories"] == {}

    def test_single_error_type(self):
        events = [
            make_event("TURN_ERROR", data={"error_type": "LLM_TIMEOUT", "elapsed_ms": 5000}),
            make_event("TURN_ERROR", data={"error_type": "LLM_TIMEOUT", "elapsed_ms": 3000}),
        ]
        idx = index_by_session(events)
        report = analyze_root_cause(idx)
        assert report["total_errors"] == 2
        assert report["categories"]["LLM_TIMEOUT"]["count"] == 2
        assert report["categories"]["LLM_TIMEOUT"]["avg_elapsed_ms"] == 4000.0

    def test_multiple_error_types(self):
        events = [
            make_event("TURN_ERROR", data={"error_type": "LLM_TIMEOUT", "elapsed_ms": 5000}),
            make_event("TURN_ERROR", data={"error_type": "RETRIEVAL_ERROR", "elapsed_ms": 1000}),
            make_event("TURN_ERROR", data={"error_type": "LLM_TIMEOUT", "elapsed_ms": 7000}),
        ]
        idx = index_by_session(events)
        report = analyze_root_cause(idx)
        assert report["total_errors"] == 3
        assert len(report["categories"]) == 2

    def test_error_with_exception_class(self):
        events = [
            make_event(
                "TURN_ERROR",
                data={
                    "error_type": "LLM_HTTP_ERROR",
                    "exception_class": "RuntimeError",
                    "exception_message": "500 Server Error",
                    "elapsed_ms": 1000,
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_root_cause(idx)
        cat = report["categories"]["LLM_HTTP_ERROR"]
        assert cat["most_common_exception"] == "RuntimeError"


# ===================================================================
# LATENCY TESTS
# ===================================================================


class TestLatency:
    def test_empty_sessions(self):
        report = analyze_latency({})
        assert report["retrieval"]["count"] == 0
        assert report["llm_total"]["count"] == 0
        assert report["overall_turn"]["count"] == 0

    def test_retrieval_only(self):
        events = [
            make_event(
                "TURN_RETRIEVAL",
                data={"latency_ms": 100},
            ),
            make_event(
                "TURN_RETRIEVAL",
                data={"latency_ms": 200},
            ),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["retrieval"]["count"] == 2
        assert report["retrieval"]["avg_ms"] == 150.0
        assert report["overall_turn"]["count"] == 1
        assert (
            report["overall_turn"]["avg_ms"] == 200.0
        )  # second event overwrites first (same turn)
        assert report["overall_turn"]["avg_ms"] != report["llm_total"]["avg_ms"]

    def test_llm_lifecycle(self):
        events = [
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "ttft_ms": 500,
                    "generation_duration_ms": 2000,
                    "postprocessing_duration_ms": 300,
                    "total_llm_duration_ms": 2800,
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["llm_ttft"]["count"] == 1
        assert report["llm_generation"]["avg_ms"] == 2000.0
        assert report["llm_total"]["avg_ms"] == 2800.0
        assert report["overall_turn"]["count"] == 1
        assert report["overall_turn"]["avg_ms"] == 2800.0  # just LLM

    def test_overall_turn_is_composite(self):
        """overall_turn should sum retrieval + LLM + TTS per turn."""
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={"latency_ms": 100},
            ),
            make_event(
                "TURN_LLM_LIFECYCLE",
                tn=1,
                data={"total_llm_duration_ms": 2000},
            ),
            make_event(
                "TURN_VOICE",
                tn=1,
                data={"tts_latency_ms": 300},
            ),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["overall_turn"]["count"] == 1
        assert report["overall_turn"]["avg_ms"] == 2400.0  # 100 + 2000 + 300
        assert report["overall_turn"]["avg_ms"] != report["llm_total"]["avg_ms"]

    def test_tts_latency(self):
        events = [
            make_event("TURN_VOICE", data={"tts_latency_ms": 500}),
            make_event("TURN_VOICE", data={"tts_latency_ms": 1500}),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["tts"]["count"] == 2
        assert report["tts"]["avg_ms"] == 1000.0

    def test_zero_latencies_ignored(self):
        events = [
            make_event("TURN_RETRIEVAL", data={"latency_ms": 0}),
            make_event("TURN_LLM_LIFECYCLE", data={"total_llm_duration_ms": 0}),
            make_event("TURN_VOICE", data={"tts_latency_ms": 0}),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["retrieval"]["count"] == 0
        assert report["llm_total"]["count"] == 0
        assert report["tts"]["count"] == 0
        assert report["overall_turn"]["count"] == 0

    def test_session_avg_latency(self):
        events = [
            make_event("TURN_LLM_LIFECYCLE", sid="s1", tn=1, data={"total_llm_duration_ms": 1000}),
            make_event("TURN_LLM_LIFECYCLE", sid="s1", tn=2, data={"total_llm_duration_ms": 3000}),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert len(report["slowest_sessions"]) == 1
        assert report["slowest_sessions"][0]["avg_latency_ms"] == 2000.0


# ===================================================================
# QUALITY TESTS
# ===================================================================


class TestQuality:
    def test_no_sessions(self):
        report = analyze_quality({}, [])
        assert report["total_sessions"] == 0
        assert report["total_turns"] == 0

    def test_count_turns_from_input(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event("TURN_RETRIEVAL", tn=1),
            make_event("TURN_INPUT", tn=2),
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        report = analyze_quality(idx, events)
        assert report["total_turns"] == 2

    def test_accumulator_metrics(self):
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event(
                "SESSION_SUMMARY",
                clarification_prompts=3,
                follow_up_queries=5,
                hallucination_guards_triggered=0,
                ambiguous_queries=1,
            ),
        ]
        idx = index_by_session(events)
        report = analyze_quality(idx, events)
        assert report["raw_counts"]["clarification_prompts"] == 3
        assert report["raw_counts"]["follow_up_queries"] == 5

    def test_hallucination_guards_from_validation(self):
        """Hallucination guards should be read from TURN_VALIDATION events
        when SESSION_SUMMARY reports 0."""
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1),
            make_event(
                "TURN_VALIDATION",
                tn=1,
                data={
                    "hallucination_guard_result": "blocked",
                },
            ),
            make_event(
                "TURN_VALIDATION",
                tn=2,
                data={
                    "hallucination_guard_result": "blocked",
                },
            ),
            make_event(
                "SESSION_SUMMARY",
                data={
                    "hallucination_guards_triggered": 0,
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_quality(idx, events)
        assert report["raw_counts"]["hallucination_guards_triggered"] == 2

    def test_special_events(self):
        events = [
            make_event("SESSION_START"),
            {"type": "SPECIAL_EVENT", "event": "FOLLOW_UP_QUERY", "session_id": "s1"},
            {"type": "SPECIAL_EVENT", "event": "FOLLOW_UP_QUERY", "session_id": "s1"},
            {"type": "SPECIAL_EVENT", "event": "REPEAT_REQUEST", "session_id": "s1"},
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        report = analyze_quality(idx, events)
        assert report["special_events_raw"]["FOLLOW_UP_QUERY"] == 2
        assert report["special_events_raw"]["REPEAT_REQUEST"] == 1

    def test_empty_sessions_have_zero_rates(self):
        events = []
        report = analyze_quality({}, events)
        assert report["total_sessions"] == 0
        assert report["total_turns"] == 0
        for k, v in report["raw_counts"].items():
            assert v == 0


# ===================================================================
# RETRIEVAL TESTS
# ===================================================================


class TestRetrieval:
    def test_empty_sessions(self):
        report = analyze_retrieval({}, [])
        assert report["count"] == 0
        assert report["avg_confidence"] == 0

    def test_confidence_stats(self):
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.5,
                    "latency_ms": 100,
                    "retrieval_query": "hello",
                    "top_chunks": [{"rank": 1}],
                },
            ),
            make_event(
                "TURN_RETRIEVAL",
                tn=2,
                data={
                    "confidence_score": 0.9,
                    "latency_ms": 200,
                    "retrieval_query": "world",
                    "top_chunks": [{"rank": 1}],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["count"] == 2
        assert report["avg_confidence"] == 0.7
        assert report["min_confidence"] == 0.5
        assert report["max_confidence"] == 0.9

    def test_per_language_confidence_two_pass(self):
        """TURN_INPUT precedes TURN_RETRIEVAL in event order.
        This tests that the two-pass approach correctly matches them."""
        events = [
            make_event("SESSION_START"),
            make_event(
                "TURN_INPUT",
                tn=1,
                data={
                    "detected_language": "en",
                    "raw_stt_transcript": "hello",
                },
            ),
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.85,
                    "retrieval_query": "hello",
                    "top_chunks": [{"rank": 1}],
                },
            ),
            make_event(
                "TURN_INPUT",
                tn=2,
                data={
                    "detected_language": "hi",
                    "raw_stt_transcript": "namaste",
                },
            ),
            make_event(
                "TURN_RETRIEVAL",
                tn=2,
                data={
                    "confidence_score": 0.75,
                    "retrieval_query": "namaste",
                    "top_chunks": [{"rank": 1}],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["avg_confidence_by_language"]["en"] == 0.85
        assert report["avg_confidence_by_language"]["hi"] == 0.75

    def test_hallucination_guard_triggers(self):
        events = [
            make_event(
                "TURN_VALIDATION",
                tn=1,
                data={
                    "hallucination_guard_result": "blocked",
                },
            ),
            make_event(
                "TURN_VALIDATION",
                tn=2,
                data={
                    "hallucination_guard_result": "passed",
                },
            ),
            make_event(
                "TURN_VALIDATION",
                tn=3,
                data={
                    "hallucination_guard_result": "blocked",
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["hallucination_guard_triggers"] == 2

    def test_empty_contexts(self):
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.0,
                    "retrieval_query": "test",
                    "top_chunks": [],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["empty_contexts"] == 1

    def test_lowest_confidence_order(self):
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.9,
                    "latency_ms": 100,
                    "retrieval_query": "high",
                    "top_chunks": [{"rank": 1}],
                },
            ),
            make_event(
                "TURN_RETRIEVAL",
                tn=2,
                data={
                    "confidence_score": 0.1,
                    "latency_ms": 100,
                    "retrieval_query": "low",
                    "top_chunks": [{"rank": 1}],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["lowest_confidence_queries"][-1]["confidence"] == 0.1
        assert report["highest_confidence_queries"][0]["confidence"] == 0.9


# ===================================================================
# LLM ANALYSIS TESTS
# ===================================================================


class TestLLMAnalysis:
    def test_empty(self):
        report = analyze_llm({}, [])
        assert report["total_llm_calls"] == 0

    def test_output_length(self):
        events = [
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "response_length_chars": 50,
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                    "model": "llama-3.1-8b-instant",
                },
            ),
        ]
        report = analyze_llm({}, events)
        assert report["total_llm_calls"] == 1
        assert report["output_length_chars"]["avg"] == 50.0
        assert report["model_distribution"]["llama-3.1-8b-instant"] == 1

    def test_correlation_data(self):
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "top_chunks": [{"rank": 1}, {"rank": 2}],
                    "retrieval_query": "test",
                },
            ),
            make_event(
                "TURN_LLM_LIFECYCLE",
                tn=1,
                data={
                    "response_length_chars": 50,
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                    "model": "x",
                },
            ),
        ]
        report = analyze_llm({}, events)
        corr = report["correlation_with_latency"]
        # With one data point, rank correlation is 0
        assert corr["prompt_tokens_rank_corr"] == 0.0

    def test_tokens_per_second(self):
        events = [
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "estimated_tokens_per_second": 25.5,
                    "tokens_prompt": 100,
                    "tokens_completion": 50,
                    "total_llm_duration_ms": 2000,
                    "model": "x",
                },
            ),
        ]
        report = analyze_llm({}, events)
        assert report["tokens_per_second"]["avg"] == 25.5

    def test_multiple_models(self):
        events = [
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "model": "model_a",
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                },
            ),
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "model": "model_b",
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                },
            ),
            make_event(
                "TURN_LLM_LIFECYCLE",
                data={
                    "model": "model_a",
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                },
            ),
        ]
        report = analyze_llm({}, events)
        assert report["model_distribution"]["model_a"] == 2
        assert report["model_distribution"]["model_b"] == 1


# ===================================================================
# EDGE CASE TESTS
# ===================================================================


class TestEdgeCases:
    def test_empty_logs(self):
        """All analysis modules should handle empty event lists."""
        from analytics.loader import load_events

        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "session_empty.jsonl"
            f.write_text("", encoding="utf-8")
            evts = load_events(str(tmpdir))
        assert evts == []
        idx = index_by_session(evts)
        assert analyze_coverage(idx) == []
        assert analyze_root_cause(idx)["total_errors"] == 0
        assert analyze_latency(idx)["retrieval"]["count"] == 0
        assert analyze_quality(idx, evts)["total_sessions"] == 0
        assert analyze_retrieval(idx, evts)["count"] == 0
        assert analyze_llm(idx, evts)["total_llm_calls"] == 0

    def test_corrupted_events_handled(self):
        """Events with missing keys should not crash."""
        evts = [
            {},  # completely empty
            {"type": "TURN_RETRIEVAL"},  # missing data
            {"type": "TURN_LLM_LIFECYCLE", "data": {}},  # empty data
            {"type": "TURN_ERROR"},  # no data
        ]
        idx = index_by_session(evts)
        try:
            assert analyze_root_cause(idx)["total_errors"] == 1
            # TURN_RETRIEVAL without data has no latency_ms → filtered out
            assert analyze_latency(idx)["retrieval"]["count"] == 0
        except Exception as e:
            pytest.fail(f"crashed on corrupted events: {e}")

    def test_incomplete_session_no_summary(self):
        """Session without SESSION_SUMMARY should still be analyzable."""
        events = [
            make_event("SESSION_START"),
            make_event("TURN_INPUT", tn=1, data={"detected_language": "en"}),
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.8,
                    "latency_ms": 100,
                    "retrieval_query": "hello",
                    "top_chunks": [{"rank": 1}],
                },
            ),
            make_event(
                "TURN_LLM_LIFECYCLE",
                tn=1,
                data={
                    "response_length_chars": 50,
                    "tokens_prompt": 100,
                    "tokens_completion": 20,
                    "total_llm_duration_ms": 1000,
                    "model": "x",
                },
            ),
        ]
        idx = index_by_session(events)
        # Coverage should note the missing summary
        cov = analyze_coverage(idx)
        assert any("SESSION_SUMMARY missing" in r["notes"] for r in cov)
        # Latency should still work
        lat = analyze_latency(idx)
        assert lat["llm_total"]["count"] == 1

    def test_duplicate_turn_numbers(self):
        """Events with duplicate turn numbers should not crash."""
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.8,
                    "latency_ms": 100,
                    "retrieval_query": "hello",
                    "top_chunks": [{"rank": 1}],
                },
            ),
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 0.9,
                    "latency_ms": 200,
                    "retrieval_query": "hello",
                    "top_chunks": [{"rank": 1}],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["count"] == 2  # counts all retrieval events

    def test_missing_timestamps(self):
        """Events without timestamp_unix should not crash."""
        events = [
            {
                "type": "TURN_RETRIEVAL",
                "session_id": "s1",
                "turn_number": 1,
                "data": {
                    "latency_ms": 100,
                    "confidence_score": 0.5,
                    "retrieval_query": "test",
                    "top_chunks": [{"rank": 1}],
                },
            },
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["retrieval"]["count"] == 1

    def test_special_event_without_event_field(self):
        """SPECIAL_EVENT missing 'event' field should not crash."""
        events = [
            {"type": "SPECIAL_EVENT", "session_id": "s1"},
            make_event("SESSION_SUMMARY"),
        ]
        idx = index_by_session(events)
        report = analyze_quality(idx, events)
        # Missing event field yields empty-string key — should not crash
        assert "" in report["special_events_raw"]
        assert report["special_events_raw"][""] == 1

    def test_negative_latency_values(self):
        """Negative latencies should be filtered out."""
        events = [
            make_event("TURN_RETRIEVAL", data={"latency_ms": -100}),
            make_event("TURN_RETRIEVAL", data={"latency_ms": 50}),
        ]
        idx = index_by_session(events)
        report = analyze_latency(idx)
        assert report["retrieval"]["count"] == 1

    def test_confidence_out_of_range(self):
        """Confidence scores outside nominal range should not crash."""
        events = [
            make_event(
                "TURN_RETRIEVAL",
                tn=1,
                data={
                    "confidence_score": 1.5,
                    "latency_ms": 100,
                    "retrieval_query": "test",
                    "top_chunks": [{"rank": 1}],
                },
            ),
        ]
        idx = index_by_session(events)
        report = analyze_retrieval(idx, events)
        assert report["max_confidence"] == 1.5
        # Histogram bucket should still work:
        hist = report["confidence_histogram"]
        assert "1.0" in hist or "1.5" in hist
