"""
Behavioral Equivalence Report Generator
Compares _fix_stt_acronyms, normalize_query, _normalize_query
"""

import sys, os, re, json, unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ============================================================================
# LAYER 1: _fix_stt_acronyms (from livekit_agent.py)
# ============================================================================
_STT_ACRONYM_FIXES = [
    (r"\bcse[\s-]?aml\b", "CSE-AIML"),
    (r"\bcs e[\s-]?aml\b", "CSE-AIML"),
    (r"\bcciml\b", "AIML"),
    (r"\ba[\s-]?i[\s-]?ml\b", "AIML"),
    (r"\bcsd\b", "CSD"),
    (r"\bdata sci\b", "Data Science"),
    (r"\bcyber sec\b", "Cyber Security"),
    (r"\binfo tech\b", "Information Technology"),
    (r"\belec[ -]?comm\b", "ECE"),
    (r"\bh[\s-]?o[\s-]?d\b", "HOD"),
    (r"\bprincipal\b", "Principal"),
]


def layer1_fix_stt_acronyms(text: str) -> str:
    result = text
    for pattern, replacement in _STT_ACRONYM_FIXES:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


# ============================================================================
# LAYER 2: normalize_query (from normalizer.py)
# ============================================================================
ENTITY_DICT_PATH = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "data"
    / "canonical"
    / "entity_dictionary.json"
)
FUZZY_STOP_WORDS = {
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
}

CONFIDENCE_FUZZY_AUTO = 0.75

with open(ENTITY_DICT_PATH, encoding="utf-8") as f:
    _EDICT = json.load(f)


def _build_maps(edict):
    alias_map = {}
    stt_map = {}
    fuzzy_candidates = []
    categories = [
        ("departments", "dept"),
        ("faculty", "faculty"),
        ("programs", "program"),
        ("common_abbreviations", "abbr"),
        ("buildings", "building"),
    ]
    for cat_key, cat_label in categories:
        section = edict.get(cat_key, {})
        for entity_key, entity in section.items():
            canonical = entity.get("canonical", "")
            if not canonical:
                continue
            lower_canon = canonical.lower()
            fuzzy_candidates.append((lower_canon, canonical, cat_label))
            for alias in entity.get("aliases", []):
                al = alias.lower().strip()
                if al:
                    alias_map[al] = canonical
            for mistake in entity.get("stt_mistakes", []):
                ml = mistake.lower().strip()
                if ml and ml not in alias_map:
                    stt_map[ml] = canonical
    return alias_map, stt_map, fuzzy_candidates


ALIAS_MAP, STT_MAP, FUZZY_CANDS = _build_maps(_EDICT)


def layer2_normalize_query(text: str) -> str:
    if not text or not text.strip():
        return text
    edict = _EDICT

    # Step 1-3: cleanup
    r = unicodedata.normalize("NFKC", text)
    r = r.lower()
    r = re.sub(r"[()\[\]{}<>]", " ", r)
    r = re.sub(r"[,@\"#$%^&*+=|\\:;~`?!]", " ", r)
    r = re.sub(r"\s*\.\s*", " ", r)
    r = " ".join(r.split())

    # Step 4: language mapping
    lang_maps = edict.get("language_mappings", {})
    for lang_key, word_map in lang_maps.items():
        for native, english in word_map.items():
            r = re.sub(re.escape(native), english, r, flags=re.IGNORECASE)

    # Step 5: STT corrections
    for mistake, canonical in sorted(STT_MAP.items(), key=lambda x: -len(x[0])):
        r = re.sub(r"\b" + re.escape(mistake) + r"\b", canonical, r, flags=re.IGNORECASE)

    # Step 6: alias replacement
    for alias, canonical in sorted(ALIAS_MAP.items(), key=lambda x: -len(x[0])):
        r = re.sub(r"\b" + re.escape(alias) + r"\b", canonical, r, flags=re.IGNORECASE)

    # Step 7: fuzzy
    tokens = r.split()
    for i, token in enumerate(tokens):
        tl = token.lower()
        if tl in FUZZY_STOP_WORDS:
            continue
        if len(tl) <= 2 and tl not in ("cy", "ds", "it", "ee", "me", "ce"):
            continue
        best_score, best_canonical = 0, ""
        for fn, canon, _ in FUZZY_CANDS:
            score = SequenceMatcher(None, tl, fn).ratio()
            if score > best_score:
                best_score, best_canonical = score, canon
        if best_score >= CONFIDENCE_FUZZY_AUTO and best_canonical.lower() != tl:
            tokens[i] = best_canonical
    r = " ".join(tokens)
    return r


