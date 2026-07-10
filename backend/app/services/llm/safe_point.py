import asyncio
import logging
import os
import random
import re
import time
from typing import Any, Callable, Optional

# Banglish (Roman-script Bengali) word markers used when Bengali Unicode ratio is low.
# Kept local to avoid import coupling — these match the words used in language_detect.py.
_BANGLISH_WORDS = frozenset({
    "ami", "amar", "amake", "amra", "tumi", "tomake", "amader",
    "kotha", "bolte", "ache", "korte", "hobe", "thik", "bhalo",
    "kothay", "ekhane", "apnar", "jabe", "asbe", "dite", "nite",
    "niye", "kemon", "dekho", "bole", "jano", "koto", "theke",
    "diye", "jonno", "moddhe", "lagbe", "lage", "laga", "chai",
    "chay", "ki", "keno", "karon", "jani", "jana", "bolun",
    "bolben", "bishoy", "kaj", "help", "kintu", "tobe", "tahole",
    "hoye", "hoy", "mone", "motto", "somporke", "songe", "bar",
    "achen", "achena", "achhen", "achhena", "tar", "take", "na",
    "ar", "ebong", "ba", "jodi", "thake", "thakena",
    "thakle", "pare", "pari", "hote", "hocche", "hoyechhe",
})

logger = logging.getLogger(__name__)


try:
    from app.config import settings

    _DEMO_SAFEPOINT_VAL = (
        bool(settings.demo_safepoint) or os.environ.get("DEMO_SAFEPOINT", "").lower() == "true"
    )
except Exception:
    _DEMO_SAFEPOINT_VAL = os.environ.get("DEMO_SAFEPOINT", "").lower() == "true"

DEMO_SAFEPOINT = _DEMO_SAFEPOINT_VAL


def _is_safe_point() -> bool:
    return DEMO_SAFEPOINT


GREETINGS = [
    "Hello, thank you for calling Dr. B.C. Roy Engineering College. How may I assist you today?",
    "Good morning, you have reached Dr. B.C. Roy Engineering College. How can I help you?",
    "Good afternoon, thank you for calling BCREC. How may I help you today?",
    "Good evening, this is Dr. B.C. Roy Engineering College. How can I assist you?",
    "Namaste, you have reached Dr. B.C. Roy Engineering College. How may I help you?",
    "नमस्ते, डॉ. बी.सी. रॉय इंजीनियरिंग कॉलेज में आपका स्वागत है। मैं आपकी कैसे मदद कर सकता हूँ?",
    "নমস্কার, ডাঃ বি.সি. রয় ইঞ্জিনিয়ারিং কলেজে আপনাকে স্বাগত। আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
    "Hello, this is the BCREC admission office. How can I help you today?",
    "Good morning, Dr. B.C. Roy Engineering College. This is the college reception. How may I help you?",
    "Welcome to Dr. B.C. Roy Engineering College. How can I assist you with admissions or general information?",
]

FILLER_RESPONSES = [
    "One moment please, I am checking that for you.",
    "Let me look that up for you. One moment please.",
    "I am checking that information. Please hold on a moment.",
    "Let me find that for you. One moment please.",
]

HANDOFF_PATTERNS = re.compile(
    r"\b(human|operator|speak\s*(to|with)|talk\s*(to|with)|connect\s*me|transfer|"
    r"real\s*person|counselor|"
    r"counsellor|receptionist|manager|call\s*me\s*back|callback)\b",
    re.IGNORECASE,
)

HANDOFF_RESPONSES = {
    "principal": "I will connect you to the principal's office. The contact number is 0343-2501353.",
    "accounts": "For accounts and fee-related queries, please contact the accounts office at 0343-2501353.",
    "admission": "For admission-specific queries, the admission office can be reached at 0343-2501353.",
    "human": "Certainly. You can reach the college office at 0343-2501353. Our staff will be happy to help you.",
    "default": "I will share the correct admission office contact. Please call 0343-2501353.",
}

PERSONALITY_PREFIXES = [
    "Certainly. ",
    "Of course. ",
    "Yes. ",
    "Absolutely. ",
    "",
]

PERSONALITY_SUFFIXES = [
    " Glad to help.",
    " Thanks for asking.",
    " I hope that helps.",
    " Let me know if you need anything else.",
    " Is there anything else I can help you with?",
]

UNKNOWN_RESPONSE = (
    "I am not completely sure about that information, "
    "but I can connect you with the admission office. "
    "Please call 0343-2501353."
)

BENGALI_LOW_CONFIDENCE = "আমি পুরোটা বুঝতে পারিনি। আরেকবার একটু ধীরে বলবেন?"

TIMEOUT_FALLBACK = "I am sorry for the delay. Let me help using the information I already have."


def get_greeting() -> str:
    return random.choice(GREETINGS)


