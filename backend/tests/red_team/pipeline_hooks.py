"""Pipeline stage capture via monkey-patching GroqService methods.

Provides a context manager that wraps key pipeline methods with logging
probes and auto-restores originals on exit.
"""

from __future__ import annotations

import time
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

import logging

logger = logging.getLogger(__name__)


@dataclass
class StageCapture:
    name: str
    start_time: float
    end_time: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    exception: str | None = None
    elapsed_ms: float | None = None

    def finish(self, output: Any = None, exception: str | None = None) -> None:
        self.end_time = time.monotonic()
        self.elapsed_ms = (self.end_time - self.start_time) * 1000
        if exception:
            self.exception = exception
        else:
            self.output = output


@dataclass
class PipelineCapture:
    """Holds the ordered list of stage captures for one test execution."""

    stages: list[StageCapture] = field(default_factory=list)
    generate_response: dict[str, Any] | None = None
    stream_response: list[str] | None = None
    stream_error: str | None = None
    generate_source: str | None = None
    stream_source: str | None = None

    def add_stage(self, name: str, **inputs: Any) -> StageCapture:
        sc = StageCapture(name=name, start_time=time.monotonic(), inputs=inputs)
        self.stages.append(sc)
        return sc

    def stage_names(self) -> list[str]:
        return [s.name for s in self.stages]

    def has_stage(self, name: str) -> bool:
        return any(s.name == name for s in self.stages)

    def get_stage(self, name: str) -> StageCapture | None:
        for s in self.stages:
            if s.name == name:
                return s
        return None

    def summary(self) -> str:
        parts = [f"{'Stage':<25} {'ms':>8} {'Output'}", "-" * 60]
        for s in self.stages:
            status = (
                s.exception[:60] if s.exception else (str(s.output)[:60] if s.output else "None")
            )
            parts.append(f"{s.name:<25} {s.elapsed_ms:>8.1f} {status}")
        return "\n".join(parts)


# -- monkey-patching logic --


def _make_probe(service: Any, method_name: str, capture: PipelineCapture) -> Any:
    """Return a replacement function that logs the call and delegates to the original."""

    original = getattr(service, f"_original_{method_name}", None)
    if original is None:
        original = getattr(service, method_name)
        setattr(service, f"_original_{method_name}", original)

    def probe(self, *args: Any, **kwargs: Any) -> Any:
        sc = capture.add_stage(
            method_name,
            args=_truncate_args(args),
            kwargs=_truncate_kwargs(kwargs),
        )
        try:
            result = original(*args, **kwargs)
            sc.finish(output=_truncate_value(result))
            return result
        except Exception as e:
            sc.finish(exception=f"{type(e).__name__}: {e}")
            raise

    return types.MethodType(probe, service)


def _truncate_value(v: Any, max_len: int = 200) -> Any:
    s = str(v)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return v


def _truncate_args(args: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(_truncate_value(a) for a in args)


def _truncate_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: _truncate_value(v) for k, v in kwargs.items()}


HOOK_METHODS = [
    "_normalize_query",
    "_validate_transcript",
    "_detect_noisy_transcript",
    "_resolve_language",
    "_is_greeting",
    "_is_out_of_domain",
    "_detect_repeat_intent",
    "_detect_on_topic_arithmetic",
    "_split_multi_intent",
    "_expand_follow_up_query",
    "_structured_lookup",
    "_retrieve_context",
    "_build_messages",
    "_validate_answer",
    "_prepare_for_tts",
    "_append_session_turn",
    "_detect_placement_eligibility_intent",
]


@contextmanager
def stage_capture_context(service: Any) -> Iterator[PipelineCapture]:
    """Context manager that monkey-patches key methods and captures pipeline stages.

    Usage:
        svc = get_groq_service()
        with stage_capture_context(svc) as cap:
            result = svc.generate_response("What is CSE fee?", "test-sid")
        print(cap.summary())
    """
    capture = PipelineCapture()
    probes = {}
    for name in HOOK_METHODS:
        if hasattr(service, name):
            probes[name] = _make_probe(service, name, capture)
            setattr(service, name, probes[name])

    original_generate = getattr(service, "_original_generate_response", None)
    if original_generate is None:
        original_generate = service.generate_response
        setattr(service, "_original_generate_response", original_generate)

    def _probe_generate(self: Any, query: str, session_id: str, **kwargs: Any) -> dict[str, Any]:
        result = original_generate(query, session_id, **kwargs)
        capture.generate_response = result
        capture.generate_source = result.get("source") if isinstance(result, dict) else None
        return result

    setattr(service, "generate_response", types.MethodType(_probe_generate, service))

    original_stream = getattr(service, "_original_stream_response", None)
    if original_stream is None:
        original_stream = service.stream_response
        setattr(service, "_original_stream_response", original_stream)

    async def _probe_stream(self: Any, query: str, session_id: str, **kwargs: Any) -> Any:
        tokens: list[str] = []
        try:
            async for token in original_stream(query, session_id, **kwargs):
                tokens.append(token)
                yield token
        except Exception as e:
            capture.stream_error = f"{type(e).__name__}: {e}"
            raise
        finally:
            capture.stream_response = tokens
            # Try to extract source from last delta if available
            if tokens:
                last = tokens[-1]
                if isinstance(last, dict) and "source" in last:
                    capture.stream_source = last["source"]
                elif isinstance(last, str):
                    capture.stream_source = "stream"

    _wrap = _probe_stream
    setattr(service, "stream_response", types.MethodType(_wrap, service))

    try:
        yield capture
    finally:
        for name in HOOK_METHODS:
            original_name = f"_original_{name}"
            if hasattr(service, original_name):
                setattr(service, name, getattr(service, original_name))
        for attr in ["_original_generate_response", "_original_stream_response"]:
            if hasattr(service, attr):
                setattr(service, attr.replace("_original_", ""), getattr(service, attr))
                delattr(service, attr)
