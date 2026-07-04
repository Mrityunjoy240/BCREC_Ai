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
from typing import Optional

logger = logging.getLogger(__name__)

# --- Configuration ---
CONFIDENCE_EXACT = 1.0
CONFIDENCE_ALIAS = 0.95
CONFIDENCE_STT_CORRECT = 0.9
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
    for lang_key, word_map in lang_maps.items():
        for native, english in word_map.items():
            result = re.sub(re.escape(native), english, result, flags=re.IGNORECASE)
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
