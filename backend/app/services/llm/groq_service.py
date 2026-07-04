"""
Groq LLM Service - Clean RAG Architecture
==========================================
Flow: User Query -> Vector Search (top 4 chunks) -> LLM with context -> Answer

No more full KB injection. No conflicting rules. Just simple, clean RAG.

Phase 0 (Hallucination Guardrail):
- After LLM response, extract numbers/entities and verify they exist in context.
- If a critical entity (fee amount, principal name, etc.) is NOT found in the
  retrieved context, replace the answer with a polite fallback.
"""

import logging
import os
import re
import sys
import time
import json
import hashlib
import asyncio
import random
import unicodedata
from typing import (
    Dict,
    List,
    Optional,
    Any,
    Tuple,
    Set,
    Literal,
    AsyncIterable,
    AsyncIterator,
    Union,
)
import collections
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _sp_enabled() -> bool:
    try:
        from .safe_point import _is_safe_point

        return _is_safe_point()
    except ImportError:
        return False


async def _sp_safe_pre(*a, **kw):
    try:
        from .safe_point import safe_generate_response

        return await safe_generate_response(*a, **kw)
    except ImportError:
        return None


def _sp_post(*a, **kw):
    try:
        from .safe_point import post_process_response

        return post_process_response(*a, **kw)
    except ImportError:
        return kw.get("result") if "result" in kw else None


def _sp_handoff(*a):
    try:
        from .safe_point import _detect_handoff

        return _detect_handoff(*a)
    except ImportError:
        return None


from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from app.services.normalization import normalize_query, normalize_for_tts, NormalizationLog

# ---------------------------------------------------------------------------
# Phase 0 — Hallucination guard configuration
# ---------------------------------------------------------------------------
# Toggle validation on/off via env var. Defaults to ON.
HALLUCINATION_GUARD_ENABLED = os.getenv("HALLUCINATION_GUARD_ENABLED", "true").lower() == "true"

# Minimum retrieval confidence to proceed to LLM (0.0-1.0).
# Below this threshold, the response falls back to the safe "I don't know" message.
# 0.15 matches ChromaDB's internal RELEVANCE_THRESHOLD. Set via env var.
RETRIEVAL_CONFIDENCE_THRESHOLD = float(os.getenv("RETRIEVAL_CONFIDENCE_THRESHOLD", "0.15"))

# Maximum response length in characters for voice output.
# Responses longer than this are truncated at the nearest sentence boundary.
MAX_VOICE_RESPONSE_CHARS = int(os.getenv("MAX_VOICE_RESPONSE_CHARS", "400"))

# Topics where we MUST validate entities against context.
# For other topics (greetings, general chat) we skip validation.
VALIDATED_TOPICS = {
    "fees",
    "fee",
    "hostel",
    "admission",
    "principal",
    "vice_principal",
    "contact",
    "phone",
    "email",
    "address",
    "placement",
    "cutoff",
    "scholarship",
    "documents",
    "eligibility",
}

GREETING_PATTERNS = (
    r"^hi+$",
    r"^hello+$",
    r"^hey+$",
    r"^hii+$",
    r"^hiii+$",
    r"^hello there$",
    r"^good (morning|afternoon|evening)$",
)

# Transcripts that are too short or incomplete to send to the LLM.
# STT often produces fragments from silence, background noise, or mid-sentence cutoffs.
INCOMPLETE_TRAILING_PATTERNS = (
    r"^(what|where|when|why|how|who|which|tell|show|explain|describe|give|list|name|say)\s*$",
    r"^(can|could|would|will|do|does|did|is|are|was|were|have|has|had)\s*$",
    r"^what (is|are|about|the|a|an)\s*$",
    r"^where (is|are|the|a|an|in|at|on)\s*$",
    r"^who (is|are|was|were)\s*$",
    r"^how (many|much|is|are|do|does|can|to)\s*$",
    r"^tell (me|us|about|the)\s*$",
    r"^show (me|us|the)\s*$",
    r"^list (the|of|all)\s*$",
    r"(what|where|when|why|how|who|which|about|of|in|at|on|for|to|the|a|an|is|are|am|was|were)\s*$",
)

FILLER_ONLY_PATTERNS = (
    r"^(okay|ok|k|yes|yeah|yep|no|nah|nope|thanks|thank you|thanku|thx|hmm|hm|mm|huh|aha|uh huh|mm hmm|oh|ah)$",
    r"^(okay|ok|k|yes|yeah|yep|thanks|thank you|thanku)+(\s+(okay|ok|k|yes|yeah|yep|thanks|thank you|thanku))*$",
    r"^(nice|great|good|fine|alright|oki|okie|got it|i see|understand|understood)$",
    r"^(हाँ|नहीं|अच्छा|ठीक|समझ|समझ गया|समझ गयी|जी|जी हाँ|जी नहीं)$",
    r"^(हाँ जी|नहीं जी|अच्छा जी|ठीक है|ठीक है जी)$",
    r"^(হ্যাঁ|না|আচ্ছা|ঠিক|বুঝলাম|বুঝতে পেরেছি|জী|জী হ্যাঁ|জী না)$",
    r"^(হ্যাঁ জী|না জী|আচ্ছা জী|ঠিক আছে|ঠিক আছে জী)$",
)

CLARIFICATION_REPEAT_EN = "I didn't quite catch that. Could you please repeat your question?"
CLARIFICATION_REPEAT_HI = "मैं आपकी बात ठीक से समझ नहीं पाया। कृपया अपना प्रश्न दोहराएँ।"
CLARIFICATION_REPEAT_BN = "আমি আপনার কথা ঠিক বুঝতে পারিনি। অনুগ্রহ করে আপনার প্রশ্নটি আবার বলুন।"

# Patterns for detecting "repeat what you just said" intent — skip RAG entirely
REPEAT_PATTERNS = (
    r"^(repeat|again|pardon|come\s+again)$",
    r"^(say|tell|read)\s+(that|it|this)(\s+again)?$",
    r"^(can|could)\s+(you\s+)?(please\s+)?repeat(\s+(that|it|this)(\s+again)?)?$",
    r"^(can|could)\s+(you\s+)?(please\s+)?rephrase(\s+(that|it|this))?$",
    r"^(can|could)\s+(you\s+)?(please\s+)?say\s+(that|it|this)(\s+again)?$",
    r"^what\s+(did\s+you\s+say|was\s+that)$",
    r"^(excuse\s+me|pardon\s+me)$",
    r"^i\s+(didn'?t|couldn'?t)\s+(hear|catch)\s+(that|you)$",
    r"^(आपने\s+क्या\s+कहा|फिर\s+से\s+बोलिए|पुन:\s+कहें|दोहराइए)$",
    r"^(আপনি\s+কী\s+বললেন|আবার\s+বলুন|কী\s+বললেন|পুনরায়\s+বলুন)$",
)

# Ambiguous single-word queries that need clarification instead of a guess
AMBIGUOUS_WORDS = frozenset(
    {
        "fee",
        "fees",
        "admission",
        "professor",
        "faculty",
        "department",
        "hostel",
        "placement",
        "library",
        "course",
        "seats",
        "prefix",
        "five",
    }
)

AMBIGUOUS_CLARIFICATIONS: Dict[str, str] = {
    "professor": "Which department's professor are you asking about?",
    "faculty": "Which department's faculty are you looking for?",
    "fees": "Which department or course fees are you asking about?",
    "fee": "Which department or course fees are you asking about?",
    "admission": "Which department are you seeking admission to?",
    "placement": "Which department's placement data are you asking about?",
    "hostel": "Would you like to know about hostel fees, facilities, or availability?",
    "library": "What would you like to know about the library?",
    "course": "Which course are you asking about? For B.Tech, the departments are CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, Cyber Security.",
    "department": "Which department would you like information about?",
    "seats": "Which department's seat availability are you asking about?",
    "prefix": "I didn't quite catch that. Could you please repeat your question?",
    "five": "I didn't quite catch that. Could you please repeat your question?",
}

AMBIGUOUS_CLARIFICATIONS_HI: Dict[str, str] = {
    "professor": "किस विभाग के प्रोफेसर के बारे में जानना चाहते हैं?",
    "faculty": "किस विभाग के संकाय के बारे में जानना चाहते हैं?",
    "fees": "किस विभाग या कोर्स की फीस के बारे में पूछ रहे हैं?",
    "fee": "किस विभाग या कोर्स की फीस के बारे में पूछ रहे हैं?",
    "admission": "किस विभाग में प्रवेश लेना चाहते हैं?",
    "placement": "किस विभाग के प्लेसमेंट के बारे में जानना चाहते हैं?",
    "hostel": "हॉस्टल की फीस, सुविधाएँ, या उपलब्धता के बारे में जानना चाहेंगे?",
    "library": "लाइब्रेरी के बारे में क्या जानना चाहेंगे?",
    "course": "किस कोर्स के बारे में पूछ रहे हैं? B.Tech के लिए विभाग हैं: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, Cyber Security.",
    "department": "किस विभाग के बारे में जानकारी चाहिए?",
    "seats": "किस विभाग की सीटों के बारे में पूछ रहे हैं?",
    "prefix": "मैं आपकी बात ठीक से समझ नहीं पाया। कृपया अपना प्रश्न दोहराएँ।",
    "five": "मैं आपकी बात ठीक से समझ नहीं पाया। कृपया अपना प्रश्न दोहराएँ।",
}

AMBIGUOUS_CLARIFICATIONS_BN: Dict[str, str] = {
    "professor": "কোন বিভাগের অধ্যাপক সম্পর্কে জানতে চান?",
    "faculty": "কোন বিভাগের শিক্ষক সম্পর্কে জানতে চান?",
    "fees": "কোন বিভাগ বা কোর্সের ফিস সম্পর্কে জানতে চান?",
    "fee": "কোন বিভাগ বা কোর্সের ফিস সম্পর্কে জানতে চান?",
    "admission": "কোন বিভাগে ভর্তি হতে চান?",
    "placement": "কোন বিভাগের প্লেসমেন্ট সম্পর্কে জানতে চান?",
    "hostel": "হোস্টেলের ফিস, সুবিধা, বা উপলব্ধতা সম্পর্কে জানতে চান?",
    "library": "লাইব্রেরি সম্পর্কে কী জানতে চান?",
    "course": "কোন কোর্স সম্পর্কে জানতে চান? B.Tech এর জন্য বিভাগ: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, Cyber Security.",
    "department": "কোন বিভাগ সম্পর্কে তথ্য চান?",
    "seats": "কোন বিভাগের আসন সংখ্যা সম্পর্কে জানতে চান?",
    "prefix": "আমি আপনার কথা ঠিক বুঝতে পারিনি। অনুগ্রহ করে আপনার প্রশ্নটি আবার বলুন।",
    "five": "আমি আপনার কথা ঠিক বুঝতে পারিনি। অনুগ্রহ করে আপনার প্রশ্নটি আবার বলুন।",
}

# Out-of-domain keywords — clearly not college-admission related
# Queries matching >= 2 distinct categories or >= 3 total keyword hits are blocked pre-retrieval
OUT_OF_DOMAIN_CATEGORIES: Dict[str, frozenset] = {
    "weather": frozenset(
        {
            "weather",
            "rain",
            "temperature",
            "climate",
            "forecast",
            "sunny",
            "cloudy",
            "humid",
            "storm",
            "snow",
        }
    ),
    "sports": frozenset(
        {
            "ipl",
            "cricket",
            "cricketer",
            "football",
            "sports",
            "match",
            "score",
            "t20",
            "world cup",
            "player",
            "team",
            "batsman",
            "bowler",
            "kabaddi",
            "hockey",
            "tennis",
            "badminton",
            "olympics",
            "sport",
            "stadium",
            "tournament",
            "league",
        }
    ),
    "politics": frozenset(
        {
            "politics",
            "election",
            "politician",
            "government",
            "minister",
            "prime minister",
            "chief minister",
            "president",
            "vote",
            "bjp",
            "congress",
            "aap",
            "trinamool",
            "tmc",
            "cpi",
            "neta",
        }
    ),
    "entertainment": frozenset(
        {
            "movie",
            "film",
            "cinema",
            "actor",
            "actress",
            "song",
            "dance",
            "entertainment",
            "celebrity",
            "star",
            "director",
            "music",
            "album",
            "tv",
            "serial",
            "drama",
        }
    ),
    "coding": frozenset(
        {
            "python",
            "javascript",
            "coding",
            "programming",
            "java",
            "c++",
            "html",
            "css",
            "react",
            "node",
            "api",
            "debug",
            "github",
            "algorithm",
            "software",
            "app development",
        }
    ),
    "math": frozenset(
        {
            "solve",
            "equation",
            "derivative",
            "integration",
            "calculate",
            "math",
            "algebra",
            "trigonometry",
            "calculus",
            "geometry",
            "theorem",
            "formula",
        }
    ),
    "news": frozenset(
        {
            "news",
            "headlines",
            "today's news",
            "breaking news",
            "current affairs",
            "newspaper",
        }
    ),
    "personal": frozenset(
        {
            "how are you",
            "who are you",
            "what is your name",
            "your name",
            "tell me a joke",
            "joke",
            "funny",
            "story",
            "poem",
            "song lyrics",
            "horoscope",
            "astrology",
        }
    ),
    "food": frozenset(
        {
            "recipe",
            "cook",
            "food",
            "restaurant",
            "eat",
            "dinner",
            "lunch",
            "breakfast",
            "ingredient",
            "biryani",
            "pizza",
            "burger",
            "cuisine",
            "dish",
            "meal",
            "spice",
            "flavor",
        }
    ),
    "travel": frozenset(
        {
            "train",
            "flight",
            "bus",
            "ticket",
            "booking",
            "hotel",
            "tourist",
            "travel",
            "vacation",
            "holiday",
        }
    ),
}

OUT_OF_DOMAIN_RESPONSE_EN = (
    "I can only answer questions about Dr. B.C. Roy Engineering College, "
    "such as admissions, courses, fees, placements, and campus facilities. "
    "Please ask a college-related question."
)
OUT_OF_DOMAIN_RESPONSE_HI = (
    "मैं केवल डॉ. बी.सी. रॉय इंजीनियरिंग कॉलेज, दुर्गापुर के बारे में प्रश्नों का उत्तर दे सकता हूँ। "
    "कृपया कॉलेज से संबंधित प्रश्न पूछें।"
)
OUT_OF_DOMAIN_RESPONSE_BN = (
    "আমি শুধুমাত্র ডা. বি.সি. রয় ইঞ্জিনিয়ারিং কলেজ, দুর্গাপুর সম্পর্কে প্রশ্নের উত্তর দিতে পারি। "
    "অনুগ্রহ করে কলেজ সংক্রান্ত প্রশ্ন করুন।"
)

# Department names for context enrichment
DEPARTMENT_NAMES = frozenset(
    {
        "cse",
        "it",
        "ece",
        "ee",
        "me",
        "ce",
        "csd",
        "aiml",
        "data science",
        "cyber security",
        "computer science",
        "information technology",
        "electronics",
        "electrical",
        "mechanical",
        "civil",
        "b.tech",
        "b tech",
    }
)

ACKNOWLEDGMENT_EN = "Got it. How else can I help you?"
ACKNOWLEDGMENT_HI = "समझ गया। और कैसे मदद कर सकता हूँ?"
ACKNOWLEDGMENT_BN = "বুঝতে পেরেছি। আর কীভাবে সাহায্য করতে পারি?"

# Tiered fallback messages — escalate naturally instead of repeating
FALLBACK_TIER1_EN = (
    "Let me check on that for you. I may not have this exact information. "
    "Could you try asking in a different way?"
)
FALLBACK_TIER1_HI = (
    "मैं आपके लिए यह जाँच रहा हूँ। हो सकता है मेरे पास यह सटीक जानकारी न हो। कृपया इसे अलग तरीके से पूछकर देखें।"
)
FALLBACK_TIER1_BN = (
    "আমি আপনার জন্য এটি যাচাই করছি। আমার কাছে এই সঠিক তথ্য নাও থাকতে পারে। "
    "অনুগ্রহ করে অন্যভাবে জিজ্ঞাসা করার চেষ্টা করুন।"
)

FALLBACK_TIER2_EN = (
    "I am still not finding what you are looking for. "
    "The best way to get accurate details is to call the college at 0343-2501353."
)
FALLBACK_TIER2_HI = (
    "मैं अब भी वह नहीं ढूँढ पाया जो आप ढूँढ रहे हैं। सटीक जानकारी के लिए कॉलेज को 0343-2501353 पर कॉल करें।"
)
FALLBACK_TIER2_BN = (
    "আমি এখনও আপনার যা খুঁজছেন তা খুঁজে পাচ্ছি না। সঠিক তথ্যের জন্য কলেজে 0343-2501353 নম্বরে কল করুন।"
)

FALLBACK_ANSWER_EN = FALLBACK_TIER1_EN
FALLBACK_ANSWER_HI = FALLBACK_TIER1_HI
FALLBACK_ANSWER_BN = FALLBACK_TIER1_BN

UNKNOWN_INFO_RESPONSE_EN = (
    "I do not have verified information for that. Please call the college at 0343-2501353."
)
UNKNOWN_INFO_RESPONSE_HI = (
    "मेरे पास इसके लिए सत्यापित जानकारी नहीं है। कृपया कॉलेज को 0343-2501353 पर कॉल करें।"
)
UNKNOWN_INFO_RESPONSE_BN = (
    "এ বিষয়ে আমার কাছে যাচাইকৃত তথ্য নেই। অনুগ্রহ করে কলেজে 0343-2501353 নম্বরে কল করুন।"
)

_HOD_UNKNOWN_EN = "I don't have the latest HOD information for that department."
_HOD_UNKNOWN_HI = "मेरे पास उस विभाग के प्रमुख की नवीनतम जानकारी नहीं है।"
_HOD_UNKNOWN_BN = "আমার কাছে সেই বিভাগের বিভাগীয় প্রধান সম্পর্কে সর্বশেষ তথ্য নেই।"

CLARIFY_REPEAT_EN = "I couldn't understand clearly. Could you please repeat?"
CLARIFY_REPEAT_HI = "मैं स्पष्ट रूप से समझ नहीं पाया। कृपया दोहराएँ?"
CLARIFY_REPEAT_BN = "আমি পরিষ্কারভাবে বুঝতে পারিনি। অনুগ্রহ করে পুনরায় বলুন?"

# Structured arithmetic — fee group definitions per department
# Maps department code -> (total_fees, admission_fee, per_semester)
FEE_GROUP_MAP: Dict[str, tuple[int, int, int]] = {
    "CSE": (604700, 98225, 72925),
    "IT": (604700, 98225, 72925),
    "ECE": (604700, 98225, 72925),
    "EE": (554100, 91900, 66100),
    "AIML": (554100, 91900, 66100),
    "DS": (554100, 91900, 66100),
    "CY": (554100, 91900, 66100),
    "CSD": (554100, 91900, 66100),
    "ME": (444100, 78150, 40800),
    "CE": (444100, 78150, 40800),
    "MBA": (419200, 121400, 0),
    "MCA": (217400, 67200, 0),
}

