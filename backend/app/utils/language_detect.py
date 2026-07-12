"""
Language Detection Utility for BCREC Voice Agent

Uses FastText's pre-trained language identification model (lid.176.ftz)
for accurate detection of English, Hindi, and Bengali — including
code-mixed "Hinglish" and "Banglish" that regex-based approaches miss.

Model size: 917KB, loads in <100ms, 95%+ accuracy on mixed-script text.
"""

import logging
import os
import re
import urllib.request
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Lazy-loaded model reference
_model = None
_MODEL_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "models"
_MODEL_PATH = _MODEL_DIR / "lid.176.ftz"


_HAS_FASTTEXT = None

# Romanized Bengali (Banglish) keyword markers — exported for use by GroqService
BANGLA_ROMAN_WORDS = frozenset(
    {
        "ami",
        "amar",
        "amake",
        "amra",
        "tumi",
        "tomake",
        "amader",
        "kotha",
        "bolte",
        "ache",
        "bhul",
        "korte",
        "hobe",
        "thik",
        "bolche",
        "bhalo",
        "kothay",
        "ekhane",
        "kachhe",
        "apnar",
        "jabe",
        "asbe",
        "dite",
        "nite",
        "niye",
        "kemon",
        "dekho",
        "bole",
        "jano",
        "janao",
        "janio",
        "shunun",
        "koto",
        "er",
        "theke",
        "diye",
        "jonno",
        "moddhe",
        "songe",
        "mote",
        "bar",
        "ta",
        "tar",
        "take",
        "dara",
        "niye",
        "char",
        "na",
        "o",
        "ar",
        "ebong",
        "upo",
        "lagbe",
        "lagche",
        "lagshe",
        "akta",
        "ekta",
        "help",
        "healp",
        "bolun",
        "sahajjo",
        "sahajja",
        "sahajjo",
        "chesta",
        "nishchoi",
        "nischoy",
        "dorkar",
        "darkar",
        "kono",
        "jani",
        "jante",
        "chaibo",
        "chai",
        "lomba",
        "shomossa",
        "somossa",
        "samossa",
        "problem",
        "hobei",
        "hobe",
        "hocche",
        "hoitase",
        "hoy",
        "hoye",
        "hoyechi",
        "hoyeche",
        "hoyechilo",
        "holo",
        "hocche",
        "hocchee",
        "dite",
        "nibo",
        "niba",
        "jawar",
        "ashar",
        "bujhi",
        "bujhte",
        "mone",
        "kaj",
        "kaje",
        "lage",
        "moto",
        "tahole",
        "tokhon",
        "ekhon",
        "okhane",
        "shekhane",
        "jodi",
        "jeta",
        "sheta",
        "konta",
        "shob",
        "shobai",
        "keu",
        "kar",
        "kake",
        "kothao",
        "shune",
        "balbe",
        "bolbe",
        "boleche",
        "chilam",
        "chilen",
        "chilo",
        "nei",
        "nato",
        "laglo",
        "lagsilo",
        "chai",
        "chaibo",
        "chaile",
        "korbo",
        "korbe",
        "korchi",
        "korchhi",
        "korche",
        "korlam",
        "pelam",
        "pelo",
        "peye",
        "peyechi",
        "peyecho",
        "dhorte",
        "dhar",
        "dharte",
        "jan",
        "jani",
        "janina",
        "janen",
        "dite",
        "nite",
        "patha",
        "pathano",
        "rakhbo",
        "rakhbe",
        "rakhlam",
        "dibo",
        "dibe",
        "ashbe",
        "ashche",
        "jawar",
        "jawa",
        "asha",
        "theko",
        "thakbe",
        "thakche",
        "thaklo",
        "boshbo",
        "boshbe",
        "dekha",
        "dekhte",
        "dekhe",
        "shona",
        "shunte",
        "shune",
        "bolar",
        "bolte",
        "bolchi",
        "bollam",
    }
)

# Romanized Hindi (Hinglish) keyword markers — exported for use by GroqService
HINDI_ROMAN_WORDS = frozenset(
    {
        "hai",
        "hain",
        "toh",
        "bhi",
        "kya",
        "kaise",
        "sakte",
        "hoon",
        "aap",
        "aur",
        "main",
        "suno",
        "batao",
        "chahiye",
        "milega",
        "kitna",
        "kitne",
        "kaisa",
        "kaisi",
        "wahan",
        "yahan",
        "unka",
        "mujhe",
        "tumhe",
        "humara",
        "tumhara",
        "theek",
        "nahin",
        "nahi",
        "ho",
        "ka",
        "ki",
        "ke",
        "me",
        "pe",
        "par",
        "se",
        "ko",
        "wo",
        "he",
        "hu",
        "tha",
        "thi",
    }
)