# ============================================================================
# LAYER 3: _normalize_query (from groq_service.py:882)
# ============================================================================
def layer3_normalize_query(query: str) -> str:
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
    q = re.sub(r"\bupo[- ]?pradhan\b", "উপ-প্রধান", q, flags=re.IGNORECASE)
    return q


# ============================================================================
# TEST SUITE
# ============================================================================
test_cases = [
    # (name, input)
    # --- STT acronyms from livekit_agent ---
    ("cseaml (no space)", "cseaml"),
    ("cse aml (space)", "cse aml"),
    ("cse-aml (hyphen)", "cse-aml"),
    ("cs e aml (split)", "cs e aml"),
    ("cciml", "cciml"),
    ("ai ml (space)", "ai ml"),
    ("a i ml (split)", "a i ml"),
    ("a-i-ml (hyphenated)", "a-i-ml"),
    ("csd", "csd"),
    ("data sci", "data sci"),
    ("cyber sec", "cyber sec"),
    ("info tech", "info tech"),
    ("elec comm", "elec comm"),
    ("elec-comm", "elec-comm"),
    ("h o d (spaced)", "h o d"),
    ("hod (compact)", "hod"),
    ("principal keyword", "who is principal"),
    # --- Patterns unique to layer 3 ---
    ("cseaml (exact, layer3)", "cseaml"),
    ("electrical", "electrical"),
    ("mechanical", "mechanical"),
    ("civil", "civil"),
    ("computer (dangerous)", "computer"),
    ("computer science", "computer science"),
    ("upo-pradhan", "upo-pradhan"),
    ("upo pradhan", "upo pradhan"),
    # --- Faculty names ---
    ("pabitra day (misspelling)", "pabitra day"),
    ("pabitra dey (alias)", "pabitra dey"),
    ("chandan chatoraj", "chandan chatoraj"),
    ("sanjay pawar", "sanjay pawar"),
    ("mrinmoy chakraborty", "mrinmoy chakraborty"),
    # --- Department names ---
    ("computer science and engineering", "computer science and engineering"),
    ("computer science", "computer science"),
    ("electronics and communication", "electronics and communication"),
    ("electronics", "electronics"),
    ("information technology", "information technology"),
    ("cse fee", "cse fee"),
    ("ece fee", "ece fee"),
    ("aiml fee", "aiml fee"),
    ("iml fee", "iml fee"),
    # --- Mixed language ---
    ("bengali fee", "ফি কত"),
    ("bengali hostel", "হোস্টেল ফি"),
    ("hindi fee", "फीस कितना"),
    ("hindi principal", "प्रिंसिपल कौन"),
    ("hindi hostel", "हॉस्टल शुल्क"),
    ("mixed bengali english", "CSE বিভাগের ফি কত"),
    # --- Punctuation and whitespace ---
    ("extra spaces", "what   is   cse   fee"),
    ("dots in abbreviation", "b.tech fee"),
    ("parentheses", "cse (aiml) fee"),
    ("contraction with apostrophe", "what's cse's fee?"),
    ("question mark", "how much fee?"),
    # --- Edge cases ---
    ("clean text", "what is the fee for college"),
    ("unknown text", "tell me a joke"),
    ("empty string", ""),
    ("single character", "a"),
    ("numbers preserved", "pin code 713301"),
    ("repeated alias", "ai ml ai ml"),
    ("all caps", "CSE AIML ECE"),
    # --- Real conversation transcripts ---
    ("real: hod name", "hod name"),
    ("real: placement without study", "if I don't study will I get placement"),
    ("real: total fee", "total fees for cse"),
    ("real: semester fee", "semester fee of ece"),
    ("real: principal", "who is the principal"),
    ("real: vice principal", "vice principal name"),
    ("real: college address", "what is the address of bcrec"),
    ("real: aiml hod", "aiml hod name"),
    ("real: exam related", "wbjee exam date"),
    ("real: scholarship", "scholarship for cse"),
    ("real: admission", "admission process for btech"),
]