# Department short codes to lookup in canonical_kb
DEPT_CODE_MAP: Dict[str, str] = {
    "cse": "CSE",
    "computer science": "CSE",
    "computer science and engineering": "CSE",
    "it": "IT",
    "information technology": "IT",
    "ece": "ECE",
    "electronics": "ECE",
    "electronics and communication": "ECE",
    "ee": "EE",
    "electrical": "EE",
    "electrical engineering": "EE",
    "me": "ME",
    "mechanical": "ME",
    "mechanical engineering": "ME",
    "ce": "CE",
    "civil": "CE",
    "civil engineering": "CE",
    "csd": "CSD",
    "computer science and design": "CSD",
    "aiml": "AIML",
    "ai ml": "AIML",
    "artificial intelligence": "AIML",
    "ds": "DS",
    "data science": "DS",
    "cy": "CY",
    "cyber security": "CY",
    "cybersecurity": "CY",
    "mba": "MBA",
    "mca": "MCA",
}

# ---------------------------------------------------------------------------
# Phase 4 — Query cache configuration
# ---------------------------------------------------------------------------
# Cache TTL (seconds) and max entries. Tunable via env vars.
try:
    import cachetools  # type: ignore

    CACHE_AVAILABLE = True
except ImportError:
    cachetools = None  # type: ignore
    CACHE_AVAILABLE = False
    logger.warning("cachetools not installed — query cache will be disabled")

CACHE_TTL_SECONDS = int(os.getenv("QUERY_CACHE_TTL", "600"))  # 10 min default
CACHE_MAX_ENTRIES = int(os.getenv("QUERY_CACHE_MAX", "256"))

# Knowledge gaps log path — admin checks this to know what queries need coverage.
_KNOWLEDGE_GAPS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_gaps.json"
)

# Canonical KB path — used for structured lookups (fees, HOD, placements, etc.)
_CANONICAL_KB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "canonical"
    / "canonical_kb.json"
)

# Combined KB path — used to auto-invalidate cache when the file changes.
_KB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "knowledge_base"
    / "combined_kb.json"
)

try:
    from groq import Groq

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

from app.config import settings
from app.services.vector_store import get_vector_store
from app.utils.language_detect import detect_language
from app.utils.conversation_logger import get_telemetry


# ---------------------------------------------------------------------------
# System Prompt — Voice-First Telephony Optimization
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an AI admission assistant for Dr. B.C. Roy Engineering College (BCREC), Durgapur.

LANGUAGE & TRANSLATION RULES:
- Bengali script input → reply in Bengali
- Hindi script input → reply in Hindi
- English/Banglish/Hinglish input → reply in the SAME style they used
- NEVER switch languages mid-response

TTS-FIRST WRITING RULES (Critical for voice — your output goes directly to text-to-speech):
- Spell out ALL numbers as words. NEVER use digits (0-9).
- Replace symbols: "percent" not "%", "per year" not "/year", "rupees" not "₹" or "Rs."
- Phone numbers as digits with dashes like 0343-2501353 — TTS reads them digit-by-digit automatically.
- NO markdown, no bullet lists, no tables, no emoji. Plain sentences only.
- Use ONLY department abbreviations: CSE, IT, ECE, EE, ME, CE, CSD, AIML
- NEVER repeat both abbreviation and full name. Say "CSE" not "CSE (Computer Science and Engineering)"
- End every sentence with a period.

LANGUAGE-SPECIFIC NUMBER FORMATING:
- ENGLISH: "six lakh four thousand seven hundred rupees", "ninety-one percent", "approximately five lakh rupees"
- HINDI: "पाँच लाख" (panch lakh), "इक्यानबे प्रतिशत" (ikyanwe pratishat)
- BENGALI: "পাঁচ লাখ" (pañch lakh), "একানব্বই শতাংশ" (ekanabboi śatansh)

CRITICAL: Numbers must be spelled out in the script of the response language.
Example — fee 6,04,700:
  ENGLISH: "six lakh four thousand seven hundred rupees"  (NOT "₹6,04,700")
  HINDI: "छह लाख चार हज़ार सात सौ रुपये"  (NOT "6,04,700 रुपये")
  BENGALI: "ছয় লাখ চার হাজার সাতশো টাকা"  (NOT "6,04,700 টাকা")

BENGALI TTS OPTIMIZATION:
- Keep Bengali responses to 2-3 short, simple sentences.
- Use common loanwords: ডিপার্টমেন্ট, এডমিশন, ফিস, প্লেসমেন্ট, ক্যাম্পাস.
- Use proper spacing: পূর্ণচ্ছেদ (।) followed by a space.
- Avoid complex compound sentences — split into simple sentences for natural TTS flow.

NATURAL VOICE RULES:
- Be conversational and natural, like a helpful campus counselor speaking on the phone.
- Keep responses concise for voice. Brief paragraphs, not lists.
- NEVER use filler phrases like "Based on the context provided", "According to the knowledge base",
  "As mentioned in the context", "As per the information", "The context states", or similar LLM leakage.
  Speak as a human receptionist would, without reference to any "context" or "knowledge base".
- NEVER use numbered lists, bullet points, or "First... Second... Third..." formatting.
  Join multiple points naturally: "Also, ...", "And regarding ...", "As for ...".
- When listing things, use natural spoken connectors like "and", "also", "as well as".
- If you are unsure, say "I am not sure about that" — do not say you are an AI or reference limitations.
- Open with natural acknowledgements: "Certainly.", "Yes, absolutely.", "I understand your concern.",
  "Of course.", "Let me help you with that." before answering. Don't overdo fillers.
- Do NOT say "I'm not sure if this is the current HOD" — either give the verified HOD name or
  say "I don't have the latest HOD information." Never expose uncertainty about internal data.

PROACTIVE SUGGESTIONS:
- After answering, naturally offer one related follow-up if relevant.
- Example: if asked about fees, say "... by the way, would you like to know about scholarships too?"
- Example: if asked about a department, say "... would you like to know their placement record as well?"
- Only do this once per conversation turn. Do not force it if unnatural.

CONCISENESS:
- Keep answers to 2-4 short sentences maximum. Give the most important answer first.
- Each sentence should be under 15 words where possible.
- After the main answer, ask "Would you like more details?" instead of giving a 300-word monologue.
- For complex topics, give the most important point first, then offer more details.

TERMINOLOGY:
- Refer to the college naturally: "Dr. B.C. Roy Engineering College", "BCREC", or "the college".
- Always say "B dot Tech" not "Bed" or any other pronunciation.
- Use department abbreviations like "CSE", "ECE", "ME" without over-expanding.

CONTENT RULES:
- Answer ONLY from the CONTEXT below. Do not make up facts.
- NEVER invent company names. Only list companies mentioned in the context.
- If user gives rank/marks, use cutoff data to tell them eligible departments. Otherwise ask for rank and marks first.
- Physics, Chemistry, Math, Biology are FIRST-YEAR SUBJECTS, NOT admission departments. B.Tech departments: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, Cyber Security.

MULTI-PART QUESTIONS:
- If the user asks multiple questions in one message, answer EACH sub-question naturally.
- Join them with natural transitions like "Also,", "Regarding", "As for"
- NEVER use "First...", "Second...", "Third..." or numbered lists.
- If you do not have information for any part, say so explicitly for that part only.

FOLLOW-UP RESOLUTION:
- The user may ask follow-ups without repeating full context.
- Use conversation history to resolve implicit references.
- Examples: "what about AIML?" means "what about the AIML department?", "and fees?" means "what are the fees?", "how many seats?" means "how many seats in the previously discussed department?".

TOPIC CONTINUITY:
- Maintain the current topic unless the user clearly changes it.
- Short utterances like "okay then", "and", "what about" are follow-ups, not new topics.

DEPARTMENT-SPECIFIC ACCURACY:
- If the user asks about a SPECIFIC department and the context only contains general college data or data for OTHER departments, say "I do not have specific information for this department" rather than substituting general data.
- Do NOT use college-wide placement stats when the user asks about a specific department's placement.

OUT-OF-KB DEFLECTION:
- If context is empty or doesn't contain the answer, respond politely with phone:
  ENGLISH: "I don't have information about this. Please call the college at 0343-2501353."
  HINDI: "मेरे पास इस बारे में जानकारी नहीं है। कृपया कॉलेज को 0343-2501353 पर कॉल करें।"
  BENGALI: "আমার কাছে এই বিষয়ে তথ্য নেই। অনুগ্রহ করে কলেজে 0343-2501353 নম্বরে কল করুন।"