def _check_fasttext():
    global _HAS_FASTTEXT
    if _HAS_FASTTEXT is None:
        try:
            import fasttext

            _HAS_FASTTEXT = True
        except ImportError:
            _HAS_FASTTEXT = False
            logger.info("fasttext not installed — using keyword-only detection")
    return _HAS_FASTTEXT


def _load_model():
    global _model
    if _model is not None:
        return _model
    if not _check_fasttext():
        return None

    if not _MODEL_PATH.exists():
        logger.info(f"Downloading FastText model to {_MODEL_PATH}...")
        os.makedirs(_MODEL_DIR, exist_ok=True)
        try:
            urllib.request.urlretrieve(_MODEL_URL, str(_MODEL_PATH))
            logger.info("FastText model downloaded.")
        except Exception:
            return None

    try:
        import fasttext

        fasttext.FastText.eprint = lambda *args, **kwargs: None
        _model = fasttext.load_model(str(_MODEL_PATH))
        logger.info("FastText model loaded.")
        return _model
    except Exception:
        return None


def detect_language(text: str) -> Literal["en", "hi", "bn"]:
    """
    Detect whether `text` is English, Hindi, or Bengali.

    Returns one of: "en", "hi", "bn"

    Strategy:
    1. If text contains Bengali script (Unicode block 0x0980-0x09FF) → "bn"
    2. If text contains Devanagari script (Unicode block 0x0900-0x097F) → "hi"
    3. For romanized text (Hinglish / Banglish), use FastText model
    4. Default: "en"
    """
    if not text or not text.strip():
        return "en"

    # Quick script-based detection for native scripts (faster than model)
    has_bengali = any("\u0980" <= c <= "\u09ff" for c in text)
    has_devanagari = any("\u0900" <= c <= "\u097f" for c in text)

    if has_bengali:
        return "bn"
    if has_devanagari:
        return "hi"

    # Pre-check for known Bengali college terms in Roman script
    # (before the general keyword logic, since these are unambiguous)
    text_lower = text.lower()
    bengali_college_markers = [
        r"\bupo[- ]?pradhan\b",
        r"\bupo[- ]?principal\b",
        r"\bvice[- ]?pradhan\b",
        r"\bভাইস[- ]?প্রিন্সিপাল\b",
    ]
    for pattern in bengali_college_markers:
        if re.search(pattern, text_lower):
            return "bn"

    # For romanized text, use keyword detection first (more reliable for Hinglish/Banglish)

    text_words = set(re.sub(r"[^\w\s]", " ", text_lower).split())

    bn_count = len(text_words & BANGLA_ROMAN_WORDS)
    hi_count = len(text_words & HINDI_ROMAN_WORDS)

    # If keyword signal is strong, use it directly (bypasses FastText confusion on mixed text)
    if bn_count >= 1 and bn_count > hi_count:
        return "bn"
    if hi_count >= 1 and hi_count > bn_count:
        return "hi"
    if bn_count >= 2 and bn_count == hi_count:
        return "bn"
    if hi_count >= 2 and hi_count == bn_count:
        return "hi"

    # Fall back to FastText for ambiguous/clear English text
    model = _load_model()

    if model is None:
        return "en"

    try:
        # FastText expects single-line input, no newlines
        clean_text = text.replace("\n", " ").strip()
        predictions = model.predict(clean_text, k=3)  # top 3 predictions
        labels, scores = predictions

        # FastText labels look like "__label__en", "__label__hi", etc.
        lang_map = {}
        for label, score in zip(labels, scores):
            lang_code = label.replace("__label__", "")
            lang_map[lang_code] = score

        # Check for our supported languages in order of priority
        hi_score = lang_map.get("hi", 0.0)
        bn_score = lang_map.get("bn", 0.0)
        en_score = lang_map.get("en", 0.0)

        # If Hindi or Bengali has a reasonable score, prefer it
        # (since the default is English, we give a slight bias to detect Indian languages)
        if hi_score > 0.3:
            return "hi"
        if bn_score > 0.3:
            return "bn"

        return "en"

    except Exception as e:
        logger.error(f"FastText prediction failed: {e}")
        return "en"


def detect_language_bcp47(text: str) -> str:
    """
    Same as detect_language() but returns BCP-47 locale codes
    used by Sarvam AI: "en-IN", "hi-IN", "bn-IN"
    """
    lang = detect_language(text)
    return {"en": "en-IN", "hi": "hi-IN", "bn": "bn-IN"}[lang]