# ============================================================================
# RUN COMPARISON
# ============================================================================
results = []
for name, inp in test_cases:
    l1 = layer1_fix_stt_acronyms(inp)
    l2 = layer2_normalize_query(inp)
    l3 = layer3_normalize_query(inp)
    differences = []
    if l1 != l2:
        differences.append("L1≠L2")
    if l1 != l3:
        differences.append("L1≠L3")
    if l2 != l3:
        differences.append("L2≠L3")
    results.append((name, inp, l1, l2, l3, differences))

# ============================================================================
# REPORT
# ============================================================================
print("=" * 120)
print("BEHAVIORAL EQUIVALENCE REPORT")
print("=" * 120)
print(
    f"\n{'Test Case':<40} {'Input':<25} {'Layer1 STT_fix':<25} {'Layer2 normalize':<25} {'Layer3 _normalize':<25} Diff"
)
print("-" * 160)

for name, inp, l1, l2, l3, diffs in results:
    inp_short = inp[:24] if inp else "(empty)"
    l1_short = l1[:24] if l1 else "(empty)"
    l2_short = l2[:24] if l2 else "(empty)"
    l3_short = l3[:24] if l3 else "(empty)"
    diff_str = ",".join(diffs) if diffs else "ALL EQUAL"
    print(f"{name:<40} {inp_short:<25} {l1_short:<25} {l2_short:<25} {l3_short:<25} {diff_str}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n\n" + "=" * 120)
print("SUMMARY")
print("=" * 120)

all_equal = sum(1 for _, _, _, _, _, d in results if not d)
all_diff = sum(1 for _, _, _, _, _, d in results if d)
print(f"Total test cases: {len(results)}")
print(f"All three layers agree: {all_equal}")
print(f"At least one difference: {all_diff}")

# Find cases where L1 != L2
print("\n--- Cases where L1 (_fix_stt_acronyms) differs from L2 (normalize_query) ---")
for name, inp, l1, l2, l3, diffs in results:
    if "L1≠L2" in diffs:
        print(f"  [{name}]")
        print(f"    Input: {inp!r}")
        print(f"    L1:    {l1!r}")
        print(f"    L2:    {l2!r}")

print("\n--- Cases where L1 (_fix_stt_acronyms) differs from L3 (_normalize_query) ---")
for name, inp, l1, l2, l3, diffs in results:
    if "L1≠L3" in diffs:
        print(f"  [{name}]")
        print(f"    Input: {inp!r}")
        print(f"    L1:    {l1!r}")
        print(f"    L3:    {l3!r}")

print("\n--- Cases where L2 (normalize_query) differs from L3 (_normalize_query) ---")
for name, inp, l1, l2, l3, diffs in results:
    if "L2≠L3" in diffs:
        print(f"  [{name}]")
        print(f"    Input: {inp!r}")
        print(f"    L2:    {l2!r}")
        print(f"    L3:    {l3!r}")

# ============================================================================
# BEHAVIOR COVERAGE ANALYSIS
# ============================================================================
print("\n\n" + "=" * 120)
print("BEHAVIOR COVERAGE ANALYSIS")
print("=" * 120)

# Catalog all unique regex patterns with their source
print("\n--- Layer 1: _fix_stt_acronyms (11 patterns) ---")
for i, (pat, repl) in enumerate(_STT_ACRONYM_FIXES, 1):
    sample_matches = [inp for _, inp in test_cases if re.search(pat, inp, re.IGNORECASE)]
    l2_handles = (
        any(layer2_normalize_query(inp) != inp for inp in sample_matches)
        if sample_matches
        else False
    )
    l3_handles = (
        any(layer3_normalize_query(inp) != inp for inp in sample_matches)
        if sample_matches
        else False
    )
    print(
        f"  {i:2d}. /{pat}/ → {repl!r:20}  L2 handles: {'YES' if l2_handles else 'NO '}  L3 handles: {'YES' if l3_handles else 'NO '}"
    )

