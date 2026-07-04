================================================================================
BEHAVIORAL EQUIVALENCE & MIGRATION REPORT
Generated: 2026-07-02
================================================================================

EXECUTIVE SUMMARY
=================

Three normalization layers exist in the codebase. Each was written independently
and they partially overlap. The config-driven Layer 2 (normalize_query) is the
most comprehensive but has gaps and one cascading-duplication bug.

FILES AND LOCATIONS
===================

Layer 1: _fix_stt_acronyms()
  File:  scripts/livekit_agent.py:244
  Owner: Module-level function
  Runs:  Immediately after Sarvam STT output, before query reaches LLM wrapper
  Scope: LiveKit worker ONLY

Layer 2: normalize_query()
  File:  backend/app/services/normalization/normalizer.py:302-368
  Owner: Module-level function
  Runs:  At top of stream_response() and generate_response()
  Scope: All pipelines (LiveKit, REST, WebSocket)

Layer 3: _normalize_query()
  File:  backend/app/services/llm/groq_service.py:882-904
  Owner: GroqService instance method
  Runs:  Twice per request — at _retrieve_context():910 and stream_response():2977
  Scope: All pipelines


BEHAVIOR COMPARISON RESULTS
===========================

68 test cases run across all three layers.
Only 9 cases (13%) produce identical output from all three layers.
59 cases (87%) produce different outputs.

The differences fall into 7 categories:


CATEGORY 1: Patterns L2 completely misses (7 patterns)
------------------------------------------------------
These are regex patterns in L1/L3 that have NO equivalent in the entity dictionary.
If L1 were removed, these would break.

  Pattern               Source  Sample Input   L1/L3 Output   L2 Output
  ───────────────────── ─────── ────────────── ────────────── ───────────
  cse[\s-]?aml          L1,L3   "cseaml"       CSE-AIML       cseaml (unchanged)
  cciml                 L1,L3   "cciml"        AIML           cciml (unchanged)
  data sci              L1,L3   "data sci"     Data Science   data sci (unchanged)
  elec[ -]?comm         L1,L3   "elec comm"    ECE            elec comm (unchanged)
  h[\s-]?o[\s-]?d       L1      "h o d"        HOD           h o d (unchanged)
  a[\s-]?i[\s-]?ml      L1      "a i ml"       AIML          a i ml (unchanged)
  upo[- ]?pradhan       L3      "upo-pradhan"  উপ-প্রধান     upo-pradhan (unchanged)

  Note: "h o d" is covered as "ho d" in stt_mistakes and "ho d" in aliases,
        but NOT as "h o d" with spaces between each letter.
  Note: "data sci" is NOT an alias in entity dict. "data science" IS (no space).

  Fix: Add these 7 patterns as stt_mistakes or aliases to entity_dictionary.json.


CATEGORY 2: L2 produces WRONG output for partial matches (2 patterns)
---------------------------------------------------------------------
L2 partially matches tokens within the input, producing incorrect results
because word-by-word alias matching doesn't respect multi-word entities.

  Pattern       Input         L1/L3 Output         L2 Output
  ────────────  ────────────  ──────────────────── ─────────────────
  info tech     "info tech"   Information Technology  info B.Tech
                                          (because "tech" → B.Tech alias)
  cyber sec     "cyber sec"   Cyber Security          CY sec
                                          (because "cyber" → CY alias)

  These are FALSE POSITIVES in L2. The partial token "tech" should not
  resolve to B.Tech when part of "info tech". Similarly "cyber" should not
  resolve to CY when followed by "sec".

  Fix: Add "info tech" and "cyber sec" as explicit multi-word aliases
       in the entity dictionary. Update the alias matching to prefer
       longest-match multi-word aliases (already done for longest-first
       sorting, but "info" is not an alias while "tech" is).


