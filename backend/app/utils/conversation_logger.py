"""
Structured Conversation Logger
==============================
Captures end-to-end telemetry for every conversation turn without modifying
any dialogue logic. Writes JSON-lines format for offline analysis.

Output: data/logs/conversations/session_{session_id}_{date}.jsonl
"""

import json
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

_LOG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "logs" / "conversations"

# Feature flag: set TELEMETRY_DETAILED=0 to disable granular lifecycle events
_TELEMETRY_DETAILED = os.environ.get("TELEMETRY_DETAILED", "1") == "1"


class ConversationTelemetry:
    """Singleton telemetry collector. Logs structured events without affecting dialogue logic."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._log_dir = _LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, Dict[str, Any]] = {}
        logger.info(f"Conversation telemetry dir: {self._log_dir}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _log_file(self, session_id: str) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"session_{session_id}_{date_str}.jsonl"

    def _write(self, session_id: str, entry: dict):
        try:
            path = self._log_file(session_id)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug(f"Telemetry write failed ({session_id}): {e}")

    def _ensure_session(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            conv_id = uuid.uuid4().hex[:12]
            self._sessions[session_id] = {
                "conversation_id": conv_id,
                "start_time": time.time(),
                "turn_count": 0,
                "acc": {
                    "follow_up_queries": 0,
                    "repeat_requests": 0,
                    "multi_topic_queries": 0,
                    "low_confidence_retrievals": 0,
                    "empty_contexts": 0,
                    "out_of_kb": 0,
                    "language_switches": 0,
                    "interruptions": 0,
                    "clarification_prompts": 0,
                    "confidence_rejections": 0,
                    "hallucination_guards_triggered": 0,
                    "ambiguous_queries": 0,
                    "retrieval_scores": [],
                    "retrieval_latencies": [],
                    "llm_latencies": [],
                    "llm_ttfts": [],
                    "llm_tokens": [],
                    "llm_token_rates": [],
                    "tts_latencies": [],
                    "all_latencies": [],
                    "errors": [],
                },
            }
        return self._sessions[session_id]

    def _inc(self, session_id: str, counter: str):
        sess = self._sessions.get(session_id)
        if sess:
            sess["acc"][counter] = sess["acc"].get(counter, 0) + 1

    def _avg(self, lst):
        return round(sum(lst) / max(len(lst), 1), 2)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def start_session(self, session_id: str) -> str:
        sess = self._ensure_session(session_id)
        entry = {
            "type": "SESSION_START",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
        }
        self._write(session_id, entry)
        logger.info(f"[TELEMETRY] SESSION_START {session_id} conv={sess['conversation_id']}")
        return sess["conversation_id"]

    def end_session(self, session_id: str):
        sess = self._sessions.pop(session_id, None)
        if not sess:
            return
        acc = sess["acc"]
        n = max(sess["turn_count"], 1)

        def _pct(vals):
            if not vals:
                return 0.0, 0.0, 0.0
            s = sorted(vals)
            return s[0], s[-1], s[len(s) // 2]

        min_lat, max_lat, med_lat = _pct(acc["all_latencies"])
        all_llm = acc["llm_latencies"]
        min_llm, max_llm, med_llm = _pct(all_llm)

        summary = {
            "type": "SESSION_SUMMARY",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "total_turns": sess["turn_count"],
            "duration_seconds": round(time.time() - sess["start_time"], 1),
            "average_retrieval_score": self._avg(acc["retrieval_scores"]),
            "average_retrieval_latency_ms": self._avg(acc["retrieval_latencies"]),
            "average_llm_latency_ms": self._avg(all_llm),
            "average_ttft_ms": self._avg(acc["llm_ttfts"]),
            "average_tts_latency_ms": self._avg(acc["tts_latencies"]),
            "average_confidence": self._avg(acc["retrieval_scores"]),
            "maximum_latency_ms": round(max_lat, 1),
            "minimum_latency_ms": round(min_lat, 1),
            "median_llm_latency_ms": round(med_llm, 1),
            "maximum_llm_latency_ms": round(max_llm, 1),
            "minimum_llm_latency_ms": round(min_llm, 1),
            "total_llm_tokens": sum(acc["llm_tokens"]),
            "average_tokens_per_second": self._avg(acc["llm_token_rates"]),
            "interruptions": acc["interruptions"],
            "clarification_prompts": acc["clarification_prompts"],
            "language_switches": acc["language_switches"],
            "follow_up_queries": acc["follow_up_queries"],
            "repeat_requests": acc["repeat_requests"],
            "multi_topic_queries": acc["multi_topic_queries"],
            "confidence_rejections": acc["confidence_rejections"],
            "empty_retrievals": acc["empty_contexts"],
            "low_confidence_retrievals": acc["low_confidence_retrievals"],
            "retrieval_failures": acc["empty_contexts"] + acc["low_confidence_retrievals"],
            "hallucination_guards_triggered": acc["hallucination_guards_triggered"],
            "ambiguous_queries": acc["ambiguous_queries"],
            "out_of_kb": acc["out_of_kb"],
            "total_errors": len(acc["errors"]),
        }
        self._write(session_id, summary)
        logger.info(
            f"[TELEMETRY] SESSION_SUMMARY {session_id}: {json.dumps(summary, ensure_ascii=False, default=str)}"
        )

    # ------------------------------------------------------------------
    # Turn input / preprocessing
    # ------------------------------------------------------------------
    def log_turn_input(
        self,
        session_id: str,
        *,
        turn_number: int,
        raw_transcript: str = "",
        normalized_transcript: str = "",
        expanded_transcript: str = "",
        detected_language: str = "",
        detected_intent: str = "",
        follow_up_topic: str = "",
        transcript_validation: str = "",
    ):
        self._ensure_session(session_id)
        entry = {
            "type": "TURN_INPUT",
            "session_id": session_id,
            "conversation_id": self._sessions[session_id]["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "raw_stt_transcript": raw_transcript,
                "normalized_transcript": normalized_transcript,
                "expanded_transcript": expanded_transcript,
                "detected_language": detected_language,
                "detected_intent": detected_intent,
                "detected_follow_up_topic": follow_up_topic,
                "transcript_validation_result": transcript_validation,
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def log_retrieval(
        self,
        session_id: str,
        *,
        turn_number: int,
        retrieval_query: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
        top_chunks: Optional[List[Dict]] = None,
        chunks_passed: int = 0,
        chunks_discarded: Optional[List[Dict]] = None,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        sess["acc"]["retrieval_scores"].append(confidence)
        sess["acc"]["retrieval_latencies"].append(latency_ms)
        entry = {
            "type": "TURN_RETRIEVAL",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "retrieval_query": retrieval_query,
                "confidence_score": confidence,
                "latency_ms": round(latency_ms, 1),
                "top_chunks": [
                    {
                        "rank": c.get("rank", 0),
                        "similarity_score": c.get("similarity_score"),
                        "section": c.get("section", ""),
                        "subsection": c.get("subsection", ""),
                        "source": c.get("source", ""),
                        "document_id": c.get("document_id", ""),
                        "preview": c.get("preview", "")[:150],
                    }
                    for c in (top_chunks or [])
                ],
                "chunks_passed_to_llm": chunks_passed,
                "chunks_discarded": [
                    {
                        "reason": d.get("reason", ""),
                        "section": d.get("section", ""),
                        "subsection": d.get("subsection", ""),
                        "preview": d.get("preview", "")[:100],
                    }
                    for d in (chunks_discarded or [])
                ],
            },
        }
        if not top_chunks or confidence == 0.0:
            sess["acc"]["empty_contexts"] += 1
            entry.setdefault("special_events", [])
            entry["special_events"].append(
                {"event": "EMPTY_CONTEXT", "details": {"reason": "no chunks"}}
            )
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def log_prompt(
        self,
        session_id: str,
        *,
        turn_number: int,
        total_prompt_chars: int = 0,
        context_chars: int = 0,
        history_chars: int = 0,
        history_turns: int = 0,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        entry = {
            "type": "TURN_PROMPT",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "total_prompt_chars": total_prompt_chars,
                "context_chars": context_chars,
                "history_chars": history_chars,
                "history_turns_included": history_turns,
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # LLM response
    # ------------------------------------------------------------------
    def log_llm_start(self, session_id: str, *, turn_number: int):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        entry = {
            "type": "TURN_LLM_START",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
        }
        self._write(session_id, entry)

    def log_llm_complete(
        self,
        session_id: str,
        *,
        turn_number: int,
        ttft_ms: float = 0.0,
        completion_time_ms: float = 0.0,
        response: str = "",
        model: str = "",
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        latency_ms: float = 0.0,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        sess["acc"]["llm_latencies"].append(latency_ms)
        entry = {
            "type": "TURN_LLM_COMPLETE",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "ttft_ms": round(ttft_ms, 1),
                "completion_time_ms": round(completion_time_ms, 1),
                "generated_response": response,
                "response_length_chars": len(response),
                "model": model,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "total_latency_ms": round(latency_ms, 1),
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def log_validation(
        self,
        session_id: str,
        *,
        turn_number: int,
        confidence_score: float = 0.0,
        configured_threshold: float = 0.0,
        validation_result: str = "",
        hallucination_guard_result: str = "",
        transcript_validation_result: str = "",
        low_confidence_triggered: bool = False,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        if low_confidence_triggered:
            sess["acc"]["confidence_rejections"] += 1
        entry = {
            "type": "TURN_VALIDATION",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "confidence_score": confidence_score,
                "configured_threshold": configured_threshold,
                "low_confidence_triggered": low_confidence_triggered,
                "validation_result": validation_result,
                "hallucination_guard_result": hallucination_guard_result,
                "transcript_validation_result": transcript_validation_result,
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # LLM lifecycle (detailed timing breakdown)
    # ------------------------------------------------------------------
    def log_llm_lifecycle(
        self,
        session_id: str,
        *,
        turn_number: int,
        request_start: float = 0.0,
        api_request_sent: float = 0.0,
        first_token_received: float = 0.0,
        last_token_received: float = 0.0,
        postprocessing_start: float = 0.0,
        postprocessing_end: float = 0.0,
        ttft_ms: float = 0.0,
        generation_duration_ms: float = 0.0,
        postprocessing_duration_ms: float = 0.0,
        total_llm_duration_ms: float = 0.0,
        output_tokens: int = 0,
        estimated_tokens_per_second: float = 0.0,
        streaming_duration_ms: float = 0.0,
        model: str = "",
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        response: str = "",
    ):
        if not _TELEMETRY_DETAILED:
            return
        sess = self._sessions.get(session_id)
        if not sess:
            return
        sess["acc"]["llm_latencies"].append(total_llm_duration_ms)
        sess["acc"]["llm_ttfts"].append(ttft_ms)
        sess["acc"]["llm_tokens"].append(tokens_completion)
        sess["acc"]["llm_token_rates"].append(estimated_tokens_per_second)
        entry = {
            "type": "TURN_LLM_LIFECYCLE",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "request_start_unix": round(request_start, 3),
                "api_request_sent_unix": round(api_request_sent, 3),
                "first_token_received_unix": round(first_token_received, 3),
                "last_token_received_unix": round(last_token_received, 3),
                "postprocessing_start_unix": round(postprocessing_start, 3),
                "postprocessing_end_unix": round(postprocessing_end, 3),
                "ttft_ms": round(ttft_ms, 1),
                "generation_duration_ms": round(generation_duration_ms, 1),
                "postprocessing_duration_ms": round(postprocessing_duration_ms, 1),
                "total_llm_duration_ms": round(total_llm_duration_ms, 1),
                "streaming_duration_ms": round(streaming_duration_ms, 1),
                "output_tokens": output_tokens,
                "estimated_tokens_per_second": round(estimated_tokens_per_second, 2),
                "model": model,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "response_length_chars": len(response),
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------
    ERROR_TYPES = {
        "RETRIEVAL_TIMEOUT": "retrieval",
        "RETRIEVAL_ERROR": "retrieval",
        "LLM_TIMEOUT": "llm",
        "LLM_RATE_LIMIT": "llm",
        "LLM_HTTP_ERROR": "llm",
        "LLM_PARSE_ERROR": "llm",
        "VALIDATION_FAILED": "validation",
        "TTS_ERROR": "tts",
        "STT_ERROR": "stt",
        "VAD_ERROR": "vad",
        "UNKNOWN": "unknown",
    }

    def classify_error(self, exception: Exception) -> str:
        msg = str(exception).lower()
        cls_name = type(exception).__name__

        if "429" in msg or "rate" in msg or "too many" in msg:
            return "LLM_RATE_LIMIT"
        if cls_name in ("TimeoutError", "asyncio.TimeoutError", "TimeoutException"):
            return "LLM_TIMEOUT"
        if (
            cls_name in ("JSONDecodeError", "json.JSONDecodeError")
            or "parse" in msg
            or "json" in msg
        ):
            return "LLM_PARSE_ERROR"
        if any(h in cls_name for h in ("HTTP", "Connection", "ConnectError")):
            return "LLM_HTTP_ERROR"
        if "stt" in cls_name.lower() or "speech" in msg:
            return "STT_ERROR"
        if "tts" in cls_name.lower() or "sarvam" in cls_name.lower():
            return "TTS_ERROR"
        if "vad" in cls_name.lower():
            return "VAD_ERROR"
        if "retriev" in cls_name.lower() or "vector" in msg or "chroma" in msg:
            return "RETRIEVAL_ERROR"
        if "valid" in msg or "hallucin" in msg:
            return "VALIDATION_FAILED"
        return "UNKNOWN"

    def log_turn_error(
        self,
        session_id: str,
        *,
        turn_number: int,
        exception: Optional[Exception] = None,
        error_type: str = "UNKNOWN",
        exception_class: str = "",
        exception_message: str = "",
        stack_location: str = "",
        elapsed_ms: float = 0.0,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return

        if exception is not None:
            if not error_type or error_type == "UNKNOWN":
                error_type = self.classify_error(exception)
            exception_class = type(exception).__name__
            exception_message = str(exception)[:500]
            stack_location = (
                f"{traceback.extract_tb(exception.__traceback__)[-1].filename}:"
                f"{traceback.extract_tb(exception.__traceback__)[-1].lineno}"
                if exception.__traceback__
                else ""
            )

        error_entry = {
            "error_type": error_type,
            "exception_class": exception_class,
            "exception_message": exception_message[:200],
            "stack_location": stack_location,
            "elapsed_ms": round(elapsed_ms, 1),
        }
        sess["acc"]["errors"].append(error_entry)

        entry = {
            "type": "TURN_ERROR",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": error_entry,
        }
        self._write(session_id, entry)
        return error_type

    # ------------------------------------------------------------------
    # Quality metrics
    # ------------------------------------------------------------------
    def log_quality_metrics(
        self,
        session_id: str,
        *,
        turn_number: int,
        is_ambiguous: bool = False,
        is_clarification: bool = False,
        hallucination_guard_triggered: bool = False,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        if is_ambiguous:
            sess["acc"]["ambiguous_queries"] += 1
        if is_clarification:
            sess["acc"]["clarification_prompts"] += 1
        if hallucination_guard_triggered:
            sess["acc"]["hallucination_guards_triggered"] += 1

    # ------------------------------------------------------------------
    # Telemetry integrity
    # ------------------------------------------------------------------
    def validate_session_integrity(self, session_id: str) -> List[str]:
        """Read the JSONL file for a session and check for structural issues.
        Returns a list of diagnostic warnings (empty = clean)."""
        warnings = []
        path = self._log_file(session_id)
        if not path.exists():
            return [f"Session file not found: {path}"]

        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    warnings.append(f"JSON parse error: {e}")

        if not events:
            return ["No events found in session file"]

        types = [e.get("type") for e in events]
        if "SESSION_START" not in types:
            warnings.append("Missing SESSION_START event")
        if "SESSION_SUMMARY" not in types:
            warnings.append("Missing SESSION_SUMMARY event")

        turn_nums = []
        prev_ts = 0.0
        for i, ev in enumerate(events):
            ts = ev.get("timestamp_unix", 0)
            if ts < prev_ts:
                warnings.append(f"Event {i} ({ev.get('type')}): non-monotonic timestamp")
            prev_ts = ts

            tn = ev.get("turn_number")
            if tn is not None:
                turn_nums.append(tn)

        for i in range(1, len(turn_nums)):
            if turn_nums[i] < turn_nums[i - 1]:
                warnings.append(
                    f"Non-sequential turn numbers: {turn_nums[i - 1]} -> {turn_nums[i]}"
                )
            if turn_nums[i] == turn_nums[i - 1]:
                warnings.append(f"Duplicate turn number: {turn_nums[i]} at event index {i}")

        return warnings

    # ------------------------------------------------------------------
    def log_voice_output(
        self,
        session_id: str,
        *,
        turn_number: int,
        raw_text: str = "",
        cleaned_text: str = "",
        tts_latency_ms: float = 0.0,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        sess["acc"]["tts_latencies"].append(tts_latency_ms)
        entry = {
            "type": "TURN_VOICE",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "data": {
                "raw_llm_text": raw_text,
                "text_after_clean_for_voice": cleaned_text,
                "tts_latency_ms": round(tts_latency_ms, 1),
            },
        }
        self._write(session_id, entry)

    # ------------------------------------------------------------------
    # Special events
    # ------------------------------------------------------------------
    def log_special_event(
        self,
        session_id: str,
        *,
        turn_number: int,
        event_type: str,
        details: Optional[Dict] = None,
    ):
        sess = self._sessions.get(session_id)
        if not sess:
            return
        counter_map = {
            "FOLLOW_UP_QUERY": "follow_up_queries",
            "REPEAT_REQUEST": "repeat_requests",
            "MULTI_TOPIC_QUERY": "multi_topic_queries",
            "LOW_CONFIDENCE_RETRIEVAL": "low_confidence_retrievals",
            "EMPTY_CONTEXT": "empty_contexts",
            "OUT_OF_KB": "out_of_kb",
            "LANGUAGE_SWITCH": "language_switches",
            "INTERRUPTION": "interruptions",
        }
        key = counter_map.get(event_type)
        if key:
            sess["acc"][key] = sess["acc"].get(key, 0) + 1
        entry = {
            "type": "SPECIAL_EVENT",
            "session_id": session_id,
            "conversation_id": sess["conversation_id"],
            "turn_number": turn_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "event": event_type,
            "details": details or {},
        }
        self._write(session_id, entry)


_telemetry: Optional[ConversationTelemetry] = None


def get_telemetry() -> ConversationTelemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = ConversationTelemetry()
    return _telemetry
