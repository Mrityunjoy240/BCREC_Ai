import logging
import re
from enum import Enum
from typing import Optional

from .context import ConversationContext

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    GREETING = "greeting"
    AUDIO_CHECK = "audio_check"
    THANKS = "thanks"
    GOODBYE = "goodbye"
    SMALL_TALK = "small_talk"
    CONFIRMATION = "confirmation"
    FOLLOW_UP = "follow_up"
    COLLEGE_INFO = "college_info"


GREETING_PATTERNS = [
    "hello",
    "hi",
    "hey",
    "hii",
    "hiii",
    "namaste",
    "namaskar",
    "namaskaram",
    "vanakkam",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "hola",
    "bonjour",
    # Devanagari (Hindi/Sanskrit)
    "नमस्ते",
    "नमस्कार",
    "नमो नमः",
    "प्रणाम",
    # Bengali
    "নমস্কার",
    "হ্যালো",
    "হাই",
]

AUDIO_CHECK_PATTERNS = [
    "can you hear me",
    "can u hear me",
    "am i audible",
    "are you there",
    "you there",
    "hello hello",
    "testing",
    "test test",
    "is this working",
    "checking",
    "check check",
    "mic test",
    "microphone test",
    "can you hear",
    "do you hear me",
    "are you listening",
    "hello can you hear",
    "can you hear me now",
    "am i coming through",
]

THANKS_PATTERNS = [
    "thank you",
    "thanks",
    "thank u",
    "thanks a lot",
    "thank you so much",
    "thanks a bunch",
    "much appreciated",
    "thank you very much",
    "dhanyavaad",
    "dhanyabad",
    "shukriya",
    "thanks bhai",
    "thank you bro",
    "धन्यवाद",
    "शुक्रिया",
    "শুক্রিয়া",
    "থ্যাঙ্কস",
    "দন্যবাদ",
    "ধন্যবাদ",
]

GOODBYE_PATTERNS = [
    "bye",
    "goodbye",
    "see you",
    "see u",
    "see ya",
    "take care",
    "talk to you later",
    "alvida",
    "bye bye",
    "bye bro",
    "see you later",
    "good night",
    "alvida",
    "फिर मिलेंगे",
    "अलविदा",
    "नमस्ते",
    "বিদায়",
    "বিদায়",
    "আবার দেখা হবে",
]

SMALL_TALK_PATTERNS = [
    "how are you",
    "how r u",
    "how are you doing",
    "what's up",
    "whats up",
    "sup",
    "how's it going",
    "how is it going",
    "how do you do",
    "kaise ho",
    "kya haal hai",
    "kemon acho",
    "কেমন আছো",
    "what are you doing",
    "whats going on",
    "how is your day",
    "how was your day",
    "what can you do",
    "what do you do",
]

CONFIRMATION_PATTERNS = [
    "yes",
    "yeah",
    "yep",
    "haan",
    "haa",
    "hmm",
    "uh huh",
    "no",
    "nahi",
    "nope",
    "na",
    "not really",
    "हाँ",
    "नहीं",
    "ह্যাঁ",
    "না",
    "जी हाँ",
]

LANG_HINDI_MARKERS = [
    "hai",
    "hain",
    "ka",
    "ki",
    "ke",
    "ko",
    "se",
    "mein",
    "me",
    "nahi",
    "kya",
    "kaise",
    "kitna",
    "kitne",
    "kahan",
    "kab",
    "kaun",
    "ब",
    "ह",
    "क",
    "न",
    "म",
]

LANG_BENGALI_MARKERS = [
    "আছে",
    "এই",
    "এবং",
    "কি",
    "কে",
    "করে",
    "করা",
    "জন্য",
    "থেকে",
    "দিয়ে",
    "নিয়ে",
    "হচ্ছে",
    "হয়",
    "বাংলা",
]


def _get_language_indicator(text: str) -> Optional[str]:
    for ch in text:
        if "\u0900" <= ch <= "\u097f":
            return "hi"
        if "\u0980" <= ch <= "\u09ff":
            return "bn"
    return None