CATEGORY 3: Aggressive resolution in L2 (2 patterns)
-----------------------------------------------------
L2 maps common English words to entities, which may cause false positives.

  Pattern       L1/L3 Behavior      L2 Behavior              Risk
  ────────────  ──────────────────  ──────────────────────── ──────────────
  principal     L1: capitalization  Resolves to faculty name  Changes intent
                L3: unchanged       "Dr. Sanjay S. Pawar"     detection
  computer      L1: unchanged       Not touched*              *L3 maps it
                L3: → "CSE"                                   to CSE
  
  * "computer" alone → L2 doesn't alias it (no single-word alias).
    "computer science" → L2 resolves to CSE via multi-word alias.

  "principal" being resolved to "Dr. Sanjay S. Pawar" changes the semantics
  for intent detection downstream (which looks for "principal" keyword).


CATEGORY 4: Faculty cascading duplication BUG in L2 (5 cases)
---------------------------------------------------------------
When a faculty STT mistake or alias is a substring of the canonical name,
the alias replacement fires again on the result.

  Example: "pabitra day" 
    Step 5 (STT correction): → "Dr. Pabitra Kumar Dey"  ✓
    Step 6 (alias): "pabitra" matches inside "Pabitra"  ✗
      → "Dr. Dr. Pabitra Kumar Dey Kumar Dey"

  This affects: Pabitra (hod_CSE), Chandan (hod_ME), Mrinmoy (hod_ECE),
  and any faculty where the alias is a substring of the canonical.
  
  Severity: HIGH — corrupts faculty names in queries.


CATEGORY 5: L2 expands queries (whitespace, case, punctuation)
---------------------------------------------------------------
L2 lowercases, removes punctuation, normalizes whitespace.
L1 does NOT do any of this. L3 does NOT do any of this.

  This is generally DESIRED behavior (cleaner input for intent detection),
  but means L2 outputs are structurally different from L1/L3.

  Example: "what   is   cse   fee" → "what is CSE fee"
           "b.tech fee" → "btech fee" → "btech" → "B.Tech" (alias: "btech" == "B.Tech")
           "what's cse's fee?" → "whats cses fee" → ... → "whats CSE fee"

  These are intentional improvements, not problems.


CATEGORY 6: L2 handles Bengali/Hindi (language mapping)
---------------------------------------------------------
L2 maps 42 Hindi/Bengali words to English.
L1 and L3 do NOT handle any non-English scripts.

  Example: "ফি কত" → "fee how much"
           "प्रिंसिपल कौन" → "Dr. Sanjay S. Pawar who"

  This is unique to L2 and valuable.


CATEGORY 7: L3 handles Bengali transliteration (unique)
--------------------------------------------------------
Only L3 maps "upo-pradhan" → "উপ-প্রধান" (Roman-script Bengali to
native script for vector search matching).

  This is NOT in L1 or L2. It's needed for retrieval to match native-script
  KB entries. Must be preserved in any consolidated solution.


PIPELINE FLOW IMPACT
====================

In the LiveKit pipeline, the three layers fire in this order:

  1. L1 (_fix_stt_acronyms) — right after STT, in livekit_agent.py
  2. L2 (normalize_query)   — at top of stream_response()
  3. L3 (_normalize_query)  — twice: retrieval + LLM prompt

Because L1 runs BEFORE L2 in LiveKit:
  - L1's 11 patterns are already applied before L2 sees the text
  - So L2's gaps (Categories 1, 2) are partially masked: L1 already
    corrected "cseaml", "h o d", "data sci", etc.
  - BUT: L2's Cascading Bug (Category 4) still fires on L1's output
  - AND: L3's unique patterns (Category 7) are never seen by L1/L2

In the REST/WebSocket pipelines (no L1):
  - L2's gaps are EXPOSED — "cseaml", "cciml", "elec comm" pass through
  - L3 catches some of these ("cseaml", "cciml", "elec comm") but only
    at the retrieval/LLM stage, not at intent detection stage


MIGRATION PLAN
==============