def _detect_handoff(query: str) -> Optional[str]:
    query_lower = query.lower()
    if not HANDOFF_PATTERNS.search(query_lower):
        return None
    for keyword, response in HANDOFF_RESPONSES.items():
        if keyword in query_lower:
            return response
    return HANDOFF_RESPONSES["default"]


def _add_personality(text: str) -> str:
    """Add natural conversational framing to responses.
    Keeps responses clean — no random prefixes or suffixes.
    The structured handlers and LLM prompt already produce complete sentences."""
    return text.strip()


def _is_unknown_response(text: str) -> bool:
    patterns = [
        r"\bi\s+(?:don'?t|do\s+not)\s+(?:know|have)",
        r"\bi\s+(?:couldn'?t|could\s+not)\s+find",
        r"\bno\s+information\b",
        r"\bnot\s+available\b",
        r"\bunable\s+to\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


class DemoLogger:
    def __init__(self):
        self.logs: list[dict] = []

    def log(self, session_id: str, entry: dict):
        entry["ts"] = time.time()
        self.logs.append(entry)
        logger.info(f"[DEMO_SAFEPOINT] [{session_id}] {entry}")

    def flush(self, session_id: str):
        relevant = [e for e in self.logs if e.get("session_id") == session_id]
        if relevant:
            logger.debug(f"[DEMO_SAFEPOINT] Flushed {len(relevant)} log entries for {session_id}")


_demo_logger = DemoLogger()


class TimeoutGuard:
    """Raises TimeoutError if the wrapped call exceeds the given seconds."""

    def __init__(self, timeout: float = 2.0):
        self.timeout = timeout
        self._timed_out = False

    @property
    def did_timeout(self) -> bool:
        return self._timed_out

    async def __call__(self, coro, fallback: str = "") -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout)
        except asyncio.TimeoutError:
            self._timed_out = True
            logger.warning(f"TimeoutGuard: operation exceeded {self.timeout}s")
            return fallback


async def safe_generate_response(service, query: str, session_id: str, lang: str) -> dict:
    if not DEMO_SAFEPOINT:
        return None

    t_start = time.time()
    handoff_response = _detect_handoff(query)
    if handoff_response:
        _demo_logger.log(
            session_id,
            {
                "event": "handoff",
                "query": query[:60],
                "latency_ms": round((time.time() - t_start) * 1000),
            },
        )
        result = {
            "answer": handoff_response,
            "voice_text": handoff_response,
            "source": "safe_point_handoff",
            "model": "none",
            "latency_ms": round((time.time() - t_start) * 1000),
            "hallucination_validated": True,
            "tokens": {"prompt": 0, "completion": 0},
            "cache_hit": False,
        }
        return result

    if lang == "bn":
        if not _bengali_confidence_ok(query):
            _demo_logger.log(
                session_id,
                {
                    "event": "bengali_low_confidence",
                    "query": query[:60],
                },
            )
            result = {
                "answer": BENGALI_LOW_CONFIDENCE,
                "voice_text": BENGALI_LOW_CONFIDENCE,
                "source": "safe_point_bengali",
                "model": "none",
                "latency_ms": round((time.time() - t_start) * 1000),
                "hallucination_validated": True,
                "tokens": {"prompt": 0, "completion": 0},
                "cache_hit": False,
            }
            return result

    return None


def _bengali_confidence_ok(query: str) -> bool:
    """Check if query is legitimately Bengali (script or Banglish).
    Passes if ≥30% Bengali Unicode chars OR ≥30% of words are Banglish markers."""
    bengali_chars = sum(1 for c in query if "\u0980" <= c <= "\u09ff")
    total_chars = len(query.strip())
    if total_chars == 0:
        return False
    # Native Bengali script check
    if bengali_chars / total_chars >= 0.3:
        return True
    # Banglish (Roman-script Bengali) check — ≥30% of words are Banglish markers
    words = re.sub(r"[^\w]", " ", query.lower()).split()
    if not words:
        return False
    banglish_matches = sum(1 for w in words if w in _BANGLISH_WORDS)
    return banglish_matches / len(words) >= 0.3


def post_process_response(service, query: str, result: dict, lang: str) -> dict:
    if not DEMO_SAFEPOINT:
        return result
    if not result or not result.get("answer"):
        return result

    answer = result["answer"]
    voice = result.get("voice_text", answer)

    is_fallback = (
        answer == UNKNOWN_RESPONSE or answer == BENGALI_LOW_CONFIDENCE or answer == TIMEOUT_FALLBACK
    )

    if _is_unknown_response(answer):
        answer = UNKNOWN_RESPONSE
        voice = UNKNOWN_RESPONSE
        result["answer"] = answer
        result["voice_text"] = voice
        result["source"] = result.get("source", "") + "+safe_point_unknown"
        is_fallback = True

    if is_fallback:
        return result

    answer = _add_personality(answer)
    voice = _add_personality(voice)

    result["answer"] = answer
    result["voice_text"] = voice
    return result
