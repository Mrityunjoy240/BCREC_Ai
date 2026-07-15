import re
import logging

logger = logging.getLogger(__name__)

try:
    import inflect

    _inflect_engine = inflect.engine()
except ImportError:
    _inflect_engine = None


# ──────────────────────────────────────────────
# Abbreviation / Acronym Expansion Map
# Merged from the old sarvam_service._normalize_text_for_tts()
# ──────────────────────────────────────────────
_ABBREVIATIONS = {
    r"\bRs\b\.?": "Rupees",
    r"\bDr\b\.?": "Doctor",
    r"\bProf\b\.?": "Professor",
    r"\bB\.?Tech\b\.?": "B Tech",
    r"\bM\.?Tech\b\.?": "M Tech",
    r"\bLPA\b": "Lakhs per annum",
    r"\bB\.?C\.?\b": "B C",
    r"\b[Dd]ept\b\.?": "Department",
    r"\b[Dd]epartment\b": "Department",
}

# Acronyms that should be spelled letter-by-letter
_ACRONYMS = [
    "MBA",
    "MCA",
    "CSE",
    "IT",
    "ECE",
    "EE",
    "ME",
    "CE",
    "MAKAUT",
    "NAAC",
    "NBA",
    "WBJEE",
    "JEE",
    "TCS",
    "TPO",
    "HOD",
    "AIML",
    "BCA",
    "AICTE",
    "UGC",
]

# ──────────────────────────────────────────────
# Single Source of Truth: Language → Sarvam Speaker Map
# Used by: tts.py API endpoint AND livekit_agent.py voice pipeline
# ──────────────────────────────────────────────
LANG_SPEAKER_MAP: dict[str, str] = {
    "hi-IN": "rahul",  # Hindi — natural male voice, better Hindi pronunciation
    "hi": "rahul",
    "bn-IN": "ritu",   # Bengali — bulbul:v3 compatible
    "bn": "ritu",
    "en-IN": "shubh",  # English — bulbul:v3 default
    "en": "shubh",
}

def indian_number_to_words(num: int) -> str:
    if num == 0:
        return "zero"

    chunks = []

    # Crores (10,000,000)
    crores = num // 10000000
    if crores > 0:
        crores_word = indian_number_to_words(crores)
        chunks.append(f"{crores_word} crore")
        num = num % 10000000

    # Lakhs (100,000)
    lakhs = num // 100000
    if lakhs > 0:
        lakhs_word = _inflect_engine.number_to_words(lakhs) if _inflect_engine else str(lakhs)
        chunks.append(f"{lakhs_word} lakh")
        num = num % 100000

    # Thousands (1,000)
    thousands = num // 1000
    if thousands > 0:
        thousands_word = (
            _inflect_engine.number_to_words(thousands) if _inflect_engine else str(thousands)
        )
        chunks.append(f"{thousands_word} thousand")
        num = num % 1000

    # Hundreds and remaining
    if num > 0:
        rest_word = _inflect_engine.number_to_words(num) if _inflect_engine else str(num)
        chunks.append(rest_word)

    return " ".join(chunks)


