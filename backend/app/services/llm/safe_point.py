import asyncio
from collections import deque
import logging
import os
import random
import re
import time
from typing import Optional

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
    MAX_LOG_ENTRIES = 1000

    def __init__(self):
        self.logs: deque = deque(maxlen=self.MAX_LOG_ENTRIES)

    def log(self, session_id: str, entry: dict):
        entry["ts"] = time.time()
        self.logs.append(entry)
        logger.info(f"[DEMO_SAFEPOINT] [{session_id}] {entry}")

    def flush(self, session_id: str):
        relevant = [e for e in self.logs if e.get("session_id") == session_id]
        if relevant:
            logger.debug(f"[DEMO_SAFEPOINT] Flushed {len(relevant)} log entries for {session_id}")


_demo_logger = DemoLogger()


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
    Passes if ≥30% Bengali Unicode chars OR ≥30% of words are Banglish markers.
    Also passes if query contains college-related keywords (legitimate query, not noise)."""
    bengali_chars = sum(1 for c in query if "\u0980" <= c <= "\u09ff")
    total_chars = len(query.strip())
    if total_chars == 0:
        return False
    # Native Bengali script check
    if bengali_chars / total_chars >= 0.3:
        return True
    # Banglish (Roman-script Bengali) check — ≥25% of words are Banglish markers
    words = re.sub(r"[^\w]", " ", query.lower()).split()
    if not words:
        return False
    banglish_matches = sum(1 for w in words if w in _BANGLISH_WORDS)
    if banglish_matches / len(words) >= 0.25:
        return True
    # College keyword check — if query mentions known college terms, it's legitimate
    _college_kw = {
        "cse", "ece", "ee", "me", "ce", "it", "csd", "ds", "cy", "aiml",
        "fee", "fees", "admission", "placement", "hostel", "faculty",
        "bcrec", "principal", "hod", "department", "library", "lab",
        "sports", "scholarship", "cutoff", "seat", "seats",
    }
    if any(w in _college_kw for w in words):
        return True
    return False


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