print("\n--- Layer 3: _normalize_query (14 patterns) ---")
l3_patterns = [
    (r"\bcseaml\b", "CSE-AIML"),
    (r"\bcs e[\s-]?aml\b", "CSE-AIML"),
    (r"\bcciml\b", "AIML"),
    (r"\bcsd\b", "CSD"),
    (r"\bdata sci\b", "Data Science"),
    (r"\bcyber sec\b", "Cyber Security"),
    (r"\binfo tech\b", "Information Technology"),
    (r"\belec[ -]?comm\b", "ECE"),
    (r"\belectrical\b", "EE"),
    (r"\bmechanical\b", "ME"),
    (r"\bcivil\b", "CE"),
    (r"\bcomputer\b", "CSE"),
    (r"\bai[\s-]?ml\b", "AIML"),
    (r"\bupo[- ]?pradhan\b", "উপ-প্রধান"),
]
for i, (pat, repl) in enumerate(l3_patterns, 1):
    sample_matches = [inp for _, inp in test_cases if re.search(pat, inp, re.IGNORECASE)]
    l1_handles = (
        any(layer1_fix_stt_acronyms(inp) != inp for inp in sample_matches)
        if sample_matches
        else False
    )
    l2_handles = (
        any(layer2_normalize_query(inp) != inp for inp in sample_matches)
        if sample_matches
        else False
    )
    print(
        f"  {i:2d}. /{pat}/ → {repl!r:20}  L1 handles: {'YES' if l1_handles else 'NO '}  L2 handles: {'YES' if l2_handles else 'NO '}"
    )

# Identify behaviors MISSING from L2
print("\n\n--- Behaviors in L1 or L3 but MISSING from L2 ---")
missing_l2 = []
for pat, repl in _STT_ACRONYM_FIXES:
    for inp_name, inp in test_cases:
        if re.search(pat, inp, re.IGNORECASE):
            l2_result = layer2_normalize_query(inp)
            # Check if the replacement is NOT present in L2 result
            if repl.lower() not in l2_result.lower() and inp.lower() == l2_result.lower():
                missing_l2.append((f"L1: /{pat}/ → {repl!r}", inp, l2_result))

for pat, repl in l3_patterns:
    for inp_name, inp in test_cases:
        if re.search(pat, inp, re.IGNORECASE):
            l2_result = layer2_normalize_query(inp)
            if repl.lower() not in l2_result.lower() and inp.lower() == l2_result.lower():
                missing_l2.append((f"L3: /{pat}/ → {repl!r}", inp, l2_result))

seen = set()
for pattern, inp, l2_result in missing_l2:
    if pattern not in seen:
        print(f"  {pattern}")
        print(f"      Input: {inp!r}  →  L2: {l2_result!r}")
        seen.add(pattern)

if not seen:
    # But we may have cases where L2 does modify but produces DIFFERENT output
    print("  (Checking for output differences instead...)")
    for pat, repl in _STT_ACRONYM_FIXES:
        for inp_name, inp in test_cases:
            if re.search(pat, inp, re.IGNORECASE):
                l1r = layer1_fix_stt_acronyms(inp)
                l2r = layer2_normalize_query(inp)
                if l1r != l2r and l1r != inp:
                    print(f"  L1: /{pat}/ → {repl!r}")
                    print(f"      Input: {inp!r}  →  L1: {l1r!r}  ≠  L2: {l2r!r}")

print("\n\n--- Assessment ---")
l3_solo = [
    p
    for p, r in l3_patterns
    if not any(
        r.lower() in layer2_normalize_query(inp).lower()
        for inp_name, inp in test_cases
        if re.search(p, inp, re.IGNORECASE)
    )
]
print(f"Layer 3 patterns NOT covered by Layer 2: {len(l3_solo)}")
for p in l3_solo:
    print(f"  - {p}")

print("\n--- Recommendations ---")
print("See behavioral_equivalence_report.txt for full details.")