def _has_script(text: str, script: str) -> bool:
    if script == "hi":
        return any("\u0900" <= ch <= "\u097f" for ch in text)
    if script == "bn":
        return any("\u0980" <= ch <= "\u09ff" for ch in text)
    return False


def _is_likely_followup(query: str, context: ConversationContext) -> bool:
    if not context.previous_user_question and not context.recent_numeric_values:
        return False

    q = query.strip().lower()
    words = q.split()
    word_count = len(words)

    followup_markers = [
        "what is",
        "what's",
        "whats",
        "how much",
        "how many",
        "what about",
        "and",
        "aur",
        "ebong",
        "but",
        "lekin",
        "kintu",
        "kin tu",
        "who is",
        "who's",
        "where is",
        "tell me more",
        "explain",
        "what does",
        "what do",
        "what are",
        "what were",
        "which",
        "यह",
        "वह",
        "इस",
        "उस",
        "कौन",
        "क्या",
        "এটা",
        "ওটা",
        "এই",
        "সে",
        "কে",
    ]

    has_marker = any(q.startswith(m) or q == m for m in followup_markers)
    is_short = word_count <= 6
    is_numeric = bool(re.search(r"\d[\d,.]*", q))
    is_pronoun = any(
        w in q.split()
        for w in [
            "it",
            "that",
            "this",
            "he",
            "she",
            "they",
            "there",
            "यह",
            "वह",
            "इस",
            "उस",
            "एটা",
            "ওটা",
        ]
    )

    if is_numeric and is_short:
        return True
    if has_marker and is_short:
        return True
    if is_pronoun and is_short:
        return True
    if word_count <= 2 and is_numeric:
        return True

    return False


def _word_boundary_match(pattern: str, text: str) -> bool:
    """Match pattern as a standalone word (not substring of another word).
    Uses lookahead/lookbehind instead of \\b to handle non-Latin scripts
    whose combining characters break \\b (e.g. Devanagari, Bengali)."""
    return bool(re.search(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", text))


_GREETING_NOISE = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "is",
        "are",
        "was",
        "were",
        "am",
        "be",
        "been",
        "being",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "to",
        "for",
        "of",
        "in",
        "on",
        "at",
        "by",
        "with",
        "as",
        "up",
        "out",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "very",
        "too",
        "so",
        "just",
        "really",
        "also",
    }
)


def _is_pure_greeting(query: str) -> bool:
    """True if query contains only greeting words (no substantive content).
    Greeting patterns are removed BEFORE punctuation stripping so that
    non-Latin scripts with combining characters (Devanagari, Bengali)
    are matched correctly."""
    q = query.lower()
    for pattern in sorted(GREETING_PATTERNS, key=len, reverse=True):
        q = re.sub(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", " ", q)
    q = re.sub(r"[^\w\s]", " ", q)
    q = " ".join(q.split())
    if not q:
        return True
    remaining = [w for w in q.split() if w not in _GREETING_NOISE]
    return len(remaining) == 0


class IntentClassifier:
    def classify(self, query: str, context: Optional[ConversationContext] = None) -> Intent:
        q = query.strip().lower()

        if not q:
            return Intent.GREETING

        check_pairs = [
            (Intent.AUDIO_CHECK, AUDIO_CHECK_PATTERNS),
            (Intent.GREETING, GREETING_PATTERNS),
            (Intent.THANKS, THANKS_PATTERNS),
            (Intent.GOODBYE, GOODBYE_PATTERNS),
            (Intent.SMALL_TALK, SMALL_TALK_PATTERNS),
            (Intent.CONFIRMATION, CONFIRMATION_PATTERNS),
        ]

        for intent, patterns in check_pairs:
            for pattern in patterns:
                if not _word_boundary_match(pattern, q):
                    continue
                if intent == Intent.GREETING and not _is_pure_greeting(q):
                    continue
                return intent

        if context and _is_likely_followup(query, context):
            return Intent.FOLLOW_UP

        return Intent.COLLEGE_INFO