- Do NOT make up data. Do NOT invent names, fees, or numbers."""


# ---------------------------------------------------------------------------
# Phase 5 — Rate limiter + circuit breaker for Groq API (429 prevention)
# ---------------------------------------------------------------------------
# Sliding window: max R requests in W seconds before self-throttling
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("GROQ_RATE_LIMIT_MAX", "25"))  # 25 req/min free tier
RATE_LIMIT_WINDOW_SEC = int(os.getenv("GROQ_RATE_LIMIT_WINDOW", "60"))

# Circuit breaker: after N consecutive 429s, pause for B seconds
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("GROQ_CIRCUIT_THRESHOLD", "3"))
CIRCUIT_BREAKER_BACKOFF = int(os.getenv("GROQ_CIRCUIT_BACKOFF", "30"))

# Max backoff cap (single call) to prevent unbounded wait
MAX_BACKOFF_SEC = 10.0

# Model fallback list — tried in order on rate limit
# Primary: llama-3.1-8b-instant (fast, good quality)
# Fallback: groq/compound-mini (lighter, different backend = separate rate limit pool)
# Fallback: qwen/qwen3-32b (good multilingual, may have separate rate limits)
FALLBACK_MODELS = ["llama-3.1-8b-instant", "groq/compound-mini", "qwen/qwen3-32b"]


@dataclass
class RateLimiter:
    """Simple sliding-window rate limiter + circuit breaker."""

    max_requests: int = RATE_LIMIT_MAX_REQUESTS
    window_sec: int = RATE_LIMIT_WINDOW_SEC
    circuit_threshold: int = CIRCUIT_BREAKER_THRESHOLD
    circuit_backoff: float = float(CIRCUIT_BREAKER_BACKOFF)

    _timestamps: "collections.deque[float]" = field(
        default_factory=lambda: collections.deque(maxlen=1000)
    )
    _consecutive_429s: int = 0
    _circuit_open_until: float = 0.0

    def _prune(self, now: float) -> None:
        """Remove timestamps outside the window."""
        cutoff = now - self.window_sec
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def acquire(self, now: float | None = None) -> float:
        """Try to acquire a slot. Returns wait time in seconds (0 = go now)."""
        now = now or time.time()
        self._prune(now)

        # Circuit breaker check
        if now < self._circuit_open_until:
            remaining = self._circuit_open_until - now
            logger.warning(
                f"Circuit breaker OPEN — waiting {remaining:.1f}s "
                f"(consecutive 429s={self._consecutive_429s})"
            )
            return min(remaining, MAX_BACKOFF_SEC)

        # Rate limit check
        if len(self._timestamps) >= self.max_requests:
            oldest = self._timestamps[0]
            wait = oldest + self.window_sec - now
            if wait > 0:
                return min(wait, MAX_BACKOFF_SEC)

        self._timestamps.append(now)
        return 0.0

    def record_429(self) -> None:
        """Record a 429 response. May open the circuit breaker."""
        self._consecutive_429s += 1
        if self._consecutive_429s >= self.circuit_threshold:
            self._circuit_open_until = time.time() + self.circuit_backoff
            logger.warning(
                f"Circuit breaker TRIPPED after {self._consecutive_429s} consecutive 429s — "
                f"pausing {self.circuit_backoff}s"
            )

    def record_success(self) -> None:
        """Reset consecutive 429 counter on success."""
        self._consecutive_429s = 0

    @property
    def is_circuit_open(self) -> bool:
        return time.time() < self._circuit_open_until


# ---------------------------------------------------------------------------
# Number-to-word helpers for TTS-safe structured responses
# ---------------------------------------------------------------------------
_NUM_WORDS_EN = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
    21: "twenty-one",
    22: "twenty-two",
    23: "twenty-three",
    24: "twenty-four",
    25: "twenty-five",
    26: "twenty-six",
    27: "twenty-seven",
    28: "twenty-eight",
    29: "twenty-nine",
    30: "thirty",
    31: "thirty-one",
    32: "thirty-two",
    33: "thirty-three",
    34: "thirty-four",
    35: "thirty-five",
    36: "thirty-six",
    37: "thirty-seven",
    38: "thirty-eight",
    39: "thirty-nine",
    40: "forty",
    41: "forty-one",
    42: "forty-two",
    43: "forty-three",
    44: "forty-four",
    45: "forty-five",
    46: "forty-six",
    47: "forty-seven",
    48: "forty-eight",
    49: "forty-nine",
    50: "fifty",
    51: "fifty-one",
    52: "fifty-two",
    53: "fifty-three",
    54: "fifty-four",
    55: "fifty-five",
    56: "fifty-six",
    57: "fifty-seven",
    58: "fifty-eight",
    59: "fifty-nine",
    60: "sixty",
    61: "sixty-one",
    62: "sixty-two",
    63: "sixty-three",
    64: "sixty-four",
    65: "sixty-five",
    66: "sixty-six",
    67: "sixty-seven",
    68: "sixty-eight",
    69: "sixty-nine",
    70: "seventy",
    71: "seventy-one",
    72: "seventy-two",
    73: "seventy-three",
    74: "seventy-four",
    75: "seventy-five",
    76: "seventy-six",
    77: "seventy-seven",
    78: "seventy-eight",
    79: "seventy-nine",
    80: "eighty",
    81: "eighty-one",
    82: "eighty-two",
    83: "eighty-three",
    84: "eighty-four",
    85: "eighty-five",
    86: "eighty-six",
    87: "eighty-seven",
    88: "eighty-eight",
    89: "eighty-nine",
    90: "ninety",
    91: "ninety-one",
    92: "ninety-two",
    93: "ninety-three",
    94: "ninety-four",
    95: "ninety-five",
    96: "ninety-six",
    97: "ninety-seven",
    98: "ninety-eight",
    99: "ninety-nine",
}

_NUM_WORDS_HI = {
    0: "शून्य",
    1: "एक",
    2: "दो",
    3: "तीन",
    4: "चार",
    5: "पाँच",
    6: "छह",
    7: "सात",
    8: "आठ",
    9: "नौ",
    10: "दस",
}

_NUM_WORDS_BN = {
    0: "শূন্য",
    1: "এক",
    2: "দুই",
    3: "তিন",
    4: "চার",
    5: "পাঁচ",
    6: "ছয়",
    7: "সাত",
    8: "আট",
    9: "নয়",
    10: "দশ",
}


def _num_to_english(n: int) -> str:
    if n <= 99:
        return _NUM_WORDS_EN.get(n, str(n))
    if n < 1000:
        h = n // 100
        r = n % 100
        base = _NUM_WORDS_EN.get(h, str(h)) + " hundred"
        if r:
            base += " " + _NUM_WORDS_EN.get(r, str(r))
        return base
    return str(n)


def _num_to_hindi(n: int) -> str:
    return _NUM_WORDS_HI.get(n, str(n))


def _num_to_bengali(n: int) -> str:
    return _NUM_WORDS_BN.get(n, str(n))


@dataclass
class DomainContext:
    domain: str
    entity: str | None = None
    subtype: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationState:
    language: str = "en"
    recent_contexts: deque = field(default_factory=lambda: deque(maxlen=5))
    domain_memory: dict = field(default_factory=dict)


class GroqService:
    """
    Clean Hybrid RAG service: JSON (Precision) + Vector Store (Context).
    """

    def __init__(self):
        self.model = "llama-3.1-8b-instant"
        self.max_tokens = 384
        self.client = settings.groq_client
        self.async_client = getattr(settings, "async_groq_client", None)
        self.vector_store = get_vector_store()

        # Session memory — in-memory dict, cleared on server restart
        self._sessions: Dict[str, List[Dict]] = {}

        # Session language state — tracks persistent language per session
        # Language is NOT redetected on every message; short follow-ups inherit.
        self._session_langs: Dict[str, str] = {}

        # Sessions that should skip ambiguous-word validation this turn
        # (used by yes/no continuation to avoid re-clarifying the same word)
        self._skip_ambiguous_validation_sessions: Set[str] = set()

        # Structured conversation state — tracks last resolved intent/department
        # for follow-up expansion. Updated whenever _structured_lookup returns a hit.
        self._session_intents: Dict[str, str] = {}
        self._session_departments: Dict[str, str] = {}

        # Core knowledge is read from disk on EVERY request (no stale cache across processes).
        self.core_kb = {}

        # Phase 4 — Query cache (in-memory, TTL-based)
        # Caches the FINAL response by (query, lang, context_hash, kb_mtime).
        # Auto-invalidates if the KB file changes on disk.
        self._cache = None
        self._cache_stats = {"hits": 0, "misses": 0}
        self._kb_mtime = None
        try:
            if _KB_PATH.exists():
                self._kb_mtime = _KB_PATH.stat().st_mtime
        except Exception:
            pass
        if CACHE_AVAILABLE and cachetools is not None:
            self._cache = cachetools.TTLCache(maxsize=CACHE_MAX_ENTRIES, ttl=CACHE_TTL_SECONDS)
            logger.info(f"Query cache ENABLED (ttl={CACHE_TTL_SECONDS}s, max={CACHE_MAX_ENTRIES})")
        else:
            logger.info("Query cache DISABLED (cachetools not installed)")

        # Phase 5 — Rate limiter + circuit breaker
        self._rate_limiter = RateLimiter()

        if self.client:
            logger.info("GroqService ready.")
        else:
            logger.warning("GroqService: Groq client not found. Check GROQ_API_KEY in .env")

    # -----------------------------------------------------------------------
    # Phase 4 — Cache helpers
    # -----------------------------------------------------------------------
    def _read_kb(self) -> dict:
        """Read combined_kb.json from disk. Cached in memory with mtime check."""
        try:
            kb_path = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "data"
                / "knowledge_base"
                / "combined_kb.json"
            )
            mtime = kb_path.stat().st_mtime
            if (
                self._kb_mtime is not None
                and mtime == self._kb_mtime
                and hasattr(self, "_kb_cache")
            ):
                return self._kb_cache
            with open(kb_path, "r", encoding="utf-8") as f:
                self._kb_cache = json.load(f)
            self._kb_mtime = mtime
            return self._kb_cache
        except Exception as e:
            logger.error(f"Failed to read combined_kb.json: {e}")
            return {}

    def _cache_key(self, query: str, lang: str, context: str) -> str:
        """Build a stable cache key from query + lang + context + KB mtime."""
        ctx_hash = hashlib.md5(context.encode("utf-8")).hexdigest()[:12] if context else "0"
        return f"{lang}|{query.strip().lower()}|{ctx_hash}|{self._kb_mtime or 0}"

    def _check_kb_changed(self) -> None:
        """Invalidate cache if combined_kb.json mtime changed on disk."""
        try:
            if not _KB_PATH.exists():
                return
            mtime = _KB_PATH.stat().st_mtime
            if self._kb_mtime is None or mtime != self._kb_mtime:
                if self._cache is not None:
                    logger.info("KB file changed on disk — invalidating query cache")
                    self._cache.clear()
                self._kb_mtime = mtime
        except Exception as e:
            logger.debug(f"KB mtime check failed: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Expose hit/miss counts for /metrics later."""
        total = self._cache_stats["hits"] + self._cache_stats["misses"]
        ratio = round(self._cache_stats["hits"] / total, 3) if total else 0.0
        return {
            **self._cache_stats,
            "total": total,
            "hit_ratio": ratio,
            "size": len(self._cache) if self._cache is not None else 0,
            "max_size": CACHE_MAX_ENTRIES,
            "ttl_seconds": CACHE_TTL_SECONDS,
            "enabled": self._cache is not None,
        }

    def invalidate_cache(self) -> int:
        """Manually clear the cache. Returns # of entries cleared."""
        if self._cache is None:
            return 0
        cleared = len(self._cache)
        self._cache.clear()
        logger.info(f"Query cache manually invalidated ({cleared} entries)")
        return cleared

    def reload_kb(self) -> int:
        """Invalidate cache. KB is read from disk on every request now,
        so no reload needed — just clear stale cache entries.
        Returns the number of voice_ready_answers entries (0 if none)."""
        try:
            self._kb_mtime = _KB_PATH.stat().st_mtime if _KB_PATH.exists() else None
            if self._cache is not None:
                self._cache.clear()
            kb = self._read_kb()
            count = len(kb.get("voice_ready_answers", {}))
            logger.info(f"Cache invalidated. KB has {count} voice_ready_answers entries")
            return count
        except Exception as e:
            logger.error(f"Failed to reload KB: {e}")
            return 0

    def _normalize_query(self, query: str) -> str:
        """Fix common STT mis-transcriptions of BCREC department names before RAG.
        Also transliterates Roman-script Bengali college terms to Bengali script
        so that vector search matches the native-script KB entries."""
        q = query
        q = re.sub(r"\bcseaml\b", "CSE-AIML", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcs e[\s-]?aml\b", "CSE-AIML", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcciml\b", "AIML", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcsd\b", "CSD", q, flags=re.IGNORECASE)
        q = re.sub(r"\bdata sci\b", "Data Science", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcyber sec\b", "Cyber Security", q, flags=re.IGNORECASE)
        q = re.sub(r"\binfo tech\b", "Information Technology", q, flags=re.IGNORECASE)
        q = re.sub(r"\belec[ -]?comm\b", "ECE", q, flags=re.IGNORECASE)
        q = re.sub(r"\belectrical\b", "EE", q, flags=re.IGNORECASE)
        q = re.sub(r"\bmechanical\b", "ME", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcivil\b", "CE", q, flags=re.IGNORECASE)
        q = re.sub(r"\bcomputer\b", "CSE", q, flags=re.IGNORECASE)
        q = re.sub(r"\bai[\s-]?ml\b", "AIML", q, flags=re.IGNORECASE)
        # Roman-script Bengali college terms → Bengali script for vector match
        q = re.sub(r"\bupo[- ]?pradhan\b", "উপ-প্রধান", q, flags=re.IGNORECASE)
        if q != query:
            logger.info(f"Query normalized: '{query}' -> '{q}'")
        return q

    def _retrieve_context(self, query: str) -> tuple[str, float]:
        """Enhanced retriever: vector search + semantic re-rank + section-aware filtering.
        Keeps top docs across sources, prioritizes by semantic anchor + language match.
        Returns (context_str, confidence) where confidence is the top relevance score (0.0-1.0)."""
        normalized = self._normalize_query(query)
        try:
            language = detect_language(query)
            results, confidence = self.vector_store.search_with_scores(normalized, k=10)
            if not results:
                self._last_retrieval_data = {
                    "query": normalized,
                    "top_10_raw": [],
                    "chunks_passed": 0,
                    "chunks_discarded": [],
                    "confidence": 0.0,
                }
                return "", 0.0

            query_lower = normalized.lower()
            query_words = set(query_lower.split())

            def semantic_score(doc):
                meta = doc.metadata if hasattr(doc, "metadata") else {}
                score = 0
                anchor = meta.get("semantic_anchor", "").lower()
                anchor_words = anchor.split()
                score += sum(1 for w in anchor_words if w in query_words)
                section = meta.get("section", "")
                if section and section.lower() in query_lower:
                    score += 2
                if meta.get("language") == language:
                    score += 1
                if meta.get("language") == "en" and language != "en":
                    score -= 0.5
                return score

            ranked = sorted(results, key=semantic_score, reverse=True)

            # Capture raw ranked results for telemetry (pre-dedup)
            telemetry_top_10 = []
            for i, doc in enumerate(ranked):
                meta = doc.metadata if hasattr(doc, "metadata") else {}
                text = doc.page_content if hasattr(doc, "page_content") else str(doc)
                if "[" in text and "]" in text:
                    text = text.split("]", 1)[-1].strip()
                telemetry_top_10.append(
                    {
                        "rank": i + 1,
                        "similarity_score": meta.get("score"),
                        "section": meta.get("section", ""),
                        "subsection": meta.get("subsection", ""),
                        "source": meta.get("source", ""),
                        "document_id": meta.get("doc_id", "") or meta.get("id", ""),
                        "preview": text[:150],
                    }
                )

            context_chunks = []
            seen_sections = set()
            discarded = []
            for doc in ranked:
                meta = doc.metadata if hasattr(doc, "metadata") else {}
                section = meta.get("section", "")
                sub = meta.get("subsection", "")
                dedup_key = f"{section}:{sub}"
                if dedup_key in seen_sections:
                    text = doc.page_content if hasattr(doc, "page_content") else str(doc)
                    discarded.append(
                        {
                            "reason": f"duplicate section:subsection ({dedup_key})",
                            "section": section,
                            "subsection": sub,
                            "preview": text[:150],
                        }
                    )
                    continue
                seen_sections.add(dedup_key)
                text = doc.page_content if hasattr(doc, "page_content") else str(doc)
                if "[" in text and "]" in text:
                    text = text.split("]", 1)[-1].strip()
                context_chunks.append(text)
                if len(context_chunks) >= 8:
                    break

            self._last_retrieval_data = {
                "query": normalized,
                "top_10_raw": telemetry_top_10,
                "chunks_passed": len(context_chunks),
                "chunks_discarded": discarded,
                "confidence": confidence,
            }

            return "\n\n---\n\n".join(context_chunks), confidence
        except Exception:
            logger.warning("Vector search failed, returning empty context")
            self._last_retrieval_data = {
                "query": query,
                "top_10_raw": [],
                "chunks_passed": 0,
                "chunks_discarded": [],
                "confidence": 0.0,
            }
            return "", 0.0

    def _build_messages(
        self, query: str, context: str, history: List[Dict], lang: str
    ) -> List[Dict]:
        """Build the messages list for Groq API."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add last 10 conversation turns (5 user + 5 assistant) for memory
        if history:
            for turn in history[-10:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Final user message with retrieved context
        lang_hint = {
            "bn": "Reply in Bengali script (বাংলা).",
            "hi": "Reply in Hindi script (हिन्दी).",
            "en": "Reply in English.",
        }.get(lang, "Reply in the same language as the user.")

        user_message = f"""CONTEXT FROM KNOWLEDGE BASE:
{context}

USER QUESTION: {query}

{lang_hint} Answer based only on the context above."""

        messages.append({"role": "user", "content": user_message})
        return messages

    def _is_lang_switch(self, query: str) -> tuple[bool, str | None]:
        """
        Detect if user is just asking to switch language.
        Returns (is_switch, forced_lang_code).
        e.g. "in bengali" → (True, "bn")
             "in hindi" → (True, "hi")
             "in english" → (True, "en")
             "বাংলায় বলো" → (True, "bn")
        """
        q = query.strip().lower()
        patterns = {
            "bn": [
                "in bengali",
                "bangla te",
                "banglay",
                "বাংলায়",
                "বাংলা তে",
                "bengali te",
                "bengali তে",
                "bangla y",
            ],
            "hi": ["in hindi", "hindi me", "hindi mein", "हिंदी में", "हिंदी मे"],
            "en": ["in english", "english e", "ইংরেজিতে", "english me"],
        }
        for lang, triggers in patterns.items():
            for t in triggers:
                if t in q or q == t:
                    return True, lang
        return False, None

    def _resolve_language(self, session_id: str, query: str) -> str:
        """
        Resolve the language for this query considering persistent session state.

        Rules:
        1. Native Bengali/Devanagari script in query → forced switch to that language.
        2. Explicit switch command ("in bengali", "hindi me") → forced switch.
        3. Short follow-ups (<=3 words, no native script) → inherit current session lang.
        4. Detected language matches session lang → no change.
        5. Detected differs from session lang:
           a. Query has >=2 keyword markers for detected lang → switch (strong evidence).
           b. Otherwise → keep session lang (weak evidence, likely false positive).
        6. Language changes are logged with reason.
        """
        current_lang = self._session_langs.get(session_id, "en")

        # 1. Native script = unambiguous language evidence
        has_bengali = bool(re.search(r"[\u0980-\u09FF]", query))
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", query))
        if has_bengali:
            if current_lang != "bn":
                logger.info(
                    f"[{session_id}] Language change: {current_lang} → bn "
                    f"(reason: Bengali script detected in query)"
                )
                self._session_langs[session_id] = "bn"
            return "bn"
        if has_devanagari:
            if current_lang != "hi":
                logger.info(
                    f"[{session_id}] Language change: {current_lang} → hi "
                    f"(reason: Devanagari script detected in query)"
                )
                self._session_langs[session_id] = "hi"
            return "hi"

        # 2. Explicit switch command
        is_switch, forced_lang = self._is_lang_switch(query)
        if is_switch and forced_lang:
            if forced_lang != current_lang:
                logger.info(
                    f"[{session_id}] Language change: {current_lang} → {forced_lang} "
                    f"(reason: explicit switch command in query)"
                )
                self._session_langs[session_id] = forced_lang
            return forced_lang

        # 3. Short follow-ups (<=3 words, no native script) → inherit current
        word_count = len(query.strip().split())
        if word_count <= 3:
            return current_lang

        # 4. Detect language for longer queries
        from app.utils.language_detect import BANGLA_ROMAN_WORDS, HINDI_ROMAN_WORDS

        detected = detect_language(query)
        if detected == current_lang:
            return current_lang

        # 5. Detected differs from current — check evidence strength.
        # If language was explicitly set (not default "en"), lock it — resist switches
        # via weak keyword markers to prevent random flipping mid-conversation.
        lang_was_explicitly_set = session_id in self._session_langs and current_lang != "en"
        text_lower = query.lower()
        text_words = set(re.sub(r"[^\w\s]", " ", text_lower).split())
        bn_kw = len(text_words & BANGLA_ROMAN_WORDS)
        hi_kw = len(text_words & HINDI_ROMAN_WORDS)

        kw_count = bn_kw if detected == "bn" else hi_kw

        if kw_count >= 2 and not lang_was_explicitly_set:
            logger.info(
                f"[{session_id}] Language change: {current_lang} → {detected} "
                f"(reason: {detected} keyword markers={kw_count}, current_lang markers were "
                f"bn={bn_kw} hi={hi_kw})"
            )
            self._session_langs[session_id] = detected
            return detected

        logger.info(
            f"[{session_id}] Language: detected={detected}, keeping {current_lang} "
            f"(reason: weak evidence, kw markers bn={bn_kw} hi={hi_kw})"
        )
        return current_lang

    def _validate_transcript(self, query: str, session_id: str) -> str | None:
        """Validate transcript quality before RAG+LLM call.

        Returns None if the transcript is acceptable (pass-through).
        Returns a clarification prompt string if the transcript should be
        rejected and the user asked to repeat.

        Detects:
        - Empty / whitespace-only transcripts.
        - Single-word filler / acknowledgment.
        - Incomplete sentence fragments (trailing prepositions / conjunctions).
        - Very short utterances that are not greetings.
        """
        q = query.strip()
        if not q:
            return CLARIFICATION_REPEAT_EN

        # Strip trailing punctuation for pattern matching (STT sometimes adds periods)
        q_clean = re.sub(r"[.?!,;]+$", "", q).strip()
        if not q_clean:
            return CLARIFICATION_REPEAT_EN

        word_count = len(q.split())
        q_lower = q_clean.lower()

        # 1. Filler-only — short acknowledgments that don't need an LLM call.
        if any(re.match(p, q_lower) for p in FILLER_ONLY_PATTERNS):
            current_lang = self._session_langs.get(session_id, "en")
            logger.info(
                f"[{session_id}] Transcript filtered: filler-only '{q}' (word_count={word_count})"
            )
            if current_lang == "hi":
                return ACKNOWLEDGMENT_HI
            if current_lang == "bn":
                return ACKNOWLEDGMENT_BN
            return ACKNOWLEDGMENT_EN

        # 2. Greeting — handled by _is_greeting later, pass through.
        if any(re.match(p, q_lower) for p in GREETING_PATTERNS):
            return None

        # 2.5 Ambiguous single-word query — ask clarification instead of guessing
        # Skip if this session was re-routed by yes/no continuation (avoid re-clarifying)
        if session_id in getattr(self, "_skip_ambiguous_validation_sessions", set()):
            self._skip_ambiguous_validation_sessions.discard(session_id)
        elif word_count == 1 and q_lower in AMBIGUOUS_WORDS:
            current_lang = self._session_langs.get(session_id, "en")
            logger.info(f"[{session_id}] Ambiguous single-word query: '{q}' (lang={current_lang})")
            if current_lang == "hi":
                return AMBIGUOUS_CLARIFICATIONS_HI.get(
                    q_lower, "कृपया बताएँ कि आप किस विभाग या कोर्स के बारे में जानना चाहते हैं?"
                )
            if current_lang == "bn":
                return AMBIGUOUS_CLARIFICATIONS_BN.get(
                    q_lower, "আপনি কোন বিভাগ বা কোর্স সম্পর্কে জানতে চান, দয়া করে বলুন?"
                )
            return AMBIGUOUS_CLARIFICATIONS.get(
                q_lower, f"Which department or course are you asking about regarding {q_lower}?"
            )

        # 2.75 Single-word repeat intent — let this through to the dedicated handler
        if word_count == 1 and q_lower in ("repeat", "pardon"):
            return None

        # 3. Too short (< 2 words) — likely STT noise or partial capture.
        if word_count < 2:
            current_lang = self._session_langs.get(session_id, "en")
            logger.info(
                f"[{session_id}] Transcript filtered: too short '{q}' (word_count={word_count})"
            )
            if current_lang == "hi":
                return CLARIFICATION_REPEAT_HI
            if current_lang == "bn":
                return CLARIFICATION_REPEAT_BN
            return CLARIFICATION_REPEAT_EN

        # 4. Incomplete sentence fragment — ends on a trailing word
        #    that suggests the user was cut off mid-sentence.
        if len(q_clean.split()) <= 5:
            for pattern in INCOMPLETE_TRAILING_PATTERNS:
                if re.search(pattern, q_lower):
                    current_lang = self._session_langs.get(session_id, "en")
                    logger.info(
                        f"[{session_id}] Transcript filtered: incomplete fragment '{q}' "
                        f"(word_count={word_count})"
                    )
                    if current_lang == "hi":
                        return CLARIFICATION_REPEAT_HI
                    if current_lang == "bn":
                        return CLARIFICATION_REPEAT_BN
                    return CLARIFICATION_REPEAT_EN

        return None  # pass through — transcript looks valid

    def _is_greeting(self, query: str) -> bool:
        """Handle short greetings without calling the LLM."""
        q = query.strip().lower()
        if not q:
            return False
        return any(re.match(pattern, q) for pattern in GREETING_PATTERNS)

    @staticmethod
    def _is_out_of_domain(query: str) -> bool:
        """Detect queries that are clearly not about college admissions.

        Counts total keyword matches across all out-of-domain categories.
        Queries with >= 3 words and at least 2 distinct keyword matches
        are considered out-of-domain. This threshold avoids false positives
        on short ambiguous terms (e.g., "python" alone could be about a course).

        Returns False for short queries (< 3 words).
        """
        q = query.strip().lower()
        if not q or len(q.split()) < 3:
            return False

        total_hits = 0
        for keywords in OUT_OF_DOMAIN_CATEGORIES.values():
            total_hits += sum(1 for kw in keywords if kw in q)

        return total_hits >= 2

    def _extract_department_from_history(self, history: List[Dict]) -> str | None:
        """Scan conversation history for the most recent department mention.

        Uses word-boundary matching to avoid false positives (e.g., "ce"
        should not match inside "ece"). Departments are checked longest-first
        so that "data science" matches before "science" (if present).
        """
        depts_sorted = sorted(DEPARTMENT_NAMES, key=len, reverse=True)
        for turn in reversed(history):
            content = turn.get("content", "").lower()
            for dept in depts_sorted:
                if re.search(rf"\b{re.escape(dept)}\b", content):
                    return dept
        return None

    def _get_last_user_question(self, history: List[Dict]) -> str | None:
        """Get the most recent user question from conversation history."""
        for turn in reversed(history):
            if turn.get("role") == "user":
                return turn.get("content", "").strip()
        return None

    def _detect_repeat_intent(self, query: str) -> bool:
        """Check if the user is asking the agent to repeat its last response."""
        q = query.strip().lower()
        return bool(re.match(r"^(repeat|again|pardon|come\s+again)$", q)) or any(
            re.match(p, q) for p in REPEAT_PATTERNS
        )

    def _get_last_assistant_response(self, history: List[Dict]) -> str | None:
        """Get the most recent assistant response from conversation history."""
        for turn in reversed(history):
            if turn.get("role") == "assistant":
                return turn.get("content", "").strip()
        return None

    _DOMAIN_KEYWORDS: Dict[str, set] = {
        "fees": {"fee", "fees", "total", "cost", "payment", "tuition", "semester", "फीस", "ফিস"},
        "hostel": {
            "hostel",
            "hostels",
            "accommodation",
            "room",
            "girls",
            "boys",
            "हॉस्टल",
            "হোস্টেল",
        },
        "admission": {
            "admission",
            "apply",
            "eligibility",
            "entrance",
            "admit",
            "seats",
            "intake",
            "एडमिशन",
            "प्रवेश",
            "এডমিশন",
            "ভর্তি",
        },
        "placement": {
            "placement",
            "placed",
            "recruit",
            "company",
            "lpa",
            "package",
            "job",
            "प्लेसमेंट",
            "প্লেসমেন্ট",
        },
        "contact": {
            "contact",
            "phone",
            "mobile",
            "call",
            "email",
            "helpline",
            "फ़ोन",
            "कॉल",
            "ফোন",
            "কল",
        },
        "courses": {
            "course",
            "courses",
            "department",
            "branch",
            "program",
            "subjects",
            "डिपार्टमेंट",
            "বিভাগ",
        },
        "documents": {"document", "documents", "require", "need", "list", "दस्तावेज़", "ডকুমেন্ট"},
        "timings": {"timing", "timings", "hour", "hours", "when", "समय", "সময়"},
        "scholarship": {"scholarship", "scholarships", "scholar", "छात्रवृत्ति", "স্কলারশিপ"},
        "hod": {"hod", "hods", "head", "professor", "faculty", "प्रोफेसर", "অধ্যাপক"},
        "principal": {"principal", "vice", "प्रिंसिपल", "অধ্যক্ষ"},
        "cutoff": {"cutoff", "rank", "closing", "opening", "कटऑफ", "র‌্যাঙ্ক"},
        "campus": {"campus", "visit", "tour", "कैंपस", "ক্যাম্পাস"},
        "counselling": {"counselling", "counseling", "counsel", "काउंसलिंग", "কাউন্সেলিং"},
        "safety": {"safety", "ragging", "safe", "security", "सुरक्षा", "নিরাপত্তা", "র্যাগিং"},
        "installment": {"installment", "installment", "emi", "pay", "किस्त", "কিস্তি"},
        "handoff": {"human", "speak", "talk", "transfer", "operator"},
    }

    def _detect_query_domain(self, query: str) -> str | None:
        q_lower = query.lower()
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in q_lower:
                    logger.info(f"DOMAIN={domain} | matched='{kw}' in query='{q_lower[:60]}'")
                    return domain
        return None

    def _detect_structured_intent(self, query: str) -> str | None:
        """Detect which structured-lookup handler would match this query.
        Mirrors the handler priority order in _structured_lookup."""
        q = query.strip().lower()
        if re.search(r"\bvice[\s-]?principal\b", q):
            return "vice_principal"
        if re.search(r"\bprincipal\b", q):
            return "principal"
        if re.search(r"\b(contact|phone|mobile|call|helpline)\b", q):
            return "contact"
        if re.search(r"\b(document|require|need|list of).*(admission|admit)\b", q):
            return "admission_documents"
        if re.search(
            r"\badmission\s*office\b|\badmission\s*department\b|\badmission\s*block\b|"
            r"\badmission\s*counsel(or|ler|lor)\b|\btalk\s*(to|with)\s*(admission|admissions)\b|"
            r"\btransfer\s*(me)?\s*(to|in)\s*(admission|admissions)\b",
            q,
        ):
            return "admission_office"
        if re.search(
            r"\b(admission\s*process|how\s*to\s*apply|admissions?|admit|apply\s*(for|to)|how\s*can\s*i\s*get)\b",
            q,
        ):
            return "admission"
        if re.search(r"\b(installments?|installments?|emi|payment\s*plan|pay\s*in\s*part)\b", q):
            return "installment"
        if re.search(r"\b(safety|safe|ragging|security|women.*safe)\b", q):
            return "safety"
        if re.search(r"\bhostel\b", q):
            return "hostel"
        if re.search(r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee)\b", q):
            return "fee"
        if re.search(r"\b(hod|hods|head\s*of\s*department|department\s*head)\b", q):
            return "hod"
        if re.search(r"\b(professor|faculty|teacher|sir|madam|dr\.?|prof\.?)\b", q):
            return "faculty"
        if re.search(r"\b(placements?|placed|recruit|package|lpa|job|company)\b", q):
            return "placement"
        if re.search(r"\b(seats|intake|capacity)\b", q):
            return "seats"
        if re.search(r"\b(cutoff|cut.off|rank|closing.rank|opening.rank)\b", q):
            return "cutoff"
        if re.search(
            r"\b(established|founded|started|founding|when.*start|when.*open|since when|how old)\b",
            q,
        ):
            return "establishment"
        if re.search(r"\bscholarship\b", q):
            return "scholarship"
        if re.search(r"\b(counselling|counseling)\b", q):
            return "counselling"
        if re.search(r"\b(eligibility|eligible|marks?|percentage|qualif)\b", q):
            return "eligibility"
        if re.search(r"\bcampus\s*visit\b|\bvisit\s*campus\b|\btour\b", q):
            return "campus_visit"
        if re.search(
            r"\b(timings?|office hours?|working hours?|college hours?|what.*time|when.*open|when.*close)\b",
            q,
        ):
            return "timings"
        if re.search(
            r"\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b",
            q,
        ):
            return "departments"
        return None

    _HOSTEL_SUBTYPE_KEYWORDS = {
        "boys",
        "girls",
        "fee",
        "fees",
        "facilities",
        "room",
        "rooms",
        "available",
        "availability",
        "capacity",
        "cost",
        "price",
        "charges",
        "wifi",
        "mess",
        "food",
        "laundry",
        "security",
        "timing",
        "timings",
    }

    _ADMISSION_SUBTYPE_KEYWORDS = {
        "document",
        "documents",
        "process",
        "procedure",
        "eligibility",
        "deadline",
        "date",
        "fee",
        "fees",
        "form",
        "apply",
        "application",
        "counseling",
        "counselling",
        "seat",
        "seats",
        "intake",
        "rank",
        "cutoff",
        "entrance",
        "exam",
        "interview",
    }

    def _expand_follow_up_query(
        self, query: str, history: List[Dict], session_id: str = ""
    ) -> Tuple[str, Dict[str, Any]]:
        """Expand a short follow-up query using conversation history.
        Returns (expanded_query, debug_info) where debug_info contains
        the previous question, domains, and reason for decision."""
        q_stripped = query.strip()
        word_count = len(q_stripped.split())
        debug = {
            "word_count": word_count,
            "previous_question": self._get_last_user_question(history)[:80] if history else None,
            "previous_domain": None,
            "current_domain": None,
            "reason": None,
        }

        if word_count >= 6:
            debug["reason"] = "long_query_no_expansion"
            logger.info(
                f"EXPAND: {q_stripped[:60]} | reason=long_query | prev_q={debug['previous_question']}"
            )
            return q_stripped, debug
        if not history:
            debug["reason"] = "no_history"
            logger.info(f"EXPAND: {q_stripped[:60]} | reason=no_history")
            return q_stripped, debug
        if self._detect_repeat_intent(q_stripped):
            debug["reason"] = "repeat_intent"
            logger.info(f"EXPAND: {q_stripped[:60]} | reason=repeat_intent")
            return q_stripped, debug

        q_lower = q_stripped.lower()
        if word_count <= 2 and q_lower in AMBIGUOUS_WORDS:
            dept = self._extract_department_from_history(history)
            if dept:
                enriched = f"{dept} {q_stripped}"
                debug["reason"] = "department_enriched"
                debug["enriched_to"] = enriched
                logger.info(
                    f"EXPAND: {q_stripped[:60]} | reason=dept_enrich | "
                    f"dept={dept} -> {enriched[:60]} | prev_q={debug['previous_question']}"
                )
                return enriched, debug

        # If the current query already expresses a complete structured intent,
        # it is self-sufficient — no expansion needed.
        current_intent = self._detect_structured_intent(q_stripped)
        if current_intent:
            debug["reason"] = "already_complete_intent"
            debug["current_intent"] = current_intent
            logger.info(
                f"EXPAND: {q_stripped[:60]} | reason=already_complete_intent | "
                f"intent={current_intent}"
            )
            return q_stripped, debug

        last_user = self._get_last_user_question(history)
        if not last_user:
            debug["reason"] = "no_previous_user_question"
            logger.info(f"EXPAND: {q_stripped[:60]} | reason=no_prev_q")
            return q_stripped, debug

        current_domain = self._detect_query_domain(q_stripped)
        last_user_domain = self._detect_query_domain(last_user)
        debug["current_domain"] = current_domain
        debug["previous_domain"] = last_user_domain

        if current_domain:
            if last_user_domain and current_domain != last_user_domain:
                debug["reason"] = "new_domain_blocked"
                logger.info(
                    f"EXPAND: {q_stripped[:60]} | reason=new_domain_blocked | "
                    f"domain={current_domain} vs prev_domain={last_user_domain} | "
                    f"prev_q={debug['previous_question']}"
                )
                return q_stripped, debug
            debug["reason"] = "same_domain_merge"

        # --- Structured state rewrite: before fallback text merge ---
        last_intent = self._session_intents.get(session_id) if session_id else None
        last_dept = self._session_departments.get(session_id) if session_id else None

        if last_intent:
            # Case 1: Department-only follow-up — "What about Mechanical?" after fee
            # Only rewrite when the last intent is department-compatible.
            # "What about Mechanical?" after hostel doesn't make sense as "ME hostel".
            dept_code = self._extract_dept_code(q_stripped)
            dept_compatible_intents = {
                "fee",
                "admission",
                "placement",
                "hod",
                "seats",
                "cutoff",
                "eligibility",
                "departments",
                "faculty",
            }
            is_dept_query = dept_code is not None or any(
                word.lower().rstrip("?.,!")
                in {
                    "cse",
                    "it",
                    "ece",
                    "ee",
                    "me",
                    "ce",
                    "aiml",
                    "csd",
                    "computer",
                    "mechanical",
                    "electrical",
                    "electronics",
                    "civil",
                    "information",
                    "data",
                    "science",
                    "cyber",
                }
                for word in q_stripped.split()
            )
            if is_dept_query and last_intent in dept_compatible_intents:
                dept = dept_code or next(
                    (
                        w.lower().rstrip("?.,!")
                        for w in q_stripped.split()
                        if w.lower().rstrip("?.,!")
                        in {
                            "cse",
                            "it",
                            "ece",
                            "ee",
                            "me",
                            "ce",
                            "aiml",
                            "csd",
                            "computer",
                            "mechanical",
                            "electrical",
                            "electronics",
                            "civil",
                            "information",
                            "data",
                            "science",
                            "cyber",
                        }
                    ),
                    "department",
                )
                expanded = f"{dept} {last_intent}"
                debug["reason"] = "structured_department_rewrite"
                debug["intent"] = last_intent
                debug["department"] = dept
                logger.info(
                    f"EXPAND: {q_stripped[:60]} | reason=structured_department_rewrite | "
                    f"intent={last_intent} | dept={dept} | expanded-> {expanded[:80]}"
                )
                return expanded, debug

            # Also check if any word in the query looks like a department name
            for word in q_stripped.split():
                word_lower = word.lower().rstrip("?.,!")
                if (
                    word_lower
                    in {
                        "cse",
                        "it",
                        "ece",
                        "ee",
                        "me",
                        "ce",
                        "aiml",
                        "csd",
                        "computer",
                        "mechanical",
                        "electrical",
                        "electronics",
                        "civil",
                        "information",
                        "data",
                        "science",
                        "cyber",
                        "btech",
                        "b.tech",
                    }
                    and last_intent in dept_compatible_intents
                ):
                    expanded = f"{word_lower} {last_intent}"
                    debug["reason"] = "structured_department_rewrite"
                    debug["intent"] = last_intent
                    debug["department"] = word_lower
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_department_rewrite | "
                        f"intent={last_intent} | dept={word_lower} | expanded-> {expanded[:80]}"
                    )
                    return expanded, debug

            # Case 2: Hostel subtype follow-up — "What about boys?" after hostel
            if last_intent == "hostel":
                subtype = None
                for sw in self._HOSTEL_SUBTYPE_KEYWORDS:
                    if sw in q_lower:
                        subtype = sw
                        break
                if subtype:
                    expanded = f"{subtype} hostel"
                    debug["reason"] = "structured_hostel_rewrite"
                    debug["subtype"] = subtype
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_hostel_rewrite | "
                        f"subtype={subtype} | expanded-> {expanded[:80]}"
                    )
                    return expanded, debug

            # Case 3: Admission subtype follow-up — "What about documents?" after admission
            if last_intent in ("admission", "admission_office", "admission_documents"):
                subtype = None
                for sw in self._ADMISSION_SUBTYPE_KEYWORDS:
                    if sw in q_lower:
                        subtype = sw
                        break
                if subtype:
                    expanded = f"{subtype} admission"
                    debug["reason"] = "structured_admission_rewrite"
                    debug["subtype"] = subtype
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_admission_rewrite | "
                        f"subtype={subtype} | expanded-> {expanded[:80]}"
                    )
                    return expanded, debug

            # Case 4: Fee follow-up — "What about ECE?" or "ECE?" after fee intent
            if last_intent == "fee":
                expanded = f"{q_stripped} fee"
                debug["reason"] = "structured_fee_followup"
                logger.info(
                    f"EXPAND: {q_stripped[:60]} | reason=structured_fee_followup | "
                    f"expanded-> {expanded[:80]}"
                )
                return expanded, debug

        # --- Fallback: text merge (only when no structured state applies) ---
        if not debug.get("reason"):
            debug["reason"] = "fallback_text_merge"
        expanded = f"{q_stripped} {last_user}"
        if len(expanded) > 300:
            expanded = expanded[:300]
        logger.info(
            f"EXPAND: {q_stripped[:60]} | reason={debug['reason']} | "
            f"domain={current_domain} | prev_domain={last_user_domain} | "
            f"prev_q={debug['previous_question']} | expanded-> {expanded[:80]}"
        )
        return expanded, debug

    # -----------------------------------------------------------------------
    # Canonical KB reader (structured data for deterministic answers)
    # -----------------------------------------------------------------------
    _canonical_kb_cache: "dict | None" = None
    _canonical_kb_mtime: "float | None" = None

    def _read_canonical_kb(self) -> dict:
        """Read the canonical KB file with caching."""
        try:
            mtime = _CANONICAL_KB_PATH.stat().st_mtime if _CANONICAL_KB_PATH.exists() else None
            if (
                self._canonical_kb_mtime is not None
                and mtime == self._canonical_kb_mtime
                and self._canonical_kb_cache is not None
            ):
                return self._canonical_kb_cache
            with open(_CANONICAL_KB_PATH, "r", encoding="utf-8") as f:
                self._canonical_kb_cache = json.load(f)
            self._canonical_kb_mtime = mtime
            return self._canonical_kb_cache
        except Exception as e:
            logger.error(f"Failed to read canonical_kb.json: {e}")
            return {}

    # -----------------------------------------------------------------------
    # Task 1 — Structured Knowledge Layer (deterministic lookups)
    # -----------------------------------------------------------------------
    def _extract_dept_code(self, query: str) -> str | None:
        """Extract a normalized department code from a query string."""
        q = query.strip().lower()
        # Check multi-word matches first (longest-first) with word boundaries
        for alias in sorted(DEPT_CODE_MAP, key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", q):
                return DEPT_CODE_MAP[alias]
        return None

    def _format_inr(self, amount: int, lang: str) -> str:
        """Format a number as Indian number words for TTS.
        Handles full Indian numbering: crore, lakh, thousand, hundred."""
        if amount == 0:
            zero_map = {"hi": "शून्य रुपये", "bn": "শূন্য টাকা", "en": "zero rupees"}
            return zero_map.get(lang, "zero rupees")

        parts = []
        remaining = amount

        crores = remaining // 10000000
        remaining %= 10000000
        lakhs = remaining // 100000
        remaining %= 100000
        thousands = remaining // 1000
        remaining %= 1000
        hundreds = remaining // 100
        remaining %= 100

        if lang == "hi":
            if crores:
                parts.append(f"{_num_to_hindi(crores)} करोड़")
            if lakhs:
                parts.append(f"{_num_to_hindi(lakhs)} लाख")
            if thousands:
                parts.append(f"{_num_to_hindi(thousands)} हज़ार")
            if hundreds:
                parts.append(f"{_num_to_hindi(hundreds)} सौ")
            if remaining:
                parts.append(_num_to_hindi(remaining))
            suffix = "रुपये"
        elif lang == "bn":
            if crores:
                parts.append(f"{_num_to_bengali(crores)} কোটি")
            if lakhs:
                parts.append(f"{_num_to_bengali(lakhs)} লাখ")
            if thousands:
                parts.append(f"{_num_to_bengali(thousands)} হাজার")
            if hundreds:
                parts.append(f"{_num_to_bengali(hundreds)} শত")
            if remaining:
                parts.append(_num_to_bengali(remaining))
            suffix = "টাকা"
        else:
            if crores:
                parts.append(f"{_num_to_english(crores)} crore")
            if lakhs:
                parts.append(f"{_num_to_english(lakhs)} lakh")
            if thousands:
                parts.append(f"{_num_to_english(thousands)} thousand")
            if hundreds:
                parts.append(f"{_num_to_english(hundreds)} hundred")
            if remaining:
                parts.append(_num_to_english(remaining))
            suffix = "rupees"

        if parts:
            return " ".join(parts) + " " + suffix
        return suffix

    # Conjunction patterns that split compound questions
    _CONJUNCTIONS = re.compile(
        r"\s+(and\s+(also\s+)?|or\s+|&\s+|,?\s+also\s+|,\s+and\s+)", re.IGNORECASE
    )

    def _split_multi_intent(self, query: str) -> list[str]:
        """Split a compound query like 'hostel and fees' into individual intents.
        Returns a list of query segments, or [query] if no split is needed.
        Only splits on 'and'/'or' between two question-like phrases, not within."""
        q = query.strip()
        # Only attempt split if there's an 'and'/'or' between meaningful phrases
        # Must have at least 3 words on each side of the conjunction
        for conj in [" and also ", " and ", " or ", " & "]:
            idx = q.lower().find(conj)
            if idx < 0:
                continue
            left = q[:idx].strip()
            right = q[idx + len(conj) :].strip()
            left_words = left.split()
            right_words = right.split()
            if len(left_words) >= 2 and len(right_words) >= 2:
                return [left, right]
        # Also split on comma-separated intents: "hostel, fees"
        if ", " in q and q.count(", ") <= 2:
            parts = [p.strip() for p in q.split(", ") if p.strip()]
            if len(parts) >= 2 and all(len(p.split()) >= 2 for p in parts):
                return parts
        return [q]

    def _structured_lookup(self, query: str, lang: str) -> str | None:
        """Try to answer a query directly from structured canonical KB data.
        Returns a formatted answer string, or None if not found."""
        kb = self._read_canonical_kb()
        if not kb:
            return None

        q = query.strip().lower()

        # --- Vice Principal lookup (must be before principal check) ---
        if re.search(r"\bvice[\s-]?principal\b", q):
            vp = kb.get("vice_principal", {})
            name = vp.get("name", {}).get("value", "")
            if name:
                logger.info(f"HANDLER: vice_principal matched for query='{q[:60]}'")
                return f"The vice principal of BCREC is {name}."

        # --- Principal lookup ---
        if re.search(r"\bprincipal\b", q):
            principal = kb.get("principal", {})
            name = principal.get("name", {}).get("value", "")
            if name:
                phone = principal.get("phone", {}).get("value", "")
                logger.info(f"HANDLER: principal matched for query='{q[:60]}'")
                return f"The principal of BCREC is {name}. You can contact them at {phone}."

        # --- Contact info ---
        if re.search(r"\b(contact|phone|mobile|call|helpline)\b", q):
            college = kb.get("college", {})
            phones = college.get("phones", {}).get("value", [])
            email = college.get("email", {}).get("value", "")
            if phones:
                phone_str = ", ".join(phones[:3])
                logger.info(f"HANDLER: contact matched for query='{q[:60]}'")
                return (
                    f"You can contact BCREC at {phone_str}. "
                    f"Email: {email}. "
                    f"Mobile: {college.get('mobile', {}).get('value', '')}."
                )

        # --- Admission documents ---
        if re.search(r"\b(document|require|need|list of).*(admission|admit)\b", q):
            docs_section = kb.get("admission_documents", {})
            parts = []
            for category, doc_list in docs_section.items():
                if isinstance(doc_list, dict) and "value" in doc_list:
                    items = doc_list["value"]
                    if isinstance(items, list) and items:
                        parts.append(f"{category}: {', '.join(items[:3])}")
            if parts:
                logger.info(f"HANDLER: admission_documents matched for query='{q[:60]}'")
                return "Required documents: " + " | ".join(parts[:3])

        # --- Admission office contact (checked BEFORE general admission) ---
        if re.search(
            r"\badmission\s*office\b|\badmission\s*department\b|\badmission\s*block\b|"
            r"\badmission\s*counsel(or|ler|lor)\b|\btalk\s*(to|with)\s*(admission|admissions)\b|"
            r"\btransfer\s*(me)?\s*(to|in)\s*(admission|admissions)\b",
            q,
        ):
            contacts = kb.get("admission", {}).get("contacts", {}).get("value", "")
            if contacts:
                logger.info(f"HANDLER: admission_office matched for query='{q[:60]}'")
                return f"You can reach the admission office at {contacts}."
            logger.info(f"HANDLER: admission_office (default) matched for query='{q[:60]}'")
            return "The admission office can be contacted at 0343-2501353."

        # --- Admission process (general) ---
        if re.search(
            r"\b(admission\s*process|how\s*to\s*apply|admissions?|admit|apply\s*(for|to)|how\s*can\s*i\s*get)\b",
            q,
        ):
            adm = kb.get("admission", {})
            eligibility = adm.get("eligibility", {}).get("btech", {}).get("value", "")
            entrance = adm.get("eligibility", {}).get("entrance", {}).get("value", "")
            if eligibility:
                logger.info(f"HANDLER: admission_general matched for query='{q[:60]}'")
                return (
                    f"B.Tech admission is through {entrance}. "
                    f"Eligibility is {eligibility}. "
                    f"Seats: WBJEE 80 percent, JEE Main 10 percent, Management Quota 10 percent. "
                    f"Apply online at the WBJEEB website or the college portal."
                )

        # --- Installment / payment plan (checked BEFORE fee to catch "pay fee in installments") ---
        if re.search(r"\b(installments?|installments?|emi|payment\s*plan|pay\s*in\s*part)\b", q):
            payment = kb.get("fees_summary", {}).get("payment_modes", {}).get("value", "")
            if payment:
                logger.info(f"HANDLER: installment matched for query='{q[:60]}'")
                return f"Payment options: {payment}."
            logger.info(f"HANDLER: installment (default) matched for query='{q[:60]}'")
            return "For fee payment options, please contact the accounts office at 0343-2501353."

        # --- Safety / Anti-ragging (checked BEFORE hostel to preserve existing order) ---
        if re.search(r"\b(safety|safe|ragging|security|women.*safe)\b", q):
            ar = kb.get("anti_ragging", {})
            policy = ar.get("policy", {}).get("value", "")
            reporting = ar.get("reporting", {}).get("value", "")
            safety = ar.get("safety", {}).get("value", "")
            if policy:
                logger.info(f"HANDLER: safety matched for query='{q[:60]}'")
                return (
                    f"BCREC has a {policy} anti-ragging policy. "
                    f"{'Reporting: ' + reporting if reporting else ''} "
                    f"{'Women safety helpline: ' + safety if safety else ''}"
                ).strip()
            return self._lang_response_unknown(lang)

        # --- Hostel general info (checked BEFORE fee so "hostel fee" returns hostel context) ---
        if re.search(r"\bhostel\b", q):
            hostel = kb.get("hostel", {})
            available = hostel.get("available", {}).get("value")
            if available is True:
                total = hostel.get("total_hostels", {}).get("value", "")
                boys = hostel.get("boys_hostels", {}).get("value", "")
                girls = hostel.get("girls_hostels", {}).get("value", "")
                capacity = hostel.get("total_capacity", {}).get("value", "")
                logger.info(f"HANDLER: hostel matched for query='{q[:60]}'")
                return (
                    f"Yes, hostel accommodation is available at BCREC. "
                    f"There are {total} hostels — {boys} for boys and {girls} for girls — "
                    f"with a total capacity of {capacity} students."
                )
            logger.info(f"HANDLER: hostel (unavailable) matched for query='{q[:60]}'")
            return "Hostel accommodation is not currently available at BCREC."

        # --- Fee lookup (with negative lookbehind to avoid stealing from hostel/installment) ---
        fee_intent = re.search(
            r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee)\b", q
        )
        if fee_intent:
            logger.info(f"HANDLER: fee_intent matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code and dept_code in FEE_GROUP_MAP:
                total, admission, per_sem = FEE_GROUP_MAP[dept_code]
                dept_name = dept_code
                if "full_name" in kb.get("courses", {}).get("btech", {}).get(dept_code, {}):
                    dept_name = kb["courses"]["btech"][dept_code]["full_name"]["value"]
                # Determine which fee type
                if re.search(r"\bsemester\s*fee\b|\bper\s*semester\b|\bsem\s*fee\b", q):
                    if per_sem > 0:
                        return (
                            f"The semester fee for {dept_name} is "
                            f"{self._format_inr(per_sem, lang)}."
                        )
                    return (
                        f"The total fee for {dept_name} is "
                        f"{self._format_inr(total, lang)}. "
                        f"Contact the college for semester-wise breakdown."
                    )
                if re.search(r"\badmission\s*fee\b", q):
                    return (
                        f"The admission fee for {dept_name} is {self._format_inr(admission, lang)}."
                    )
                # Default: total fee
                return f"The total fee for {dept_name} is {self._format_inr(total, lang)}."

            # No department specified — general fee info
            if re.search(r"\b(fee structure|fee|fees)\b", q):
                return (
                    "BCREC B.Tech fees: CSE, IT, ECE: "
                    f"{self._format_inr(604700, 'en')} total. "
                    "EE, AIML, DS, CY, CSD: "
                    f"{self._format_inr(554100, 'en')} total. "
                    "ME, CE: "
                    f"{self._format_inr(444100, 'en')} total. "
                    "Contact the college for exact semester-wise fees."
                )

        # --- HOD lookup ---
        if re.search(r"\b(hod|hods|head\s*of\s*department|department\s*head)\b", q):
            logger.info(f"HANDLER: hod matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code:
                depts = kb.get("departments", {})
                dept_data = depts.get(dept_code, {})
                hod = dept_data.get("hod", {})
                hod_name = hod.get("name", {}).get("value", "")
                if hod_name:
                    email = hod.get("email", {}).get("value", "")
                    dept_full = dept_code
                    if "full_name" in kb.get("courses", {}).get("btech", {}).get(dept_code, {}):
                        dept_full = kb["courses"]["btech"][dept_code]["full_name"]["value"]
                    return f"The HOD of {dept_full} is {hod_name}. Email: {email}."
                return self._lang_hod_unknown(lang)
            # No dept specified — list all HODs
            depts = kb.get("departments", {})
            hod_list = []
            for code, data in depts.items():
                hod = data.get("hod", {})
                name = hod.get("name", {}).get("value", "")
                if name:
                    hod_list.append(f"{code}: {name}")
            if hod_list:
                return "Department Heads: " + "; ".join(hod_list[:6]) + "."
            return self._lang_hod_unknown(lang)

        # --- Faculty name resolution ---
        if re.search(r"\b(professor|faculty|teacher|sir|madam|dr\.?|prof\.?)\b", q):
            logger.info(f"HANDLER: faculty matched for query='{q[:60]}'")
            return self._resolve_faculty_name(q, kb)

        # --- Placement lookup ---
        if re.search(r"\b(placements?|placed|recruit|package|lpa|job|company)\b", q):
            logger.info(f"HANDLER: placement matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            placements = kb.get("placements", {})
            if dept_code:
                dept_course = kb.get("courses", {}).get("btech", {}).get(dept_code, {})
                dept_placement = dept_course.get("placement", {})
                if dept_placement:
                    rate = dept_placement.get("rate_2024_25", {}).get("value", "")
                    avg = dept_placement.get("avg_lpa", {}).get("value", "")
                    max_p = dept_placement.get("max_lpa", {}).get("value", "")
                    if rate:
                        return (
                            f"The placement rate for {dept_code} is {rate}. "
                            f"Average package is {avg} LPA. "
                            f"Maximum package is {max_p} LPA."
                        )
            # Overall placement
            overall = placements.get("overall_rate_2025", {}).get("value", "")
            if overall and re.search(r"\b(overall|college|average)\b", q):
                avg_pkg = placements.get("average_package", {}).get("value", "")
                return (
                    f"The overall placement rate for BCREC is {overall}. "
                    f"Average package is {avg_pkg}."
                )

        # --- Department seat info ---
        if re.search(r"\b(seats|intake|capacity)\b", q):
            logger.info(f"HANDLER: seats matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code:
                dept_course = kb.get("courses", {}).get("btech", {}).get(dept_code, {})
                intake = dept_course.get("intake", {}).get("value", "")
                if intake:
                    return f"The intake for {dept_code} is {intake} seats."
                return UNKNOWN_INFO_RESPONSE_EN

        # --- Cutoff / rank info ---
        if re.search(r"\b(cutoff|cut.off|rank|closing.rank|opening.rank)\b", q):
            logger.info(f"HANDLER: cutoff matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code:
                _CUTOFF_MAP = {
                    "CSE": {"2024": "16059", "2025": "67761", "2026_est": "~65000"},
                    "IT": {"2024": "30000", "2025": "~70000", "2026_est": "~75000"},
                    "ECE": {"2024": "40000", "2025": "~80000", "2026_est": "~80000"},
                    "EE": {"2024": "50000", "2025": "~90000", "2026_est": "~90000"},
                    "ME": {"2024": "60000", "2025": "~100000", "2026_est": "~100000"},
                    "CE": {"2024": "65000", "2025": "~110000", "2026_est": "~110000"},
                }
                if dept_code in _CUTOFF_MAP:
                    co = _CUTOFF_MAP[dept_code]
                    return (
                        f"The WBJEE cutoff rank for {dept_code} is: "
                        f"2024: {co['2024']}, "
                        f"2025: {co['2025']}, "
                        f"estimated 2026: {co['2026_est']}. "
                        f"These are approximate values and may vary by category."
                    )
            return "I don't have the specific cutoff data for that department. Please contact the college admission office for accurate rank information."

        # --- Establishment / founded / history ---
        if re.search(
            r"\b(established|founded|started|founding|when.*start|when.*open|since when|how old)\b",
            q,
        ):
            logger.info(f"HANDLER: establishment matched for query='{q[:60]}'")
            return (
                "Dr. B.C. Roy Engineering College was established in August 2000. "
                "It became autonomous from the 2024-25 academic session."
            )

        # --- Computer lab timings (before general timings) ---
        if re.search(r"\bcomputer\s*lab|lab\s*timing|lab\s*hours?\b", q):
            logger.info(f"HANDLER: computer_lab matched for query='{q[:60]}'")
            return (
                "Computer labs are open during college hours: Monday to Friday, "
                "10:00 AM to 5:30 PM. The campus is closed on Saturday and Sunday."
            )

        # --- Library timings ---
        if re.search(r"\blibrary\s*(timing|hours?)|reading\s*room\b", q):
            logger.info(f"HANDLER: library matched for query='{q[:60]}'")
            return (
                "The library is open Monday to Friday, 10:00 AM to 5:30 PM. "
                "It is closed on Saturday and Sunday."
            )

        # --- College timings ---
        if re.search(
            r"\b(timings?|office hours?|working hours?|college hours?|what.*time|when.*open|when.*close)\b",
            q,
        ):
            logger.info(f"HANDLER: timings matched for query='{q[:60]}'")
            return (
                "College timings: Monday to Friday, 10:00 AM to 5:30 PM. "
                "The campus is closed on Saturday and Sunday."
            )

        # --- College info (departments) ---
        if (
            re.search(
                r"\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b",
                q,
            )
            and not fee_intent
        ):
            logger.info(f"HANDLER: departments matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code:
                dept_course = kb.get("courses", {}).get("btech", {}).get(dept_code, {})
                full_name = dept_course.get("full_name", {}).get("value", "")
                intake = dept_course.get("intake", {}).get("value", "")
                if full_name:
                    result = f"{full_name} ({dept_code})"
                    if intake:
                        result += f" — Intake: {intake} seats"
                    return result
            # No specific department — list all B.Tech courses
            btech_courses = kb.get("courses", {}).get("btech", {})
            course_list = []
            for code, data in btech_courses.items():
                name = data.get("full_name", {}).get("value", "")
                intake = data.get("intake", {}).get("value", "")
                if name:
                    entry = f"{name} ({code})"
                    if intake:
                        entry += f" - {intake} seats"
                    course_list.append(entry)
            if course_list:
                return "BCREC offers B.Tech in: " + "; ".join(course_list) + "."
            return "BCREC offers B.Tech programs in CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, and Cyber Security."

        # --- Scholarship ---
        if re.search(r"\bscholarship", q):
            logger.info(f"HANDLER: scholarship matched for query='{q[:60]}'")
            schemes = kb.get("scholarships", {}).get("schemes", {})
            names = []
            for key, sch in schemes.items():
                name = sch.get("name", {}).get("value", "")
                if name:
                    names.append(name)
            if names:
                merit = (
                    kb.get("scholarships", {})
                    .get("eligibility", {})
                    .get("merit", {})
                    .get("value", "")
                )
                means = (
                    kb.get("scholarships", {})
                    .get("eligibility", {})
                    .get("means", {})
                    .get("value", "")
                )
                return (
                    f"Scholarships available at BCREC include: {', '.join(names)}. "
                    f"Merit eligibility: {merit}. "
                    f"Means eligibility: {means}."
                )
            return self._lang_response_unknown(lang)
        # --- Counselling ---
        if re.search(r"\b(counselling|counseling)\b", q):
            logger.info(f"HANDLER: counselling matched for query='{q[:60]}'")
            counselling = kb.get("admission", {}).get("counseling", {}).get("value", "")
            if counselling:
                return f"Admission counselling for BCREC is conducted through {counselling}."
            return self._lang_response_unknown(lang)

        # --- Eligibility based on marks/percentage ---
        if re.search(r"\b(eligibility|eligible|marks?|percentage|qualif)\b", q):
            logger.info(f"HANDLER: eligibility matched for query='{q[:60]}'")
            adm = kb.get("admission", {})
            eligibility = adm.get("eligibility", {}).get("btech", {}).get("value", "")
            entrance = adm.get("eligibility", {}).get("entrance", {}).get("value", "")
            if eligibility:
                return (
                    f"Eligibility for B.Tech admission: {eligibility}. Entrance exam: {entrance}."
                )
            return self._lang_response_unknown(lang)

        # --- Campus visit ---
        if re.search(r"\bcampus\s*visit\b|\bvisit\s*campus\b|\btour\b", q):
            logger.info(f"HANDLER: campus_visit matched for query='{q[:60]}'")
            return (
                "You are welcome to visit the BCREC campus. "
                "College timings are Monday to Friday, 10:00 AM to 5:30 PM. "
                "Please call 0343-2501353 to schedule a visit."
            )

        return None

    # -----------------------------------------------------------------------
    # Task 4 — Fuzzy Name Resolution for Faculty
    # -----------------------------------------------------------------------
    _FACULTY_ALIASES: Dict[str, str] = {
        "chandan bandopadhyay": "Dr. Chandan Bandyopadhyay",
        "chandan bandyopadhyay": "Dr. Chandan Bandyopadhyay",
        "chandan bandopaddhyay": "Dr. Chandan Bandyopadhyay",
        "chandan": "Dr. Chandan Bandyopadhyay",
        "dr chandan": "Dr. Chandan Bandyopadhyay",
        "dr. chandan": "Dr. Chandan Bandyopadhyay",
        "pabitra dey": "Dr. Pabitra Kumar Dey",
        "pabitra kumar dey": "Dr. Pabitra Kumar Dey",
        "dr pabitra": "Dr. Pabitra Kumar Dey",
        "dr. pabitra": "Dr. Pabitra Kumar Dey",
        "dinesh pradhan": "Dr. Dinesh Kumar Pradhan",
        "dinesh kumar pradhan": "Dr. Dinesh Kumar Pradhan",
        "dr dinesh": "Dr. Dinesh Kumar Pradhan",
        "mrinmoy chakraborty": "Dr. Mrinmoy Chakraborty",
        "dr mrinmoy": "Dr. Mrinmoy Chakraborty",
        "shibendu mahata": "Dr. Shibendu Mahata",
        "dr shibendu": "Dr. Shibendu Mahata",
        "sanjay sengupta": "Dr. Sanjay Sengupta",
        "dr sanjay sengupta": "Dr. Sanjay Sengupta",
        "poulomi mukherjee": "Dr. Poulomi Mukherjee Tewari",
        "poulomi tewari": "Dr. Poulomi Mukherjee Tewari",
        "dr poulomi": "Dr. Poulomi Mukherjee Tewari",
        "gour sundar mitra thakur": "Dr. Gour Sundar Mitra Thakur",
        "gour mitra thakur": "Dr. Gour Sundar Mitra Thakur",
        "dr gour": "Dr. Gour Sundar Mitra Thakur",
        "chandan chattoraj": "Dr. Chandan Chattoraj",
        "dr chandan chattoraj": "Dr. Chandan Chattoraj",
        "sanjay pawar": "Dr. Sanjay S. Pawar",
        "dr sanjay pawar": "Dr. Sanjay S. Pawar",
        "sanjoy pawar": "Dr. Sanjay S. Pawar",
    }

    def _build_faculty_index(self, kb: dict) -> list[tuple[str, str, str]]:
        """Build a list of (normalized_name, display_name, dept) from canonical KB."""
        idx = []
        depts = kb.get("departments", {})
        for code, data in depts.items():
            hod = data.get("hod", {})
            name = hod.get("name", {}).get("value", "")
            if name:
                idx.append((name.lower(), name, code))
        # Principal & VP
        principal = kb.get("principal", {}).get("name", {}).get("value", "")
        vp = kb.get("vice_principal", {}).get("name", {}).get("value", "")
        if principal:
            idx.append((principal.lower(), principal, "Principal"))
        if vp:
            idx.append((vp.lower(), vp, "Vice Principal"))
        return idx

    def _resolve_faculty_name(self, query: str, kb: dict) -> str | None:
        """Try to resolve a faculty/staff name in the query using exact match,
        alias table, and fuzzy matching."""
        q = query.strip().lower()

        # 1. Check aliases first (common mispronunciations)
        for alias, canonical in self._FACULTY_ALIASES.items():
            if alias in q:
                # Find the department for this faculty member
                dept_name = ""
                depts = kb.get("departments", {})
                for code, data in depts.items():
                    hod = data.get("hod", {})
                    name = hod.get("name", {}).get("value", "").lower()
                    if name and canonical.lower() in name:
                        dept_name = f" (HOD of {code})"
                        break
                if "principal" in canonical.lower():
                    dept_name = " (Principal, BCREC)"
                return f"Did you mean {canonical}{dept_name}?"

        # 2. Build faculty index and try difflib fuzzy matching
        faculty_idx = self._build_faculty_index(kb)
        if not faculty_idx:
            return None

        # Extract name-like tokens from query (remove known non-name words)
        stop_words = {
            "who",
            "is",
            "the",
            "of",
            "tell",
            "me",
            "about",
            "what",
            "name",
            "professor",
            "faculty",
            "teacher",
            "sir",
            "madam",
            "hod",
            "head",
            "department",
            "in",
            "please",
            "call",
            "contact",
        }
        tokens = []
        for w in q.split():
            w_clean = w.strip(".,!?;:")
            if w_clean not in stop_words and len(w_clean) > 2:
                tokens.append(w_clean)
        if not tokens:
            return None

        query_names = [" ".join(tokens)]
        # Also try individual significant tokens
        for t in tokens:
            if t not in ("dr", "prof", "mr", "mrs", "ms"):
                query_names.append(t)

        best_match = None
        best_score = 0
        best_display = ""
        best_dept = ""

        for norm_name, display_name, dept_code in faculty_idx:
            for qn in query_names:
                score = difflib.SequenceMatcher(None, qn, norm_name).ratio()
                # Also check if query name is a substring of the faculty name
                if qn in norm_name:
                    score = max(score, 0.8)
                if score > best_score:
                    best_score = score
                    best_match = norm_name
                    best_display = display_name
                    best_dept = dept_code
                elif score == best_score and dept_code == "Principal":
                    best_match = norm_name
                    best_display = display_name
                    best_dept = dept_code

        if best_score >= 0.7:
            dept_suffix = f" ({best_dept})" if best_dept else ""
            if best_score < 0.85:
                return f"Did you mean {best_display}{dept_suffix}?"
            return f"{best_display}{dept_suffix}."
        if best_score >= 0.5:
            return f"Did you mean {best_display}?"
        return None

    # -----------------------------------------------------------------------
    # Task 5 — Better Question Intent Detection (placement eligibility)
    # -----------------------------------------------------------------------
    def _detect_placement_eligibility_intent(self, query: str) -> bool:
        """Detect if the query is about placement eligibility despite not
        using explicit eligibility keywords."""
        q = query.strip().lower()
        # "If I don't study, will I get placement?"
        # "Without studying can I get placed?"
        # "Fail in exam placement?"
        # These are NOT about attendance — they're about placement criteria.
        patterns = [
            r"if\s+i\s+(don't|do not|not|never)\s+(study|read|attend)",
            r"(without|no|not)\s+(studying|reading|attending)",
            r"(fail|failed|failing).*(placement|job|placed)",
            r"(backlog|arrear|supply).*(placement|job)",
            r"(placement|job|placed).*(without|no|not).*(study|mark|grade)",
        ]
        return any(re.search(p, q) for p in patterns)

    # -----------------------------------------------------------------------
    # Task 6 — Structured Arithmetic
    # -----------------------------------------------------------------------
    def _calculate_total_fees(self, dept_code: str, lang: str) -> str | None:
        """Calculate total fee for a department programmatically."""
        if dept_code.upper() in FEE_GROUP_MAP:
            total, admission, per_sem = FEE_GROUP_MAP[dept_code.upper()]
            return (
                f"The total fee for {dept_code.upper()} is "
                f"{self._format_inr(total, lang)}. "
                f"This includes an admission fee of {self._format_inr(admission, lang)} "
                f"and per semester fee of {self._format_inr(per_sem, lang)}."
            )
        return None

    def _calculate_semester_fees(self, dept_code: str, lang: str) -> str | None:
        """Calculate per-semester fee."""
        if dept_code.upper() in FEE_GROUP_MAP:
            total, admission, per_sem = FEE_GROUP_MAP[dept_code.upper()]
            if per_sem > 0:
                return (
                    f"The semester fee for {dept_code.upper()} is "
                    f"{self._format_inr(per_sem, lang)}."
                )
            return (
                f"The total fee for {dept_code.upper()} is "
                f"{self._format_inr(total, lang)}. "
                f"Contact college for semester breakdown."
            )
        return None

    def _calculate_seat_total(self, kb: dict) -> str | None:
        """Calculate total B.Tech seats across all departments."""
        btech = kb.get("courses", {}).get("btech", {})
        total = 0
        counts = []
        for code, data in btech.items():
            if isinstance(data, dict):
                intake = data.get("intake", {})
                val = intake.get("value", 0)
                if isinstance(val, (int, float)):
                    total += int(val)
                    counts.append(f"{code}: {int(val)}")
        if total > 0:
            return (
                f"Total B.Tech seats across all departments: {total}. "
                + "; ".join(counts[:5])
                + "."
            )
        return None

    def _detect_on_topic_arithmetic(self, query: str) -> bool:
        """Detect queries that should be answered with arithmetic instead of LLM."""
        q = query.strip().lower()
        patterns = [
            r"total\s+(fee|fees|seats|intake|amount)",
            r"(fee|fees|seat|seats|intake)\s*(total|\+sum)",
            r"semester\s*(fee|fees|wise)",
            r"per\s*semester",
            r"overall\s+(placement|placed|percentage)",
            r"sum\s+of",
            r"add\s+(all|up)",
        ]
        return any(re.search(p, q) for p in patterns)

    # -----------------------------------------------------------------------
    # Task 3 — Conversation Replay (differentiated)
    # -----------------------------------------------------------------------
    def _detect_repeat_conversation_intent(self, query: str) -> str | None:
        """Detect what kind of repeat the user wants.
        Returns: 'last' for last response, 'all' for full recent conversation,
                 None if not a repeat request."""
        q = query.strip().lower()
        # "Repeat everything" / "repeat all" / "tell me everything again"
        if re.search(r"repeat\s+(everything|all|full|whole|entire)", q):
            return "all"
        if re.search(r"tell\s+(me\s+)?everything\s+(again|once more)?", q):
            return "all"
        if re.search(r"say\s+(everything|it\s+all)", q):
            return "all"
        if re.search(r"(full|whole)\s+(conversation|chat|discussion)", q):
            return "all"
        return None

    def _repeat_recent_conversation(self, history: List[Dict]) -> str | None:
        """Return the last few assistant responses (up to 3) joined together."""
        responses = []
        for turn in reversed(history):
            if turn.get("role") == "assistant":
                content = turn.get("content", "").strip()
                if content:
                    responses.append(content)
            if len(responses) >= 3:
                break
        if responses:
            return " ".join(reversed(responses))
        return None

    # -----------------------------------------------------------------------
    # Task 7 — STT Recovery (noisy/garbage transcript detection)
    # -----------------------------------------------------------------------
    def _detect_noisy_transcript(self, query: str) -> bool:
        """Detect low-quality transcripts with repeated garbage tokens."""
        q = query.strip()
        if not q or len(q.split()) < 2:
            return False

        # 1. Check for repeated single-character tokens (STT noise)
        tokens = q.split()
        single_char_count = sum(1 for t in tokens if len(t) == 1)
        if single_char_count >= len(tokens) * 0.5 and len(tokens) >= 3:
            return True

        # 2. Check for repeated identical tokens (stuttering/stammering in STT)
        if len(tokens) >= 4:
            unique = set(t.lower() for t in tokens)
            if len(unique) <= 2:
                return True

        # 3. Check for very long runs of non-alphabetic characters
        non_alpha_ratio = sum(1 for c in q if not c.isalpha() and not c.isspace()) / max(len(q), 1)
        if non_alpha_ratio > 0.5 and len(q) > 5:
            return True

        # 4. Check for repeated substrings (ah ah ah, um um um)
        if len(tokens) >= 3:
            for i in range(len(tokens) - 2):
                if tokens[i].lower() == tokens[i + 1].lower() == tokens[i + 2].lower():
                    return True

        return False

    # -----------------------------------------------------------------------
    # Task 2 — Unknown Data Policy response
    # -----------------------------------------------------------------------
    def _structured_unknown_fallback(self, lang: str) -> str:
        """Return a language-appropriate 'could not find verified info' response."""
        if lang == "hi":
            return UNKNOWN_INFO_RESPONSE_HI
        if lang == "bn":
            return UNKNOWN_INFO_RESPONSE_BN
        return UNKNOWN_INFO_RESPONSE_EN

    # -----------------------------------------------------------------------
    # Session memory (in-memory, clears on restart)
    # -----------------------------------------------------------------------
    def _get_session_history(self, session_id: str) -> List[Dict]:
        """Get conversation history for a session. Returns empty list if new session."""
        return self._sessions.get(session_id, [])

    def _append_session_turn(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        """Store a user+assistant turn in the session's in-memory history."""
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append({"role": "user", "content": user_msg})
        self._sessions[session_id].append({"role": "assistant", "content": assistant_msg})
        # Keep last 12 turns to prevent unbounded growth
        if len(self._sessions[session_id]) > 12:
            self._sessions[session_id] = self._sessions[session_id][-12:]

    def clear_session(self, session_id: str) -> None:
        """Clear a session's memory and language state. Called when session ends."""
        self._sessions.pop(session_id, None)
        self._session_langs.pop(session_id, None)

    # -----------------------------------------------------------------------
    # Phase 0 — Hallucination guard
    # -----------------------------------------------------------------------
    def _should_validate(self, query: str) -> bool:
        """Only validate on high-stakes topics (fees, names, contact, etc.)."""
        if not HALLUCINATION_GUARD_ENABLED:
            return False
        q = query.lower()
        return any(topic in q for topic in VALIDATED_TOPICS)

    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract verifiable entities from the LLM answer.
        Returns: {"numbers": [...], "names": [...], "phone_like": [...]}
        """
        entities: Dict[str, List[str]] = {
            "numbers": [],
            "names": [],
            "phone_like": [],
        }

        # 1) Numbers (≥3 digit) — likely fee amounts, intakes, cutoffs
        #    E.g. "598300", "5,98,300", "180" — but NOT "93.6" (decimal)
        for m in re.finditer(r"\b\d[\d,]{2,}\b", text):
            raw = m.group(0)
            # Skip if this number is part of a percentage (e.g., 80.62%)
            end_pos = m.end()
            if end_pos < len(text) and text[end_pos] == "%":
                continue
            num = raw.replace(",", "")
            if num.isdigit() and len(num) >= 3:
                entities["numbers"].append(num)

        # 2) Percentages like "90%", "85%+"
        for m in re.finditer(r"\b\d{1,3}\s*%(?:\+)?", text):
            entities["numbers"].append(m.group(0).strip().replace("+", ""))

        # 3) Phone-like numbers (10+ digits possibly with hyphens/spaces)
        for m in re.finditer(r"\b\d{4}[\s\-]?\d{3,7}\b", text):
            entities["phone_like"].append(re.sub(r"[\s\-]", "", m.group(0)))

        # 4) Proper nouns / titles: "Dr.", "Prof.", words starting with capital
        #    We only check KNOWN key names below — generic names create noise.
        #    So we leave this empty; number/phone checks are stronger signals.
        return entities

    def _context_contains(self, context: str, entity: str) -> bool:
        """Check if entity appears in context (normalize Unicode digits to ASCII)."""
        if not entity:
            return True

        def normalize_digits(text: str) -> str:
            """Convert all Unicode digit scripts to ASCII."""
            result = text
            bengali_digits = "০১২৩৪৫৬৭৮৯"
            devanagari_digits = "०१२३४५६७८९"
            for i in range(10):
                result = result.replace(bengali_digits[i], str(i))
                result = result.replace(devanagari_digits[i], str(i))
            return result

        ctx_norm = normalize_digits(context).replace(",", "").replace(" ", "").lower()
        ent_norm = normalize_digits(entity).replace(",", "").replace(" ", "").lower()
        return ent_norm in ctx_norm

    def _validate_answer(self, answer: str, context: str, query: str) -> tuple[bool, str]:
        """
        Validate that critical entities in `answer` appear in the context.
        Skips numbers that appear in the user's query (they provided them).
        Skips low-risk queries like placement rate (college-wide stat, never hallucinated).
        Returns (is_valid, reason_if_invalid).
        """
        if not self._should_validate(query):
            return True, ""

        # Exempt only general placement queries without numbers — ones asking about rate/companies
        query_lower = query.lower()
        has_number = bool(re.search(r"\d", query_lower))
        if not has_number and any(
            word in query_lower for word in ["placement", "प्लेसमेंट", "প্লেসমেন্ট"]
        ):
            return True, ""

        entities = self._extract_entities(answer)

        # Only check numbers and phone-like strings — these are the high-signal
        # hallucination markers. Names are too noisy to check blindly.
        critical = entities["numbers"] + entities["phone_like"]
        if not critical:
            return True, ""

        # Extract user-provided numbers from the query — skip those
        query_entities = self._extract_entities(query)
        query_numbers = set(query_entities["numbers"] + query_entities["phone_like"])

        missing = [
            e for e in critical if e not in query_numbers and not self._context_contains(context, e)
        ]
        if missing:
            return False, f"entities not found in context: {missing[:5]}"
        return True, ""

    def _prepare_for_tts(self, text: str, lang: str) -> str:
        """Normalize acronyms for TTS, then catch remaining digits the LLM missed."""
        try:
            from app.utils.voice_utils import clean_for_voice

            text = clean_for_voice(text)
        except Exception:
            pass
        text = normalize_for_tts(text)
        return text

    def _safe_fallback(self, lang: str) -> str:
        """Return a polite, language-appropriate fallback message."""
        if lang == "hi":
            return FALLBACK_ANSWER_HI
        if lang == "bn":
            return FALLBACK_ANSWER_BN
        return FALLBACK_ANSWER_EN

    def _lang_response_unknown(self, lang: str) -> str:
        return {
            "hi": UNKNOWN_INFO_RESPONSE_HI,
            "bn": UNKNOWN_INFO_RESPONSE_BN,
        }.get(lang, UNKNOWN_INFO_RESPONSE_EN)

    def _lang_hod_unknown(self, lang: str) -> str:
        return {
            "hi": _HOD_UNKNOWN_HI,
            "bn": _HOD_UNKNOWN_BN,
        }.get(lang, _HOD_UNKNOWN_EN)

    def _log_gap(self, query: str, lang: str, reason: str) -> None:
        """Log an unanswered query to knowledge_gaps.json so admins know what to add."""
        import datetime

        try:
            path = _KNOWLEDGE_GAPS_PATH
            gaps = []
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    gaps = json.load(f)
            gaps.append(
                {
                    "query": query,
                    "lang": lang,
                    "reason": reason,
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "count": 1,
                }
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(gaps, f, indent=2, ensure_ascii=False)
            logger.info(f"Knowledge gap logged: '{query[:60]}' ({reason})")
        except Exception as e:
            logger.debug(f"Failed to log knowledge gap: {e}")

    async def generate_response(self, query: str, session_id: str = "default") -> Dict[str, Any]:
        """Main entry point. Uses in-memory session memory for conversation context.
        Returns dict with 'answer', 'voice_text', 'source'."""
        if not self.client:
            return {
                "answer": "Service unavailable. Please call 0343-2501353.",
                "voice_text": "",
                "source": "error",
            }

        start = time.time()
        telemetry = get_telemetry()
        t_request_start = start
        t_api_sent = 0.0
        t_first_token = 0.0
        t_last_token = 0.0
        t_post_start = 0.0
        t_post_end = 0.0
        lifecycle_tracked = False
        from app.utils.stage_profiler import StageProfiler

        _profiler = StageProfiler()
        _profiler.start()
        try:
            history = self._get_session_history(session_id)
            turn_number = len(history) // 2 + 1

            # 0. Normalization — STT recovery and entity resolution
            _profiler.mark("normalization")
            norm_log = normalize_query(query)
            if norm_log.changes:
                logger.info(
                    f"[{session_id}] Query normalized: '{query[:60]}' -> '{norm_log.normalized_text[:60]}'"
                )
                query = norm_log.normalized_text

            # 0.5 Yes/no continuation — "yes"/"no" after "Would you like" clarification re-routes
            # to the ambiguous word that triggered the clarification prompt
            if history:
                q_lower = query.strip().lower()
                is_yes = q_lower in ("yes", "yeah", "yep", "हाँ", "जी", "जी हाँ", "হ্যাঁ", "জী", "জী হ্যাঁ")
                is_no = q_lower in ("no", "nah", "nope", "नहीं", "जी नहीं", "না", "জী না")
                if is_yes or is_no:
                    last_assistant = self._get_last_assistant_response(history)
                    if last_assistant and "would you like" in last_assistant.lower():
                        if is_yes:
                            last_user_q = self._get_last_user_question(history)
                            if last_user_q:
                                logger.info(
                                    f"[{session_id}] YES/NO: 'yes' after clarification — "
                                    f"re-routing to last user question: '{last_user_q[:60]}'"
                                )
                                query = last_user_q
                                self._skip_ambiguous_validation_sessions.add(session_id)
                        else:
                            lang = self._session_langs.get(session_id, "en")
                            ack_map = {"hi": ACKNOWLEDGMENT_HI, "bn": ACKNOWLEDGMENT_BN}
                            ack = ack_map.get(lang, ACKNOWLEDGMENT_EN)
                            logger.info(
                                f"[{session_id}] YES/NO: 'no' after clarification — acknowledgment"
                            )
                            self._append_session_turn(session_id, query, ack)
                            return {
                                "answer": ack,
                                "voice_text": ack,
                                "source": "yes_no_continuation",
                                "model": "none",
                                "latency_ms": round((time.time() - start) * 1000),
                                "hallucination_validated": True,
                                "tokens": {"prompt": 0, "completion": 0},
                                "cache_hit": False,
                            }

            # 0.75 Transcript validation — reject STT noise / fragments before RAG+LLM
            validation_result = self._validate_transcript(query, session_id)
            if validation_result is not None:
                logger.info(
                    f"[{session_id}] Transcript rejected: '{query[:80]}' "
                    f"→ clarification: '{validation_result[:60]}'"
                )
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    transcript_validation=validation_result,
                    detected_intent="clarification",
                )
                self._append_session_turn(session_id, query, validation_result)
                return {
                    "answer": validation_result,
                    "voice_text": validation_result,
                    "source": "transcript_clarification",
                    "model": "none",
                    "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True,
                    "tokens": {"prompt": 0, "completion": 0},
                    "cache_hit": False,
                }

            # 0.5 STT noise detection — catch garbage/repeated tokens before processing
            if self._detect_noisy_transcript(query):
                lang = self._session_langs.get(session_id, "en")
                clarify = {
                    "en": CLARIFY_REPEAT_EN,
                    "hi": CLARIFY_REPEAT_HI,
                    "bn": CLARIFY_REPEAT_BN,
                }.get(lang, CLARIFY_REPEAT_EN)
                logger.info(f"[{session_id}] Noisy transcript detected: '{query[:80]}'")
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    transcript_validation=clarify,
                    detected_intent="transcript_noise",
                )
                self._append_session_turn(session_id, query, clarify)
                return {
                    "answer": clarify,
                    "voice_text": clarify,
                    "source": "transcript_noise",
                    "model": "none",
                    "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True,
                    "tokens": {"prompt": 0, "completion": 0},
                    "cache_hit": False,
                }

            # 1. Resolve language using persistent session state
            lang = self._resolve_language(session_id, query)
            _profiler.mark("lang_detect")

            # ── DEMO_SAFEPOINT: Pre-processing ──
            if _sp_enabled():
                sp_result = await _sp_safe_pre(self, query, session_id, lang)
                if sp_result:
                    logger.info(
                        f"[{session_id}] SAFEPOINT pre-processing intercepted: {sp_result.get('source', '?')}"
                    )
                    return sp_result
            # ── End DEMO_SAFEPOINT pre-processing ──

            # Track language switches
            prev_lang = self._session_langs.get(session_id, "en")
            if lang != prev_lang:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="LANGUAGE_SWITCH",
                    details={"from": prev_lang, "to": lang},
                )

            # If user explicitly switched language, re-run the previous question
            is_switch, forced_lang = self._is_lang_switch(query)
            if is_switch and forced_lang and history:
                prev_question = self._get_last_user_question(history[:-1] if history else [])
                if prev_question:
                    query = prev_question
                    logger.info(
                        f"Language switch detected → re-running '{query[:50]}' in lang={forced_lang}"
                    )

            # 2. Deterministic greeting
            if self._is_greeting(query):
                greeting_answer = {
                    "en": "Hello. How can I help you with admissions, fees, courses, or hostel details?",
                    "hi": "नमस्ते। मैं admissions, fees, courses, और hostel details में मदद कर सकता हूँ।",
                    "bn": "হ্যালো। আমি admissions, fees, courses, আর hostel details নিয়ে সাহায্য করতে পারি।",
                }.get(lang, "Hello. How can I help you?")

                latency_ms = round((time.time() - start) * 1000)
                logger.info(f"GREETING HIT (lang={lang}, {latency_ms}ms): '{query[:60]}'")
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    detected_language=lang,
                    detected_intent="greeting",
                )
                self._append_session_turn(session_id, query, greeting_answer)
                return {
                    "answer": greeting_answer,
                    "voice_text": greeting_answer,
                    "source": "greeting_deterministic",
                    "model": "none",
                    "latency_ms": latency_ms,
                    "hallucination_validated": True,
                    "tokens": {"prompt": 0, "completion": 0},
                    "cache_hit": False,
                }

            # 2.25 Out-of-domain detection — block clearly off-topic queries before retrieval/LLM
            if self._is_out_of_domain(query):
                ood_response = {
                    "en": OUT_OF_DOMAIN_RESPONSE_EN,
                    "hi": OUT_OF_DOMAIN_RESPONSE_HI,
                    "bn": OUT_OF_DOMAIN_RESPONSE_BN,
                }.get(lang, OUT_OF_DOMAIN_RESPONSE_EN)

                logger.info(f"OUT-OF-DOMAIN BLOCKED (lang={lang}): '{query[:80]}'")
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="OUT_OF_DOMAIN",
                    details={"query": query[:100], "lang": lang},
                )
                self._append_session_turn(session_id, query, ood_response)
                return {
                    "answer": ood_response,
                    "voice_text": ood_response,
                    "source": "out_of_domain",
                    "model": "none",
                    "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True,
                    "tokens": {"prompt": 0, "completion": 0},
                    "cache_hit": False,
                }

            # 2.5 Repeat intent — return last assistant response without RAG
            if self._detect_repeat_intent(query):
                last_response = self._get_last_assistant_response(history)
                if last_response:
                    logger.info(
                        f"REPEAT HIT: returning last assistant response ({len(last_response)} chars)"
                    )
                    telemetry.log_special_event(
                        session_id,
                        turn_number=turn_number,
                        event_type="REPEAT_REQUEST",
                        details={"replayed_response_length": len(last_response)},
                    )
                    telemetry.log_turn_input(
                        session_id,
                        turn_number=turn_number,
                        raw_transcript=query,
                        detected_language=lang,
                        detected_intent="repeat",
                    )
                    self._append_session_turn(session_id, query, last_response)
                    return {
                        "answer": last_response,
                        "voice_text": last_response,
                        "source": "repeat_replay",
                        "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0},
                        "cache_hit": False,
                    }
                logger.info("REPEAT HIT but no history — falling through to normal flow")

            # 2.65 Placement eligibility intent detection (Task 5)
            if self._detect_placement_eligibility_intent(query):
                placement_info = self._structured_lookup("placement eligibility", lang)
                if placement_info:
                    logger.info(
                        f"[{session_id}] PLACEMENT ELIGIBILITY intent detected: '{query[:80]}'"
                    )
                    self._append_session_turn(session_id, query, placement_info)
                    return {
                        "answer": placement_info,
                        "voice_text": placement_info,
                        "source": "structured_placement_eligibility",
                        "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0},
                        "cache_hit": False,
                    }
                else:
                    # Fallback: return general placement info
                    fallback = (
                        "Placement is based on your academic performance, "
                        "technical skills, and aptitude. Regular study and "
                        "skill development are recommended. Contact the T&P "
                        "cell for specific eligibility criteria."
                    )
                    self._append_session_turn(session_id, query, fallback)
                    return {
                        "answer": fallback,
                        "voice_text": fallback,
                        "source": "placement_eligibility_fallback",
                        "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0},
                        "cache_hit": False,
                    }

            # 2.7 Differentiated conversation replay (Task 3)
            repeat_type = self._detect_repeat_conversation_intent(query)
            if repeat_type == "all":
                replay = self._repeat_recent_conversation(history)
                if replay:
                    logger.info(
                        f"[{session_id}] REPEAT ALL: returning recent conversation ({len(replay)} chars)"
                    )
                    telemetry.log_special_event(
                        session_id,
                        turn_number=turn_number,
                        event_type="REPEAT_CONVERSATION",
                        details={"replayed_length": len(replay)},
                    )
                    self._append_session_turn(session_id, query, replay)
                    return {
                        "answer": replay,
                        "voice_text": replay,
                        "source": "repeat_conversation_replay",
                        "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0},
                        "cache_hit": False,
                    }

            # 2.75 Expand short follow-up queries for better retrieval context
            retrieval_query, expand_debug = self._expand_follow_up_query(query, history, session_id)
            is_follow_up = retrieval_query != query.strip()
            _profiler.mark("followup_expand")

            # 2.8 Structured knowledge lookup (Task 1, 6) — before retrieval
            if self._detect_on_topic_arithmetic(query) or True:
                # Try arithmetic lookups first (Task 6)
                dept_code = self._extract_dept_code(retrieval_query)
                if dept_code:
                    if re.search(
                        r"\bsemester\s*fee\b|\bper\s*semester\b|\bsem\s*fee\b", retrieval_query
                    ):
                        arith_result = self._calculate_semester_fees(dept_code, lang)
                        if arith_result:
                            logger.info(
                                f"[{session_id}] STRUCTURED ARITHMETIC: {arith_result[:60]}"
                            )
                            self._append_session_turn(session_id, query, arith_result)
                            return {
                                "answer": arith_result,
                                "voice_text": arith_result,
                                "source": "structured_arithmetic",
                                "model": "none",
                                "latency_ms": round((time.time() - start) * 1000),
                                "hallucination_validated": True,
                                "tokens": {"prompt": 0, "completion": 0},
                                "cache_hit": False,
                            }
                    if re.search(r"\btotal\s*(fee|fees)\b|\bfee\s*total\b", retrieval_query):
                        arith_result = self._calculate_total_fees(dept_code, lang)
                        if arith_result:
                            logger.info(
                                f"[{session_id}] STRUCTURED ARITHMETIC: {arith_result[:60]}"
                            )
                            self._append_session_turn(session_id, query, arith_result)
                            return {
                                "answer": arith_result,
                                "voice_text": arith_result,
                                "source": "structured_arithmetic",
                                "model": "none",
                                "latency_ms": round((time.time() - start) * 1000),
                                "hallucination_validated": True,
                                "tokens": {"prompt": 0, "completion": 0},
                                "cache_hit": False,
                            }
                    if re.search(
                        r"\b(seats|intake)\b.*\btotal\b|\btotal\b.*\b(seats|intake)\b",
                        retrieval_query,
                    ):
                        kb = self._read_canonical_kb()
                        seat_result = self._calculate_seat_total(kb)
                        if seat_result:
                            logger.info(
                                f"[{session_id}] STRUCTURED ARITHMETIC (seats): {seat_result[:60]}"
                            )
                            self._append_session_turn(session_id, query, seat_result)
                            return {
                                "answer": seat_result,
                                "voice_text": seat_result,
                                "source": "structured_arithmetic",
                                "model": "none",
                                "latency_ms": round((time.time() - start) * 1000),
                                "hallucination_validated": True,
                                "tokens": {"prompt": 0, "completion": 0},
                                "cache_hit": False,
                            }

                # Try general structured lookup (Task 1) — with multi-intent support
                intents = self._split_multi_intent(retrieval_query)
                if len(intents) > 1:
                    results = []
                    for intent in intents:
                        r = self._structured_lookup(intent, lang)
                        if r:
                            results.append(r)
                    if len(results) >= 2:
                        combined = " ".join(results)
                        logger.info(
                            f"[{session_id}] MULTI-INTENT LOOKUP: {len(results)} parts from "
                            f"'{retrieval_query[:60]}'"
                        )
                        telemetry.log_special_event(
                            session_id,
                            turn_number=turn_number,
                            event_type="MULTI_INTENT_LOOKUP",
                            details={"parts": len(results), "query": retrieval_query[:80]},
                        )
                        self._append_session_turn(session_id, query, combined)
                        return {
                            "answer": combined,
                            "voice_text": combined,
                            "source": "structured_lookup",
                            "model": "none",
                            "latency_ms": round((time.time() - start) * 1000),
                            "hallucination_validated": True,
                            "tokens": {"prompt": 0, "completion": 0},
                            "cache_hit": False,
                        }

                logger.info(
                    f"[{session_id}] RAW='{query[:80]}' | EXPANDED='{retrieval_query[:80]}'"
                )
                structured_result = self._structured_lookup(retrieval_query, lang)
                if structured_result:
                    # Update structured session state for follow-up expansion
                    intent = self._detect_structured_intent(retrieval_query)
                    if intent:
                        self._session_intents[session_id] = intent
                    dept_code = self._extract_dept_code(retrieval_query)
                    if dept_code:
                        self._session_departments[session_id] = dept_code
                    logger.info(
                        f"[{session_id}] STRUCTURED LOOKUP HIT: '{retrieval_query[:60]}' "
                        f"-> '{structured_result[:60]}'"
                    )
                    telemetry.log_special_event(
                        session_id,
                        turn_number=turn_number,
                        event_type="STRUCTURED_LOOKUP",
                        details={"query": retrieval_query[:80], "source": "canonical_kb"},
                    )
                    self._append_session_turn(session_id, query, structured_result)
                    return {
                        "answer": structured_result,
                        "voice_text": structured_result,
                        "source": "structured_lookup",
                        "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0},
                        "cache_hit": False,
                    }

            # 3. Retrieve context (returns context string + confidence score)
            _profiler.mark("structured_done")
            t_retrieval_start = time.time()
            context, confidence = self._retrieve_context(retrieval_query)
            t_retrieval_ms = (time.time() - t_retrieval_start) * 1000
            _profiler.mark("retrieval_done")

            logger.debug(
                f"[{session_id}] RETRIEVED confidence={confidence:.4f} "
                f"context_len={len(context)} threshold={RETRIEVAL_CONFIDENCE_THRESHOLD}"
            )

            # Log retrieval telemetry
            rd = getattr(self, "_last_retrieval_data", {})
            is_empty_context = not context or confidence == 0.0
            telemetry.log_retrieval(
                session_id,
                turn_number=turn_number,
                retrieval_query=retrieval_query,
                confidence=confidence,
                latency_ms=t_retrieval_ms,
                top_chunks=rd.get("top_10_raw", []),
                chunks_passed=rd.get("chunks_passed", 0),
                chunks_discarded=rd.get("chunks_discarded", []),
            )

            # Log follow-up detection
            if is_follow_up:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="FOLLOW_UP_QUERY",
                    details={"original": query, "expanded": retrieval_query},
                )

            if is_empty_context:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="EMPTY_CONTEXT",
                    details={"confidence": confidence, "context_len": len(context)},
                )

            # Log turn input after all preprocessing
            telemetry.log_turn_input(
                session_id,
                turn_number=turn_number,
                raw_transcript=query,
                expanded_transcript=retrieval_query if is_follow_up else "",
                detected_language=lang,
                detected_intent="rag_query",
                follow_up_topic=query if is_follow_up else "",
            )

            # 3.5 Low-confidence retrieval guard — skip LLM when context is irrelevant
            low_confidence_triggered = bool(context and confidence < RETRIEVAL_CONFIDENCE_THRESHOLD)
            if low_confidence_triggered:
                logger.info(
                    f"Low confidence retrieval ({confidence:.3f}) for '{query[:60]}' — using fallback"
                )
                telemetry.log_validation(
                    session_id,
                    turn_number=turn_number,
                    confidence_score=confidence,
                    configured_threshold=RETRIEVAL_CONFIDENCE_THRESHOLD,
                    low_confidence_triggered=True,
                )
                fallback = self._safe_fallback(lang)
                self._log_gap(query, lang, f"low_confidence_retrieval_{confidence:.3f}")
                self._append_session_turn(session_id, query, fallback)
                return {
                    "answer": fallback,
                    "voice_text": fallback,
                    "source": "low_confidence_retrieval",
                    "model": "none",
                    "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True,
                    "tokens": {"prompt": 0, "completion": 0},
                    "cache_hit": False,
                }

            # 4. Cache lookup (skip for sessions with history)
            if self._cache is not None and not history:
                self._check_kb_changed()
                cache_key = self._cache_key(query, lang, context)
                cached = self._cache.get(cache_key)
                if cached is not None:
                    self._cache_stats["hits"] += 1
                    latency_ms = round((time.time() - start) * 1000)
                    logger.info(f"CACHE HIT (lang={lang}, {latency_ms}ms): '{query[:60]}'")
                    cached_out = dict(cached)
                    cached_out["latency_ms"] = latency_ms
                    cached_out["cache_hit"] = True
                    self._append_session_turn(session_id, query, cached_out["answer"])
                    return cached_out
                self._cache_stats["misses"] += 1

            # 5. Build messages with session history + context
            messages = self._build_messages(
                query=query, context=context, history=history, lang=lang
            )

            # Log prompt telemetry
            total_prompt = sum(len(m.get("content", "")) for m in messages)
            history_chars = sum(len(t.get("content", "")) for t in history[-10:])
            telemetry.log_prompt(
                session_id,
                turn_number=turn_number,
                total_prompt_chars=total_prompt,
                context_chars=len(context),
                history_chars=history_chars,
                history_turns=min(len(history), 10),
            )

            # 6. Call Groq with rate limiter + model fallback + circuit breaker
            completion = None
            used_model = self.model
            models_to_try = list(dict.fromkeys([self.model] + FALLBACK_MODELS))
            success = False

            for current_model in models_to_try:
                for attempt in range(3):
                    wait = self._rate_limiter.acquire()
                    if wait > 0:
                        logger.info(
                            f"Rate limiter: waiting {wait:.1f}s before calling {current_model}"
                        )
                        await asyncio.sleep(wait)

                    try:
                        t_api_sent = time.time()
                        if _sp_enabled():
                            try:
                                completion = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        self.client.chat.completions.create,
                                        model=current_model,
                                        messages=messages,
                                        temperature=0.3,
                                        max_tokens=self.max_tokens,
                                    ),
                                    timeout=6.0,
                                )
                            except asyncio.TimeoutError:
                                from .safe_point import FILLER_RESPONSES as _filler_responses

                                filler = random.choice(_filler_responses)
                                logger.warning(
                                    f"[{session_id}] LLM call timed out (>2s), using filler"
                                )
                                self._append_session_turn(session_id, query, filler)
                                return {
                                    "answer": filler,
                                    "voice_text": filler,
                                    "source": "timeout_filler",
                                    "model": "none",
                                    "latency_ms": round((time.time() - start) * 1000),
                                    "hallucination_validated": True,
                                    "tokens": {"prompt": 0, "completion": 0},
                                    "cache_hit": False,
                                }
                        else:
                            completion = self.client.chat.completions.create(
                                model=current_model,
                                messages=messages,
                                temperature=0.3,
                                max_tokens=self.max_tokens,
                            )
                        t_first_token = time.time()
                        t_last_token = t_first_token
                        self._rate_limiter.record_success()
                        used_model = current_model
                        success = True
                        break
                    except Exception as e:
                        error_str = str(e)
                        is_rate_limit = (
                            "429" in error_str
                            or "rate" in error_str.lower()
                            or "too many" in error_str.lower()
                        )
                        if is_rate_limit:
                            self._rate_limiter.record_429()
                            if attempt < 2:
                                backoff = min((2**attempt) + random.random(), MAX_BACKOFF_SEC)
                                logger.warning(
                                    f"Groq rate limited on {current_model} "
                                    f"(model {models_to_try.index(current_model) + 1}/{len(models_to_try)}, "
                                    f"attempt {attempt + 1}/3), "
                                    f"retrying in {backoff:.1f}s"
                                )
                                await asyncio.sleep(backoff)
                            else:
                                logger.warning(f"All retries exhausted for {current_model}")
                        else:
                            raise
                if success:
                    break
                if current_model != models_to_try[-1]:
                    logger.warning(
                        f"Switching model {current_model} -> {models_to_try[models_to_try.index(current_model) + 1]}"
                    )

            if not success:
                raise RuntimeError(f"All Groq models ({models_to_try}) rate limited after retries")
            t_llm_start = time.time()
            answer = completion.choices[0].message.content.strip()
            # Strip reasoning tags (e.g. <think>...</think>) from inference models
            import re as _re

            answer = _re.sub(r"<think>.*?</think>\s*", "", answer, flags=_re.DOTALL).strip()
            _profiler.mark("llm_response")

            # 6.5 Ensure concise response — cap at MAX_VOICE_RESPONSE_CHARS for voice
            # Uses character-based limit with sentence-boundary awareness.
            # Avoids sentence-splitting regex which breaks on "Dr. B.C. Roy" type abbreviations.
            if len(answer) > MAX_VOICE_RESPONSE_CHARS:
                truncated = answer[:MAX_VOICE_RESPONSE_CHARS]
                # Find the last sentence boundary before the limit
                last_period = max(truncated.rfind(". "), truncated.rfind("। "))
                if last_period > MAX_VOICE_RESPONSE_CHARS // 2:
                    answer = truncated[: last_period + 1]
                else:
                    answer = truncated.rsplit(" ", 1)[0] + "."
                logger.info(
                    f"Response length-capped {len(answer)}->{len(truncated)} chars: "
                    f"'{answer[:60]}...'"
                )

            # Token tracking
            prompt_tokens = 0
            completion_tokens = 0
            try:
                usage = getattr(completion, "usage", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            except Exception:
                pass
            latency_ms = round((time.time() - start) * 1000)

            # Log LLM completion telemetry
            telemetry.log_llm_complete(
                session_id,
                turn_number=turn_number,
                ttft_ms=0,
                completion_time_ms=(time.time() - t_llm_start) * 1000,
                response=answer,
                model=used_model,
                tokens_prompt=prompt_tokens,
                tokens_completion=completion_tokens,
                latency_ms=latency_ms,
            )

            # 7. Hallucination guard
            is_valid, reason = self._validate_answer(answer, context, query)
            hallucination_triggered = False
            if not is_valid:
                logger.warning(
                    f"PHASE 0 GUARD TRIPPED (lang={lang}, query='{query[:60]}'): {reason}. "
                    f"LLM said: '{answer[:80]}'"
                )
                self._log_gap(query, lang, f"hallucination_guard: {reason}")
                hallucination_triggered = True
                telemetry.log_quality_metrics(
                    session_id,
                    turn_number=turn_number,
                    hallucination_guard_triggered=True,
                )
                answer = self._safe_fallback(lang)

            t_post_start = time.time()

            # 7.5 Out-of-KB detection
            out_of_kb = False
            if is_valid and not self._is_greeting(query) and "0343-2501353" not in answer:
                a = answer.lower().strip()
                unknown_signals = (
                    a.startswith("i'm not ")
                    or a.startswith("i am not ")
                    or "no information" in a
                    or "not aware" in a
                    or "don't have" in a
                    or "does not contain" in a
                    or "context does not contain" in a
                    or "not found in" in a
                    or a.startswith("i'm afraid")
                    or a.startswith("i'm sorry")
                    or "unfortunately" in a
                    or "sorry, i" in a
                    or "beyond the context" in a
                    or "can't find" in a
                    or "cannot find" in a
                    or "cannot answer" in a
                    or "जानकारी नहीं" in a
                    or "पता नहीं" in a
                    or "জান নেই" in a
                    or "পাওয়া যায়নি" in a
                )
                if unknown_signals:
                    logger.warning(
                        f"OUT-OF-KB DETECTED (lang={lang}, query='{query[:60]}'): "
                        f"LLM said '{answer[:80]}' without phone → replacing with fallback"
                    )
                    self._log_gap(query, lang, "out_of_kb_deflection")
                    out_of_kb = True
                    telemetry.log_special_event(
                        session_id,
                        turn_number=turn_number,
                        event_type="OUT_OF_KB",
                        details={"answer": answer[:100]},
                    )
                    answer = self._safe_fallback(lang)

            # 8. Bengali normalization
            if lang == "bn":
                answer = answer.replace("রুপি", "টাকা").replace("টাকা.", "টাকা।")

            # 8.5 Prepare for TTS — catch remaining digits the LLM missed
            voice_text = self._prepare_for_tts(answer, lang)

            # Log validation telemetry
            telemetry.log_validation(
                session_id,
                turn_number=turn_number,
                confidence_score=confidence,
                configured_threshold=RETRIEVAL_CONFIDENCE_THRESHOLD,
                low_confidence_triggered=False,
                validation_result="out_of_kb" if out_of_kb else "ok",
                hallucination_guard_result="blocked" if not is_valid else "passed",
            )

            # Log voice output telemetry
            telemetry.log_voice_output(
                session_id, turn_number=turn_number, raw_text=answer, cleaned_text=voice_text
            )

            logger.info(
                f"Groq response ({lang}, {latency_ms}ms, validated={is_valid}, "
                f"tokens=in:{prompt_tokens}/out:{completion_tokens}): {answer[:80]}..."
            )

            response_payload: Dict[str, Any] = {
                "answer": answer,
                "voice_text": voice_text,
                "source": "groq_rag",
                "model": used_model,
                "latency_ms": latency_ms,
                "hallucination_validated": is_valid,
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                },
                "cache_hit": False,
            }

            # 10. Store in session memory
            self._append_session_turn(session_id, query, answer)

            # 11. Cache (only if no history, i.e. first turn)
            if self._cache is not None and is_valid and not history:
                try:
                    cache_key = self._cache_key(query, lang, context)
                    self._cache[cache_key] = response_payload
                except Exception as e:
                    logger.debug(f"Cache store failed: {e}")

            t_post_end = time.time()
            total_duration = (t_post_end - t_request_start) * 1000
            gen_duration = (t_last_token - t_api_sent) * 1000 if t_api_sent else 0
            post_duration = (t_post_end - t_post_start) * 1000
            tokens_sec = (
                (completion_tokens / max(gen_duration / 1000, 0.001))
                if completion_tokens > 0 and gen_duration > 0
                else 0
            )
            telemetry.log_llm_lifecycle(
                session_id,
                turn_number=turn_number,
                request_start=t_request_start,
                api_request_sent=t_api_sent,
                first_token_received=t_first_token,
                last_token_received=t_last_token,
                postprocessing_start=t_post_start,
                postprocessing_end=t_post_end,
                ttft_ms=(t_first_token - t_api_sent) * 1000 if t_api_sent else 0,
                generation_duration_ms=gen_duration,
                postprocessing_duration_ms=post_duration,
                total_llm_duration_ms=total_duration,
                output_tokens=completion_tokens,
                estimated_tokens_per_second=tokens_sec,
                streaming_duration_ms=0,
                model=used_model,
                tokens_prompt=prompt_tokens,
                tokens_completion=completion_tokens,
                response=answer,
            )

            # ── DEMO_SAFEPOINT: Post-processing ──
            if _sp_enabled():
                response_payload = _sp_post(self, query, response_payload, lang)
            # ── End DEMO_SAFEPOINT post-processing ──
            _profiler.mark("post_process")

            return response_payload

        except Exception as e:
            elapsed = round((time.time() - t_request_start) * 1000)
            telemetry.log_turn_error(
                session_id,
                turn_number=turn_number,
                exception=e,
                elapsed_ms=elapsed,
            )
            logger.error(f"Groq error ({elapsed}ms): {e}")
            answer = "I'm sorry for the inconvenience. Please call the college at 0343-2501353 for assistance."
            if _sp_enabled():
                answer = "I am sorry for the trouble. Please contact the admission office at 0343-2501353 and they will help you."
            return {
                "answer": answer,
                "voice_text": answer,
                "source": "error",
                "cache_hit": False,
            }
        finally:
            if _profiler._marks:
                _profiler.mark("pipeline_end")
                timing_lines = _profiler.report().split("\n")
                for line in timing_lines:
                    logger.info(f"[PERF {session_id}] {line}")

    async def stream_response(
        self,
        query: str,
        session_id: str = "default",
        conversation_history: Optional[List[Dict]] = None,
    ):
        """True streaming for low-latency telephony. Yields tokens immediately.
        Hallucination guard runs in background — logs violations but does NOT block.
        """
        t0 = time.time()
        t_request_start = t0
        telemetry = get_telemetry()
        if not self.async_client:
            yield "Service unavailable. Please call 0343-2501353."
            return

        try:
            history = (
                conversation_history
                if conversation_history is not None
                else self._get_session_history(session_id)
            )
            turn_number = len(history) // 2 + 1

            # 0. Normalization — STT recovery and entity resolution
            norm_log = normalize_query(query)
            if norm_log.changes:
                logger.info(
                    f"[{session_id}] Query normalized (stream): '{query[:60]}' -> '{norm_log.normalized_text[:60]}'"
                )
                query = norm_log.normalized_text

            # 0.5 Transcript validation — reject STT noise / fragments
            validation_result = self._validate_transcript(query, session_id)
            if validation_result is not None:
                logger.info(
                    f"[{session_id}] Transcript rejected (stream): '{query[:80]}' "
                    f"→ '{validation_result[:60]}'"
                )
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    transcript_validation=validation_result,
                    detected_intent="clarification",
                )
                for word in validation_result.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            # 0.5 STT noise detection (Task 7)
            if self._detect_noisy_transcript(query):
                lang = self._session_langs.get(session_id, "en")
                clarify = {
                    "en": CLARIFY_REPEAT_EN,
                    "hi": CLARIFY_REPEAT_HI,
                    "bn": CLARIFY_REPEAT_BN,
                }.get(lang, CLARIFY_REPEAT_EN)
                logger.info(f"[{session_id}] Noisy transcript (stream): '{query[:80]}'")
                for word in clarify.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            lang = self._resolve_language(session_id, query)

            # Track language switches
            prev_lang = self._session_langs.get(session_id, "en")
            if lang != prev_lang:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="LANGUAGE_SWITCH",
                    details={"from": prev_lang, "to": lang},
                )

            # Handoff detection — intercept before any structured lookup or LLM
            handoff_response = _sp_handoff(query)
            if handoff_response:
                logger.info(f"[{session_id}] Handoff detected (stream): '{query[:60]}'")
                for word in handoff_response.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            # Out-of-domain detection — block clearly off-topic queries before retrieval/LLM
            if self._is_out_of_domain(query):
                ood_response = {
                    "en": OUT_OF_DOMAIN_RESPONSE_EN,
                    "hi": OUT_OF_DOMAIN_RESPONSE_HI,
                    "bn": OUT_OF_DOMAIN_RESPONSE_BN,
                }.get(lang, OUT_OF_DOMAIN_RESPONSE_EN)

                logger.info(f"OUT-OF-DOMAIN BLOCKED (stream, lang={lang}): '{query[:80]}'")
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="OUT_OF_DOMAIN",
                    details={"query": query[:100], "lang": lang},
                )
                for word in ood_response.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            # Repeat intent — return last assistant response without RAG
            if self._detect_repeat_intent(query):
                last_response = self._get_last_assistant_response(history)
                if last_response:
                    logger.info(
                        f"REPEAT HIT (stream): returning last response ({len(last_response)} chars)"
                    )
                    telemetry.log_special_event(
                        session_id,
                        turn_number=turn_number,
                        event_type="REPEAT_REQUEST",
                        details={"replayed_response_length": len(last_response)},
                    )
                    telemetry.log_turn_input(
                        session_id,
                        turn_number=turn_number,
                        raw_transcript=query,
                        detected_language=lang,
                        detected_intent="repeat",
                    )
                    for word in last_response.split():
                        yield word + " "
                        await asyncio.sleep(0.02)
                    if conversation_history is None:
                        self._append_session_turn(session_id, query, last_response)
                    return
                logger.info("REPEAT HIT (stream) but no history — falling through")

            # Placement eligibility intent (stream, Task 5)
            if self._detect_placement_eligibility_intent(query):
                placement_info = self._structured_lookup("placement eligibility", lang)
                if not placement_info:
                    placement_info = (
                        "Placement is based on your academic performance, "
                        "technical skills, and aptitude. Regular study and "
                        "skill development are recommended."
                    )
                for word in placement_info.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            # Differentiated conversation replay (stream, Task 3)
            repeat_type = self._detect_repeat_conversation_intent(query)
            if repeat_type == "all":
                replay = self._repeat_recent_conversation(history)
                if replay:
                    for word in replay.split():
                        yield word + " "
                        await asyncio.sleep(0.02)
                    return

            # Expand short follow-up queries for better retrieval context
            retrieval_query, expand_debug = self._expand_follow_up_query(query, history, session_id)
            is_follow_up = retrieval_query != query.strip()

            # Structured lookup check (stream, Task 1)
            structured_result = self._structured_lookup(retrieval_query, lang)
            if not structured_result:
                dept_code = self._extract_dept_code(retrieval_query)
                if dept_code and self._detect_on_topic_arithmetic(retrieval_query):
                    if re.search(r"\bsemester\s*fee\b|\bper\s*semester\b", retrieval_query):
                        structured_result = self._calculate_semester_fees(dept_code, lang)
                    elif re.search(r"\btotal\s*(fee|fees)\b", retrieval_query):
                        structured_result = self._calculate_total_fees(dept_code, lang)
            if structured_result:
                # Update structured session state for follow-up expansion (stream path)
                intent = self._detect_structured_intent(retrieval_query)
                if intent:
                    self._session_intents[session_id] = intent
                dept_code = self._extract_dept_code(retrieval_query)
                if dept_code:
                    self._session_departments[session_id] = dept_code
                for word in structured_result.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            llm_query = self._normalize_query(query)
            t_retrieval_start = time.time()
            context, confidence = self._retrieve_context(retrieval_query)
            t_retrieval_ms = (time.time() - t_retrieval_start) * 1000
            logger.debug(
                f"[{session_id}] RETRIEVED (stream) confidence={confidence:.4f} "
                f"context_len={len(context)}"
            )
            t_prep = time.time() - t0

            # Log retrieval telemetry
            rd = getattr(self, "_last_retrieval_data", {})
            is_empty_context = not context or confidence == 0.0
            telemetry.log_retrieval(
                session_id,
                turn_number=turn_number,
                retrieval_query=retrieval_query,
                confidence=confidence,
                latency_ms=t_retrieval_ms,
                top_chunks=rd.get("top_10_raw", []),
                chunks_passed=rd.get("chunks_passed", 0),
                chunks_discarded=rd.get("chunks_discarded", []),
            )

            if is_follow_up:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="FOLLOW_UP_QUERY",
                    details={"original": query, "expanded": retrieval_query},
                )

            if is_empty_context:
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="EMPTY_CONTEXT",
                    details={"confidence": confidence, "context_len": len(context)},
                )

            telemetry.log_turn_input(
                session_id,
                turn_number=turn_number,
                raw_transcript=query,
                expanded_transcript=retrieval_query if is_follow_up else "",
                detected_language=lang,
                detected_intent="rag_query",
                follow_up_topic=query if is_follow_up else "",
            )

            # Low-confidence retrieval guard — skip LLM when context is irrelevant
            if context and confidence < RETRIEVAL_CONFIDENCE_THRESHOLD:
                logger.info(
                    f"Low confidence retrieval (stream, {confidence:.3f}) for '{query[:60]}' — using fallback"
                )
                fallback = self._safe_fallback(lang)
                self._log_gap(query, lang, f"low_confidence_retrieval_{confidence:.3f}")
                telemetry.log_validation(
                    session_id,
                    turn_number=turn_number,
                    confidence_score=confidence,
                    configured_threshold=RETRIEVAL_CONFIDENCE_THRESHOLD,
                    low_confidence_triggered=True,
                )
                for word in fallback.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                return

            messages = self._build_messages(llm_query, context, history, lang)

            # Log prompt telemetry
            total_prompt = sum(len(m.get("content", "")) for m in messages)
            history_chars = sum(len(t.get("content", "")) for t in history[-10:])
            telemetry.log_prompt(
                session_id,
                turn_number=turn_number,
                total_prompt_chars=total_prompt,
                context_chars=len(context),
                history_chars=history_chars,
                history_turns=min(len(history), 10),
            )

            # Retry/backoff for rate limits (async) — with rate limiter + model fallback
            stream = None
            models_to_try = list(dict.fromkeys([self.model] + FALLBACK_MODELS))
            success = False
            used_model = self.model

            for current_model in models_to_try:
                for attempt in range(3):
                    wait = self._rate_limiter.acquire()
                    if wait > 0:
                        await asyncio.sleep(wait)

                    try:
                        telemetry.log_llm_start(session_id, turn_number=turn_number)
                        t_api_sent = time.time()
                        stream = await self.async_client.chat.completions.create(
                            model=current_model,
                            messages=messages,
                            temperature=0.3,
                            max_tokens=self.max_tokens,
                            stream=True,
                        )
                        self._rate_limiter.record_success()
                        used_model = current_model
                        success = True
                        break
                    except Exception as e:
                        error_str = str(e)
                        is_rate_limit = (
                            "429" in error_str
                            or "rate" in error_str.lower()
                            or "too many" in error_str.lower()
                        )
                        if is_rate_limit:
                            self._rate_limiter.record_429()
                            if attempt < 2:
                                backoff = min((2**attempt) + random.random(), MAX_BACKOFF_SEC)
                                logger.warning(
                                    f"Groq rate limited (async) on {current_model} "
                                    f"(model {models_to_try.index(current_model) + 1}/{len(models_to_try)}, "
                                    f"attempt {attempt + 1}/3), "
                                    f"retrying in {backoff:.1f}s"
                                )
                                await asyncio.sleep(backoff)
                            else:
                                logger.warning(f"All retries exhausted for {current_model}")
                        else:
                            raise
                if success:
                    break
                if current_model != models_to_try[-1]:
                    logger.warning(
                        f"Switching model {current_model} -> "
                        f"{models_to_try[models_to_try.index(current_model) + 1]}"
                    )

            if not success:
                raise RuntimeError(f"All Groq models ({models_to_try}) rate limited after retries")
            t_llm_first = time.time() - t0

            # Stream tokens immediately — no upfront buffering
            buffer: List[str] = []
            first_token = True
            ttft = 0.0
            t_first_token = 0.0
            stream_char_count = 0
            stream_truncated = False
            async for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    if first_token:
                        t_first_token = time.time()
                        ttft = round((t_first_token - t0) * 1000)
                        logger.info(
                            f"STREAM TTFT={ttft}ms prep={round(t_prep * 1000)}ms "
                            f"llm_setup={round((t_llm_first - t_prep) * 1000)}ms "
                            f"lang={lang} q='{query[:60]}'"
                        )
                        first_token = False
                    buffer.append(content)
                    if not stream_truncated:
                        yield content
                        stream_char_count += len(content)
                        if stream_char_count > MAX_VOICE_RESPONSE_CHARS:
                            stream_truncated = True
                            logger.info(
                                f"STREAM TRUNCATED at {MAX_VOICE_RESPONSE_CHARS} chars "
                                f"(lang={lang} q='{query[:40]}...')"
                            )

            t_last_token = time.time()
            full_answer = "".join(buffer).strip()
            if not full_answer:
                return

            t_total = round((time.time() - t0) * 1000)
            char_count = len(full_answer)
            logger.info(
                f"STREAM COMPLETE total={t_total}ms chars={char_count} "
                f"~{round(char_count / t_total * 1000, 1)}cps lang={lang}"
            )

            # Log LLM completion telemetry
            telemetry.log_llm_complete(
                session_id,
                turn_number=turn_number,
                ttft_ms=ttft,
                completion_time_ms=(time.time() - t0) * 1000,
                response=full_answer,
                model=self.model,
                latency_ms=t_total,
            )

            # Non-blocking validation (logs warnings, doesn't replace output)
            t_post_start = time.time()
            is_valid, reason = self._validate_answer(full_answer, context, query)
            hallucination_guard_result = "passed"
            if not is_valid:
                logger.warning(
                    f"PHASE 0 GUARD (stream, non-blocking) lang={lang} query='{query[:60]}': {reason}"
                )
                self._log_gap(query, lang, f"hallucination_guard_stream: {reason}")
                hallucination_guard_result = "blocked"
                telemetry.log_quality_metrics(
                    session_id,
                    turn_number=turn_number,
                    hallucination_guard_triggered=True,
                )

            already_said_no_info = any(
                phrase in full_answer.lower()
                for phrase in (
                    "no information",
                    "not aware",
                    "don't have",
                    "does not contain",
                    "context does not contain",
                    "not found in",
                    "can't find",
                    "cannot find",
                    "cannot answer",
                    "जानकारी नहीं",
                    "পাতা নেই",
                    "পাওয়া যায়নি",
                    "জান নেই",
                )
            )
            if already_said_no_info and "0343-2501353" not in full_answer:
                logger.warning(
                    f"OUT-OF-KB DETECTED (stream, non-blocking) lang={lang} query='{query[:60]}': "
                    f"LLM said '{full_answer[:80]}' without phone"
                )
                self._log_gap(query, lang, "out_of_kb_deflection_stream")
                telemetry.log_special_event(
                    session_id,
                    turn_number=turn_number,
                    event_type="OUT_OF_KB",
                    details={"answer": full_answer[:100]},
                )

            # Log validation telemetry
            telemetry.log_validation(
                session_id,
                turn_number=turn_number,
                confidence_score=confidence,
                configured_threshold=RETRIEVAL_CONFIDENCE_THRESHOLD,
                low_confidence_triggered=False,
                hallucination_guard_result=hallucination_guard_result,
            )

            t_post_end = time.time()
            total_duration = (t_post_end - t_request_start) * 1000
            gen_duration = (t_last_token - t_api_sent) * 1000
            post_duration = (t_post_end - t_post_start) * 1000
            streaming_duration = (t_last_token - t_first_token) * 1000 if t_first_token else 0
            telemetry.log_llm_lifecycle(
                session_id,
                turn_number=turn_number,
                request_start=t_request_start,
                api_request_sent=t_api_sent,
                first_token_received=t_first_token,
                last_token_received=t_last_token,
                postprocessing_start=t_post_start,
                postprocessing_end=t_post_end,
                ttft_ms=ttft,
                generation_duration_ms=gen_duration,
                postprocessing_duration_ms=post_duration,
                total_llm_duration_ms=total_duration,
                output_tokens=0,
                estimated_tokens_per_second=0,
                streaming_duration_ms=streaming_duration,
                model=used_model,
                response=full_answer,
            )

            if conversation_history is None:
                self._append_session_turn(session_id, query, full_answer)

        except Exception as e:
            elapsed = round((time.time() - t_request_start) * 1000)
            telemetry.log_turn_error(
                session_id,
                turn_number=turn_number,
                exception=e,
                elapsed_ms=elapsed,
            )
            logger.error(f"Groq stream error ({elapsed}ms): {e}")
            yield "Sorry, something went wrong."

    def is_available(self) -> bool:
        return self.client is not None


# Singleton
_groq_service = None


def get_groq_service() -> GroqService:
    global _groq_service
    if _groq_service is None:
        _groq_service = GroqService()
    return _groq_service
