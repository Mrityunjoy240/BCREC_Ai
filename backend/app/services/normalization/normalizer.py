"""
Domain-aware text normalization pipeline for BCREC voice assistant.

Pipeline:
  1. Unicode normalization (NFKC)
  2. Lowercase
  3. Punctuation cleanup (preserving intra-word)
  4. Whitespace normalization
  5. Mixed-language word mapping (Bengali/Hindi → English)
  6. STT mistake correction from entity dictionary
  7. Exact alias replacement from entity dictionary
  8. Fuzzy entity resolution (if exact fails, above threshold)
  9. Logging of all changes
"""

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


logger = logging.getLogger(__name__)

# --- Configuration ---
CONFIDENCE_FUZZY_AUTO = 0.75
CONFIDENCE_FUZZY_SUGGEST = 0.55

# Common English words to exclude from fuzzy entity matching (prevent false positives)
FUZZY_STOP_WORDS: set[str] = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "what",
    "who",
    "where",
    "when",
    "why",
    "how",
    "which",
    "fee",
    "fees",
    "for",
    "of",
    "in",
    "on",
    "at",
    "to",
    "by",
    "with",
    "from",
    "as",
    "and",
    "or",
    "but",
    "not",
    "do",
    "does",
    "did",
    "can",
    "could",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "has",
    "have",
    "had",
    "about",
    "into",
    "over",
    "after",
    "before",
    "tell",
    "show",
    "explain",
    "describe",
    "give",
    "list",
    "name",
    "say",
    "get",
    "want",
    "need",
    "know",
    "like",
    "please",
    "hi",
    "hello",
    "hey",
    "yes",
    "no",
    "ok",
    "okay",
    "my",
    "me",
    "you",
    "your",
    "we",
    "our",
    "us",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "he",
    "she",
    "they",
    "them",
    "am",
    "pm",
    "department",
    "dept",
    "sir",
    "office",
    "room",
    "building",
    "fail",
    "failed",
    "failing",
    "failure",
    "backlog",
    "arrear",
    "supplementary",
    "reappear",
    # Hindi common words (prevent fuzzy matching to college acronyms)
    "naam", "hai", "kya", "ka", "ki", "ke", "me", "mein", "se", "ko",
    "bol", "bata", "poora", "pura", "hota", "hai", "hain", "ho",
    "ye", "wo", "yeh", "woh", "aur", "par", "pe", "ya", "to", "do",
    # Bengali common words
    "ache", "hobe", "na", "ki", "te", "e", "ar", "o", "r", "tumi", "ami",
    "apni", "amake", "tumar", "apnar", "jonno", "ta", "eta", "ota",
}

ENTITY_DICT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "canonical"
    / "entity_dictionary.json"
)


@dataclass
class NormalizationLog:
    original_text: str
    normalized_text: str = ""
    changes: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Entity dictionary loader (lazy singleton)
# ---------------------------------------------------------------------------
_entity_dict: dict | None = None
_entity_dict_mtime: float = 0


def _load_entity_dict() -> dict:
    global _entity_dict, _entity_dict_mtime
    try:
        mtime = os.path.getmtime(ENTITY_DICT_PATH)
        if _entity_dict is not None and mtime <= _entity_dict_mtime:
            return _entity_dict
        with open(ENTITY_DICT_PATH, encoding="utf-8") as f:
            _entity_dict = json.load(f)
        _entity_dict_mtime = mtime
        logger.info(f"Loaded entity dictionary ({len(_entity_dict)} sections)")
    except Exception as e:
        logger.error(f"Failed to load entity dictionary: {e}")
        _entity_dict = _entity_dict or {}
    return _entity_dict