Phase 1: Fix cascading duplication bug in L2 (normalizer.py)
-------------------------------------------------------------
  Bug: _apply_exact_aliases and _apply_stt_corrections replace substrings
       within previously-replaced canonical names.

  Fix approach (conceptual):
    - Track which tokens have been replaced
    - Use re.sub with a callback that checks a "do not retouch" set
    - Or: process in a single left-to-right pass, never re-scanning
      already-replaced regions

  Without this fix, faculty name resolution produces garbage output
  that would corrupt downstream intent detection.

Phase 2: Add missing patterns to entity_dictionary.json
---------------------------------------------------------
  Add to departments → AIML → stt_mistakes: ["cciml", "cseaml"]
  Add to departments → AIML → aliases: ["a i ml"] (3-space variant)
  Add new section "stt_patterns" or add to existing:
    - "data sci" → "Data Science" (or as alias for CSE/DS)
    - "elec comm" → "ECE"
    - "elec-comm" → "ECE"
    - "info tech" → "IT" (or "Information Technology")
    - "cyber sec" → "CY" (or "Cyber Security")
    - "h o d" → "HOD"
    - "upo-pradhan" → "উপ-প্রধান"
    - "upo pradhan" → "উপ-প্রধান"
    - "computer" → "CSE" (with LOW confidence / optional flag)

Phase 3: Remove L1 (_fix_stt_acronyms) after entity dict covers its patterns
-----------------------------------------------------------------------------
  After Phase 2, verify:
    - All 11 L1 patterns have equivalents in entity_dictionary.json
    - L2 correctly handles each pattern

  Then: delete `_STT_ACRONYM_FIXES` and `_fix_stt_acronyms()` from
  `scripts/livekit_agent.py`. Remove the call at line 278.

Phase 4: Remove L3 (_normalize_query) after entity dict covers its unique patterns
-----------------------------------------------------------------------------------
  After Phase 2, verify:
    - All 14 L3 patterns have equivalents in entity_dictionary.json
    - Exception: "computer" → "CSE" is dangerous as a standalone alias.
      Keep it as a LOW-CONFIDENCE fuzzy candidate or only in L3 for now.
    - "upo-pradhan" → "উপ-প্রধান" needs explicit support in L2 (it's a
      TRANSLITERATION, not an alias. It may need a separate transliteration
      step in normalizer.py or remain as post-normalization in L3.

  Then: remove `_normalize_query()` from groq_service.py and update
  callers at lines 910 and 2977 to use L2 instead.

Phase 5: Consolidate TTS normalization (separate effort)
----------------------------------------------------------
  The LiveKit pipeline uses `apply_lexicon()` (hardcoded LEXICON dict in
  livekit_agent.py:112). The REST pipeline uses `normalize_for_tts()`
  (config-driven from entity_dictionary.json). These are NOT in sync.

  E.g., "B.Tech" → LEXICON: "B Tech" vs entity_dict: "B dot Tech"
        "MAKAUT" → LEXICON: "Ma-Kaut" vs entity_dict: "M A K A U T"

  This is a separate consolidation task outside the scope of this report.


SUMMARY OF CRITICAL FINDINGS
============================

1. L2 CAN supersede L1 in the LiveKit pipeline (since L1 runs first anyway)
   but CANNOT yet be removed as the single normalization source because:
   - 7 patterns are missing from entity_dictionary.json
   - 2 partial-match false positives exist
   - 1 cascading duplication bug must be fixed first

2. The cascading duplication bug in L2 is the HIGHEST priority fix — it
   corrupts ALL faculty name lookups.

3. L3's "upo-pradhan" → Bengali script transliteration has no equivalent
   in L1 or L2 and must be added separately (it's a transliteration, not
   an alias/STT correction).

4. L3's remaining patterns overlap completely with L1 (cseaml, cciml,
   elec-comm, data sci) — once L2 covers them, L3 can be removed.

5. "computer" → "CSE" in L3 is the most dangerous pattern and should NOT
   be naively added to L2. It should remain in L3 or be a low-confidence
   fuzzy candidate.

================================================================================
END OF REPORT
================================================================================
