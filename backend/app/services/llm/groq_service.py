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

import difflib
import logging
import os
import re
import time
import json
import hashlib
import asyncio
from typing import (
    Dict,
    List,
    Optional,
    Any,
    Tuple,
    Set,
)
import collections
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# FeeEngine import (shadow mode — Phase 2)
# ---------------------------------------------------------------------------
try:
    from .fee_engine import FeeEngine as _FeeEngine

    _FEE_ENGINE_AVAILABLE = True
except ImportError:
    _FeeEngine = None  # type: ignore
    _FEE_ENGINE_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("FeeEngine not available — using legacy fee handler only")

try:
    from .intent_classifier import IntentClassifier as _IntentClassifier

    _INTENT_CLASSIFIER_AVAILABLE = True
except ImportError:
    _IntentClassifier = None  # type: ignore
    _INTENT_CLASSIFIER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("IntentClassifier not available — classifier dependent features disabled")

# Feature flag: when True, fee queries use the new FeeEngine instead of FEE_GROUP_MAP


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


logger = logging.getLogger(__name__)


# =========================================================================
# ConversationState — per-domain structured memory for follow-up resolution
# =========================================================================


@dataclass
class DomainSlot:
    """Tracks the last resolved intent and department for a single domain."""

    domain: str
    intent: str | None = None
    department: str | None = None
    handler_result: str | None = None
    last_updated: int = 0


@dataclass
class ConversationState:
    """Per-session state tracking all visited domains for cross-domain follow-up."""

    slots: Dict[str, DomainSlot] = field(default_factory=dict)
    visit_order: deque = field(default_factory=lambda: deque(maxlen=8))
    _counter: int = 0


# Which facets each domain supports (used for cross-domain follow-up resolution).
# Recency wins when multiple domains support the same facet.
DOMAIN_FACETS: Dict[str, Set[str]] = {
    "fee": {"department", "fee", "total", "semester", "installment"},
    "hostel": {
        "hostel",
        "boy",
        "girl",
        "facilities",
        "fee",
        "room",
        "wifi",
        "mess",
        "capacity",
        "document",
        "available",
        "cost",
    },
    "admission": {
        "admission",
        "department",
        "document",
        "process",
        "eligibility",
        "counselling",
        "seat",
        "cutoff",
        "fee",
        "form",
        "entrance",
        "deadline",
        "apply",
        "rank",
        "exam",
        "scholarship",
    },
    "placement": {"placement", "department", "package", "recruit", "company", "lpa"},
    "hod": {"hod", "department", "faculty", "professor", "head"},
    "scholarship": {"scholarship", "eligibility", "fee"},
    "safety": {"safety", "ragging", "security", "women"},
    "contact": {"contact", "phone", "email", "helpline", "call", "mobile"},
    "principal_info": {"principal", "vice_principal"},
    "college_info": {"establishment", "timing", "established", "founded"},
    "departments_info": {"department", "branch", "course", "program"},
}

_INTENT_TO_DOMAIN: Dict[str, str] = {
    "fee": "fee",
    "installment": "fee",
    "hostel": "hostel",
    "safety": "safety",
    "admission": "admission",
    "admission_documents": "admission",
    "admission_office": "admission",
    "counselling": "admission",
    "eligibility": "admission",
    "seats": "admission",
    "cutoff": "admission",
    "scholarship": "scholarship",
    "placement": "placement",
    "hod": "hod",
    "faculty": "hod",
    "departments": "departments_info",
    "contact": "contact",
    "principal": "principal_info",
    "vice_principal": "principal_info",
    "establishment": "college_info",
    "timings": "college_info",
    "campus_visit": "campus",
    "backlog": "policies",
}

_INTENT_TO_FACET: Dict[str, str] = {
    "fee": "fee",
    "installment": "fee",
    "hostel": "hostel",
    "safety": "safety",
    "admission": "admission",
    "admission_documents": "document",
    "admission_office": "admission",
    "counselling": "counselling",
    "eligibility": "eligibility",
    "scholarship": "scholarship",
    "placement": "placement",
    "hod": "hod",
    "faculty": "faculty",
    "seats": "seat",
    "cutoff": "cutoff",
    "departments": "departments",
    "contact": "contact",
    "principal": "principal",
    "vice_principal": "principal",
    "establishment": "establishment",
    "timings": "timings",
    "campus_visit": "campus_visit",
}