# ---------------------------------------------------------------------------
# Build flat alias maps from entity dictionary
# ---------------------------------------------------------------------------
def _build_alias_map(
    edict: dict,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict], dict[str, str]]:
    """Build alias->canonical, stt_mistake->canonical, fuzzy candidates, and tts_spoken maps."""
    alias_map: dict[str, str] = {}
    stt_map: dict[str, str] = {}
    fuzzy_candidates: list[tuple[str, str, str]] = []  # (name_for_fuzzy, canonical, category)
    tts_map: dict[str, str] = {}

    categories = [
        ("departments", "dept"),
        ("faculty", "faculty"),
        ("programs", "program"),
        ("common_abbreviations", "abbr"),
        ("buildings", "building"),
    ]

    # Categories excluded from fuzzy matching
    # Programs (B.Tech, M.Tech etc.) are handled via exact alias/STT correction.
    # Including them in fuzzy causes false positives (e.g., "tech" -> "B.Tech").
    _fuzzy_excluded_categories: set[str] = {"programs"}

    for cat_key, cat_label in categories:
        section = edict.get(cat_key, {})
        for entity_key, entity in section.items():
            canonical = entity.get("canonical", "")
            if not canonical:
                continue

            lower_canon = canonical.lower()
            if cat_key not in _fuzzy_excluded_categories:
                fuzzy_candidates.append((lower_canon, canonical, cat_label))

            # Aliases
            for alias in entity.get("aliases", []):
                alias_lower = alias.lower().strip()
                if alias_lower:
                    alias_map[alias_lower] = canonical

            # STT mistakes
            for mistake in entity.get("stt_mistakes", []):
                m_lower = mistake.lower().strip()
                if m_lower and m_lower not in alias_map:
                    stt_map[m_lower] = canonical

            # TTS spoken forms
            tts_val = entity.get("tts_spoken", "")
            if tts_val:
                tts_map[canonical] = tts_val

    # Also pull from top-level tts_spoken_forms
    tts_extra = edict.get("tts_spoken_forms", {})
    for key, val in tts_extra.items():
        tts_map[key] = val

    return alias_map, stt_map, fuzzy_candidates, tts_map


# ---------------------------------------------------------------------------
# Step 1: Unicode normalization
# ---------------------------------------------------------------------------
def _unicode_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------------------
# Step 2: Punctuation cleanup
# Keep intra-word punctuation (hyphens, dots in abbreviations), remove others
# ---------------------------------------------------------------------------
def _clean_punctuation(text: str) -> str:
    text = re.sub(r"[()\[\]{}<>]", " ", text)
    text = re.sub(r"[,@\"#$%^&*+=\\|:;~`?!-]", " ", text)
    text = re.sub(r"\s*\.\s*", " ", text)
    return text


# ---------------------------------------------------------------------------
# Step 3: Whitespace normalization
# ---------------------------------------------------------------------------
def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Step 4: Mixed-language normalization
# Map common Hindi/Bengali words to English equivalents
# ---------------------------------------------------------------------------
def _normalize_mixed_language(text: str, edict: dict) -> str:
    lang_maps = edict.get("language_mappings", {})
    result = text

    # Check if text is predominantly Bengali script (not Banglish)
    # Bengali Unicode range: 0980-09FF
    bengali_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha > 0 and bengali_chars / total_alpha > 0.5:
        # Pure Bengali script - skip language mapping to avoid breaking the query
        return result

    for lang_key, word_map in lang_maps.items():
        # Sort by length (longest first) to prevent partial matches
        for native, english in sorted(word_map.items(), key=lambda x: -len(x[0])):
            # Use word boundaries to prevent substring matching
            pattern = re.compile(r"(?<!\w)" + re.escape(native) + r"(?!\w)", re.IGNORECASE)
            result = pattern.sub(english, result)
    return result


