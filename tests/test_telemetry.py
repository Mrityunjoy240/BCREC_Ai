"""
Unit tests for ConversationTelemetry (Task 7)
=============================================
Tests schema correctness, error classification, integrity validation,
and session summary fields.

Usage:
    python -m pytest tests/test_telemetry.py -v
    python -m pytest tests/test_telemetry.py -v --tb=short
"""

import json
import os
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest

from app.utils.conversation_logger import ConversationTelemetry, get_telemetry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def telemetry():
    """Fresh telemetry instance with a temp log directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        t = ConversationTelemetry.__new__(ConversationTelemetry)
        t._initialized = True
        t._log_dir = Path(tmpdir)
        t._sessions = {}
        yield t


@pytest.fixture
def session(telemetry):
    """Start a session and return (telemetry, session_id)."""
    sid = "test_session_001"
    conv_id = telemetry.start_session(sid)
    return telemetry, sid, conv_id


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_avg_empty(self):
        t = ConversationTelemetry.__new__(ConversationTelemetry)
        assert t._avg([]) == 0.0

    def test_avg_values(self):
        t = ConversationTelemetry.__new__(ConversationTelemetry)
        assert t._avg([1, 2, 3, 4]) == 2.5
        assert t._avg([10]) == 10.0

    def test_avg_rounding(self):
        t = ConversationTelemetry.__new__(ConversationTelemetry)
        assert t._avg([1, 2, 2]) == 1.67

    def test_inc_existing(self, telemetry):
        telemetry._ensure_session("s1")
        telemetry._inc("s1", "follow_up_queries")
        assert telemetry._sessions["s1"]["acc"]["follow_up_queries"] == 1
        telemetry._inc("s1", "follow_up_queries")
        assert telemetry._sessions["s1"]["acc"]["follow_up_queries"] == 2

    def test_inc_nonexistent(self, telemetry):
        telemetry._inc("no_such_session", "follow_up_queries")
        # Should not crash

    def test_inc_initializes_counter(self, telemetry):
        telemetry._ensure_session("s2")
        telemetry._inc("s2", "new_counter")
        assert telemetry._sessions["s2"]["acc"]["new_counter"] == 1


# ---------------------------------------------------------------------------
# Session lifecycle tests
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_start_session(self, telemetry):
        sid = "lifecycle_test"
        conv_id = telemetry.start_session(sid)
        assert conv_id is not None
        assert len(conv_id) == 12
        assert sid in telemetry._sessions
        assert telemetry._sessions[sid]["turn_count"] == 0

    def test_start_session_writes_file(self, telemetry):
        sid = "write_test"
        telemetry.start_session(sid)
        log_file = telemetry._log_file(sid)
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "SESSION_START" in content
        assert sid in content

    def test_end_session_produces_summary(self, telemetry):
        sid = "end_test"
        telemetry.start_session(sid)
        telemetry._ensure_session(sid)
        telemetry._sessions[sid]["turn_count"] = 5
        telemetry._sessions[sid]["acc"]["llm_latencies"] = [100, 200, 300]
        telemetry._sessions[sid]["acc"]["llm_ttfts"] = [50, 60]
        telemetry._sessions[sid]["acc"]["llm_tokens"] = [50, 100]
        telemetry._sessions[sid]["acc"]["llm_token_rates"] = [10.5, 20.3]
        telemetry._sessions[sid]["acc"]["retrieval_scores"] = [0.8, 0.9]
        telemetry._sessions[sid]["acc"]["retrieval_latencies"] = [20, 30]
        telemetry._sessions[sid]["acc"]["tts_latencies"] = [100, 200]
        telemetry._sessions[sid]["acc"]["all_latencies"] = [100, 200, 300]
        telemetry._sessions[sid]["acc"]["hallucination_guards_triggered"] = 2
        telemetry._sessions[sid]["acc"]["ambiguous_queries"] = 1
        telemetry._sessions[sid]["acc"]["errors"] = [{"error_type": "LLM_TIMEOUT"}]
        telemetry.end_session(sid)

        log_file = telemetry._log_file(sid)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        summary = json.loads(lines[-1])
        assert summary["type"] == "SESSION_SUMMARY"
        assert summary["total_turns"] == 5
        assert summary["average_llm_latency_ms"] == 200.0
        assert summary["average_ttft_ms"] == 55.0
        assert summary["total_llm_tokens"] == 150
        assert summary["average_tokens_per_second"] == 15.4
        assert summary["hallucination_guards_triggered"] == 2
        assert summary["ambiguous_queries"] == 1
        assert summary["total_errors"] == 1
        assert summary["minimum_latency_ms"] == 100.0
        assert summary["maximum_latency_ms"] == 300.0
        assert summary["median_llm_latency_ms"] == 200.0

    def test_end_session_missing(self, telemetry):
        telemetry.end_session("no_such_session")
        # Should not crash

    def test_end_session_cleans_up(self, telemetry):
        sid = "cleanup_test"
        telemetry.start_session(sid)
        assert sid in telemetry._sessions
        telemetry.end_session(sid)
        assert sid not in telemetry._sessions


# ---------------------------------------------------------------------------
# LLM lifecycle tests
# ---------------------------------------------------------------------------


class TestLLMLifecycle:
    def test_log_llm_lifecycle_schema(self, session):
        telemetry, sid, _ = session
        now = time.time()
        telemetry._sessions[sid]["turn_count"] = 1

        telemetry.log_llm_lifecycle(
            sid,
            turn_number=1,
            request_start=now - 5,
            api_request_sent=now - 4.5,
            first_token_received=now - 3,
            last_token_received=now - 1,
            postprocessing_start=now - 0.8,
            postprocessing_end=now,
            ttft_ms=1500.0,
            generation_duration_ms=2000.0,
            postprocessing_duration_ms=800.0,
            total_llm_duration_ms=5000.0,
            output_tokens=100,
            estimated_tokens_per_second=50.0,
            streaming_duration_ms=2000.0,
            model="llama-3.3-70b",
            tokens_prompt=500,
            tokens_completion=100,
            response="This is a test response.",
        )

        log_file = telemetry._log_file(sid)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        lifecycle_events = [json.loads(l) for l in lines if "TURN_LLM_LIFECYCLE" in l]
        assert len(lifecycle_events) == 1
        ev = lifecycle_events[0]
        assert ev["type"] == "TURN_LLM_LIFECYCLE"
        assert ev["session_id"] == sid
        assert ev["turn_number"] == 1
        d = ev["data"]
        assert d["ttft_ms"] == 1500.0
        assert d["generation_duration_ms"] == 2000.0
        assert d["postprocessing_duration_ms"] == 800.0
        assert d["total_llm_duration_ms"] == 5000.0
        assert d["estimated_tokens_per_second"] == 50.0
        assert d["model"] == "llama-3.3-70b"
        assert d["response_length_chars"] == len("This is a test response.")

    def test_log_llm_lifecycle_appends_acc(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        telemetry.log_llm_lifecycle(
            sid,
            turn_number=1,
            total_llm_duration_ms=3000.0,
            ttft_ms=1000.0,
            tokens_completion=200,
            estimated_tokens_per_second=66.67,
        )
        acc = telemetry._sessions[sid]["acc"]
        assert acc["llm_latencies"] == [3000.0]
        assert acc["llm_ttfts"] == [1000.0]
        assert acc["llm_tokens"] == [200]
        assert acc["llm_token_rates"] == [66.67]

    def test_log_llm_lifecycle_disabled_by_flag(self, session):
        telemetry, sid, _ = session
        with patch("app.utils.conversation_logger._TELEMETRY_DETAILED", False):
            telemetry.log_llm_lifecycle(sid, turn_number=1)
            log_file = telemetry._log_file(sid)
            content = log_file.read_text(encoding="utf-8")
            assert "TURN_LLM_LIFECYCLE" not in content


# ---------------------------------------------------------------------------
# Error classification tests
# ---------------------------------------------------------------------------


class TestErrorClassification:
    def test_classify_rate_limit(self, telemetry):
        assert telemetry.classify_error(RuntimeError("429 Too Many Requests")) == "LLM_RATE_LIMIT"
        assert telemetry.classify_error(RuntimeError("rate limit exceeded")) == "LLM_RATE_LIMIT"
        assert (
            telemetry.classify_error(RuntimeError("too many requests, try again"))
            == "LLM_RATE_LIMIT"
        )

    def test_classify_timeout(self, telemetry):
        assert telemetry.classify_error(TimeoutError("connection timed out")) == "LLM_TIMEOUT"

    def test_classify_http_error(self, telemetry):
        class HTTPError(Exception):
            pass

        assert telemetry.classify_error(HTTPError("500 Server Error")) == "LLM_HTTP_ERROR"

    def test_classify_parse_error(self, telemetry):
        assert (
            telemetry.classify_error(json.JSONDecodeError("Expecting value", "", 0))
            == "LLM_PARSE_ERROR"
        )
        assert (
            telemetry.classify_error(RuntimeError("parse error: invalid json")) == "LLM_PARSE_ERROR"
        )

    def test_classify_stt_error(self, telemetry):
        class STTError(Exception):
            pass

        assert telemetry.classify_error(STTError("speech recognition failed")) == "STT_ERROR"

    def test_classify_tts_error(self, telemetry):
        class TTSException(Exception):
            pass

        assert telemetry.classify_error(TTSException("synthesis failed")) == "TTS_ERROR"

    def test_classify_vad_error(self, telemetry):
        class VADError(Exception):
            pass

        assert telemetry.classify_error(VADError("voice activity detection failed")) == "VAD_ERROR"

    def test_classify_retrieval_error(self, telemetry):
        class RetrievalError(Exception):
            pass

        assert telemetry.classify_error(RetrievalError("chroma query failed")) == "RETRIEVAL_ERROR"
        assert telemetry.classify_error(RuntimeError("vector search error")) == "RETRIEVAL_ERROR"

    def test_classify_validation_failed(self, telemetry):
        assert (
            telemetry.classify_error(RuntimeError("hallucination detected")) == "VALIDATION_FAILED"
        )
        assert telemetry.classify_error(RuntimeError("validation error")) == "VALIDATION_FAILED"

    def test_classify_unknown(self, telemetry):
        assert (
            telemetry.classify_error(RuntimeError("something completely unexpected")) == "UNKNOWN"
        )
        assert telemetry.classify_error(ValueError("bad value")) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Turn error tests
# ---------------------------------------------------------------------------


class TestTurnError:
    def test_log_turn_error_from_exception(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        try:
            raise ValueError("test error message")
        except ValueError as e:
            telemetry.log_turn_error(sid, turn_number=1, exception=e, elapsed_ms=500.0)

        log_file = telemetry._log_file(sid)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        error_events = [json.loads(l) for l in lines if "TURN_ERROR" in l]
        assert len(error_events) == 1
        ev = error_events[0]
        assert ev["type"] == "TURN_ERROR"
        assert ev["session_id"] == sid
        assert ev["turn_number"] == 1
        d = ev["data"]
        assert d["error_type"] == "UNKNOWN"
        assert d["exception_class"] == "ValueError"
        assert "test error message" in d["exception_message"]
        assert d["elapsed_ms"] == 500.0

    def test_log_turn_error_with_explicit_type(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        telemetry.log_turn_error(
            sid,
            turn_number=1,
            error_type="LLM_TIMEOUT",
            exception_class="TimeoutError",
            exception_message="connection timed out",
            stack_location="groq_service.py:1234",
            elapsed_ms=30000.0,
        )
        log_file = telemetry._log_file(sid)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        error_events = [json.loads(l) for l in lines if "TURN_ERROR" in l]
        assert len(error_events) == 1
        d = error_events[0]["data"]
        assert d["error_type"] == "LLM_TIMEOUT"
        assert d["stack_location"] == "groq_service.py:1234"
        assert d["elapsed_ms"] == 30000.0

    def test_log_turn_error_appends_acc(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        telemetry.log_turn_error(sid, turn_number=1, error_type="LLM_RATE_LIMIT")
        assert len(telemetry._sessions[sid]["acc"]["errors"]) == 1
        assert telemetry._sessions[sid]["acc"]["errors"][0]["error_type"] == "LLM_RATE_LIMIT"

    def test_log_turn_error_classifies_auto(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        telemetry.log_turn_error(
            sid,
            turn_number=1,
            exception=TimeoutError("timed out"),
            elapsed_ms=1000.0,
        )
        errors = telemetry._sessions[sid]["acc"]["errors"]
        assert errors[0]["error_type"] == "LLM_TIMEOUT"


# ---------------------------------------------------------------------------
# Quality metrics tests
# ---------------------------------------------------------------------------


class TestQualityMetrics:
    def test_quality_metrics_ambiguous(self, session):
        telemetry, sid, _ = session
        telemetry._ensure_session(sid)
        telemetry.log_quality_metrics(sid, turn_number=1, is_ambiguous=True)
        assert telemetry._sessions[sid]["acc"]["ambiguous_queries"] == 1

    def test_quality_metrics_clarification(self, session):
        telemetry, sid, _ = session
        telemetry._ensure_session(sid)
        telemetry.log_quality_metrics(sid, turn_number=1, is_clarification=True)
        assert telemetry._sessions[sid]["acc"]["clarification_prompts"] == 1

    def test_quality_metrics_hallucination_guard(self, session):
        telemetry, sid, _ = session
        telemetry._ensure_session(sid)
        telemetry.log_quality_metrics(sid, turn_number=1, hallucination_guard_triggered=True)
        assert telemetry._sessions[sid]["acc"]["hallucination_guards_triggered"] == 1

    def test_quality_metrics_multiple(self, session):
        telemetry, sid, _ = session
        telemetry._ensure_session(sid)
        telemetry.log_quality_metrics(
            sid,
            turn_number=1,
            is_ambiguous=True,
            is_clarification=True,
        )
        acc = telemetry._sessions[sid]["acc"]
        assert acc["ambiguous_queries"] == 1
        assert acc["clarification_prompts"] == 1
        assert acc["hallucination_guards_triggered"] == 0


# ---------------------------------------------------------------------------
# Integrity validation tests
# ---------------------------------------------------------------------------


class TestIntegrityValidation:
    def test_validate_clean_session(self, session):
        telemetry, sid, _ = session
        telemetry._sessions[sid]["turn_count"] = 1
        telemetry.end_session(sid)
        warnings = telemetry.validate_session_integrity(sid)
        assert warnings == [], f"Expected clean session, got warnings: {warnings}"

    def test_validate_missing_file(self, telemetry):
        warnings = telemetry.validate_session_integrity("nonexistent_session_12345")
        assert len(warnings) == 1
        assert "not found" in warnings[0]

    def test_validate_missing_start(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("no_start")
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 1000.0}, f)
                f.write("\n")
                json.dump({"type": "SESSION_SUMMARY", "timestamp_unix": 2000.0}, f)
                f.write("\n")
            warnings = telemetry.validate_session_integrity("no_start")
            assert any("Missing SESSION_START" in w for w in warnings)

    def test_validate_missing_summary(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("no_summary")
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"type": "SESSION_START", "timestamp_unix": 1000.0}, f)
                f.write("\n")
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 1500.0}, f)
                f.write("\n")
            warnings = telemetry.validate_session_integrity("no_summary")
            assert any("Missing SESSION_SUMMARY" in w for w in warnings)

    def test_validate_non_monotonic_timestamps(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("bad_ts")
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"type": "SESSION_START", "timestamp_unix": 3000.0}, f)
                f.write("\n")
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 2000.0, "turn_number": 1}, f)
                f.write("\n")
                json.dump({"type": "SESSION_SUMMARY", "timestamp_unix": 4000.0}, f)
                f.write("\n")
            warnings = telemetry.validate_session_integrity("bad_ts")
            assert any("non-monotonic" in w.lower() for w in warnings)

    def test_validate_duplicate_turn_numbers(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("dup_turn")
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"type": "SESSION_START", "timestamp_unix": 1000.0}, f)
                f.write("\n")
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 2000.0, "turn_number": 1}, f)
                f.write("\n")
                json.dump({"type": "TURN_RETRIEVAL", "timestamp_unix": 3000.0, "turn_number": 1}, f)
                f.write("\n")
                json.dump({"type": "SESSION_SUMMARY", "timestamp_unix": 4000.0}, f)
                f.write("\n")
            warnings = telemetry.validate_session_integrity("dup_turn")
            assert any("Duplicate" in w for w in warnings)

    def test_validate_non_sequential_turns(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("seq_turn")
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump({"type": "SESSION_START", "timestamp_unix": 1000.0}, f)
                f.write("\n")
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 2000.0, "turn_number": 3}, f)
                f.write("\n")
                json.dump({"type": "TURN_INPUT", "timestamp_unix": 3000.0, "turn_number": 1}, f)
                f.write("\n")
                json.dump({"type": "SESSION_SUMMARY", "timestamp_unix": 4000.0}, f)
                f.write("\n")
            warnings = telemetry.validate_session_integrity("seq_turn")
            assert any("Non-sequential" in w for w in warnings)

    def test_validate_json_decode_error(self, telemetry):
        with tempfile.TemporaryDirectory() as tmpdir:
            telemetry._log_dir = Path(tmpdir)
            log_file = telemetry._log_file("bad_json")
            with open(log_file, "w", encoding="utf-8") as f:
                f.write('{"type": "SESSION_START", "timestamp_unix": 1000.0}\n')
                f.write("this is not valid json\n")
                f.write('{"type": "SESSION_SUMMARY", "timestamp_unix": 2000.0}\n')
            warnings = telemetry.validate_session_integrity("bad_json")
            assert any("JSON parse error" in w for w in warnings)


# ---------------------------------------------------------------------------
# Singleton / get_telemetry tests
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_telemetry_returns_same_instance(self):
        t1 = get_telemetry()
        t2 = get_telemetry()
        assert t1 is t2

    def test_get_telemetry_is_initialized(self):
        t = get_telemetry()
        assert t._initialized is True