# Department words that trigger =department facet in query classification
_DEPT_WORDS: frozenset = frozenset(
    {
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
)

# Intents compatible with department follow-up ("What about Mechanical?" after fee/admission/etc.)
_DEPT_COMPATIBLE_INTS: frozenset = frozenset(
    {
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
)

from app.services.normalization import normalize_query, normalize_for_tts

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
    r"^(namaste|नमस्ते|নমস্কার)$",
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
    r"\b(what|where|when|why|how|who|which|about|of|in|at|on|for|to|the|a|an|is|are|am|was|were)\b\s*$",
)

FILLER_ONLY_PATTERNS = (
    r"^(okay|ok|k|yes|yeah|yep|no|nah|nope|na|nahi|nahin|nahi|thanks|thank you|thanku|thx|hmm|hm|mm|huh|aha|uh huh|mm hmm|oh|ah)$",
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
            "bollywood",
            "hollywood",
            "trailer",
            "series",
            "episode",
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
            "website",
            "web development",
            "web dev",
            "frontend",
            "backend",
            "full stack",
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
        }
    ),
    "translation": frozenset(
        {
            "translate",
            "translator",
            "translation",
            "dictionary",
            "meaning",
            "vocabulary",
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

FALLBACK_ANSWER_EN = FALLBACK_TIER1_EN
FALLBACK_ANSWER_HI = FALLBACK_TIER1_HI
FALLBACK_ANSWER_BN = FALLBACK_TIER1_BN

UNKNOWN_INFO_RESPONSE_EN = (
    "I don't have that information right now. Please call the college at 0343-2501353 and they will help you."
)
UNKNOWN_INFO_RESPONSE_HI = (
    "Mere paas iski jankari abhi nahi hai. College ko 0343-2501353 par call karein, woh aapki madad karenge."
)
UNKNOWN_INFO_RESPONSE_BN = (
    "এই বিষয়ে আমার কাছে এখন তথ্য নেই। কলেজে 0343-2501353 নম্বরে কল করুন, তারা আপনাকে সাহায্য করবে।"
)

_HOD_UNKNOWN_EN = "I don't have the HOD details for that department right now. Would you like the college contact number instead?"
_HOD_UNKNOWN_HI = "Us department ke HOD ke baare mein mere paas abhi jankari nahi hai. Kya aap college ka number chahenge?"
_HOD_UNKNOWN_BN = "ওই বিভাগের HOD সম্পর্কে আমার কাছে এখন তথ্য নেই। আপনি কি কলেজের নম্বর চান?"

CLARIFY_REPEAT_EN = "Sorry, I didn't catch that clearly. Could you please repeat?"
CLARIFY_REPEAT_HI = "Maaf kijiye, main achhe se samajh nahi paya. Kya aap dobara bata sakte hain?"
CLARIFY_REPEAT_BN = "দুঃখিত, আমি স্পষ্টভাবে বুঝতে পারিনি। আপনি কি আবার বলতে পারেন?"

# Structured arithmetic — fee group definitions per department
# Maps department code -> (total_fees, admission_fee, per_semester)
FEE_GROUP_MAP: Dict[str, tuple[int, int, int]] = {
    # Values verified from BCREC fee structure PDF 2026-30
    "CSE": (617700, 99225, 73925),
    "IT": (617700, 99225, 73925),
    "ECE": (617700, 99225, 73925),
    "EE": (567100, 92900, 67600),
    "AIML": (567100, 92900, 67600),
    "DS": (567100, 92900, 67600),
    "CY": (567100, 92900, 67600),
    "CSD": (567100, 92900, 67600),
    "ME": (429100, 75650, 50350),
    "CE": (429100, 75650, 50350),
    "MBA": (419200, 121400, 0),
    "MCA": (214600, 67800, 48600),
}

# FeeEngine feature flag — see _handle_fee_query()
# Set USE_NEW_FEE_ENGINE = True at module top or via env var at your own risk.
_USE_NEW_FEE_ENGINE = os.getenv("USE_NEW_FEE_ENGINE", "0") == "1"

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
    # Hindi abbreviations
    "सीएससी": "CSE", "सीएसई": "CSE",
    "एसी": "ECE", "ईएससी": "ECE",
    "ईई": "EE", "एमई": "ME", "सीई": "CE",
    "एआईएमएल": "AIML", "डीएस": "DS",
    "आई टी": "IT",
    # Bengali abbreviations
    "ইসিই": "ECE", "ইই": "EE", "এমই": "ME",
    "সিই": "CE", "সিএসই": "CSE", "এআইএমএল": "AIML",
}

# Hindi keyword normalization — converts Hindi domain terms to English BEFORE handlers
HINDI_KEYWORD_MAP = {
    "फैकल्टी": "faculty", "प्रोफेसर": "professor",
    "प्लेसमेंट": "placement", "नौकरी": "job",
    "कटऑफ": "cutoff", "फीस": "fee", "फी": "fee",
    "हॉस्टल": "hostel", "स्कॉलरशिप": "scholarship",
    "एडमिशन": "admission", "भर्ती": "admission",
    "अटेंडेंस": "attendance", "बैकलॉग": "backlog",
    "वैकेंटी": "vacancy", "सीट": "seat", "सीटें": "seats",
    "सबसे अच्छा": "best", "बेस्ट": "best",
    "डिपार्टमेंट": "department", "विभाग": "department",
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
SYSTEM_PROMPT = """You are a friendly BCREC admission counselor talking to a student or parent on the phone. You work for Dr. B.C. Roy Engineering College, Durgapur. Be warm, helpful, and conversational — like a real counselor who genuinely wants to help.

CORE RULES:
1. Answer ONLY in the user's language. If user writes in Hindi (Roman), answer in Hindi with NOT A SINGLE Bengali word. If user writes in Bengali/Banglish, answer in Banglish. NEVER mix languages.
2. Be concise: Answer in 2-3 short sentences. Give the most important answer first. Then add 1 helpful context sentence. Then stop.
3. Be conversational and natural — like a helpful campus counselor on the phone. Use "ji", "bilkul", "aap" for Hindi.
4. Never use filler like "Based on the context" or "According to the knowledge base". Just answer directly.
5. If query is Hinglish (Hindi+English): use Roman Hindi. NEVER start with "Bhalo", "Bhalo,", "Achha", "Theek hai" — just answer directly. Bengali words like "bhalo", "kemon", "ache", "hobe", "hoyeche" are FORBIDDEN in Hindi responses.
6. If query is Banglish (Bengali+English): use colloquial Banglish. NEVER use "aaraadhya", "prasiddh", "shrestha", "shiksha". Use "bhalo", "placement bhalo", "fees kom", "current".
7. INTENT CLARITY: "admission lena hai/chahiye/chahta hu" = ADMISSION PROCESS (tell about WBJEE, eligibility, exams). "kyu/q/keno admission" = WHY BCREC (selling points). Never confuse these.
8. RESPONSE STRUCTURE: Answer the exact question in 1 sentence, then add 1 helpful context sentence, then end with exactly 1 relevant follow-up question.
9. COUNSELOR BEHAVIOR: Speak like a human counselor, not a database. Never dump bullet points or colon-delimited facts. Weave facts into natural sentences. Use "aap" (formal) throughout.
10. EMOTIONAL QUERIES: If the user sounds worried (backlog, marks, rejection), first acknowledge and reassure, then give the factual policy, then offer help. Never blame or lecture.

TTS STYLE:
- Spell out numbers as words: "six lakh" NOT "6,00,000", "ninety-one percent" NOT "91%".
- Phone numbers with dashes: 0343-2501353.
- No markdown, bullet lists, tables, or emoji. Plain sentences only.
- Use abbreviations: CSE, IT, ECE, EE, ME, CE, CSD, AIML. Not both abbreviation and full name.

ABSOLUTE VOICE RULES (BREAKING THESE IS A BUG):
1. NEVER generate more than 3 sentences. Period. No exceptions.
2. NEVER use markdown: no **, no ###, no -, no |, no tables, no bullet lists.
3. NEVER use emojis.
4. If you don't have structured data for a query, say ONE sentence: "I don't have that information right now." Do NOT guess or hallucinate.
5. NEVER explain how you work. NEVER say "as an AI", "according to my knowledge", "I think".
6. For "tell me about X" questions: give ONE fact, then ask "Would you like to know more?"
7. Responses over 50 words are TOO LONG for voice. Cut them down.
8. For Hindi responses: use ONLY spoken Hindi words. Never use Devanagari script.

PROFANITY & ABUSE:
- If user swears or is angry: acknowledge briefly ("I understand your concern") and professionally redirect.
- Never argue, lecture, or moralize. Stay polite and keep offering help.

OUT-OF-SCOPE:
- Only answer questions about BCREC. For weather, jokes, politics, etc., politely decline.

HONESTY:
- If you don't have information, say so. Never make up facts or numbers.
- For exact data (fees, phone numbers, HOD names, placement stats, cutoff ranks), use the provided tools.
- When a tool returns data, use it directly. Do not modify numbers.

LANGUAGE HINTS:
- In Hindi/Hinglish, "kyu", "kyun", or "q" before "admission" means "Why should I take admission?"
- In Bengali/Banglish, "keno" before "admission" means "Why should I take admission?"
- Treat these as "why choose BCREC" questions, NOT admission process questions.

SELLING POINTS FOR BCREC (use when user asks why choose BCREC):
- Established 2000. Autonomous from 2024. NAAC B+. NBA accredited: CSE, ECE, IT, EE, ME.
- NIRF ranked 201-250. AICTE IDEA Lab #1 in India.
- 208+ faculty across 15 departments. 17 acre campus. 80,000+ books in library.
- 91% overall placement, CSE 93.6%. Average package 4.25 LPA.
- Top recruiters: TCS, Infosys, Wipro, Capgemini, Accenture, Amazon, HCL.
- Fee very affordable: approximately 1.5 lakh per year.
- Branch change allowed after first year.
- Hostel optional, anti-ragging strictly enforced.

TOOLS:
You do NOT need tools. ALL the information you need is provided above. Answer directly from your knowledge and the data in this prompt. Be accurate with numbers and names — they are verified facts from the college's official database.

KEY EXACT DATA:
- Principal: Dr. Sanjay S. Pawar (Phone: 0343-2501353)
- Vice Principal: Prof. Dr. Partha Pratim Sarkar
- College Phones: 0343-2501353, 0343-2502449, 0343-2503985
- Email: info@bcrec.ac.in
- Mobile: +91-6297128554
- Address: Jemua Road, Fuljhore, Durgapur - 713206, West Bengal
- Established: August 2000
- Autonomous: Yes (from 2024-25 batch)
- NAAC Grade: B+ (CGPA 2.83)
- NBA Accredited: CSE, ECE, IT, EE, ME
- NIRF Rank: 201-250 (Engineering 2025)
- Faculty: 208+ members across 15 departments, student-teacher ratio 15:1 to 20:1
- Campus: 17 acres
- Library: 80,000+ books, IEEE/Springer/Elsevier/ScienceDirect
- FEES (total for 4 years B.Tech):
  - CSE, IT, ECE: 6,04,700 (six lakh four thousand seven hundred)
  - EE, AIML, DS, CY, CSD: 5,54,700 (five lakh fifty-four thousand seven hundred)
  - ME, CE: 4,44,700 (four lakh forty-four thousand seven hundred)
  - Per semester: approximately 65,000 to 75,000
  - Admission fee: approximately 8,000
- PLACEMENT: Overall 91% (2025). CSE 93.6%. Average package 4.25 LPA. Highest on-campus 7 LPA. Off-campus up to 9 LPA.
- Top Recruiters: TCS, Infosys, Wipro, Capgemini, Accenture, Amazon, HCL
- Students placed 2025: 1017+ (across all years)
- Companies visited 2025: 100+
- HOSTEL: Optional. Single bed: 30,000/sem, Double/triple: 10,000/sem. Mess: 5,000/month (includes non-veg)
- Total hostels: 7 (5 boys, 2 girls). Capacity: 1500+
- SCHOLARSHIPS: TFW, Swami Vivekananda, Kanyashree, OASIS/Aikyashree
- ADMISSION: Through WBJEE or JEE Main. Eligibility: 10+2 with PCM, 50% marks.
- CUTOFF (WBJEE 2025 approximate ranks): CSE ~5000, IT ~8000, ECE ~12000, EE ~18000, ME ~25000, CE ~30000
- HODs: CSE Prof. (Dr.) Raj Kumar Samanta, ECE Dr. Mrinmoy Chakraborty, IT Dr. Dinesh Kumar Pradhan, EE Dr. Shibendu Mahata, ME Dr. Chandan Chattoraj, CE Dr. Sanjay Sengupta
- BACKLOG: Supplementary exams held every semester for failed subjects. Students can reappear as per MAKAUT rules.
- ANTI-RAGGING: Strictly enforced. Women safety helpline: 9851006415 (24x7).
- BRANCH CHANGE: Allowed after first year subject to criteria and availability.
- CAMPUS FACILITIES: Labs for each department (CSE, ECE, IT, EE, ME, CE, AIML). Sports grounds, gym, indoor games. Library with 80,000+ books. WiFi campus. Hostel with mess. Two canteens: ADDA (fast food, snacks, ice cream) and Main Canteen (Bengali food, South Indian, veg/non-veg separate). ATM and banking facility available on campus.
- CLUBS & SOCIETIES: Robotics Club, Coding Club, Literary Club, Music Club, Dance Club, Sports Club, Photography Club, Debate Club, Cultural Committee.
- SPORTS: Cricket ground, football, basketball, volleyball, badminton, table tennis, gymnasium.
- RAGGING: Strictly prohibited. Anti-ragging committee active. Women safety helpline 9851006415 (24x7)."""

# Tool definitions for Groq function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_fees",
            "description": "Get the fee structure for B.Tech programs. Returns semester fees and total fees for each branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch code optional. Leave empty for all branches. Options: CSE, ECE, IT, EE, ME, CE, AIML, DS, CY, CSD.",
                        "enum": ["CSE", "ECE", "IT", "EE", "ME", "CE", "AIML", "DS", "CY", "CSD"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_contact_info",
            "description": "Get college contact information: phone numbers, email, address, mobile number.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_principal_info",
            "description": "Get the name and contact details of the principal and vice principal.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_placement_info",
            "description": "Get placement statistics including overall rate, branch-wise rates, average package, highest package, and top recruiters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch code optional. Leave empty for overall stats. Options: CSE, ECE, IT, EE, ME, CE, AIML, DS, CY, CSD.",
                        "enum": ["CSE", "ECE", "IT", "EE", "ME", "CE", "AIML", "DS", "CY", "CSD"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_branch_info",
            "description": "Get information about all B.Tech branches offered at BCREC, including intake and details.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_admission_process",
            "description": "Get admission process details: eligibility criteria, required documents, entrance exams (WBJEE/JEE Main), counseling process, management quota, and contacts.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hostel_info",
            "description": "Get hostel details: availability, fees, room types, capacity, boys/girls hostels, and mess information.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_scholarship_info",
            "description": "Get information about available scholarships, eligibility, and schemes like TFW, Swami Vivekananda, Kanyashree, OASIS/Aikyashree.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cutoff_info",
            "description": "Get WBJEE cutoff ranks for different branches and categories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch code optional. Leave empty for all cutoffs. Options: CSE, ECE, IT, EE, ME, CE, AIML, DS, CY, CSD.",
                        "enum": ["CSE", "ECE", "IT", "EE", "ME", "CE", "AIML", "DS", "CY", "CSD"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_hod_info",
            "description": "Get the Head of Department (HOD) names for each branch or a specific branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch code optional. Leave empty for all HODs. Options: CSE, ECE, IT, EE, ME, CE, AIML, DS, CY, CSD.",
                        "enum": ["CSE", "ECE", "IT", "EE", "ME", "CE", "AIML", "DS", "CY", "CSD"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_backlog_policy",
            "description": "Get information about backlog/arrear policy, supplementary exams, re-examination, and academic failure procedures.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_college_info",
            "description": "Get general college information: establishment year, campus size, accreditation, faculty count, NAAC/NBA/NIRF ratings, autonomous status, and facilities.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]


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
class ConversationResult:
    """Result from conversation processing pipeline."""
    answer: str
    source: str = "llm_tools"
    lang: str = "en"
    latency_ms: float = 0
    short_circuited: bool = False
    hallucination_validated: bool = True
    tokens: dict = None
    cache_hit: bool = False

    def __post_init__(self):
        if self.tokens is None:
            self.tokens = {"prompt": 0, "completion": 0}


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

        # Sessions that have already been greeted (prevent greeting repeats)
        self._greeted_sessions: Set[str] = set()

        # Sessions that should skip ambiguous-word validation this turn
        # (used by yes/no continuation to avoid re-clarifying the same word)
        self._skip_ambiguous_validation_sessions: Set[str] = set()

        # Structured conversation state — per-domain slots with visit_order deque
        # for cross-domain follow-up resolution. Updated when _structured_lookup hits.
        self._session_states: Dict[str, ConversationState] = {}

        # Follow-up turn counter — resets when a structured lookup hits or clear intent is detected.
        # After 3+ follow-ups without a clear new intent, the bot re-asks what the user wants.
        self._session_follow_up_count: Dict[str, int] = {}

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

        # Intent classifier — initialized lazily; may be None if not available
        self.intent_classifier = _IntentClassifier() if _IntentClassifier is not None else None

        if self.client:
            logger.info("GroqService ready.")
        else:
            logger.warning("GroqService: Groq client not found. Check GROQ_API_KEY in .env")

    # -----------------------------------------------------------------------
    # LLM call — simple, no tool-calling overhead
    # -----------------------------------------------------------------------
    async def _call_llm_with_tools(
        self, messages: list, session_id: str, query: str, start: float, lang: str
    ) -> str:
        """Call Groq with the given messages. Hard timeout, graceful fallback."""
        LLM_TIMEOUT = 6.0
        models_to_try = list(dict.fromkeys([self.model] + FALLBACK_MODELS))
        t_start = time.time()

        for current_model in models_to_try:
            for attempt in range(2):
                wait = self._rate_limiter.acquire()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    completion = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.client.chat.completions.create,
                            model=current_model,
                            messages=messages,
                            temperature=0.3,
                            max_tokens=self.max_tokens,
                        ),
                        timeout=LLM_TIMEOUT,
                    )
                    self._rate_limiter.record_success()
                    content = (completion.choices[0].message.content or "").strip()
                    import re as _re
                    # Strip complete <think>...</think> blocks (multiline, multiple blocks)
                    content = _re.sub(r"<think>.*?</think>\s*", "", content, flags=_re.DOTALL)
                    # Strip unclosed <think> tag markup (no </think> present)
                    content = _re.sub(r"<think>", "", content).strip()
                    elapsed = time.time() - t_start
                    if elapsed > 1.0:
                        logger.info(f"LLM call completed in {elapsed:.1f}s on {current_model}")
                    return content
                except asyncio.TimeoutError:
                    elapsed = time.time() - t_start
                    logger.warning(
                        f"LLM timeout on {current_model} "
                        f"(attempt {attempt+1}/2, elapsed={elapsed:.1f}s, "
                        f"query='{query[:60]}')"
                    )
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                except Exception as e:
                    error_str = str(e)
                    elapsed = time.time() - t_start
                    is_rate_limit = "429" in error_str or "rate" in error_str.lower() or "too many" in error_str.lower()
                    if is_rate_limit and attempt == 0:
                        self._rate_limiter.record_429()
                        backoff = min(1.0, MAX_BACKOFF_SEC)
                        logger.warning(f"LLM rate limited on {current_model}, backoff {backoff}s")
                        await asyncio.sleep(backoff)
                    else:
                        logger.warning(
                            f"LLM error on {current_model} (attempt {attempt+1}/2, "
                            f"elapsed={elapsed:.1f}s): {error_str[:80]}"
                        )

        logger.warning(
            f"LLM call failed after all retries ({time.time()-t_start:.1f}s). "
            f"Returning fallback for query='{query[:60]}'"
        )
        return "I'm sorry, I'm having trouble connecting. Please call 0343-2501353."

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

    # Banglish → canonical English synonym mappings for academic failure terms.
    # Multi-word patterns must precede single-word patterns to avoid partial matches.
    _BANGLISH_SYNONYMS = [
        (r"\bback\s+chole\s+aseche\b", "backlog"),
        (r"\bback\s+as(?:che|e)\b", "backlog"),
        (r"\bback\s+hoyeche\b", "backlog"),
        (r"\bback\s+lag(?:be|se)\b", "backlog"),
        (r"\bback\s+ache\b", "backlog"),
        (r"\bsem(?:ester)?\s+back\b", "backlog failed semester"),
        (r"\bresult.*back\b", "backlog"),
        (r"\bback\s+paper\b", "backlog supplementary exam"),
        (r"\bfyel\b", "fail"),
    ]

    def _normalize_query(self, query: str) -> str:
        """Fix common STT mis-transcriptions of BCREC department names before RAG.
        Also transliterates Roman-script Bengali college terms to Bengali script
        so that vector search matches the native-script KB entries.
        Applies Banglish→canonical synonym mapping for academic failure terms."""
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
        # Banglish → canonical synonym mapping for academic failure terms
        for pattern, replacement in self._BANGLISH_SYNONYMS:
            q = re.sub(pattern, replacement, q, flags=re.IGNORECASE)
        if q != query:
            logger.info(f"Query normalized: '{query}' -> '{q}'")
        return q

    _ACADEMIC_FAILURE_EXPANSION = "fail semester backlog supplementary exam reappear"

    _ACADEMIC_FAILURE_TRIGGER = re.compile(
        r"\b(backlog|fail|supplementary|arrear|back\s+paper|reappear)\b",
        re.IGNORECASE,
    )

    def _expand_query(self, normalized: str) -> str:
        """Append canonical academic failure terms when the normalized query
        contains backlog-related signals. This boosts embedding similarity
        to the English policies KB entry for Banglish queries where the
        Banglish context dilutes the English keyword signal."""
        if self._ACADEMIC_FAILURE_TRIGGER.search(normalized):
            return f"{normalized} {self._ACADEMIC_FAILURE_EXPANSION}"
        return normalized

    def _retrieve_context(self, query: str) -> tuple[str, float]:
        """Enhanced retriever: vector search + semantic re-rank + section-aware filtering.
        Keeps top docs across sources, prioritizes by semantic anchor + language match.
        Returns (context_str, confidence) where confidence is the top relevance score (0.0-1.0)."""
        normalized = self._normalize_query(query)
        # Query expansion: append canonical terms for academic failure queries
        # so that Banglish sentences (e.g. "amar ekta sem a fail hoyeche")
        # get embedding proximity to the English policies KB entry.
        expanded = self._expand_query(normalized)
        if expanded != normalized:
            logger.info(
                f"Query expanded: '{normalized}' -> '{expanded}'"
            )
        try:
            language = detect_language(query)
            results, confidence = self.vector_store.search_with_scores(expanded, k=10)
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
        lang_prefix = {
            "bn": "CRITICAL LANGUAGE RULE: The user is writing in Banglish (Roman Bengali). You MUST reply in Banglish. Never use Hindi. If unsure, default to Banglish.\n\n",
            "hi": "CRITICAL LANGUAGE RULE: The user is writing in Hindi. You MUST reply in Roman Hindi (NOT Devanagari script). Never use Bengali or English words.\n\n",
            "en": "CRITICAL LANGUAGE RULE: The user is writing in English. Reply in English.\n\n",
        }.get(lang, "")
        system_content = lang_prefix + SYSTEM_PROMPT
        messages = [{"role": "system", "content": system_content}]

        # Add last 10 conversation turns (5 user + 5 assistant) for memory
        if history:
            for turn in history[-10:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Final user message with retrieved context
        lang_hint = {
            "bn": "The user's language is Banglish (Roman Bengali). Reply ONLY in Banglish. Do NOT use Hindi words. Do NOT switch to English unless the user writes in English.",
            "hi": "The user's language is Hindi. Reply ONLY in Roman Hindi (NOT Devanagari script). Do NOT use Bengali or English words unless the user writes in that language.",
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

        # 3. Check language of short queries using keyword markers
        word_count = len(query.strip().split())
        from app.utils.language_detect import BANGLA_ROMAN_WORDS, HINDI_ROMAN_WORDS
        text_lower = query.lower()
        text_words = set(re.sub(r"[^\w\s]", " ", text_lower).split())
        bn_kw = len(text_words & BANGLA_ROMAN_WORDS)
        hi_kw = len(text_words & HINDI_ROMAN_WORDS)

        if word_count <= 3:
            # For short queries, switch lang if there are strong keyword markers
            if bn_kw >= 2 and current_lang != "bn" and session_id not in self._session_langs:
                logger.info(f"[{session_id}] Language change: {current_lang} → bn (reason: keyword markers={bn_kw} in short query)")
                self._session_langs[session_id] = "bn"
                return "bn"
            if hi_kw >= 2 and current_lang != "hi" and session_id not in self._session_langs:
                logger.info(f"[{session_id}] Language change: {current_lang} → hi (reason: keyword markers={hi_kw} in short query)")
                self._session_langs[session_id] = "hi"
                return "hi"
            # Weak-but-clear signal: 1 exclusive marker for a language
            if bn_kw >= 1 and hi_kw == 0 and session_id not in self._session_langs:
                logger.info(f"[{session_id}] Language change: {current_lang} → bn (reason: exclusive Bangla marker={bn_kw} in short query)")
                self._session_langs[session_id] = "bn"
                return "bn"
            if hi_kw >= 1 and bn_kw == 0 and session_id not in self._session_langs:
                logger.info(f"[{session_id}] Language change: {current_lang} → hi (reason: exclusive Hindi marker={hi_kw} in short query)")
                self._session_langs[session_id] = "hi"
                return "hi"
            return current_lang

        # 4. Detect language for longer queries
        detected = detect_language(query)
        if detected == current_lang:
            return current_lang

        # 5. Detected differs from current — check evidence strength.
        # If language was explicitly set (not default "en"), lock it — resist switches
        # via weak keyword markers to prevent random flipping mid-conversation.
        lang_was_explicitly_set = session_id in self._session_langs and current_lang != "en"

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

        # 2.75 Single-word college terms — let through to LLM (department names, facilities, etc.)
        _single_word_college_terms = {
            "aiml", "cse", "ece", "ee", "me", "ce", "it", "csd", "ds", "cy",
            "labs", "lab", "hostel", "library", "sports", "club", "clubs",
            "fees", "fee", "placement", "faculty", "admission", "cutoff",
            "repeat", "pardon", "backlog", "arrear", "scholarship",
            "departments", "department",
        }
        if word_count == 1 and q_lower in _single_word_college_terms:
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

        Returns False for queries mentioning campus facilities/activities.
        Returns False for short queries (< 3 words).
        """
        q = query.strip().lower()
        if not q or len(q.split()) < 3:
            return False

        # College-context keywords — if present, query is about campus life, not off-topic
        _college_context = {
            "club", "clubs", "lab", "labs", "sports", "activity", "activities",
            "curricular", "khel", "ground", "facility", "facilities",
            "ke bare me", "ke baare mein", "k bare me", "batayea", "bataye",
            "kya he", "kya hai", "em kya", "kya ya",
        }
        if any(kw in q for kw in _college_context):
            return False

        total_hits = 0
        for keywords in OUT_OF_DOMAIN_CATEGORIES.values():
            total_hits += sum(1 for kw in keywords if kw in q)

        if total_hits >= 2:
            return True

        # Regex-based OOD patterns — catch queries the keyword threshold misses
        # These target specific query structures that are clearly not college-related.
        _ood_patterns = [
            r"\bhow\s+to\s+(make|cook|bake|prepare|build|create|play|install|setup|"
            r"reset|remove|delete|update|fix|repair|solve|calculate|"
            r"find|get|become|learn|start|stop|restart|download|upload|login|register)\b",
            r"\btranslate\s+(to|into|from)\b",
            r"\b(?:latest|top|new|best)\s+(bollywood|hollywood)\s+(movie|film|song|album|news)\b",
            r"\bplay\s+\w+\s+(with\s+)?me\b",
            r"\bwhat\s+is\s+(the\s+)?(weather|temperature|climate|time|date|day|meaning|horoscope)\b",
            r"\b(tell|recite|say|sing|write|create)\b.*\b(joke|story|poem|song|poetry|quote|rap|shayari|ghazal)\b",
            r"\b(?:how\s+)?(?:to\s+)?(?:make|prepare|cook)\s+.*\b(food|biryani|pizza|burger|pasta|noodles|curry|rice|chicken|paneer|sabzi|roti|paratha|dal|chawal|khana)\b",
        ]
        if any(re.search(p, q) for p in _ood_patterns):
            return True

        return False

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
            "number",
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
        if re.search(r"\b(scholarship|scholership|scolarship|schollarship)\b", q):
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
            # Long queries with a resolved domain still need expansion for pronoun resolution.
            # E.g. "what his concact info number or mil" after "who is the principal"
            # should expand "his" -> "principal".
            state = self._session_states.get(session_id) if session_id else None
            if not (state and state.visit_order):
                debug["reason"] = "long_query_no_expansion"
                logger.info(
                    f"EXPAND: {q_stripped[:60]} | reason=long_query (no session ctx) | "
                    f"prev_q={debug['previous_question']}"
                )
                return q_stripped, debug
            # Has session context — proceed with expansion
            logger.info(
                f"EXPAND: {q_stripped[:60]} | reason=long_query_with_ctx | "
                f"domains={list(state.visit_order)}"
            )
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

        # --- Structured state rewrite using ConversationState ---
        state = self._session_states.get(session_id) if session_id else None

        if state and state.visit_order:
            q_lower = q_stripped.lower()
            dept_code = self._extract_dept_code(q_stripped)
            hostel_subtype = self._match_hostel_subtype(q_stripped)
            admission_subtype = self._match_admission_subtype(q_stripped)

            dept_words = {
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
            is_dept_query = dept_code is not None or any(
                word.lower().rstrip("?.,!") in dept_words for word in q_stripped.split()
            )

            detected_facets: set = set()
            if is_dept_query:
                detected_facets.add("department")
            for facet_candidate in [
                "fee",
                "hostel",
                "boy",
                "girl",
                "document",
                "admission",
                "eligibility",
                "counselling",
                "placement",
                "scholarship",
                "safety",
                "contact",
                "principal",
                "faculty",
                "cutoff",
                "seat",
                "room",
                "facilities",
                "mess",
                "establishment",
                "timing",
                "installment",
                "total",
                "semester",
                "capacity",
                "wifi",
                "available",
                "cost",
                "form",
                "entrance",
                "deadline",
                "apply",
                "rank",
                "exam",
                "process",
                "package",
                "recruit",
                "company",
                "lpa",
                "professor",
                "head",
                "ragging",
                "security",
                "women",
                "phone",
                "email",
                "helpline",
                "call",
                "mobile",
                "vice_principal",
                "established",
                "founded",
                "branch",
                "course",
                "program",
            ]:
                if facet_candidate in q_lower:
                    detected_facets.add(facet_candidate)

            for domain in reversed(state.visit_order):
                domain_facets = DOMAIN_FACETS.get(domain, set())
                if not (detected_facets & domain_facets):
                    continue

                slot = state.slots.get(domain)
                last_intent = slot.intent if slot else None

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

                if is_dept_query and last_intent in dept_compatible_intents:
                    dept = dept_code or next(
                        (
                            w.lower().rstrip("?.,!")
                            for w in q_stripped.split()
                            if w.lower().rstrip("?.,!") in dept_words
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

                if domain == "fee" and last_intent == "fee":
                    expanded = f"{q_stripped} fee"
                    debug["reason"] = "structured_fee_followup"
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_fee_followup | "
                        f"expanded-> {expanded[:80]}"
                    )
                    return expanded, debug

                if domain == "hostel" and hostel_subtype:
                    expanded = f"{hostel_subtype} hostel"
                    debug["reason"] = "structured_hostel_rewrite"
                    debug["subtype"] = hostel_subtype
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_hostel_rewrite | "
                        f"subtype={hostel_subtype} | expanded-> {expanded[:80]}"
                    )
                    return expanded, debug

                if domain == "admission" and admission_subtype:
                    expanded = f"{admission_subtype} admission"
                    debug["reason"] = "structured_admission_rewrite"
                    debug["subtype"] = admission_subtype
                    logger.info(
                        f"EXPAND: {q_stripped[:60]} | reason=structured_admission_rewrite | "
                        f"subtype={admission_subtype} | expanded-> {expanded[:80]}"
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

    # ------------------------------------------------------------------
    # Fee query abstraction — routes to old or new engine
    # ------------------------------------------------------------------

    def _handle_fee_query_old(
        self, q: str, lang: str, kb: dict
    ) -> str | None:
        """Legacy fee handler using FEE_GROUP_MAP."""
        fee_intent = re.search(
            r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee)\b", q
        )
        if not fee_intent:
            return None
        logger.info(f"HANDLER (old): fee_intent matched for query='{q[:60]}'")
        dept_code = self._extract_dept_code(q)
        if dept_code and dept_code in FEE_GROUP_MAP:
            total, admission, per_sem = FEE_GROUP_MAP[dept_code]
            dept_name = dept_code
            if "full_name" in kb.get("courses", {}).get("btech", {}).get(dept_code, {}):
                dept_name = kb["courses"]["btech"][dept_code]["full_name"]["value"]
            if re.search(r"\bsemester\s*fee\b|\bper\s*semester\b|\bsem\s*fee\b", q):
                if per_sem > 0:
                    return self._lang_fee_response(lang, "semester", dept_name, per_sem, 0, 0)
                return self._lang_fee_response(lang, "total", dept_name, total, 0, 0)
            if re.search(r"\badmission\s*fee\b", q):
                return self._lang_fee_response(lang, "admission", dept_name, 0, admission, 0)
            return self._lang_fee_response(lang, "total", dept_name, total, 0, 0)

        # No department specified — general fee info
        if re.search(r"\b(fee structure|fee|fees)\b", q):
            fee_cse = self._format_inr(617700, lang)
            fee_other = self._format_inr(567100, lang)
            fee_me_ce = self._format_inr(429100, lang)
            if lang == "hi":
                return (
                    "BCREC mein B.Tech fees branch ke hisaab se alag hai. "
                    f"CSE, IT, ECE: total {fee_cse}. "
                    f"EE, AIML, DS, CY, CSD: total {fee_other}. "
                    f"ME, CE: total {fee_me_ce}. "
                    "Kya aap kisi specific branch ki fees jaanna chahenge?"
                )
            if lang == "bn":
                return (
                    "BCREC তে B.Tech এর ফি শাখা অনুযায়ী আলাদা। "
                    f"CSE, IT, ECE: মোট {fee_cse}. "
                    f"EE, AIML, DS, CY, CSD: মোট {fee_other}. "
                    f"ME, CE: মোট {fee_me_ce}. "
                    "আপনি কি কোনো নির্দিষ্ট শাখার ফি জানতে চান?"
                )
            return (
                "BCREC B.Tech fees vary by branch. "
                f"CSE, IT, ECE: {self._format_inr(617700, 'en')} total. "
                f"EE, AIML, DS, CY, CSD: {self._format_inr(567100, 'en')} total. "
                f"ME, CE: {self._format_inr(429100, 'en')} total. "
                "Would you like fees for a specific branch?"
            )
        return None

    # ------------------------------------------------------------------
    # Phase 3: Dynamic fee response formatting
    # ------------------------------------------------------------------

    def _fmt_total_fee(
        self, total: int, dept_name: str, dept_code: str, lang: str,
        fsp: int | None, rsf: int | None,
    ) -> str:
        ts = self._format_inr(total, lang)
        if lang == "hi":
            if fsp and rsf and rsf > 0:
                a = self._format_inr(fsp, lang)
                b = self._format_inr(rsf, lang)
                return (
                    f"{dept_name} ({dept_code}) का कुल कोर्स शुल्क {ts} है। "
                    f"इसमें पहले सेमेस्टर का {a} और बाकी सेमेस्टर का {b} प्रति सेमेस्टर शामिल है।"
                )
            rem = total - (fsp or 0)
            if fsp and rem > 0:
                a = self._format_inr(fsp, lang)
                b = self._format_inr(rem, lang)
                return (
                    f"{dept_name} ({dept_code}) का कुल कोर्स शुल्क {ts} है। "
                    f"इसमें पहले सेमेस्टर का {a} और बाकी कोर्स का {b} शामिल है।"
                )
            return f"{dept_name} ({dept_code}) का कुल कोर्स शुल्क {ts} है।"

        if lang == "bn":
            if fsp and rsf and rsf > 0:
                a = self._format_inr(fsp, lang)
                b = self._format_inr(rsf, lang)
                return (
                    f"{dept_name} ({dept_code}) এর মোট কোর্স ফি {ts}। "
                    f"এতে প্রথম সেমিস্টারের {a} এবং বাকি সেমিস্টারের {b} করে অন্তর্ভুক্ত।"
                )
            rem = total - (fsp or 0)
            if fsp and rem > 0:
                a = self._format_inr(fsp, lang)
                b = self._format_inr(rem, lang)
                return (
                    f"{dept_name} ({dept_code}) এর মোট কোর্স ফি {ts}। "
                    f"এতে প্রথম সেমিস্টারের {a} এবং বাকি কোর্সের {b} অন্তর্ভুক্ত।"
                )
            return f"{dept_name} ({dept_code}) এর মোট কোর্স ফি {ts}।"

        if fsp and rsf and rsf > 0:
            a = self._format_inr(fsp, lang)
            b = self._format_inr(rsf, lang)
            return (
                f"The total course fee for {dept_name} ({dept_code}) is {ts}. "
                f"This includes first semester charges of {a} and "
                f"subsequent semesters at {b} each."
            )
        rem = total - (fsp or 0)
        if fsp and rem > 0:
            a = self._format_inr(fsp, lang)
            b = self._format_inr(rem, lang)
            return (
                f"The total course fee for {dept_name} ({dept_code}) is {ts}. "
                f"This includes the first semester payable of {a} and "
                f"the remaining course fee of {b}."
            )
        return f"The total course fee for {dept_name} ({dept_code}) is {ts}."

    def _fmt_admission_fee(
        self, amount: int, dept_name: str, dept_code: str, lang: str,
        group, one_time_total: int, sem1_comp_total: int,
    ) -> str:
        ts = self._format_inr(amount, lang)
        onet = self._format_inr(one_time_total, lang) if one_time_total else None
        sem1t = self._format_inr(sem1_comp_total, lang) if sem1_comp_total else None
        has_detail = onet and sem1t and sem1_comp_total > 0

        if lang == "hi":
            if has_detail:
                return (
                    f"{dept_name} ({dept_code}) में प्रवेश के समय देय राशि {ts} है। "
                    f"इसमें एकमुश्त शुल्क {onet} और पहले सेमेस्टर की ट्यूशन व अन्य फीस {sem1t} शामिल है।"
                )
            return f"{dept_name} ({dept_code}) में प्रवेश के समय देय राशि {ts} है।"

        if lang == "bn":
            if has_detail:
                return (
                    f"{dept_name} ({dept_code}) এ ভর্তির সময় প্রদেয় পরিমাণ {ts}। "
                    f"এতে এককালীন ফি {onet} এবং প্রথম সেমিস্টারের টিউশন ও অন্যান্য ফি {sem1t} অন্তর্ভুক্ত।"
                )
            return f"{dept_name} ({dept_code}) এ ভর্তির সময় প্রদেয় পরিমাণ {ts}।"

        if has_detail:
            return (
                f"The admission-time payable for {dept_name} ({dept_code}) is {ts}. "
                f"This covers one-time charges of {onet} (admission fee, caution money, registration) "
                f"and the first semester tuition, development fee, and other charges of {sem1t}."
            )
        return f"The admission-time payable for {dept_name} ({dept_code}) is {ts}."

    def _fmt_first_semester(
        self, amount: int, dept_name: str, dept_code: str, lang: str,
        one_time_total: int, sem1_comp_total: int,
    ) -> str:
        ts = self._format_inr(amount, lang)
        onet = self._format_inr(one_time_total, lang)
        sem1t = self._format_inr(sem1_comp_total, lang)
        has_breakdown = one_time_total > 0 and sem1_comp_total > 0

        if lang == "hi":
            if has_breakdown:
                return (
                    f"{dept_name} ({dept_code}) का पहला सेमेस्टर देय {ts} है। "
                    f"विवरण: एकमुश्त शुल्क {onet} और सेमेस्टर शुल्क {sem1t}।"
                )
            return f"{dept_name} ({dept_code}) का पहला सेमेस्टर देय {ts} है।"
        if lang == "bn":
            if has_breakdown:
                return (
                    f"{dept_name} ({dept_code}) এর প্রথম সেমিস্টার প্রদেয় {ts}। "
                    f"বিবরণ: এককালীন ফি {onet} এবং সেমিস্টার ফি {sem1t}।"
                )
            return f"{dept_name} ({dept_code}) এর প্রথম সেমিস্টার প্রদেয় {ts}।"
        if has_breakdown:
            return (
                f"The first semester payable for {dept_name} ({dept_code}) is {ts}. "
                f"Breakdown: one-time charges {onet} (admission fee, caution money, registration) "
                f"plus semester fees {sem1t} (tuition, development, other charges)."
            )
        return f"The first semester payable for {dept_name} ({dept_code}) is {ts}."

    def _fmt_semester_fee(
        self, amount: int, sem_num: int, dept_name: str, dept_code: str, lang: str,
        tuition: int, development: int, other: int,
    ) -> str:
        ts = self._format_inr(amount, lang)
        tt = self._format_inr(tuition, lang)
        dt = self._format_inr(development, lang)
        ot = self._format_inr(other, lang)

        if lang == "hi":
            return (
                f"{dept_name} ({dept_code}) का सेमेस्टर {sem_num} शुल्क {ts} है। "
                f"इसमें ट्यूशन फीस {tt}, डेवलपमेंट फीस {dt}, और अन्य सेमेस्टर शुल्क {ot} शामिल हैं।"
            )
        if lang == "bn":
            return (
                f"{dept_name} ({dept_code}) এর সেমিস্টার {sem_num} ফি {ts}। "
                f"এতে টিউশন ফি {tt}, ডেভেলপমেন্ট ফি {dt}, এবং অন্যান্য সেমিস্টার চার্জ {ot} অন্তর্ভুক্ত।"
            )
        return (
            f"The semester {sem_num} fee for {dept_name} ({dept_code}) is {ts}. "
            f"This covers tuition fee of {tt}, development fee of {dt}, "
            f"and other semester charges of {ot}."
        )

    def _format_fee_response(
        self, resp_type: str, dept_code: str, dept_name: str, lang: str,
        result,
    ) -> str | None:
        """Format a language-aware fee response from FeeEngine data.

        resp_type: 'total', 'admission', 'first_semester', 'semester'
        """
        group = result.group_data
        total = result.total_fee or 0
        sem_fee = result.semester_fee or 0
        sem_num = result.semester or 0

        computed = group.computed if group else None
        fsp = computed.first_semester_payable if computed else None
        rsf = computed.regular_semester_fee if computed else None

        components = group.components if group else []

        # Compute one-time charges in semester 1
        one_time_total = sum(
            c.amount for c in components
            if c.type.value == "one_time" and c.charged_in_semester == 1 and not c.is_optional
        )
        # Compute per-semester charges in semester 1
        sem1_comp_total = sum(
            c.amount for c in components
            if c.type.value == "per_semester" and 1 in (c.applicable_semesters or []) and not c.is_optional
        )

        # Tuition, development, other for a specific semester
        tuition = sum(
            c.amount for c in components
            if c.id == "tuition_fee" and not c.is_optional
        )
        development = sum(
            c.amount for c in components
            if c.id == "development_fee" and not c.is_optional
        )
        other = sum(
            c.amount for c in components
            if c.id == "other_semester_charges" and not c.is_optional
        )

        if resp_type == "total":
            return self._fmt_total_fee(total, dept_name, dept_code, lang, fsp, rsf)
        if resp_type == "admission":
            return self._fmt_admission_fee(
                sem_fee, dept_name, dept_code, lang,
                group, one_time_total, sem1_comp_total,
            )
        if resp_type == "first_semester":
            return self._fmt_first_semester(
                sem_fee, dept_name, dept_code, lang,
                one_time_total, sem1_comp_total,
            )
        if resp_type == "semester":
            return self._fmt_semester_fee(
                sem_fee, sem_num, dept_name, dept_code, lang,
                tuition, development, other,
            )
        return None

    def _format_general_fee_info(self, lang: str, engine) -> str:
        """Generate a general fee overview without 'alag se' phrasing."""
        fee_cse_str = self._format_inr(617700, lang)
        fee_ee_str = self._format_inr(567100, lang)
        fee_me_str = self._format_inr(429100, lang)
        try:
            cse_t = engine.get_total_fee("CSE")
            ee_t = engine.get_total_fee("EE")
            me_t = engine.get_total_fee("ME")
            if cse_t.total_fee and ee_t.total_fee and me_t.total_fee:
                fee_cse_str = self._format_inr(cse_t.total_fee, lang)
                fee_ee_str = self._format_inr(ee_t.total_fee, lang)
                fee_me_str = self._format_inr(me_t.total_fee, lang)
        except Exception:
            pass

        if lang == "hi":
            return (
                f"BCREC में B.Tech प्रोग्राम का कुल कोर्स शुल्क शाखा के अनुसार अलग-अलग है। "
                f"CSE, IT, ECE: {fee_cse_str}. "
                f"EE, AIML, DS, CY, CSD: {fee_ee_str}. "
                f"ME, CE: {fee_me_str}. "
                "क्या आप किसी विशेष शाखा की फीस जानना चाहेंगे?"
            )
        if lang == "bn":
            return (
                f"BCREC তে B.Tech প্রোগ্রামের মোট কোর্স ফি শাখা অনুযায়ী আলাদা। "
                f"CSE, IT, ECE: {fee_cse_str}. "
                f"EE, AIML, DS, CY, CSD: {fee_ee_str}. "
                f"ME, CE: {fee_me_str}. "
                "আপনি কি কোনো নির্দিষ্ট শাখার ফি জানতে চান?"
            )
        return (
            f"BCREC offers B.Tech programs with total course fees ranging from "
            f"{fee_me_str} to {fee_cse_str}, depending on the branch. "
            f"CSE, IT, ECE: {fee_cse_str}. "
            f"EE, AIML, DS, CY, CSD: {fee_ee_str}. "
            f"ME, CE: {fee_me_str}. "
            "Would you like fee details for a specific branch?"
        )

    def _handle_fee_query_new(
        self, q: str, lang: str, kb: dict
    ) -> str | None:
        """Fee handler using FeeEngine — dynamic, language-aware responses."""
        fee_intent = re.search(
            r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee)\b", q
        )
        if not fee_intent:
            return None
        logger.info(f"HANDLER (new): fee_intent matched for query='{q[:60]}'")
        try:
            engine = _FeeEngine()
            load_result = engine.load_all()
            if not load_result.is_valid:
                logger.warning(f"FeeEngine validation failed, falling back: {load_result.errors[:2]}")
                return self._handle_fee_query_old(q, lang, kb)
        except Exception as exc:
            logger.error(f"FeeEngine init failed: {exc}")
            return self._handle_fee_query_old(q, lang, kb)

        dept_code = self._extract_dept_code(q)
        if not dept_code:
            if re.search(r"\b(fee structure|fee|fees)\b", q):
                return self._format_general_fee_info(lang, engine)
            return None

        dept_name = dept_code
        if "full_name" in kb.get("courses", {}).get("btech", {}).get(dept_code, {}):
            dept_name = kb["courses"]["btech"][dept_code]["full_name"]["value"]

        # 1. First semester / semester 1
        if re.search(r"\bfirst\s+semester\b|\bsemester\s+1\b", q):
            fr = engine.get_first_semester_payable(dept_code)
            if not fr.error and fr.semester_fee:
                return self._format_fee_response("first_semester", dept_code, dept_name, lang, fr)

        # 2. Specific semester (>= 2)
        sem_match = re.search(r"\bsemester\s*(\d+)\b", q)
        if sem_match:
            sem_num = int(sem_match.group(1))
            if sem_num >= 2:
                sr = engine.get_semester_fee(dept_code, sem_num)
                if not sr.error and sr.semester_fee:
                    return self._format_fee_response("semester", dept_code, dept_name, lang, sr)

        # 3. Admission fee
        if re.search(r"\badmission\s*fee\b", q):
            ar = engine.get_first_semester_payable(dept_code)
            if not ar.error and ar.semester_fee:
                return self._format_fee_response("admission", dept_code, dept_name, lang, ar)

        # 4. Generic semester / per-semester (use sem 2 as regular)
        if re.search(r"\bsemester\s*fee\b|\bper\s*semester\b|\bsem\s*fee\b", q):
            sr = engine.get_semester_fee(dept_code, 2)
            if not sr.error and sr.semester_fee and sr.semester_fee > 0:
                return self._format_fee_response("semester", dept_code, dept_name, lang, sr)
            # Fallback to total (MBA has no per-semester)
            tr = engine.get_total_fee(dept_code)
            if tr.total_fee:
                return self._format_fee_response("total", dept_code, dept_name, lang, tr)

        # 5. Default: total fee
        tr = engine.get_total_fee(dept_code)
        if tr.total_fee:
            return self._format_fee_response("total", dept_code, dept_name, lang, tr)

        return None

    def _handle_fee_query(self, q: str, lang: str, kb: dict) -> str | None:
        """Route fee queries to old or new engine based on feature flag.

        Logs which engine served the response for debugging.
        """
        if _USE_NEW_FEE_ENGINE:
            result = self._handle_fee_query_new(q, lang, kb)
            if result is not None:
                logger.debug("FEE_ENGINE=New")
            return result
        result = self._handle_fee_query_old(q, lang, kb)
        if result is not None:
            logger.debug("FEE_ENGINE=Old")
        return result

    def _structured_lookup(self, query: str, lang: str) -> str | None:
        """Try to answer a query directly from structured canonical KB data.
        Returns a formatted answer string, or None if not found."""
        kb = self._read_canonical_kb()
        if not kb:
            return None

        q = query.strip().lower()

        # --- Combined principal + vice principal lookup ---
        # Handle queries asking about BOTH with a conjunction:
        #   "principal r vice principal ar nam ki"
        #   "principal and vice principal name"
        #   "principal & vice principal"
        # Must have a word like 'and', 'r', '&', 'aur' or ',' between them.
        if (re.search(r"\b(principal|princepal)\b", q)
                and re.search(r"\bvice\b", q)
                and not re.search(r"\badvice\b", q)
                and re.search(r"\b(and|r\b|aur|&|,)", q)):
            principal = kb.get("principal", {})
            vp = kb.get("vice_principal", {})
            p_name = principal.get("name", {}).get("value", "")
            vp_name = vp.get("name", {}).get("value", "")
            if p_name and vp_name:
                logger.info(f"HANDLER: principal_and_vice matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ke principal {p_name} hain aur vice principal {vp_name} hain."
                if lang == "bn":
                    return f"BCREC এর principal {p_name} এবং vice principal {vp_name}।"
                return f"The principal of BCREC is {p_name} and the vice principal is {vp_name}."
            elif p_name:
                logger.info(f"HANDLER: principal+vice → only principal matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ke principal {p_name} hain."
                if lang == "bn":
                    return f"BCREC এর principal {p_name}।"
                return f"The principal of BCREC is {p_name}."
            elif vp_name:
                logger.info(f"HANDLER: principal+vice → only vice matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ke vice principal {vp_name} hain."
                if lang == "bn":
                    return f"BCREC এর vice principal {vp_name}।"
                return f"The vice principal of BCREC is {vp_name}."

        # --- Vice Principal lookup (must be before principal check) ---
        if re.search(r"\bvice[\s-]?(principal|princepal)\b", q):
            vp = kb.get("vice_principal", {})
            name = vp.get("name", {}).get("value", "")
            if name:
                logger.info(f"HANDLER: vice_principal matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ke vice principal {name} hain."
                if lang == "bn":
                    return f"BCREC এর vice principal {name}।"
                return f"The vice principal of BCREC is {name}."

        # --- Principal lookup (handles "principal" and "princepal" typos) ---
        if re.search(r"\b(principal|princepal)\b", q):
            principal = kb.get("principal", {})
            name = principal.get("name", {}).get("value", "")
            if name:
                phone = principal.get("phone", {}).get("value", "")
                logger.info(f"HANDLER: principal matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ke principal {name} hain. Unka phone {phone} hai."
                if lang == "bn":
                    return f"BCREC এর principal {name}। তাঁর ফোন {phone}।"
                return f"The principal of BCREC is {name}. Their phone is {phone}."

        # --- Negativity / complaint / "why not join" handler ---
        if re.search(
            r"\b(not\s*join|negative|bad\s*review|complaints?|nuksan|kharab|buraiya|"
            r"grievance|drawback|disadvantage|criticism|flaw|problem\s*hai|"
            r"dikkat|problem|issue|why\s*not\s*(join|choose|take)|"
            r"tell\s*me\s*(something\s*)?bad|don'?t\s*(join|go|choose)|"
            r"should\s*not|kya\s*bura|bura\s*kya)\b",
            q,
        ):
            logger.info(f"HANDLER: negativity matched for query='{q[:60]}'")
            if lang == "hi":
                return (
                    "Main samajh sakta hoon ki aapke kuch concerns hain. "
                    "BCREC ke baare mein factual information doon — placement, faculty, fees, ya academics? "
                    "Jo bhi aapki specific concern hai, main uske baare mein sahi jaankari de sakta hoon."
                )
            if lang == "bn":
                return (
                    "আমি বুঝতে পারছি আপনার কিছু উদ্বেগ আছে। "
                    "BCREC সম্পর্কে factual তথ্য দিতে পারি — placement, faculty, fees, বা academics? "
                    "আপনার নির্দিষ্ট কোনো concern থাকলে জানান, আমি সঠিক তথ্য দিতে পারব।"
                )
            return (
                "I understand you have some concerns. "
                "I can share factual information about BCRECs placements, faculty, fees, or academics. "
                "Is there a specific area you would like to discuss?"
            )

        # --- Contact info ---
        if re.search(r"\b(contact|phone|mobile|call|helpline|number)\b", q):
            college = kb.get("college", {})
            phones = college.get("phones", {}).get("value", [])
            email = college.get("email", {}).get("value", "")
            if phones:
                phone_str = ", ".join(phones[:3])
                logger.info(f"HANDLER: contact matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC se aap {phone_str} ya email {email} par contact kar sakte hain."
                if lang == "bn":
                    return f"BCREC এ যোগাযোগ করতে পারেন {phone_str} অথবা ইমেইল {email}।"
                return f"BCREC can be reached at {phone_str} or email {email}."

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
                if lang == "hi":
                    return f"Admission ke liye {parts[0]} jaise documents chahiye."
                if lang == "bn":
                    return f"ভর্তির জন্য {parts[0]} এর মতো documents প্রয়োজন।"
                return f"Required documents for admission include {parts[0]}."

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
                if lang == "hi":
                    return f"Admission office se aap {contacts} par baat kar sakte hain."
                if lang == "bn":
                    return f"Admission office এ যোগাযোগ করতে পারেন {contacts}।"
                return f"You can reach the admission office at {contacts}."
            logger.info(f"HANDLER: admission_office (default) matched for query='{q[:60]}'")
            if lang == "hi":
                return "Admission office ka number 0343-2501353 hai."
            if lang == "bn":
                return "Admission office এর নম্বর 0343-2501353।"
            return "The admission office number is 0343-2501353."

        # --- Why BCREC / convince / advantages (language-aware) ---
        # Placed BEFORE admission handler so "why should I take admission" hits the right handler.
        if re.search(
            r"\b(why bcrec|why choose|convince|convins\w*|persuade|kya acha hai|kya khas hai|kyun join karein|"
            r"mujhe bcrec kyun join karna chahiye|bcrec kyun behtar hai|"
            r"bcrec ke fayde|bcrec kyun accha hai|dusre college se behtar|"
            r"why.*admission|kyu.*admission|q\b.*admission|keno.*admission|why.*join.*college)\b",
            q,
        ):
            logger.info(f"HANDLER: why_bcrec matched for query='{q[:60]}'")
            if lang == "hi":
                return (
                    "BCREC ek bahut achha college hai — NBA accredited aur NAAC B+ grade. "
                    "Placement rate 91% hai, average package 4.25 LPA hai aur top companies aati hain. "
                    "Fee bhi reasonable hai, approximately 1.5 lakh per year."
                )
            if lang == "bn":
                return (
                    "BCREC একটি খুব ভালো কলেজ — NBA স্বীকৃত এবং NAAC B+ গ্রেডপ্রাপ্ত। "
                    "প্লেসমেন্ট রেট ৯১%, গড় প্যাকেজ ৪.২৫ LPA এবং টপ কোম্পানি আসে। "
                    "ফিও খুব যুক্তিসঙ্গত, প্রায় ১.৫ লক্ষ টাকা প্রতি বছর।"
                )
            return (
                "BCREC is a great choice — NBA accredited and NAAC B+ graded. "
                "Placement rate is 91 percent with an average package of 4.25 LPA and top recruiters visit regularly. "
                "Fee is also very reasonable at around 1.5 lakh per year."
            )

        # --- Admission process (general) ---
        # Negative lookahead prevents "apply for hostel" from matching here
        # NOTE: Only factual process questions should trigger this handler.
        # Generic intent like "mujhe admission lena hai" goes to LLM.
        if re.search(
            r"\b(admission\s*(process|procedure|criteria|requirements?)|how\s*to\s*apply|apply\s*(for|to)|how\s*can\s*i\s*(get|apply))\b",
            q,
        ) and not re.search(r"\bhostel\b", q) and not re.search(r"\b(convince|convins\w*|persuade)\b", q) and not re.search(r"\b(kon si branch|kaun si branch|which branch|branch choose|branch recommend|best branch|sabse acchi branch|konsa (subject|department|branch))\b", q):
            adm = kb.get("admission", {})
            eligibility = adm.get("eligibility", {}).get("btech", {}).get("value", "")
            entrance = adm.get("eligibility", {}).get("entrance", {}).get("value", "")
            if eligibility:
                logger.info(f"HANDLER: admission_general matched for query='{q[:60]}'")
                if lang == "hi":
                    return (
                        f"B.Tech admission {entrance} ke through hota hai. Eligibility {eligibility} hai. "
                        f"80% seats WBJEE ke through, 10% JEE Main aur 10% Management Quota ke through."
                    )
                if lang == "bn":
                    return (
                        f"B.Tech ভর্তি {entrance} এর মাধ্যমে হয়। যোগ্যতা {eligibility}। "
                        f"80% seats WBJEE, 10% JEE Main এবং 10% Management Quota এর মাধ্যমে।"
                    )
                return (
                    f"B.Tech admission is through {entrance}. Eligibility is {eligibility}. "
                    f"80% seats are through WBJEE, 10% through JEE Main, and 10% through Management Quota."
                )

        # --- Installment / payment plan (checked BEFORE fee to catch "pay fee in installments") ---
        if re.search(r"\b(installments?|installments?|emi|payment\s*plan|pay\s*in\s*part)\b", q):
            payment = kb.get("fees_summary", {}).get("payment_modes", {}).get("value", "")
            if payment:
                logger.info(f"HANDLER: installment matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"Fees {payment} mein pay kar sakte hain."
                if lang == "bn":
                    return f"ফি {payment} এ পরিশোধ করতে পারেন।"
                return f"Fees can be paid through {payment}."
            logger.info(f"HANDLER: installment (default) matched for query='{q[:60]}'")
            if lang == "hi":
                return "Payment options ke liye accounts office 0343-2501353 par contact karein."
            if lang == "bn":
                return "পেমেন্ট অপশনের জন্য accounts office 0343-2501353 নম্বরে যোগাযোগ করুন।"
            return "For payment options, contact the accounts office at 0343-2501353."

        # --- Safety / Anti-ragging (checked BEFORE hostel to preserve existing order) ---
        if re.search(r"\b(safety|safe|ragging|security|women.*safe)\b", q):
            ar = kb.get("anti_ragging", {})
            policy = ar.get("policy", {}).get("value", "")
            reporting = ar.get("reporting", {}).get("value", "")
            safety = ar.get("safety", {}).get("value", "")
            if policy:
                logger.info(f"HANDLER: safety matched for query='{q[:60]}'")
                if lang == "hi":
                    result = f"BCREC mein ragging strictly prohibited hai. "
                    if reporting:
                        result += f"Reporting {reporting}. "
                    if safety:
                        result += f"Women safety helpline {safety}. "
                    result += "Chinta mat kariye, campus bahut safe hai."
                elif lang == "bn":
                    result = f"BCREC এ ragging কঠোরভাবে নিষিদ্ধ। "
                    if reporting:
                        result += f"রিপোর্টিং {reporting}. "
                    if safety:
                        result += f"মহিলা সুরক্ষা হেল্পলাইন {safety}. "
                    result += "চিন্তা করবেন না, ক্যাম্পাস খুবই নিরাপদ।"
                else:
                    result = f"BCREC has a strict anti-ragging policy. "
                    if reporting:
                        result += f"Reporting: {reporting}. "
                    if safety:
                        result += f"Women safety helpline: {safety}. "
                    result += "The campus is very safe."
                return result.strip()
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
                if lang == "hi":
                    return (
                        f"Ji, BCREC mein hostel facility available hai. "
                        f"{total} hostels hain — {boys} boys ke liye aur {girls} girls ke liye — "
                        f"total {capacity} students ki capacity hai."
                    )
                if lang == "bn":
                    return (
                        f"জি, BCREC এ হোস্টেল সুবিধা উপলব্ধ। "
                        f"{total}টি হোস্টেল — {boys}টি ছেলেদের এবং {girls}টি মেয়েদের জন্য — "
                        f"মোট {capacity} শিক্ষার্থীর ধারণক্ষমতা।"
                    )
                return (
                    f"Yes, hostel accommodation is available at BCREC. "
                    f"There are {total} hostels — {boys} for boys and {girls} for girls — "
                    f"with a total capacity of {capacity} students."
                )
            logger.info(f"HANDLER: hostel (unavailable) matched for query='{q[:60]}'")
            return "Hostel accommodation is not currently available at BCREC."

        # --- Fee lookup (routed through _handle_fee_query abstraction) ---
        fee_response = self._handle_fee_query(q, lang, kb)
        if fee_response is not None:
            return fee_response

        # --- Academic failure / backlog / back-paper (checked BEFORE HOD) ---
        if re.search(
            r"\b(backlog|backlag|back.?paper|arrear|supply|supplementary|reappear|fail)"
            r"|back\s+(ache|hoyeche|lag|lagbe|lagse|chole|as)",
            q,
        ):
            logger.info(f"HANDLER: academic_failure matched for query='{q[:60]}' lang={lang}")
            combined_kb = self._read_kb()
            policies = combined_kb.get("voice_ready_answers", {}).get("policies", {})
            answer = (policies.get("answers", {}) or {}).get(lang, "")
            if not answer:
                answer = policies.get("answers", {}).get("en", "")
            if answer:
                # Strip laptop/dress code noise — only return the fail/backlog part
                main_part = re.split(
                    r"Laptops|ল্যাপটপ|लैपटॉप", answer, maxsplit=1
                )[0].strip().rstrip(",")
                if lang == "hi":
                    return f"Koi baat nahi, backlog common hai. {main_part} Aapko kis semester mein backlog aaya hai?"
                if lang == "bn":
                    return f"Chinta korben na, backlog common byapara. {main_part} Kono semester e backlog ache?"
                return f"Don't worry, backlogs are common. {main_part} Which semester has the backlog?"
            logger.warning(f"HANDLER: academic_failure matched but policies.answers missing or empty for lang={lang}, answer_len={len(answer) if answer else 0}")
            return None

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
                    if lang == "hi":
                        return f"{dept_full} department ke HOD {hod_name} hain. Email {email} hai."
                    if lang == "bn":
                        return f"{dept_full} বিভাগের HOD {hod_name}। ইমেইল {email}।"
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
                if lang == "hi":
                    return "Department Heads: " + "; ".join(hod_list[:6]) + "."
                if lang == "bn":
                    return "বিভাগীয় প্রধান: " + "; ".join(hod_list[:6]) + "।"
                return "Department Heads: " + "; ".join(hod_list[:6]) + "."
            return self._lang_hod_unknown(lang)

        # --- Faculty quality (general, before name resolution) ---
        if re.search(r"\b(faculty|faculty.*quality|faculty.*kaisa|faculty.*kaisi|faculty.*kaise|प्रोफेसर|शिक्षक)\b", q):
            if not re.search(r"\b(name|kaun|kaunsa|kaunsi|dr\.?|prof\.?)\b", q):
                logger.info(f"HANDLER: faculty_quality matched for query='{q[:60]}'")
                dept_code = self._extract_dept_code(q)
                if dept_code:
                    if lang == "hi":
                        return f"{dept_code} department ka faculty bahut experienced hai. Research papers bhi publish kiye hain."
                    if lang == "bn":
                        return f"{dept_code} department-র faculty খুব experienced। Research papersও publish করেছে।"
                    return f"The {dept_code} department has experienced faculty with published research papers."
                if lang == "hi":
                    return "BCREC mein 208+ faculty members hain 15 departments mein. Sab experienced hain."
                if lang == "bn":
                    return "BCREC-তে ১৫টি department-তে ২০৮+ faculty member আছে। সবাই experienced।"
                return "BCREC has 208+ faculty members across 15 departments. All are experienced."

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
                        if lang == "hi":
                            return (
                                f"{dept_code} ke placements bahut achhe hain! "
                                f"Rate {rate} hai, average package {avg} LPA hai."
                            )
                        if lang == "bn":
                            return (
                                f"{dept_code} এর প্লেসমেন্ট খুব ভালো! "
                                f"রেট {rate}, গড় প্যাকেজ {avg} LPA।"
                            )
                        return (
                            f"{dept_code} has excellent placements! "
                            f"Placement rate is {rate} with an average package of {avg} LPA."
                        )
            # Overall placement
            overall = placements.get("overall_rate_2025", {}).get("value", "")
            if overall and re.search(r"\b(overall|college|average)\b", q):
                avg_pkg = placements.get("average_package", {}).get("value", "")
                if lang == "hi":
                    return (
                        f"BCREC ka overall placement rate {overall} hai, average package {avg_pkg} hai. "
                        f"Top companies jaise TCS, Infosys, Wipro aati hain."
                    )
                if lang == "bn":
                    return (
                        f"BCREC এর overall placement rate {overall}, গড় প্যাকেজ {avg_pkg}। "
                        f"টপ কোম্পানিগুলোর মধ্যে TCS, Infosys, Wipro রয়েছে।"
                    )
                return (
                    f"BCREC's overall placement rate is {overall} with an average package of {avg_pkg}. "
                    f"Top recruiters include TCS, Infosys, and Wipro."
                )

        # --- Department seat info ---
        if re.search(r"\b(seats|intake|capacity)\b", q):
            logger.info(f"HANDLER: seats matched for query='{q[:60]}'")
            dept_code = self._extract_dept_code(q)
            if dept_code:
                dept_course = kb.get("courses", {}).get("btech", {}).get(dept_code, {})
                intake = dept_course.get("intake", {}).get("value", "")
                if intake:
                    if lang == "hi":
                        return f"{dept_code} mein {intake} seats hain."
                    if lang == "bn":
                        return f"{dept_code} এ {intake} টি seats আছে।"
                    return f"{dept_code} has {intake} seats."
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
                    if lang == "hi":
                        return (
                            f"{dept_code} ka WBJEE cutoff rank 2024 mein {co['2024']} tha, "
                            f"2025 mein {co['2025']} tha. "
                            f"2026 ka estimated {co['2026_est']} hai. Yeh approximate hain."
                        )
                    if lang == "bn":
                        return (
                            f"{dept_code} এর WBJEE cutoff rank 2024 এ {co['2024']}, "
                            f"2025 এ {co['2025']}। "
                            f"2026 এর estimated {co['2026_est']}। এগুলো আনুমানিক।"
                        )
                    return (
                        f"The WBJEE cutoff rank for {dept_code} was {co['2024']} in 2024, "
                        f"{co['2025']} in 2025. "
                        f"The estimated 2026 rank is {co['2026_est']}. These are approximate."
                    )
            return "I don't have the specific cutoff data for that department. Please contact the college admission office for accurate rank information."

        # --- Establishment / founded / history ---
        if re.search(
            r"\b(established|founded|started|founding|when.*start|when.*open|since when|how old)\b",
            q,
        ):
            logger.info(f"HANDLER: establishment matched for query='{q[:60]}'")
            if lang == "hi":
                return (
                    "BCREC August 2000 mein establish hua tha. "
                    "2024-25 session se autonomous college ban gaya hai."
                )
            if lang == "bn":
                return (
                    "BCRECT আগস্ট ২০০০ সালে প্রতিষ্ঠিত হয়। "
                    "২০২৪-২৫ সেশন থেকে autonomous কলেজ হয়েছে।"
                )
            return (
                "BCREC was established in August 2000. "
                "It became autonomous from the 2024-25 session."
            )

        # --- Computer lab timings (before general timings) ---
        if re.search(r"\bcomputer\s*lab|lab\s*timing|lab\s*hours?\b", q):
            logger.info(f"HANDLER: computer_lab matched for query='{q[:60]}'")
            if lang == "hi":
                return "Computer labs Monday to Friday 10:00 AM se 5:30 PM tak khule rehte hain. Saturday aur Sunday band rehte hain."
            if lang == "bn":
                return "কম্পিউটার ল্যাব সোমবার থেকে শুক্রবার সকাল ১০:০০ থেকে বিকাল ৫:৩০ পর্যন্ত খোলা থাকে। শনিবার এবং রবিবার বন্ধ।"
            return "Computer labs are open Monday to Friday, 10:00 AM to 5:30 PM. Closed on Saturday and Sunday."

        # --- Library timings ---
        if re.search(r"\blibrary\s*(timing|hours?)|reading\s*room\b", q):
            logger.info(f"HANDLER: library matched for query='{q[:60]}'")
            if lang == "hi":
                return "Library Monday to Friday 10:00 AM se 5:30 PM tak khuli rehti hai. 80,000 se zyada books hain."
            if lang == "bn":
                return "লাইব্রেরি সোমবার থেকে শুক্রবার সকাল ১০:০০ থেকে বিকাল ৫:৩০ পর্যন্ত খোলা থাকে। ৮০,০০০ এর বেশি বই আছে।"
            return "The library is open Monday to Friday, 10:00 AM to 5:30 PM. It has over 80,000 books."

        # --- College timings ---
        if re.search(
            r"\b(timings?|office hours?|working hours?|college hours?|what.*time|when.*open|when.*close)\b",
            q,
        ):
            logger.info(f"HANDLER: timings matched for query='{q[:60]}'")
            if lang == "hi":
                return "College Monday to Friday 10:00 AM se 5:30 PM tak khula rehta hai. Saturday aur Sunday band rahta hai."
            if lang == "bn":
                return "কলেজ সোমবার থেকে শুক্রবার সকাল ১০:০০ থেকে বিকাল ৫:৩০ পর্যন্ত খোলা থাকে। শনিবার এবং রবিবার বন্ধ।"
            return "College is open Monday to Friday, 10:00 AM to 5:30 PM. Closed on Saturday and Sunday."

        # --- Fee intent guard (prevents department handler from intercepting fee queries) ---
        fee_intent = re.search(
            r"\b(fee|fees|total\s*fee|semester\s*fee|admission\s*fee|course\s*fee)\b", q
        )

        # --- College info (departments) ---
        if (
            re.search(
                r"\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b",
                q,
            )
            and not fee_intent
            and not re.search(
                r"\b(kon si branch|kaun si branch|which branch|branch choose|branch recommend|"
                r"best branch|sabse acchi branch|"
                r"(?:konsa|kon sa|kaunsa) (?:subject|department|branch))\b", q
            )
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
                        result += f" — {intake} seats"
                    return result + "."
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
                if lang == "hi":
                    return "BCREC B.Tech courses: " + "; ".join(course_list[:5]) + "."
                if lang == "bn":
                    return "BCREC এর B.Tech কোর্স: " + "; ".join(course_list[:5]) + "।"
                return "BCREC offers B.Tech in: " + "; ".join(course_list[:5]) + "."
            if lang == "hi":
                return "BCREC mein CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, aur Cyber Security jaise B.Tech programs hain."
            if lang == "bn":
                return "BCREC তে CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, এবং Cyber Security এর মতো B.Tech প্রোগ্রাম আছে।"
            return "BCREC offers B.Tech programs in CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, and Cyber Security."

        # --- Scholarship ---
        if re.search(r"\b(scholarship|scholership|scolarship|schollarship)", q):
            logger.info(f"HANDLER: scholarship matched for query='{q[:60]}'")
            is_cancellation = re.search(
                r"\b(cancel|band|stop|kat|cancel\s+ho|cancel\s+hoe|rukh|rukn|hata|khatam)\b", q
            )
            if is_cancellation:
                if lang == "hi":
                    return (
                        "Scholarship cancellation ke alag-alag niyam alag scholarship ke liye hote hain. "
                        "Aap kaun si scholarship le rahe hain — SVMCM, Aikyashree, OASIS, TFW, "
                        "ya koi aur? Naam batao to main sahi jaankari de sakta hoon."
                    )
                if lang == "bn":
                    return (
                        "Scholarship cancellation er niyom alada alada scholarship er jonno alada. "
                        "Apni konta scholarship nichen — SVMCM, Aikyashree, OASIS, TFW, "
                        "na onno kichu? Naam bolle ami thik jankti dite parbo."
                    )
                return (
                    "Scholarship cancellation rules depend on which scholarship you have. "
                    "Which one are you receiving — SVMCM, Aikyashree, OASIS, TFW, or another? "
                    "Let me know and I can give you the correct information."
                )
            schemes = kb.get("scholarships", {}).get("schemes", {})
            names = []
            for key, sch in schemes.items():
                name = sch.get("name", {}).get("value", "")
                if name:
                    names.append(name)
            if names:
                if lang == "hi":
                    return (
                        f"BCREC mein {', '.join(names)} jaise scholarship options hain. "
                        f"Kya aap chahte hain main aapki eligibility check karoon?"
                    )
                if lang == "bn":
                    return (
                        f"BCREC তে {', '.join(names)} এর মতো scholarship options আছে। "
                        f"আপনি কি চান আমি আপনার eligibility check করি?"
                    )
                return (
                    f"BCREC offers scholarships like {', '.join(names)}. "
                    f"Would you like me to check your eligibility?"
                )
            return self._lang_response_unknown(lang)
        # --- Counselling ---
        if re.search(r"\b(counselling|counseling)\b", q):
            logger.info(f"HANDLER: counselling matched for query='{q[:60]}'")
            counselling = kb.get("admission", {}).get("counseling", {}).get("value", "")
            if counselling:
                if lang == "hi":
                    return f"Admission counselling {counselling} ke through hota hai."
                if lang == "bn":
                    return f"Admission counselling {counselling} এর মাধ্যমে হয়।"
                return f"Admission counselling for BCREC is conducted through {counselling}."
            return self._lang_response_unknown(lang)

        # --- Eligibility based on marks/percentage ---
        if re.search(r"\b(eligibility|eligible|marks?|percentage|qualif)\b", q):
            logger.info(f"HANDLER: eligibility matched for query='{q[:60]}'")
            adm = kb.get("admission", {})
            eligibility = adm.get("eligibility", {}).get("btech", {}).get("value", "")
            entrance = adm.get("eligibility", {}).get("entrance", {}).get("value", "")
            if eligibility:
                if lang == "hi":
                    return (
                        f"B.Tech ke liye eligibility {eligibility} hai, entrance {entrance} hai. "
                        f"Aapne kitna percentage laya hai?"
                    )
                if lang == "bn":
                    return (
                        f"B.Tech এর জন্য যোগ্যতা {eligibility}, প্রবেশিকা {entrance}। "
                        f"আপনি কত percent পেয়েছেন?"
                    )
                return (
                    f"Eligibility for B.Tech is {eligibility} through {entrance}. "
                    f"What percentage did you score?"
                )
            return self._lang_response_unknown(lang)

        # --- Branch recommendation (which branch to choose, language-aware) ---
        # Covers: "konsa department lu", "ap bolo konsa acha hoga", "kon sa better hai",
        # "suggest karo", "recommend karo", "batao konsa", etc.
        if re.search(
            r"\b(kon si branch|kaun si branch|which branch|branch choose|"
            r"konsa department (?:lu|lena|choose|loon|loonga|chahiye)|"
            r"kon sa department (?:lu|lena|choose|loon|loonga|chahiye)|"
            r"kaunsa department (?:lu|lena|choose|loon|loonga|chahiye)|"
            r"konsa subject (?:lu|lena|choose|loon|loonga|chahiye)|"
            r"konsa branch (?:lu|lena)|"
            r"kon sa branch (?:lu|lena)|"
            r"kaunsa branch (?:lu|lena)|"
            r"konsa acha hoga|konsa accha rahega|kon sa better hai|"
            r"konsa lena chahiye|kon sa lena chahiye|mujhe konsa lena chahiye|"
            r"konsa sahi rahega|kon sa sahi rahega|"
            r"mujhe branch chuni hai|mujhe konsa branch lena chahiye|"
            r"best branch|sabse acchi branch|"
            r"kon department choose korbo|"
            r"suggest karo|recommend karo|suggestion do|"
            r"suggest konsa|recommend konsa|batao konsa|btaiye konsa|bolo konsa)\b",
            q,
        ):
            logger.info(f"HANDLER: branch_recommendation matched for query='{q[:60]}'")
            if lang == "hi":
                return (
                    "Ji, aapke interest ke hisaab se main suggest kar sakta hoon! "
                    "Aapko kis field mein interest hai — coding, AI aur Machine Learning, hardware aur circuits, "
                    "ya manufacturing aur construction?"
                )
            if lang == "bn":
                return (
                    "আপনার আগ্রহ অনুযায়ী আমি suggest করতে পারি! "
                    "আপনার কোন field এ interest — coding, AI এবং Machine Learning, hardware এবং circuits, "
                    "নাকি manufacturing এবং construction?"
                )
            return (
                "I can suggest a branch based on your interest! "
                "What field interests you — coding, AI and Machine Learning, hardware and circuits, "
                "or manufacturing and construction?"
            )

        # --- "What else" / "or kya" follow-up — let LLM handle with conversation history ---
        if re.search(
            r"\b(or kya|aur kya|or kya kya|what else|anything else|"
            r"aur batao|or batao|kya aur|kya aur hai|kya kya hai|or kya he|or kya acha)\b",
            q,
        ):
            logger.info(f"HANDLER: or_kya follow-up — passing through to LLM")
            return None

        # --- Campus visit ---
        if re.search(r"\bcampus\s*visit\b|\bvisit\s*campus\b|\btour\b", q):
            logger.info(f"HANDLER: campus_visit matched for query='{q[:60]}'")
            if lang == "hi":
                return "Aap BCREC campus visit kar sakte hain. College Monday to Friday 10:00 AM se 5:30 PM tak khula rehta hai. Schedule ke liye 0343-2501353 par call karein."
            if lang == "bn":
                return "আপনি BCREC ক্যাম্পাস ভিজিট করতে পারেন। কলেজ সোমবার থেকে শুক্রবার সকাল ১০:০০ থেকে বিকাল ৫:৩০ পর্যন্ত খোলা থাকে। শিডিউলের জন্য 0343-2501353 নম্বরে কল করুন।"
            return "You are welcome to visit the BCREC campus. College is open Monday to Friday, 10:00 AM to 5:30 PM. Call 0343-2501353 to schedule a visit."

        # --- College email (standalone, without "contact" context which is handled above) ---
        if re.search(r"\bemail\b", q) and not re.search(r"\b(contact|phone|mobile|call|helpline|number)\b", q):
            college = kb.get("college", {})
            email = college.get("email", {}).get("value", "")
            if email:
                logger.info(f"HANDLER: email matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ka email address {email} hai."
                if lang == "bn":
                    return f"BCREC এর ইমেইল {email}।"
                return f"The college email address is {email}."
            if lang == "hi":
                return "BCREC ka email info@bcrec.ac.in hai."
            if lang == "bn":
                return "BCREC এর ইমেইল info@bcrec.ac.in।"
            return "The college email is info@bcrec.ac.in."

        # --- College address (standalone, without "contact" context) ---
        if re.search(r"\baddress\b", q) and not re.search(r"\b(contact|phone|mobile|call|helpline|number)\b", q):
            college = kb.get("college", {})
            addr = college.get("address", {}).get("value", "")
            if addr:
                logger.info(f"HANDLER: address matched for query='{q[:60]}'")
                if lang == "hi":
                    return f"BCREC ka address {addr} hai."
                if lang == "bn":
                    return f"BCREC এর ঠিকানা {addr}।"
                return f"BCREC is located at {addr}."
            if lang == "hi":
                return "BCREC ka address — Jemua Road, Fuljhore, Durgapur - 713206, West Bengal hai."
            if lang == "bn":
                return "BCREC এর ঠিকানা — Jemua Road, Fuljhore, Durgapur - 713206, West Bengal।"
            return "BCREC is located at Jemua Road, Fuljhore, Durgapur - 713206, West Bengal."

        # --- How to reach / directions ---
        if re.search(r"\b(reach|direction|route|map|kaise\s*(pahuche?|jaaye?|aaye?)|kivabe\s*(pou?chbo|jabo|asbo)|kemon\s*?(ja?bo|yaben)|raasta|rasta|way\s*to)\b", q):
            logger.info(f"HANDLER: directions matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC Durgapur mein, Jemua Road, Fuljhore mein hai. Aap Durgapur station se auto ya cab le sakte hain. Address: Jemua Road, Fuljhore, Durgapur - 713206."
            if lang == "bn":
                return "BCREC দুর্গাপুরে, Jemua Road, Fuljhore-এ অবস্থিত। আপনি দুর্গাপুর স্টেশন থেকে অটো বা ক্যাব নিতে পারেন। ঠিকানা: Jemua Road, Fuljhore, Durgapur - 713206।"
            return "BCREC is in Durgapur on Jemua Road, Fuljhore. You can take an auto or cab from Durgapur station. Address: Jemua Road, Fuljhore, Durgapur - 713206."

        # --- College website ---
        if re.search(r"\b(website|site|online\s*portal|web.*address)\b", q):
            logger.info(f"HANDLER: website matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC ki official website www.bcrec.ac.in hai. Wahan aapko sabhi details mil jaayengi."
            if lang == "bn":
                return "BCREC এর অফিসিয়াল ওয়েবসাইট www.bcrec.ac.in। সেখানে সব তথ্য পাবেন।"
            return "The official BCREC website is www.bcrec.ac.in. You will find all details there."

        # --- Affiliation / recognition ---
        if re.search(r"\b(affiliation|affiliated|recogni|recognised|recognized|under\s*which\s*university|approved\s*by|permanent\s*affiliation)\b", q):
            logger.info(f"HANDLER: affiliation matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC Maulana Abul Kalam Azad University of Technology, West Bengal se affiliated hai, AICTE approved hai, aur 2024-25 se autonomous college hai."
            if lang == "bn":
                return "BCREC Maulana Abul Kalam Azad University of Technology, West Bengal এর অধিভুক্ত, AICTE অনুমোদিত, এবং ২০২৪-২৫ থেকে autonomous কলেজ।"
            return "BCREC is affiliated to Maulana Abul Kalam Azad University of Technology, West Bengal, approved by AICTE, and is autonomous from the 2024-25 session."

        # --- Accreditation / NBA / NAAC ---
        if re.search(r"\b(nba|naac|grade|accredit|accreditation|certif)\b", q):
            logger.info(f"HANDLER: accreditation matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC NAAC B+ grade (CGPA 2.83) hai aur CSE, ECE, IT, EE, ME NBA accredited hain."
            if lang == "bn":
                return "BCRECT NAAC B+ গ্রেড (CGPA ২.৮৩) এবং CSE, ECE, IT, EE, ME NBA স্বীকৃত।"
            return "BCREC is NAAC B+ grade (CGPA 2.83) and has NBA accreditation for CSE, ECE, IT, EE, ME."

        # --- Admission last date / deadline ---
        if re.search(r"\b(last\s*date|deadline|closing\s*date|admission\s*till|last\s*day|kab\s*tak|f.or\s*tak|last\s*chance)\b", q):
            logger.info(f"HANDLER: admission_deadline matched for query='{q[:60]}'")
            if lang == "hi":
                return "Admission dates ke liye kripya college ko call karein 0343-2501353 par. WBJEE counselling ke through admission hota hai aur uski dates WBJEE board announce karta hai."
            if lang == "bn":
                return "ভর্তির তারিখের জন্য অনুগ্রহ করে কলেজে 0343-2501353 নম্বরে কল করুন। WBJEE কাউন্সেলিং এর মাধ্যমে ভর্তি হয় এবং তারিখগুলো WBJEE বোর্ড announces করে।"
            return "For admission dates, please call the college at 0343-2501353. Admission is through WBJEE counselling and dates are announced by the WBJEE board."

        # --- Dean ---
        if re.search(r"\bdean\b", q):
            logger.info(f"HANDLER: dean matched for query='{q[:60]}'")
            if lang == "hi":
                return "Dean ke baare mein jaankari ke liye college office 0343-2501353 par contact karein."
            if lang == "bn":
                return "Dean সম্পর্কে জানতে কলেজ অফিসে 0343-2501353 নম্বরে যোগাযোগ করুন।"
            return "For dean details, please contact the college office at 0343-2501353."

        # --- Chairman ---
        if re.search(r"\bchairman\b", q):
            logger.info(f"HANDLER: chairman matched for query='{q[:60]}'")
            if lang == "hi":
                return "Chairman ke baare mein jaankari ke liye college office 0343-2501353 par contact karein."
            if lang == "bn":
                return "Chairman সম্পর্কে জানতে কলেজ অফিসে 0343-2501353 নম্বরে যোগাযোগ করুন।"
            return "For chairman details, please contact the college office at 0343-2501353."

        # --- Canteen / food facilities ---
        if re.search(r"\b(canteen|cafeteria|food|mess|khana|khabar)\b", q):
            logger.info(f"HANDLER: canteen matched for query='{q[:60]}'")
            if lang == "hi":
                return "Ji, BCREC mein canteen facility available hai. Students ke liye khane ki achhi arrangement hai."
            if lang == "bn":
                return "জি, BCREC এ canteen facility আছে। ছাত্রদের খাওয়ার ভালো ব্যবস্থা আছে।"
            return "Yes, BCREC has a canteen facility with good food arrangements for students."

        # --- Laboratory facilities ---
        if re.search(r"\b(laborator|lab\s*facility|lab\s*available|lab\s*equipment|laboratory\s*facility)\b", q):
            logger.info(f"HANDLER: lab_facilities matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC mein sabhi departments ke liye well-equipped laboratories hain. Computer lab bhi available hai."
            if lang == "bn":
                return "BCRECT সব বিভাগের জন্য well-equipped laboratories আছে। কম্পিউটার ল্যাবও উপলব্ধ।"
            return "BCREC has well-equipped laboratories for all departments. Computer labs are also available."

        # --- Sports facilities ---
        if re.search(r"\b(sport|playground|ground|gym|play\s*field|indoor|outdoor\s*game|khel|khela|krida)\b", q):
            logger.info(f"HANDLER: sports matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC mein sports facilities hain — playground, indoor games aur sports events hote hain."
            if lang == "bn":
                return "BCRECT খেলাধূলার সুবিধা আছে — playground, indoor games এবং sports events হয়।"
            return "BCREC has sports facilities including a playground, indoor games, and regular sports events."

        # --- Faculty list / faculty count ---
        if re.search(r"\b(faculty\s*list|list\s*of\s*faculty|all\s*faculty|faculty\s*member|teachers?\s*list|how\s*many\s*faculty|total\s*faculty|faculty\s*strength|faculty\s*count|kitne\s*faculty|koto\s*faculty|professor\s*list)\b", q):
            logger.info(f"HANDLER: faculty_list matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC mein 208 se zyada faculty members hain 15 departments mein. Kisi specific department ki faculty chahiye to batao."
            if lang == "bn":
                return "BCREC এ ২০৮ এর বেশি faculty members আছে ১৫ টি department এ। কোনো নির্দিষ্ট department এর faculty চাইলে জানান।"
            return "BCREC has over 208 faculty members across 15 departments. Let me know if you need faculty from a specific department."

        # --- Student strength / total students ---
        if re.search(r"\b(total\s*student|student\s*strength|how\s*many\s*student|intake\s*total|kitne\s*student|koto\s*student|student\s*population|number\s*of\s*student|students?\s*count)\b", q):
            logger.info(f"HANDLER: student_strength matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC mein total students ki sankhya 3000 ke aas-paas hai, har saal 600-700 naye students admit hote hain."
            if lang == "bn":
                return "BCREC তে মোট students সংখ্যা প্রায় ৩০০০, প্রতিবছর ৬০০-৭০০ নতুন students ভর্তি হয়।"
            return "BCREC has approximately 3000 total students, with 600-700 new students admitted each year."

        # --- College type / government / private ---
        if re.search(r"\b(government|private|aided|college\s*type|kya\s*college|kon\s*dhoroner|sarkari|bessarkari)\b", q):
            logger.info(f"HANDLER: college_type matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC ek private engineering college hai, jo MAKAUT, West Bengal se affiliated hai aur AICTE approved hai."
            if lang == "bn":
                return "BCRECT একটি private engineering college, যা MAKAUT, West Bengal এর অধিভুক্ত এবং AICTE অনুমোদিত।"
            return "BCREC is a private engineering college affiliated to MAKAUT, West Bengal and approved by AICTE."

        # --- Approvals (AICTE, UGC, etc.) ---
        if re.search(r"\b(approval|approved|aicte|ugc|dte)\b", q):
            logger.info(f"HANDLER: approval matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC AICTE approved hai aur MAKAUT, West Bengal se affiliated hai. 2024-25 se autonomous status mil gaya hai."
            if lang == "bn":
                return "BCRECT AICTE অনুমোদিত এবং MAKAUT, West Bengal এর অধিভুক্ত। ২০২৪-২৫ থেকে autonomous status পেয়েছে।"
            return "BCREC is AICTE approved and affiliated to MAKAUT, West Bengal. It has autonomous status from 2024-25."

        # --- How many departments / total departments ---
        if re.search(r"\b(how\s*many\s*department|total\s*department|list\s*all\s*department|departments?\s*offer|department\s*count)\b", q):
            logger.info(f"HANDLER: department_count matched for query='{q[:60]}'")
            if lang == "hi":
                return "BCREC mein total 15 departments hain. B.Tech programs: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, aur Cyber Security."
            if lang == "bn":
                return "BCREC তে মোট ১৫ টি department আছে। B.Tech programs: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, এবং Cyber Security।"
            return "BCREC has 15 departments. B.Tech programs: CSE, IT, ECE, EE, ME, CE, CSD, AIML, Data Science, and Cyber Security."

        return None

    # -----------------------------------------------------------------------
    # Task 4 — Fuzzy Name Resolution for Faculty
    # -----------------------------------------------------------------------
    _FACULTY_ALIASES: Dict[str, str] = {
        "chandan chattoraj": "Dr. Chandan Chattoraj",
        "dr chandan chattoraj": "Dr. Chandan Chattoraj",
        "chandan bandopadhyay": "Dr. Chandan Bandyopadhyay",
        "chandan bandyopadhyay": "Dr. Chandan Bandyopadhyay",
        "chandan bandopaddhyay": "Dr. Chandan Bandyopadhyay",
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
            name = hod.get("name", {}).get("value", "") if isinstance(hod.get("name"), dict) else hod.get("name", "")
            if name:
                idx.append((name.lower(), name, code))
            # Index individual faculty members
            faculty_list = data.get("faculty", [])
            for f in faculty_list:
                fname = f.get("name", "")
                if fname:
                    idx.append((fname.lower(), fname, code))
        # First-year (BSH) faculty
        first_year = kb.get("first_year", {})
        if first_year:
            hod = first_year.get("hod", {})
            hname = hod.get("name", "") if isinstance(hod.get("name"), str) else ""
            if hname:
                idx.append((hname.lower(), hname, "BSH (First Year)"))
            for f in first_year.get("faculty", []):
                fname = f.get("name", "")
                if fname:
                    idx.append((fname.lower(), fname, "BSH"))
        # Principal & VP
        principal = kb.get("principal", {}).get("name", {}).get("value", "")
        vp = kb.get("vice_principal", {}).get("name", {}).get("value", "")
        if not principal:
            principal = kb.get("principal", {}).get("name", "")
        if not vp:
            vp = kb.get("vice_principal", {}).get("name", "")
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
                    name = hod.get("name", "")
                    if isinstance(name, dict):
                        name = name.get("value", "")
                    if name and canonical.lower() in name.lower():
                        dept_name = f" (HOD of {code})"
                        break
                if "principal" in canonical.lower():
                    dept_name = " (Principal, BCREC)"
                return f"Kya aap {canonical}{dept_name} ke baare mein poochh rahe hain?"

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
            "how", "was", "who", "what", "when", "where", "why",
            "kaisa", "kese", "kesa", "hai", "hain", "he", "ho",
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
                return f"Kya aap {best_display}{dept_suffix} ke baare mein poochh rahe hain?"
                return f"{best_display}{dept_suffix} hain."
        if best_score >= 0.5:
            return f"Kya aap {best_display} ke baare mein poochh rahe hain?"
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

    # -----------------------------------------------------------------------
    # ConversationState helpers — cross-domain follow-up resolution
    # -----------------------------------------------------------------------

    def _get_or_create_state(self, session_id: str) -> ConversationState:
        if session_id not in self._session_states:
            self._session_states[session_id] = ConversationState()
        return self._session_states[session_id]

    def _push_domain_visit(self, session_id: str, domain: str) -> None:
        """Record a visit to a domain, moving it to the most-recent position."""
        state = self._get_or_create_state(session_id)
        if domain not in state.slots:
            state.slots[domain] = DomainSlot(domain=domain, last_updated=int(time.time()))
        if domain in state.visit_order:
            state.visit_order.remove(domain)
        state.visit_order.append(domain)

    def _match_hostel_subtype(self, query: str) -> str | None:
        q = query.lower()
        for w in sorted(self._HOSTEL_SUBTYPE_KEYWORDS, key=len, reverse=True):
            if w in q:
                return w
        return None

    def _match_admission_subtype(self, query: str) -> str | None:
        q = query.lower()
        for w in sorted(self._ADMISSION_SUBTYPE_KEYWORDS, key=len, reverse=True):
            if w in q:
                return w
        return None

    def clear_session(self, session_id: str) -> None:
        """Clear a session's memory and language state. Called when session ends."""
        self._sessions.pop(session_id, None)
        self._session_langs.pop(session_id, None)
        self._session_states.pop(session_id, None)

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

    def _lang_fee_response(self, lang: str, fee_type: str, dept: str, amount: int, admission: int, per_sem: int) -> str:
        """Return a language-appropriate fee response."""
        amount_str = self._format_inr(amount, lang)
        if lang == "hi":
            if fee_type == "semester":
                return f"{dept} ka semester fee {amount_str} hai. Admission fee alag se hai."
            if fee_type == "admission":
                return f"{dept} ka admission fee {self._format_inr(admission, lang)} hai. Semester fee alag hai."
            return f"{dept} ka total fee {amount_str} hai. Admission aur semester fee alag se hain."
        if lang == "bn":
            if fee_type == "semester":
                return f"{dept} এর সেমিস্টার ফি {amount_str}। ভর্তি ফি আলাদা।"
            if fee_type == "admission":
                return f"{dept} এর ভর্তি ফি {self._format_inr(admission, lang)}। সেমিস্টার ফি আলাদা।"
            return f"{dept} এর মোট ফি {amount_str}। ভর্তি এবং সেমিস্টার ফি আলাদা।"
        if fee_type == "semester":
            return f"The semester fee for {dept} is {amount_str}. Admission fee is separate."
        if fee_type == "admission":
            return f"The admission fee for {dept} is {self._format_inr(admission, 'en')}. Semester fee is separate."
        return f"The total fee for {dept} is {amount_str}. Admission and semester fees are separate."

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

            # 0.4 Hindi keyword normalization — converts Hindi domain terms to English
            # so ALL English handlers work with Hindi text automatically
            if re.search(r'[\u0900-\u097F\u0980-\u09FF]', query):
                for hindi, english in HINDI_KEYWORD_MAP.items():
                    if hindi in query:
                        query = query.replace(hindi, english)
                logger.info(f"[{session_id}] Hindi normalized: '{query[:60]}'")

            # 0.45 Hinglish/Banglish normalization — common abbreviations used in texting
            # "q" before admission-related words = "kyu" (why) in Hindi
            if re.search(r'\bq\b', query) and re.search(r'\b(admission|join|lu|loon|loonga)\b', query, re.IGNORECASE):
                query = re.sub(r'\bq\b', 'kyu', query, flags=re.IGNORECASE)
                logger.info(f"[{session_id}] Hinglish normalization: 'q' -> 'kyu'")
            # "keno" = "why" in Bengali (কেন)
            if re.search(r'\bkeno\b', query) and re.search(r'\b(admission|join|nebo|nibo|hobe|korbo)\b', query, re.IGNORECASE):
                query = re.sub(r'\bkeno\b', 'why', query, flags=re.IGNORECASE)
                logger.info(f"[{session_id}] Banglish normalization: 'keno' -> 'why'")

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

            # 0.6 Standalone yes/no — single-word acknowledgment not in "would you like" context
            q_lower = query.strip().lower()
            if q_lower in ("yes", "yeah", "yep", "हाँ", "जी", "जी हाँ", "হ্যাঁ", "জী", "জী হ্যাঁ"):
                lang = self._session_langs.get(session_id, "en")
                ack_map = {"hi": ACKNOWLEDGMENT_HI, "bn": ACKNOWLEDGMENT_BN}
                ack = ack_map.get(lang, ACKNOWLEDGMENT_EN)
                logger.info(f"[{session_id}] Standalone yes — acknowledgment")
                self._append_session_turn(session_id, query, ack)
                return {
                    "answer": ack, "voice_text": ack, "source": "yes_no_continuation",
                    "model": "none", "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True, "tokens": {"prompt": 0, "completion": 0}, "cache_hit": False,
                }
            if q_lower in ("no", "nah", "nope", "नहीं", "जी नहीं", "না", "জী না"):
                lang = self._session_langs.get(session_id, "en")
                ack_map = {"hi": ACKNOWLEDGMENT_HI, "bn": ACKNOWLEDGMENT_BN}
                ack = ack_map.get(lang, ACKNOWLEDGMENT_EN)
                logger.info(f"[{session_id}] Standalone no — acknowledgment")
                self._append_session_turn(session_id, query, ack)
                return {
                    "answer": ack, "voice_text": ack, "source": "yes_no_continuation",
                    "model": "none", "latency_ms": round((time.time() - start) * 1000),
                    "hallucination_validated": True, "tokens": {"prompt": 0, "completion": 0}, "cache_hit": False,
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
                # Dedup: if already greeted, return short response
                if session_id in self._greeted_sessions:
                    short_greeting = {
                        "en": "Hello! I'm here to help. What would you like to know about BCREC?",
                        "hi": "Namaste! Aapko BCREC ke baare mein kya jaanna hai?",
                        "bn": "নমস্কার! আপনি BCREC সম্পর্কে কী জানতে চান?",
                    }.get(lang, "Hello! I'm here to help. What would you like to know about BCREC?")
                    self._append_session_turn(session_id, query, short_greeting)
                    return {
                        "answer": short_greeting, "voice_text": short_greeting,
                        "source": "greeting_dedup", "model": "none",
                        "latency_ms": round((time.time() - start) * 1000),
                        "hallucination_validated": True,
                        "tokens": {"prompt": 0, "completion": 0}, "cache_hit": False,
                    }

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
                self._greeted_sessions.add(session_id)
                return {
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

            # 2.9 Structured lookup — KB handlers for known query types
            # Handles backlog, fees, admission, HOD, principal, contact, etc.
            # Only falls through to LLM when no handler matches.
            _profiler.mark("structured_lookup")
            structured_result = self._structured_lookup(query, lang)
            if structured_result:
                logger.info(
                    f"[{session_id}] Structured lookup hit (len={len(structured_result)})"
                )
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    detected_language=lang,
                    detected_intent="structured_lookup",
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

            # 2.9.5 LLM + Tool-calling — single path for ALL other queries
            # The LLM handles intent, follow-ups, profanity, mixed language naturally.
            # Tools provide exact data (fees, contacts, etc.) when the LLM requests them.
            _profiler.mark("llm_tools_start")

            # Build messages: system prompt + history + current query
            lang_prefix = {
                "bn": "CRITICAL LANGUAGE RULE: The user is writing in Banglish (Roman Bengali). You MUST reply in Banglish. Never use Hindi. If unsure, default to Banglish.\n\n",
                "hi": "CRITICAL LANGUAGE RULE: The user is writing in Hindi. You MUST reply in Roman Hindi (NOT Devanagari script). Never use Bengali or English words.\n\n",
                "en": "CRITICAL LANGUAGE RULE: The user is writing in English. Reply in English.\n\n",
            }.get(lang, "")
            lang_hint = {
                "bn": " The user's language is Banglish (Roman Bengali). Reply ONLY in Banglish. Do NOT use Hindi words.",
                "hi": " The user's language is Hindi. Reply ONLY in Roman Hindi (NOT Devanagari script). Do NOT use Bengali words.",
                "en": " Reply in English.",
            }.get(lang, "")
            messages = [{"role": "system", "content": lang_prefix + SYSTEM_PROMPT}]
            if history:
                for turn in history[-10:]:
                    role = turn.get("role", "user")
                    content = turn.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": query + lang_hint})

            # Call LLM with tools — let it decide whether to use tools or answer directly
            answer = await self._call_llm_with_tools(messages, session_id, query, start, lang)
            _profiler.mark("llm_response")

            # Cap response length for TTS
            if len(answer) > MAX_VOICE_RESPONSE_CHARS:
                truncated = answer[:MAX_VOICE_RESPONSE_CHARS]
                last_period = max(truncated.rfind(". "), truncated.rfind("। "))
                if last_period > MAX_VOICE_RESPONSE_CHARS // 2:
                    answer = truncated[: last_period + 1]
                else:
                    answer = truncated.rsplit(" ", 1)[0] + "."

            latency_ms = round((time.time() - start) * 1000)
            response_payload = {
                "answer": answer,
                "voice_text": answer,
                "source": "llm_tools",
                "model": self.model,
                "latency_ms": latency_ms,
                "hallucination_validated": True,
                "tokens": {"prompt": 0, "completion": 0},
                "cache_hit": False,
            }

            self._append_session_turn(session_id, query, answer)

            if _sp_enabled():
                response_payload = _sp_post(self, query, response_payload, lang)
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

            # 0.4 Hindi keyword normalization — converts Hindi domain terms to English
            if re.search(r'[\u0900-\u097F\u0980-\u09FF]', query):
                for hindi, english in HINDI_KEYWORD_MAP.items():
                    if hindi in query:
                        query = query.replace(hindi, english)
                logger.info(f"[{session_id}] Hindi normalized (stream): '{query[:60]}'")

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

            # Structured lookup (stream path) — KB handlers for known query types
            structured_result = self._structured_lookup(query, lang)
            if structured_result:
                logger.info(
                    f"[{session_id}] Structured lookup hit (stream, len={len(structured_result)})"
                )
                telemetry.log_turn_input(
                    session_id,
                    turn_number=turn_number,
                    raw_transcript=query,
                    detected_language=lang,
                    detected_intent="structured_lookup",
                )
                for word in structured_result.split():
                    yield word + " "
                    await asyncio.sleep(0.02)
                if conversation_history is None:
                    self._append_session_turn(session_id, query, structured_result)
                return

            # LLM + Tool-calling (stream path) — tool resolution + streaming
            # Build messages: system prompt + history + current query
            lang_prefix = {
                "bn": "CRITICAL LANGUAGE RULE: The user is writing in Banglish (Roman Bengali). You MUST reply in Banglish. Never use Hindi. If unsure, default to Banglish.\n\n",
                "hi": "CRITICAL LANGUAGE RULE: The user is writing in Hindi. You MUST reply in Roman Hindi (NOT Devanagari script). Never use Bengali or English words.\n\n",
                "en": "CRITICAL LANGUAGE RULE: The user is writing in English. Reply in English.\n\n",
            }.get(lang, "")
            lang_hint = {
                "bn": " The user's language is Banglish (Roman Bengali). Reply ONLY in Banglish. Do NOT use Hindi words.",
                "hi": " The user's language is Hindi. Reply ONLY in Roman Hindi (NOT Devanagari script). Do NOT use Bengali words.",
                "en": " Reply in English.",
            }.get(lang, "")
            messages = [{"role": "system", "content": lang_prefix + SYSTEM_PROMPT}]
            if history:
                for turn in history[-10:]:
                    role = turn.get("role", "user")
                    content = turn.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": query + lang_hint})

            # Resolve tool calls (non-streaming, up to 4 turns), then stream final answer
            answer = await self._call_llm_with_tools(messages, session_id, query, t0, lang)

            # Safety net: truncate long responses for voice
            words = answer.split()
            if len(words) > 80:
                import re as _re
                sentences = _re.split(r'(?<=[.!?।])\s+', answer)
                if len(sentences) >= 2:
                    answer = sentences[0] + " " + sentences[1]
                else:
                    answer = " ".join(words[:60]) + "."
                logger.info(f"TRUNCATED: response to {len(answer.split())} words")

            # Stream the answer word by word
            for word in answer.split():
                yield word + " "
                await asyncio.sleep(0.02)
            return

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