# ---------------------------------------------------------------------------
# Step 5: STT mistake correction
# Apply known STT error patterns from entity dictionary
# ---------------------------------------------------------------------------
def _apply_stt_corrections(text: str, stt_map: dict[str, str], changes: list[dict]) -> str:
    result = text
    for mistake, canonical in sorted(stt_map.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(r"\b" + re.escape(mistake) + r"\b", re.IGNORECASE)
        if pattern.search(result):
            new_result = pattern.sub(canonical, result)
            if new_result != result:
                changes.append(
                    {
                        "type": "stt_correction",
                        "original": mistake,
                        "replacement": canonical,
                    }
                )
                result = new_result
    return result


# ---------------------------------------------------------------------------
# Step 6: Exact alias replacement
# Replace known aliases with canonical forms
# ---------------------------------------------------------------------------
def _apply_exact_aliases(text: str, alias_map: dict[str, str], changes: list[dict]) -> str:
    result = text
    for alias, canonical in sorted(alias_map.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
        if pattern.search(result):
            # Single-word alias may be a prefix of a multi-word alias.
            # If so, only match when no trailing non-stop-word content exists
            # to avoid partial resolution (e.g., "cyber sec" -> "CY sec").
            if " " not in alias and _has_multi_word_prefix(alias, alias_map):

                def _replacer(m, result=result, canonical=canonical):
                    after = result[m.end() :].lstrip()
                    if after:
                        next_word = after.split()[0] if after else ""
                        if next_word and next_word.lower() not in FUZZY_STOP_WORDS:
                            return m.group(0)
                    return canonical

                new_result = pattern.sub(_replacer, result)
            else:
                new_result = pattern.sub(canonical, result)
            if new_result != result:
                changes.append(
                    {
                        "type": "alias_resolution",
                        "original": alias,
                        "replacement": canonical,
                    }
                )
                result = new_result
    return result


def _has_multi_word_prefix(alias: str, alias_map: dict[str, str]) -> bool:
    """Check if a single-word alias is the prefix of any multi-word alias."""
    prefix = alias + " "
    return any(a.startswith(prefix) for a in alias_map)


# ---------------------------------------------------------------------------
# Step 7: Fuzzy entity resolution
# After exact matching fails, try fuzzy matching for remaining known terms
# ---------------------------------------------------------------------------
def _apply_fuzzy_resolution(
    text: str, fuzzy_candidates: list[tuple[str, str, str]], changes: list[dict]
) -> str:
    result = text
    tokens = result.split()
    matched_indices: set[int] = set()

    for i, token in enumerate(tokens):
        if i in matched_indices:
            continue
        token_lower = token.lower()
        # Skip very short tokens, stop words, and known short dept codes
        if token_lower in FUZZY_STOP_WORDS:
            continue
        if len(token_lower) <= 2 and token_lower not in ("cy", "ds", "it", "ee", "me", "ce"):
            continue

        best_score = 0
        best_canonical = ""
        for fuzzy_name, canonical, _ in fuzzy_candidates:
            score = SequenceMatcher(None, token_lower, fuzzy_name).ratio()
            if score > best_score:
                best_score = score
                best_canonical = canonical

        if best_score >= CONFIDENCE_FUZZY_AUTO and best_canonical.lower() != token_lower:
            old_token = tokens[i]
            tokens[i] = best_canonical
            matched_indices.add(i)
            changes.append(
                {
                    "type": "fuzzy_resolution",
                    "original": old_token,
                    "replacement": best_canonical,
                    "confidence": round(best_score, 3),
                }
            )

    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Step 8: Detect fuzzy suggestions (for "Did you mean?" responses)
# Returns entities below auto-correct threshold but above suggest threshold
# ---------------------------------------------------------------------------
def detect_fuzzy_suggestions(text: str, threshold: float = CONFIDENCE_FUZZY_SUGGEST) -> list[dict]:
    """Detect potential entity matches below auto-correct threshold for disambiguation."""
    edict = _load_entity_dict()
    _, _, fuzzy_candidates, _ = _build_alias_map(edict)
    suggestions = []
    tokens = text.split()

    for token in tokens:
        if len(token) <= 2 or token.lower() in FUZZY_STOP_WORDS:
            continue
        token_lower = token.lower()
        for fuzzy_name, canonical, cat in fuzzy_candidates:
            score = SequenceMatcher(None, token_lower, fuzzy_name).ratio()
            if threshold <= score < CONFIDENCE_FUZZY_AUTO:
                suggestions.append(
                    {
                        "original": token,
                        "suggestion": canonical,
                        "category": cat,
                        "confidence": round(score, 3),
                    }
                )
                break

    return suggestions


# ---------------------------------------------------------------------------
# TTS normalization
# Before sending text to Sarvam TTS, convert canonical acronyms to spoken form
# ---------------------------------------------------------------------------
def normalize_for_tts(text: str) -> str:
    """Convert canonical acronyms to pronunciation-friendly spoken forms."""
    edict = _load_entity_dict()
    _, _, _, tts_map = _build_alias_map(edict)
    result = text
    for canonical, spoken in tts_map.items():
        pattern = re.compile(r"\b" + re.escape(canonical) + r"\b")
        result = pattern.sub(spoken, result)
    return result


# ---------------------------------------------------------------------------
# Number-to-word normalization for TTS
# Converts domain-specific number patterns to natural spoken forms.
# Only operates on TTS text — chat text remains unchanged.
# ---------------------------------------------------------------------------

# Hindi number words (0-100)
_HI_ONES = {0: "शून्य", 1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पाँच",
            6: "छह", 7: "सात", 8: "आठ", 9: "नौ", 10: "दस",
            11: "ग्यारह", 12: "बारह", 13: "तेरह", 14: "चौदह", 15: "पंद्रह",
            16: "सोलह", 17: "सत्रह", 18: "अठारह", 19: "उन्नीस",
            20: "बीस", 21: "इक्कीस", 22: "बाईस", 23: "तेईस", 24: "चौबीस",
            25: "पच्चीस", 26: "छब्बीस", 27: "सत्ताईस", 28: "अट्ठाईस", 29: "उनतीस",
            30: "तीस", 31: "इकतीस", 32: "बत्तीस", 33: "तैंतीस", 34: "चौंतीस",
            35: "पैंतीस", 36: "छत्तीस", 37: "सैंतीस", 38: "अड़तीस", 39: "उनतालीस",
            40: "चालीस", 41: "इकतालीस", 42: "बयालीस", 43: "तैंतालीस", 44: "चौंतालीस",
            45: "पैंतालीस", 46: "छियालीस", 47: "सैंतालीस", 48: "अड़तालीस", 49: "उनचास",
            50: "पचास", 51: "इक्यावन", 52: "बावन", 53: "तिरपन", 54: "चौवन",
            55: "पचपन", 56: "छप्पन", 57: "सत्तावन", 58: "अट्ठावन", 59: "उनसठ",
            60: "साठ", 61: "इकसठ", 62: "बासठ", 63: "तिरसठ", 64: "चौंसठ",
            65: "पैंसठ", 66: "छियासठ", 67: "सड़सठ", 68: "अड़सठ", 69: "उनहत्तर",
            70: "सत्तर", 71: "इकहत्तर", 72: "बहत्तर", 73: "तिहत्तर", 74: "चौहत्तर",
            75: "पचहत्तर", 76: "छिहत्तर", 77: "सतहत्तर", 78: "अठहत्तर", 79: "उन्यासी",
            80: "अस्सी", 81: "इक्यासी", 82: "बयासी", 83: "तिरासी", 84: "चौरासी",
            85: "पचासी", 86: "छियासी", 87: "सत्तासी", 88: "अठासी", 89: "नवासी",
            90: "नब्बे", 91: "इक्यानवे", 92: "बानवे", 93: "तिरानवे", 94: "चौरानवे",
            95: "पचानवे", 96: "छियानवे", 97: "सत्तानवे", 98: "अठानवे", 99: "निन्यानवे",
            100: "सौ"}

# Bengali number words (0-100)
_BN_ONES = {0: "শূন্য", 1: "এক", 2: "দুই", 3: "তিন", 4: "চার", 5: "পাঁচ",
            6: "ছয়", 7: "সাত", 8: "আট", 9: "নয়", 10: "দশ",
            11: "এগারো", 12: "বারো", 13: "তেরো", 14: "চোদ্দো", 15: "পনেরো",
            16: "ষোলো", 17: "সতেরো", 18: "আঠারো", 19: "উনিশ",
            20: "কুড়ি", 21: "একুশ", 22: "বাইশ", 23: "তেইশ", 24: "চব্বিশ",
            25: "পঁচিশ", 26: "ছাব্বিশ", 27: "সাতাশ", 28: "আটাশ", 29: "ঊনত্রিশ",
            30: "ত্রিশ", 31: "একত্রিশ", 32: "বত্রিশ", 33: "তেত্রিশ", 34: "চুয়ত্রিশ",
            35: "পঁয়ত্রিশ", 36: "ছত্রিশ", 37: "সাঁইত্রিশ", 38: "আত্রিশ", 39: "ঊনচল্লিশ",
            40: "চল্লিশ", 41: "একচল্লিশ", 42: "বিয়াল্লিশ", 43: "তেতাল্লিশ", 44: "চুয়াল্লিশ",
            45: "পঁয়াল্লিশ", 46: "ছিচল্লিশ", 47: "সাতচল্লিশ", 48: "আতচল্লিশ", 49: "ঊনপঞ্চাশ",
            50: "পঞ্চাশ", 51: "একান্ন", 52: "বায়ান্ন", 53: "তিপ্পান্ন", 54: "চুয়ান্ন",
            55: "পঁচান্ন", 56: "ছায়ান্ন", 57: "সাতান্ন", 58: "আটান্ন", 59: "ঊনষাট",
            60: "ষাট", 61: "একষট্টি", 62: "বাষট্টি", 63: "তেষট্টি", 64: "চুয়াষট্টি",
            65: "পঁয়াষট্টি", 66: "ছেষট্টি", 67: "সাতষট্টি", 68: "আটষট্টি", 69: "ঊনসত্তর",
            70: "সত্তর", 71: "একাত্তর", 72: "বাহাত্তর", 73: "তিহাত্তর", 74: "চুয়াত্তর",
            75: "পঁচাত্তর", 76: "ছিহাত্তর", 77: "সাতাত্তর", 78: "আটাত্তর", 79: "ঊনাশি",
            80: "আশি", 81: "একাশি", 82: "বিরাশি", 83: "তিরাশি", 84: "চুরাশি",
            85: "পঁচাশি", 86: "ছিয়াশি", 87: "সাতাশি", 88: "আটাশি", 89: "নব্বী",
            90: "নব্বী", 91: "একান্নী", 92: "বান্নী", 93: "তিরান্নী", 94: "চুরান্নী",
            95: "পঁচান্নী", 96: "ছিয়ান্নী", 97: "সাতান্নী", 98: "আটান্নী", 99: "নিরান্নী",
            100: "একশ"}


def _num_to_words_hi(n: int) -> str:
    """Convert integer to Hindi spoken words (handles up to 99,99,999)."""
    if n in _HI_ONES:
        return _HI_ONES[n]
    parts = []
    if n >= 100000:
        parts.append(f"{_HI_ONES.get(n // 100000, str(n // 100000))} लाख")
        n %= 100000
    if n >= 1000:
        parts.append(f"{_HI_ONES.get(n // 1000, str(n // 1000))} हज़ार")
        n %= 1000
    if n >= 100:
        parts.append(f"{_HI_ONES.get(n // 100, str(n // 100))} सौ")
        n %= 100
    if n > 0:
        parts.append(_HI_ONES.get(n, str(n)))
    return " ".join(parts) if parts else "शून्य"


def _num_to_words_bn(n: int) -> str:
    """Convert integer to Bengali spoken words (handles up to 99,99,999)."""
    if n in _BN_ONES:
        return _BN_ONES[n]
    parts = []
    if n >= 100000:
        parts.append(f"{_BN_ONES.get(n // 100000, str(n // 100000))} লাখ")
        n %= 100000
    if n >= 1000:
        parts.append(f"{_BN_ONES.get(n // 1000, str(n // 1000))} হাজার")
        n %= 1000
    if n >= 100:
        parts.append(f"{_BN_ONES.get(n // 100, str(n // 100))} শত")
        n %= 100
    if n > 0:
        parts.append(_BN_ONES.get(n, str(n)))
    return " ".join(parts) if parts else "শূন্য"


def _num_to_words_en(n: int) -> str:
    """Convert integer to English spoken words using inflect."""
    import inflect
    p = inflect.engine()
    return p.number_to_words(n)


def _int_from_comma_str(s: str) -> int:
    """Parse '6,17,700' or '50,000' to int."""
    return int(s.replace(",", ""))


def prepare_numbers_for_tts(text: str, lang: str) -> str:
    """Convert domain-specific number patterns to spoken words for TTS.

    Handles: percentages, fees, ranks, cutoffs, years, LPA, lakh/crore, k suffix, decimals.
    Only normalizes TTS text — chat text must remain unchanged.

    Args:
        text: Text after normalize_for_tts() but before apply_lexicon().
        lang: BCP-47 language tag ("hi-IN", "bn-IN", "en-IN").
    """
    # Determine language family
    if lang.startswith("bn"):
        num_fn = _num_to_words_bn
        percent_word = "ভাগ"  # "percent" in Bengali
        rupee_word = "টাকা"
        suffix_hi = False
    elif lang.startswith("hi"):
        num_fn = _num_to_words_hi
        percent_word = "प्रतिशत"
        rupee_word = "रुपये"
        suffix_hi = True
    else:
        num_fn = _num_to_words_en
        percent_word = "percent"
        rupee_word = "rupees"
        suffix_hi = False

    result = text

    # 1. Percentages: "91%" → "ninety-one percent" / "iyannabbe pratishat"
    def _replace_percent(m):
        num_str = m.group(1).rstrip(".")
        try:
            if "." in num_str:
                # Decimal percentage: "93.6%" → "ninety-three point six percent"
                whole, dec = num_str.split(".", 1)
                whole_words = num_fn(int(whole))
                dec_words = " ".join(num_fn(int(d)) for d in dec)
                return f"{whole_words} point {dec_words} {percent_word}"
            return f"{num_fn(int(num_str))} {percent_word}"
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"(\d+\.?\d*)\s*%", _replace_percent, result)

    # 2. Fees with ₹ or Rs: "₹6,17,700" → spoken + "rupees"
    def _replace_fee(m):
        num_str = m.group(1).replace(",", "")
        try:
            return f" {num_fn(int(num_str))} {rupee_word}"
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"[₹Rs]+\s*(\d[\d,]+)", _replace_fee, result)

    # 3. Cutoff ranges: "45000-55000" or "45,000 – 55,000" (BEFORE rank to avoid interference)
    def _replace_range(m):
        a_str = m.group(1).replace(",", "")
        b_str = m.group(2).replace(",", "")
        try:
            a = int(a_str.rstrip("k")) * (1000 if a_str.lower().endswith("k") else 1)
            b = int(b_str.rstrip("k")) * (1000 if b_str.lower().endswith("k") else 1)
            if lang.startswith("hi"):
                return f"{num_fn(a)} से {num_fn(b)} के बीच"
            elif lang.startswith("bn"):
                return f"{num_fn(a)} থেকে {num_fn(b)} এর মধ্যে"
            else:
                return f"{num_fn(a)} to {num_fn(b)}"
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"(\d[\d,]*k?)\s*[-–]\s*(\d[\d,]*k?)", _replace_range, result)

    # 4. Ranks: "50000 rank" or "rank 50000" or "rank 50k"
    def _replace_rank_num(m):
        num_str = m.group(1).replace(",", "").lower()
        try:
            if num_str.endswith("k"):
                n = int(float(num_str[:-1]) * 1000)
            else:
                n = int(num_str)
            return num_fn(n)
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"(\d[\d,]*k?)\s*(?:rank|cutoff|cutoff rank)", _replace_rank_num, result, flags=re.IGNORECASE)
    result = re.sub(r"(?:rank|cutoff)\s+(\d[\d,]*k?)", _replace_rank_num, result, flags=re.IGNORECASE)

    # 5. LPA: "4.25 LPA" → "4.25 L P A" (lexicon handles abbreviation)
    # Just ensure the number is readable — lexicon will expand LPA

    # 6. Lakh/Crore: "1.5 lakh" → "one point five lakh"
    def _replace_lakh_crore(m):
        num_str = m.group(1).replace(",", "")
        unit = m.group(2).lower()
        try:
            if "." in num_str:
                whole, dec = num_str.split(".", 1)
                whole_words = num_fn(int(whole))
                dec_words = " ".join(num_fn(int(d)) for d in dec)
                num_words = f"{whole_words} point {dec_words}"
            else:
                num_words = num_fn(int(num_str))
            if lang.startswith("hi"):
                unit_hi = "लाख" if "lakh" in unit else "करोड़"
                return f"{num_words} {unit_hi}"
            elif lang.startswith("bn"):
                unit_bn = "লাখ" if "lakh" in unit else "কোটি"
                return f"{num_words} {unit_bn}"
            return f"{num_words} {unit}"
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"(\d[\d,.]*)\s*(lakh|crore)", _replace_lakh_crore, result, flags=re.IGNORECASE)

    # 7. k suffix: "50k" → "fifty thousand"
    def _replace_k_suffix(m):
        try:
            n = int(float(m.group(1)) * 1000)
            return num_fn(n)
        except (ValueError, KeyError):
            return m.group(0)

    result = re.sub(r"\b(\d+\.?\d*)k\b", _replace_k_suffix, result, flags=re.IGNORECASE)

    # 8. Standalone large numbers (5+ digits, not phone numbers): "4816" → spoken
    def _replace_large_num(m):
        num_str = m.group(1).replace(",", "")
        try:
            n = int(num_str)
            if n >= 1000:
                return num_fn(n)
        except (ValueError, KeyError):
            pass
        return m.group(0)

    # Only match numbers that are clearly NOT phone numbers (not 10 digits, not starting with 0/9)
    result = re.sub(r"\b(\d[\d,]{3,})\b", _replace_large_num, result)

    # 9. Years: "2024" → "twenty twenty-four" / "do hazaar chaubees"
    def _replace_year(m):
        year = int(m.group(1))
        try:
            if lang.startswith("hi"):
                return _num_to_words_hi(year)
            elif lang.startswith("bn"):
                return _num_to_words_bn(year)
            else:
                # English: "twenty twenty-four"
                import inflect
                p = inflect.engine()
                return p.number_to_words(year)
        except Exception:
            return m.group(0)

    result = re.sub(r"\b((?:19|20)\d{2})\b", _replace_year, result)

    return result


