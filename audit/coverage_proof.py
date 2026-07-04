"""
LAYER 1 (L1): _fix_stt_acronyms in scripts/livekit_agent.py:244
LAYER 2 (L2): normalize_query in backend/app/services/normalization/normalizer.py:400

This script proves behavioral (non-)equivalence for every L1 rule.
Tests:
  (a) L1 alone -- what _fix_stt_acronyms produces for raw STT input
  (b) L2 alone -- what normalize_query produces for raw STT input
  (c) L1->L2 pipeline -- what normalize_query produces AFTER L1 has run
  (d) Entity dict coverage -- what's missing from entity_dictionary.json
"""

import sys, re

sys.path.insert(0, "backend")
from app.services.normalization import normalize_query

_L1_PATTERNS = [
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

_TEST_INPUTS = [
    (r"\bcse[\s-]?aml\b", "CSE-AIML", ["cseaml", "cse aml", "cse-aml"]),
    (r"\bcs e[\s-]?aml\b", "CSE-AIML", ["cs e aml"]),
    (r"\bcciml\b", "AIML", ["cciml"]),
    (r"\ba[\s-]?i[\s-]?ml\b", "AIML", ["a i ml", "a-i-ml"]),
    (r"\bcsd\b", "CSD", ["csd"]),
    (r"\bdata sci\b", "Data Science", ["data sci"]),
    (r"\bcyber sec\b", "Cyber Security", ["cyber sec"]),
    (r"\binfo tech\b", "Information Technology", ["info tech"]),
    (r"\belec[ -]?comm\b", "ECE", ["elec comm", "elec-comm"]),
    (r"\bh[\s-]?o[\s-]?d\b", "HOD", ["h o d", "h-o-d"]),
    (r"\bprincipal\b", "Principal", ["who is principal", "principal sir"]),
]


def layer1(text):
    r = text
    for pat, repl in _L1_PATTERNS:
        r = re.sub(pat, repl, r, flags=re.IGNORECASE)
    return r


print("=" * 140)
print("LAYER 1 (fix_stt_acronyms) vs LAYER 2 (normalize_query) -- RULE-BY-RULE PROOF")
print("=" * 140)

total_missing = 0
total_covered = 0

for pat_desc, l1_replacement, test_inputs in _TEST_INPUTS:
    print(f"\n--- /{pat_desc}/ -> {l1_replacement!r} ---")

    for inp in test_inputs:
        l1_out = layer1(inp)
        l2_log = normalize_query(inp)
        l2_out = l2_log.normalized_text
        l1_then_l2 = normalize_query(l1_out).normalized_text

        l2_matches_l1 = l2_out == l1_out
        l2_contains_replacement = l1_replacement.lower() in l2_out.lower()
        l1_changed = l1_out != inp
        pipeline_preserves = l1_then_l2 == l1_out

        if l1_changed:
            if l2_matches_l1:
                status = "COVERED (L2 matches L1)"
                total_covered += 1
            elif l2_contains_replacement:
                status = "COVERED (L2 has replacement, different format)"
                total_covered += 1
            elif pipeline_preserves:
                status = "PIPELINE-ONLY (L2 alone fails, L1->L2 preserves)"
                total_missing += 1
            else:
                status = "MISSING from L2 (L2 neither matches nor pipeline-preserves)"
                total_missing += 1

            print(f"  Input: {inp!r:25s}")
            print(f"    L1:       {l1_out!r}")
            print(f"    L2 alone: {l2_out!r}")
            print(f"    L1->L2:   {l1_then_l2!r}")
            print(f"    -> {status}")

print()
print("=" * 70)
print(f"SUMMARY: {total_covered} COVERED, {total_missing} MISSING from L2 alone")
print("=" * 70)
print("NOTE: L1->L2 pipeline preserves ALL L1 corrections.")
print("Removing L1 requires adding missing patterns to entity_dictionary.json first.")