def clean_for_voice(text: str) -> str:
    """
    Single source of truth for text-to-voice normalization.

    Pipeline:
    1. Protect phone numbers (10-digit mobile, landline with dash)
    2. Expand abbreviations (Rs. → Rupees, LPA → Lakhs per annum)
    3. Space out acronyms (CSE → C. S. E.)
    4. Convert numbers to words (English only, skip protected numbers)
    5. Format units and symbols
    6. Cleanup
    """
    if not text:
        return text

    has_bengali = bool(re.search(r"[\u0980-\u09FF]", text))
    has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))

    clean = text
    # Protect BCREC from being spaced out
    clean = re.sub(r"\bBCREC\b", "TEMP_BCREC", clean, flags=re.IGNORECASE)

    # ── Expand Department Names to Full Spoken Forms ──
    # Handle specializations first
    clean = re.sub(
        r"\bC\s*S\s*E\s*[-(\s]*A\s*I\s*M\s*L\b\s*\)?",
        "Computer Science and Engineering with Artificial Intelligence and Machine Learning",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\bC\s*S\s*E\s*[-(\s]*D\s*s\b\s*\)?",
        "Computer Science and Engineering with Data Science",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\bC\s*S\s*E\s*[-(\s]*D\s*e\s*s\s*i\s*g\s*n\b\s*\)?",
        "Computer Science and Engineering with Design",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"\bC\s*S\s*E\s*[-(\s]*C\s*s\b\s*\)?",
        "Computer Science and Engineering with Cyber Security",
        clean,
        flags=re.IGNORECASE,
    )
    # Standalone specializations (e.g. "AIML department")
    clean = re.sub(
        r"\bA\s*I\s*M\s*L\b",
        "Artificial Intelligence and Machine Learning",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\bCY\b", "Cyber Security", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bHOD\b", "Head of Department", clean, flags=re.IGNORECASE)
    # Base departments
    clean = re.sub(r"\bC\s*S\s*E\b", "Computer Science and Engineering", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(I\s+T|IT)\b", "Information Technology", clean)
    clean = re.sub(
        r"\bE\s*C\s*E\b", "Electronics and Communication Engineering", clean, flags=re.IGNORECASE
    )
    clean = re.sub(r"\bE\s*E\b", "Electrical Engineering", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(M\s+E|ME)\b", "Mechanical Engineering", clean)
    clean = re.sub(r"\b(C\s+E|CE)\b", "Civil Engineering", clean)

    # ── Remove duplicate abbreviations in brackets/parentheses e.g., "Computer Science and Engineering (Computer Science and Engineering)" ──
    # If the text has a repetition like "XYZ (XYZ)" or "XYZ (XYZ Department)"
    clean = re.sub(
        r"\b(Computer Science and Engineering|Information Technology|Electronics and Communication Engineering|Electrical Engineering|Mechanical Engineering|Civil Engineering|Artificial Intelligence and Machine Learning)\s*[-(\[\s]+\1(?:\s+Department)?[-)\]\s]*",
        r"\1 ",
        clean,
        flags=re.IGNORECASE,
    )
    # Also clean up generic brackets containing repeated details if they arise
    clean = re.sub(
        r"\b(Computer Science and Engineering|Information Technology|Electronics and Communication Engineering|Electrical Engineering|Mechanical Engineering|Civil Engineering|Artificial Intelligence and Machine Learning)\s*\(\s*(?:CSE|IT|ECE|EE|ME|CE|AIML)\s*\)",
        r"\1",
        clean,
        flags=re.IGNORECASE,
    )

    # ── Step 1: Protect phone numbers ──
    # 10-digit Indian mobile numbers → read digit-by-digit
    # MUST happen before inflect touches them
    clean = re.sub(
        r"\b(\d{10})\b",
        lambda m: " ".join(m.group(1)),
        clean,
    )
    # Landline numbers like 0343-2501353
    clean = re.sub(
        r"\b(\d{3,4})-(\d{7})\b",
        lambda m: " ".join(m.group(1)) + ", " + " ".join(m.group(2)),
        clean,
    )
    # Protect 4+ digit numbers that look like years or room numbers
    # (e.g., 2024, Room 301) — keep them as-is
    # We'll let inflect handle large financial numbers below

    # ── Step 1.5: Read PIN/postal codes as individual digits ──
    # 6-digit numbers (e.g. 713206) are postal PIN codes in college contexts.
    # Converting them to words ("seven lakh thirteen thousand...") or stripping
    # them leaves awkward gaps. Read digit-by-digit instead.
    clean = re.sub(
        r"\b(\d{6})\b",
        lambda m: " ".join(m.group(1)),
        clean,
    )

    # ── Step 2: Expand abbreviations (English/Romanized only) ──
    if not has_bengali and not has_devanagari:
        for pattern, replacement in _ABBREVIATIONS.items():
            clean = re.sub(pattern, replacement, clean, flags=re.IGNORECASE)

        # ── Step 3: Space out acronyms (English/Romanized only) ──
        # Known acronyms → C. S. E. / M. A. K. A. U. T.
        for acronym in sorted(_ACRONYMS, key=len, reverse=True):
            clean = re.sub(
                rf"\b{acronym}\b",
                ". ".join(list(acronym)) + ".",
                clean,
            )
        # Handle already-spaced acronyms (any length)
        clean = re.sub(r"\b([A-Z])\s+([A-Z])\s+([A-Z])\s+([A-Z])\b", r"\1. \2. \3. \4.", clean)
        clean = re.sub(r"\b([A-Z])\s+([A-Z])\s+([A-Z])\b", r"\1. \2. \3.", clean)
        clean = re.sub(r"\b([A-Z])\s+([A-Z])\b", r"\1. \2.", clean)

    # Ensure BCREC is protected and NOT spaced or dotted (since Step 3 can add dots if not handled)
    # Let's completely clean out any dotted version like B. C. R. E. C.
    clean = re.sub(r"\bB\.\s*C\.\s*R\.\s*E\.\s*C\.\b", "BCREC", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bB\s*C\s*R\s*E\s*C\b", "BCREC", clean, flags=re.IGNORECASE)

    # ── Step 4: Number-to-words (Dynamic Indian Number-to-Words Algorithm) ──
    has_bengali = bool(re.search(r"[\u0980-\u09FF]", clean))
    has_devanagari = bool(re.search(r"[\u0900-\u097F]", clean))

    # Determine default language mode for romanized mixes
    # We check if context contains indicators of Bengali/Hindi voice prompts
    # If it is Hinglish/Banglish, we'll write the numbers in Bengali/Hindi scripts/words
    # dynamically so the respective STT/TTS engine reads it right.
    # To keep it extremely robust, we translate any digits to fully spelled-out words.

    # 1-99 number words mapping for Bengali, Hindi and English
    bn_numbers = {
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
        11: "এগারো",
        12: "বারো",
        13: "তেরো",
        14: "চৌদ্দ",
        15: "পনেরো",
        16: "ষোল",
        17: "সতেরো",
        18: "আঠারো",
        19: "উনিশ",
        20: "কুড়ি",
        21: "একুশ",
        22: "বাইশ",
        23: "তেইশ",
        24: "চব্বিশ",
        25: "পঁচিশ",
        26: "ছাব্বিশ",
        27: "সাতাশ",
        28: "আটাশ",
        29: "উনত্রিশ",
        30: "ত্রিশ",
        31: "একত্রিশ",
        32: "বত্রিশ",
        33: "তেত্রিশ",
        34: "চৌত্রিশ",
        35: "পঁয়ত্রিশ",
        36: "ছত্রিশ",
        37: "সাঁইত্রিশ",
        38: "আটত্রিশ",
        39: "উনচল্লিশ",
        40: "চল্লিশ",
        41: "একচল্লিশ",
        42: "বিয়াল্লিশ",
        43: "তেতাল্লিশ",
        44: "চৌয়াল্লিশ",
        45: "পঁয়তাল্লিশ",
        46: "ছেচল্লিশ",
        47: "সাতচল্লিশ",
        48: "আটচল্লিশ",
        49: "উনপঞ্চাশ",
        50: "পঞ্চাশ",
        51: "একান্ন",
        52: "বায়ান্ন",
        53: "তিপ্পান্ন",
        54: "চৌয়ান্ন",
        55: "পঞ্চান্ন",
        56: "ছাপ্পান্ন",
        57: "সাতান্ন",
        58: "আটান্ন",
        59: "উনষাট",
        60: "ষাট",
        61: "একষট্টি",
        62: "ষট্টি",
        63: "তেষট্টি",
        64: "চৌষট্টি",
        65: "পঁয়ষট্টি",
        66: "ছেষট্টি",
        67: "সাতষট্টি",
        68: "আটষট্টি",
        69: "উনসত্তর",
        70: "সত্তর",
        71: "একাত্তর",
        72: "বাহাত্তর",
        73: "তিয়াত্তর",
        74: "চৌহাত্তর",
        75: "পঁচাত্তর",
        76: "ছিয়াত্তর",
        77: "সাতাত্তর",
        78: "আটাত্তর",
        79: "উনাশি",
        80: "আশি",
        81: "একাশি",
        82: "বিয়াশি",
        83: "তিরাশি",
        84: "চৌরাশি",
        85: "পঁচাশী",
        86: "ছিয়াশি",
        87: "সাতাশি",
        88: "অষ্টাশি",
        89: "নবাশি",
        90: "নব্বই",
        91: "একানব্বই",
        92: "বিরানব্বই",
        93: "তিরানব্বই",
        94: "চৌরানব্বই",
        95: "পঁচানব্বই",
        96: "ছিয়ানব্বই",
        97: "সাতানব্বই",
        98: "আটানব্বই",
        99: "নিরানব্বই",
    }

    hi_numbers = {
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
        11: "ग्यारह",
        12: "बारह",
        13: "तेरह",
        14: "चौदह",
        15: "पन्द्रह",
        16: "सोलह",
        17: "सत्रह",
        18: "अठारह",
        19: "उन्नीस",
        20: "बीस",
        21: "इक्कीस",
        22: "बाईस",
        23: "तेईस",
        24: "चौबीस",
        25: "पच्चीस",
        26: "छब्बीस",
        27: "सत्ताईस",
        28: "अट्ठाईस",
        29: "उनतीस",
        30: "तीस",
        31: "इकतीस",
        32: "बत्तीस",
        33: "तैंतीस",
        34: "चौंतीस",
        35: "पैंतीस",
        36: "छत्तीस",
        37: "सैंतीस",
        38: "अड़तीस",
        39: "उनतालीस",
        40: "चालीस",
        41: "इकतालीस",
        42: "बयालीस",
        43: "तैंतालीस",
        44: "चतुर्दाश",
        45: "पैंतालीस",
        46: "छियालीस",
        47: "सैंतालीस",
        48: "अड़तालीस",
        49: "उनचास",
        50: "पचास",
        51: "इक्यावन",
        52: "बावन",
        53: "तिरेपन",
        54: "चौवन",
        55: "पचपन",
        56: "छप्पन",
        57: "सतावन",
        58: "अट्ठावन",
        59: "उनसठ",
        60: "साठ",
        61: "इकसठ",
        62: "बासठ",
        63: "तिरसठ",
        64: "चौंसठ",
        65: "पैंसठ",
        66: "छियासठ",
        67: "सरसठ",
        68: "अड़सठ",
        69: "उनहत्तर",
        70: "सत्तर",
        71: "इकहत्तर",
        72: "बहत्तर",
        73: "तिहत्तर",
        74: "चौहत्तर",
        75: "पचहत्तर",
        76: "छियहत्तर",
        77: "सतहत्तर",
        78: "अठहत्तर",
        79: "उनासी",
        80: "अस्सी",
        81: "इक्यासी",
        82: "बयासी",
        83: "तिरासी",
        84: "चौरासी",
        85: "पचासी",
        86: "छियासी",
        87: "सतासी",
        88: "अठासी",
        89: "नवासी",
        90: "नब्बे",
        91: "इक्यानबे",
        92: "बानबे",
        93: "तिरानबे",
        94: "चौरानबे",
        95: "पचानबे",
        96: "छियानबे",
        97: "सत्तानबे",
        98: "अट्ठानबे",
        99: "निन्यानबे",
    }

    def convert_sub_100(val, lang):
        if lang == "bn":
            return bn_numbers.get(val, str(val))
        elif lang == "hi":
            return hi_numbers.get(val, str(val))
        return str(val)

    def convert_indian_system(number, lang):
        if number == 0:
            return bn_numbers[0] if lang == "bn" else hi_numbers[0]

        parts = []
        # Crores (1,00,00,000)
        crores = number // 10000000
        if crores > 0:
            word = (
                convert_sub_100(crores, lang)
                if crores < 100
                else convert_indian_system(crores, lang)
            )
            suffix = "কোটি" if lang == "bn" else "करोड़"
            parts.append(f"{word} {suffix}")
            number %= 10000000

        # Lakhs (1,00,000)
        lakhs = number // 100000
        if lakhs > 0:
            word = (
                convert_sub_100(lakhs, lang) if lakhs < 100 else convert_indian_system(lakhs, lang)
            )
            suffix = "লাখ" if lang == "bn" else "लाख"
            parts.append(f"{word} {suffix}")
            number %= 100000

        # Thousands (1,000)
        thousands = number // 1000
        if thousands > 0:
            word = (
                convert_sub_100(thousands, lang)
                if thousands < 100
                else convert_indian_system(thousands, lang)
            )
            suffix = "হাজার" if lang == "bn" else "हज़ार"
            parts.append(f"{word} {suffix}")
            number %= 1000

        # Hundreds (100)
        hundreds = number // 100
        if hundreds > 0:
            word = convert_sub_100(hundreds, lang)
            suffix = "শত" if lang == "bn" else "सौ"
            parts.append(f"{word} {suffix}")
            number %= 100

        # Tens and Units (1-99)
        if number > 0:
            parts.append(convert_sub_100(number, lang))

        return " ".join(parts)

    # Main replace handler
    def _replace_number_dynamically(match):
        num_str = match.group(0).replace(",", "")
        if " " in match.group(0):
            return match.group(0)
        try:
            num = int(num_str)
            if 1900 <= num <= 2099:
                return match.group(0)  # Skip years
            # Skip single-digit numbers for English plain text to avoid unnatural reading
            if num < 10 and not has_bengali and not has_devanagari:
                return match.group(0)

            # Determine target spelling language
            if has_bengali:
                return convert_indian_system(num, "bn")
            elif has_devanagari:
                return convert_indian_system(num, "hi")
            else:
                # English fallback or Hinglish/Banglish detection
                # Let's inspect context to see if there are Bengali words in English letters
                # If so, translate numbers to English words but in Indian formatting system
                if _inflect_engine:
                    # e.g. 520000 -> five lakh twenty thousand (Indian numbering format)
                    if num >= 100000:
                        crores = num // 10000000
                        rem = num % 10000000
                        lakhs = rem // 100000
                        rem = rem % 100000
                        thousands = rem // 1000
                        rem = rem % 1000

                        parts = []
                        if crores > 0:
                            parts.append(f"{_inflect_engine.number_to_words(crores)} crore")
                        if lakhs > 0:
                            parts.append(f"{_inflect_engine.number_to_words(lakhs)} lakh")
                        if thousands > 0:
                            parts.append(f"{_inflect_engine.number_to_words(thousands)} thousand")
                        if rem > 0:
                            parts.append(_inflect_engine.number_to_words(rem))
                        return " ".join(parts)
                    return _inflect_engine.number_to_words(num_str)
                return num_str
        except Exception as e:
            logger.error(f"Error converting number {num_str}: {e}")
            return match.group(0)

    clean = re.sub(r"\b\d+(?:,\d+)*\b", _replace_number_dynamically, clean)

    # ── Step 5: Unit and symbol formatting ──
    clean = clean.replace("%", " percent")
    clean = re.sub(r"/month\b", " per month", clean, flags=re.IGNORECASE)
    clean = re.sub(r"/year\b", " per year", clean, flags=re.IGNORECASE)
    clean = re.sub(r"/sem\b", " per semester", clean, flags=re.IGNORECASE)

    # ── Step 6: Cleanup ──
    # Restore protected words
    clean = clean.replace("TEMP_BCREC", "BCREC")
    # Remove double dots from overlapping rules
    clean = clean.replace(". .", ".")
    clean = clean.replace("..", ".")
    # Remove period after single letters that aren't acronyms
    # Collapse multiple spaces
    clean = re.sub(r"\s+", " ", clean).strip()

    return clean