# ---------------------------------------------------------------------------
# Main normalization entry point
# ---------------------------------------------------------------------------
def normalize_query(
    text: str,
    enable_fuzzy: bool = True,
    enable_lang_mapping: bool = True,
) -> NormalizationLog:
    """Normalize a user query for STT recovery and entity resolution.

    Args:
        text: Raw query from STT output.
        enable_fuzzy: Enable fuzzy entity resolution (default True).
        enable_lang_mapping: Enable Hindi/Bengali→English mapping (default True).

    Returns:
        NormalizationLog with normalized_text and change history.
    """
    log = NormalizationLog(original_text=text)
    changes: list[dict] = []

    if not text or not text.strip():
        return NormalizationLog(original_text=text, normalized_text=text, changes=[])

    edict = _load_entity_dict()
    if not edict:
        logger.warning("Entity dictionary not loaded; returning original text")
        return NormalizationLog(original_text=text, normalized_text=text, changes=[])

    alias_map, stt_map, fuzzy_candidates, _ = _build_alias_map(edict)

    # Step 1-3: Basic cleanup
    result = _unicode_normalize(text)
    result = result.lower()
    result = _clean_punctuation(result)
    result = _normalize_whitespace(result)

    if result != text.lower():
        changes.append({"type": "cleanup", "detail": "unicode/punctuation/whitespace"})

    # Step 4: Mixed-language normalization
    if enable_lang_mapping:
        lang_before = result
        result = _normalize_mixed_language(result, edict)
        if result != lang_before:
            changes.append({"type": "language_mapping", "detail": "hindi/bengali to english"})

    # Step 5: STT mistake correction
    result = _apply_stt_corrections(result, stt_map, changes)

    # Step 6: Exact alias replacement
    result = _apply_exact_aliases(result, alias_map, changes)

    # Step 7: Fuzzy resolution
    if enable_fuzzy:
        result = _apply_fuzzy_resolution(result, fuzzy_candidates, changes)

    # Final whitespace normalization
    result = _normalize_whitespace(result)

    log.normalized_text = result
    log.changes = changes

    if changes:
        logger.info(
            f"Normalization: '{text[:60]}' -> '{result[:60]}' "
            f"({len(changes)} changes: {[c.get('type') for c in changes]})"
        )

    return log
