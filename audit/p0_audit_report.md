# Phase 3A Quality Audit — P0 Red-Team Evaluation Catalog

## 1. Duplicate Detection

### Exact Duplicates
| Test A | Test B | Similarity | Verdict |
|--------|--------|-----------|---------|
| A08 (wrong phone) | G02 (wrong phone) | **Identical mechanism** — both inject a wrong phone, both test non-blocking stream guard | **MERGE** G02 into A08 |
| A07 (wrong fee) | G01 (wrong placement package) | **Almost identical mechanism** — both inject wrong number, both test non-blocking guard. Fee vs placement is just entity type | **KEEP** as distinct (fee = structured_arithmetic path vs placement = RAG path — different pipeline stages exercised) |
| G09 (NAAC out-of-KB) | G10 (NAAC via API) | **Same query, different path** — G09 tests stream, G10 tests generate. But A10 already tests the same out-of-KB blocking difference with "college ranking in sports" | **MERGE** A10 into G09; **REMOVE** G10 (out-of-KB blocking is covered by G09's comparison across both paths) |
| I01 (structured→timeout) | I02 (placement→timeout) | **Same finding**: structured interception avoids LLM timeout. Different handler (fee vs placement) | **MERGE** I02 into I01 with note that multiple handlers have same behavior |
| I07 (structured→ChromaDB) | I08 (establishment→ChromaDB) | **Same finding**: structured interception avoids ChromaDB. Different handler | **MERGE** I08 into I07 |
| F01 ("fee and hostel and placement") | F02 ("hostel, fees, placement") | **Same root cause**: `_split_multi_intent` requires ≥2 words per side | **MERGE** F02 into F01 with comma-separated variant as sub-case |

### Semantic Near-Duplicates
| Test Pair | Reason | Verdict |
|-----------|--------|---------|
| B03 (hello), B04 (good morning), B05 ("নমস্কার") | Same missing feature (greeting in stream), different input | **KEEP ALL** — different patterns (greeting variants) + multilingual |
| C03 (python scripting), C18 (joke), C19 (joke about engineering) | Different OOD behaviors (0 hits, 1 hit, ambiguous) | **KEEP ALL** — each tests a distinct threshold behavior |

### Duplicate Percentage: **6.3%** (6 semi-duplicate tests of 96)
### Recommended Merges: **5 merges** → removes 5 tests from count

---

## 2. Risk Coverage Matrix — P0 Risks Only

| Risk ID | Description | P0 Level? | Tests Covering | Count | Verdict |
|---------|-------------|-----------|----------------|-------|---------|
| **R01** | Stream hallucination guard non-blocking | **P0 ✅** | A07, A08, A10, G01, G02, G03, G04, G05, G06, G07 | **10 direct** | ✅ Covered |
| **R02** | Generate/Stream parity gap | **P0 ✅** | A01-A10, B01-B15, D01-D10, E01-E10, F01-F10, G08-G10, H01-H07 | **~75 direct** | ✅ Covered (10+ behavioral differences mapped) |
| **R03** | OOD false positives/negatives | **P0 ✅** | C01-C20 | **20** | ✅ Covered |
| **R04** | ConversationState staleness | **P1** (but HIGH impact) | A06, E03, E04, E05, H02 | **5** | ⚠️ Only 5 tests for P1 risk exposed in P0 suite; adequate for P0 phase but needs expansion in P1 |
| **R05** | Stream lacks multi-intent | **P1** | B06, B07, F01-F04 | **6** | ⚠️ Adequate for P0 phase |
| **R06** | No LLM timeout in non-SAFEPOINT | **P1** | I04 | **1** | ⚠️ Minimal — 1 test (edge case: "extracurricular" with timeout) |
| **R07** | Prompt query difference | **P1** | B09 | **1** | ⚠️ Minimal — 1 test |
| **R08** | Rate limiter no circuit breaker | **P2** | I05, I06 | **2** | ⚠️ Minimal — covered by injection tests |
| **R09** | Structured lookup regex priority | **P2** | F05, F06, F07, F08 | **4** | ✅ Adequate |
| **R10** | Language-ignorant handlers | **P2** | A04, A05, D10, E09, F05, F06, H07 | **7** | ⚠️ Tests exist but only 7/27 handlers tested for language compliance |
| **R11** | In-memory session (not persistent) | **P2** | H10 | **1** | ⚠️ Minimal |
| **R12** | Yes/no missing from stream | **P2** | B01 | **1** | ✅ Single feature gap, one test suffices |
| **R13** | Greeting missing from stream | **P2** | B03, B04, B05 | **3** | ✅ Covered |
| **R14** | Language switch re-run missing | **P2** | B02, E01, E02, H01 | **4** | ✅ Covered |
| **R15** | TTS prep missing from stream | **P2** | B10, B11 | **2** | ✅ Covered |
| **R16** | Bengali normalization missing | **P3** | (none documented) | **0** | ❌ **GAP** — Bengali "রুপি" normalization not tested |
| **R17** | Fee handler duplication | **P3** | A09 | **1** | ⚠️ Single test |
| **R18** | Ambiguous clarification quality | **P3** | D04, D05 | **2** | ⚠️ Minimal |
| **R19** | FEE_GROUP_MAP completeness | **P3** | F10 | **1** | ⚠️ Minimal |
| **R20** | Cache key includes context | **P3** | B08 | **1** | ⚠️ Minimal |

### Coverage Verdict: P0 risks R01-R03 → ✅ FULLY COVERED. P1-P3 risks → partial coverage as expected for P0 phase.

### Notable Gap: **R16 (Bengali normalization)** has ZERO tests. This is trivial ("রুপি" → "টাকা") but is a confirmed behavioral difference.

---

## 3. Pipeline Stage Coverage Matrix

| Stage | A | B | C | D | E | F | G | H | I | Total Tests | Coverage Verdict |
|-------|---|---|---|---|---|---|---|---|---|-------------|-----------------|
| `normalize_query` | 10 | 15 | 20 | 10 | 10 | 10 | 10 | 10 | 10 | **96** | ✅ Every test exercises it |
| `_validate_transcript` | 0 | 1(B01) | 0 | 7(D03-D09) | 3(E06,E07,E10) | 0 | 0 | 2(H03,H05) | 1(I10) | **14** | ⚠️ Low — validation behavior only tested in D and B |
| `_detect_noisy_transcript` | 0 | 0 | 0 | 2(D07,D08) | 0 | 0 | 0 | 0 | 0 | **2** | ❌ **Critical gap** — noisy transcript detection barely tested |
| `yes_no_continuation` | 0 | 1(B01) | 0 | 0 | 0 | 0 | 0 | 1(H01) | 0 | **2** | ✅ Single feature, covered by B01 |
| `_resolve_language` | 2(A04,A05) | 3(B02,B05) | 2(C14,C15) | 2(D09,D10) | 10(E01-E10) | 0 | 0 | 2(H01,H07) | 0 | **21** | ✅ Well covered |
| `_is_greeting` | 0 | 3(B03,B04,B05) | 0 | 0 | 0 | 0 | 0 | 1(H01) | 0 | **4** | ✅ Covered |
| `_is_out_of_domain` | 0 | 0 | 20(C01-C20) | 0 | 0 | 0 | 0 | 0 | 0 | **20** | ✅ Only C group, but exhaustive |
| `_detect_repeat_intent` | 0 | 1(B02) | 0 | 1(D06) | 1(E02) | 0 | 0 | 2(H01,H08) | 0 | **5** | ⚠️ Low but simple feature |
| `_detect_placement_eligibility` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | ❌ **CRITICAL GAP — ZERO TESTS** |
| `_detect_repeat_conversation` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1(H02) | 0 | **1** | ⚠️ Minimal — 1 test |
| `_expand_follow_up_query` | 1(A06) | 0 | 0 | 2(D04,D05) | 5(E03-E05,E07) | 0 | 0 | 4(H01,H02,H04) | 0 | **12** | ⚠️ Low — staleness scenarios need more |
| `_split_multi_intent` | 0 | 2(B06,B07) | 0 | 0 | 0 | 4(F01-F04) | 0 | 0 | 0 | **6** | ✅ Covered in B and F |
| `_detect_on_topic_arithmetic` | 4(A01,A02,A03,A09) | 1(B08) | 0 | 1(D01) | 0 | 1(F10) | 0 | 7(H01,H03,H05,H06,H08,H09,H10) | 2(I01,I05) | **16** | ✅ Well covered |
| `_structured_lookup` | 6(A01-A06) | 6(B06,B07,B10,B11) | 3(C15,C16,C17) | 3(D04,D10) | 6(E01,E02,E04,E05,E08,E09) | 10(F01-F10) | 2(G04,G05) | 5(H01,H02,H07,H08) | 2(I02,I08) | **43** | ✅ Most tested stage (43 tests across 27 handlers) |
| `_retrieve_context` | 3(A07,A08,A10) | 2(B09,B12) | 20(C01-C20) | 0 | 0 | 1(F09) | 8(G01-G03,G06,G07,G08) | 1(H04) | 4(I03,I04,I06,I09) | **39** | ✅ Well covered |
| `low_confidence_guard` | 1(A10) | 0 | 0 | 0 | 0 | 0 | 1(G06) | 0 | 2(I03,I09) | **4** | ⚠️ Low — only 4 tests |
| `_build_messages` | 2(A07,A08) | 2(B09,B12) | 0 | 0 | 0 | 0 | 1(G08) | 0 | 1(I04) | **6** | ⚠️ Low — prompt structure not deeply tested |
| `LLM call (with rate limiter)` | 3(A07,A08,A10) | 3(B03,B04,B13) | 2(C03,C05) | 0 | 0 | 0 | 5(G01-G03,G08,G09) | 1(H04) | 2(I04,I06) | **16** | ⚠️ Moderate — most tests hit LLM only when structured lookup fails |
| `_validate_answer` | 2(A07,A08) | 0 | 0 | 0 | 0 | 0 | 7(G01-G07) | 0 | 0 | **9** | ✅ Covered in A and G |
| `out_of_KB_detection` | 1(A10) | 0 | 0 | 0 | 0 | 0 | 2(G09,G10) | 0 | 0 | **3** | ⚠️ Minimal — only 3 tests |
| `_prepare_for_tts` | 0 | 2(B10,B11) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **2** | ⚠️ Low — only 2 tests |
| `_append_session_turn` | 0 | 1(B15) | 0 | 0 | 0 | 0 | 0 | 3(H06,H09,H10) | 0 | **4** | ⚠️ Low — session lifecycle not deeply tested |

### Pipeline Coverage Summary
| Verdict | Count | Stages |
|---------|-------|--------|
| ✅ Well covered (≥10 tests) | 7 | normalize_query, _resolve_language, _is_out_of_domain, _structured_lookup, _retrieve_context, _detect_on_topic_arithmetic |
| ⚠️ Low (1-9 tests) | 12 | _validate_transcript, yes_no_continuation, _is_greeting, _detect_repeat_intent, _detect_repeat_conversation, _expand_follow_up_query, low_confidence_guard, _build_messages, LLM call, out_of_KB_detection, _prepare_for_tts, _append_session_turn |
| ❌ **Critical gap (0 tests)** | **1** | **`_detect_placement_eligibility_intent`** |

---

## 4. Failure Attribution — Mixed-Risk Tests

### Tests with Multiple Primary Objectives

| Test | Risks Attached | Actual Primary Failure | Secondary Issue | Verdict |
|------|---------------|----------------------|-----------------|---------|
| **A04** | R01,R02 | Roman Hindi language detection threshold | Language-ignorant handler (R10) also exposed | **SPLIT** — A04a: language detection fragility; A04b: handler ignores lang param |
| **A05** | R01,R02 | Roman Bengali language detection | Language-ignorant handler (R10) | **SPLIT** — A05a: language detection; A05b: handler ignores lang param |
| **A09** | R01,R02 | Fee handler duplication (arithmetic vs structured_lookup) | Also tests arithmetic ordering (stream vs generate) | **KEEP** — single root cause: duplicated fee logic |
| **H01** | R02,R01 | 7 behavioral differences in one conversation (composite) | Multiple feature gaps compound | **KEEP** — valuable as end-to-end multi-turn scenario. **BUT** annotate that it exercises R02 (greeting, yes/no, language switch, repeat, ambig word) + R01 (non-blocking guard by proxy) |
| **H02** | R02,R01 | Staleness across multi-domain visit order | Compound state interactions | **KEEP** — the multi-turn interaction is the point |
| **I01** | R01,R02 | LLM timeout: structured interception | Also tests timeout behavior | **KEEP** — single root cause: structured queries avoid LLM timeout |
| **I03** | R01,R02 | Low confidence guard avoids LLM timeout | Also tests low confidence threshold | **KEEP** — but annotate primary objective: low-confidence guard behavior |

### Splits Required
| Original | Split Into | Reason |
|----------|-----------|--------|
| A04 | A04a: "CSE me kitne seats hain?" → tests language detection threshold (R02) | A04b: same query → tests that structured_lookup returns English despite lang=hi (R10) |
| A05 | A05a: "ami CSE te admission nite chai" → tests Roman Bengali detection (R02) | A05b: same query → tests that admission handler ignores lang=bn (R10) |

### Net change from splits: **+2 tests**

---

## 5. Realism Score Report

| Group | Avg Score | Range | Lowest-Scoring Tests | Reason |
|-------|-----------|-------|---------------------|--------|
| **A** — Hallucination guard | **3.8** | 2-5 | A07-A10 (score 2) | Require LLM response injection — not natural conversations |
| **B** — Missing features | **4.0** | 2-5 | B08 (score 3: same query twice), B12 (score 2: injection), B13 (score 2: mock 500), B14 (score 2: SAFEPOINT) | Some require mock/injection; most are natural |
| **C** — OOD | **4.5** | 3-5 | C11-C13 (score 3: weather variations) | Slightly repetitive artificial variations |
| **D** — Normalization/Validation | **3.5** | 2-5 | D07 (score 3: "yes yes yes yes" — stutter pattern is realistic but over-rep), D08 (score 2: "a b c d e f" — artificial noise pattern) | Edge cases are less realistic |
| **E** — Language/State | **4.5** | 4-5 | All 4-5 | Very realistic mixed-language conversation flows |
| **F** — Structured lookup | **4.5** | 4-5 | F01-F10 (all 4-5) | Realistic compound + ambiguous queries |
| **G** — RAG/LLM | **2.5** | 2-3 | G01-G10 (all 2-3) | All require LLM response injection |
| **H** — Long multi-turn | **4.2** | 2-5 | H06 (score 2: LiveKit disconnect), H10 (score 2: crash recovery) | Infrastructure-dependent; H01-H05, H07-H09 are 5/5 realistic |
| **I** — Failure injection | **1.5** | 1-2 | I01-I10 (all 1-2) | All require injection by design |

### Realism Verdict
- **Average realism score: 3.6/5**
- **Tests scoring ≤2 (artificial)**: A07-A10, B12-B14, D08, G01-G10, H06, H10, I01-I10 = **28 tests** (29%)
- **Tests scoring ≥4 (realistic)**: B01-B07, B09-B11, B15, C01-C10, C14-C20, D01-D06, D09-D10, E01-E10, F01-F10, H01-H05, H07-H09 = **68 tests** (71%)

**Flags for artificiality that should be noted in test runner configuration** (no changes needed — injection tests are necessary):
- G01-G10: Mark as "requires LLM mock"
- I01-I10: Mark as "requires external dependency mock"
- B12-B14: Mark as "requires server state modification"

---

## 6. Automation Readiness Report

| Automation Level | Count | Percentage | Test IDs |
|-----------------|-------|-----------|----------|
| ✅ **Fully automated** (no mock needed, deterministic) | 66 | **69%** | A01-A06, A09, B01-B11, B15, C01-C20, D01-D10, E01-E10, F01-F10, G04-G06, H01-H05, H07-H09 |
| ⚠️ **Semi-automated** (needs LLM/Groq mock) | 24 | **25%** | A07-A08, A10, B12-B14, G01-G03, G07-G10, I01-I06 |
| 🔴 **Manual** (needs LiveKit/Sarvam infrastructure) | 6 | **6%** | H06 (LiveKit disconnect), H10 (agent crash), I07-I09 (ChromaDB down), I10 (Sarvam STT failure) |

### Automation Requirements Summary
| Requirement | Tests Affected |
|------------|---------------|
| **Groq LLM response injection** (mock `client.chat.completions.create`) | A07, A08, A10, B12, B13, G01-G03, G07-G10, I01-I06 |
| **Groq rate limiting injection** (mock 429 response) | I05, I06 |
| **Cached response injection** (prime cache, then test) | B08 |
| **SAFEPOINT flag toggle** (enable/disable DEMO_SAFEPOINT) | B14 |
| **External conversation_history injection** (bypass stream persistence) | B15 |
| **ChromaDB connection mock** (simulate connection refused) | I07-I09 |
| **Sarvam STT mock** (simulate empty transcript) | I10 |
| **LiveKit disconnect simulation** (infrastructure) | H06, H10 |

### Recommended Test Harness Architecture
```
red_team_runner.py
├── pytest markers:
│   ├── @pytest.mark.p0
│   ├── @pytest.mark.requires_groq_mock
│   ├── @pytest.mark.requires_chromadb_mock
│   ├── @pytest.mark.requires_livekit
│   └── @pytest.mark.manual
├── conftest.py fixtures:
│   ├── mock_groq_hallucination(response_text)
│   ├── mock_groq_429()
│   ├── mock_groq_timeout(delay_seconds)
│   ├── mock_chromadb_unavailable()
│   ├── mock_sarvam_failure()
│   └── livekit_session(session_id)
└── assert helpers:
    ├── assert_hallucination_blocked(gen_response)
    ├── assert_hallucination_not_blocked(stream_tokens)
    ├── assert_pipeline_stage(response, expected_stage)
    └── assert_language(response, expected_lang)
```

---

## 7. Missing Critical Scenarios

### ⚠️ P0-Grade Gaps (should be added before Phase 3B)

| # | Missing Scenario | Risk | Why P0 | Impact |
|---|-----------------|------|--------|--------|
| **M01** | `_detect_placement_eligibility_intent` — no test exists | **R02** (parity gap: this handler fires in both paths but untested) | A bug in placement eligibility regex would silently fire on wrong queries, producing "If you don't study, placement depends on skills" for unrelated questions | **HIGH** — confuses users |
| **M02** | STT noise detection with repeated single-char sequence (`_detect_noisy_transcript` not tested) | **R02** | "a a a a a" passes through validation → goes to LLM → wastes tokens | **MEDIUM** — performance, not correctness |

### ⚠️ P1-Grade Gaps (acceptable for P0 phase, must add in P1)

| # | Missing Scenario | Risk | Notes |
|---|-----------------|------|-------|
| M03 | Session history pruning beyond 12 turns | R11 | Not tested anywhere — 13th turn behavior untested |
| M04 | OOD + structured handler intersection (e.g., "weather cutoff for CSE") | R03+R09 | Both handlers could fire; which wins? |
| M05 | Multi-intent + OOD (e.g., "weather and fee") | R03+R05 | Does OOD block the entire query or split? |
| M06 | "Nearly ambiguous" words that should NOT trigger clarification | R18 | e.g., "fees hostel" (2 words, not ambiguous) vs "fees" (1 word, ambiguous) |
| M07 | 0-length session_id | R11 | Empty session_id may cause key collisions in in-memory dicts |
| M08 | Non-ASCII session_id (Unicode/spaces) | R11 | Bengali session_id edge case |
| M09 | Bengali "রুপি" normalization in generate vs stream | R16 | Confirmed behavior difference, no test |

---

## 8. Revised Test Plan

### Changes to Apply
| Action | Count | Tests Affected |
|--------|-------|---------------|
| **Merge** | -5 | A10→G09, G02→A08, I02→I01, I08→I07, F02→F01 |
| **Split** | +2 | A04→A04a+A04b, A05→A05a+A05b |
| **Add** (P0 gaps) | +2 | M01 (placement eligibility), M02 (STT noise: repeated single char) |
| **Remove** | 0 | (none) |
| **Net change** | **-1** | 96 - 5 + 2 + 2 = **95 tests** |

### Revised Catalog Summary
| Group | Focus | Original | After Audit |
|-------|-------|----------|-------------|
| A | Hallucination guard parity | 10 | **12** (A04, A05 split; A10 merged into G09) |
| B | Missing features | 15 | **15** (unchanged) |
| C | OOD false positives | 20 | **20** (unchanged) |
| D | Normalization/validation | 10 | **10** (unchanged + M02 added) |
| E | Language/conversation state | 10 | **10** (unchanged) |
| F | Structured lookup/multi-intent | 10 | **9** (F02 merged into F01) |
| G | RAG/LLM/post-processing | 10 | **9** (A10 merged to G09; G02 merged to A08; +M01 added) |
| H | Long multi-turn/voice | 10 | **10** (unchanged) |
| I | Failure injection | 10 | **8** (I02 merged into I01; I08 merged into I07) |
| **Total** | | **96** | **95** |

### Audit Verdict: **PASS — Conditional**

The P0 catalog is **approved for use** with the following conditions:

1. ✅ **P0 risks R01-R03**: Fully covered (10+ tests each)
2. ✅ **Pipeline stages**: 7/20 stages well-covered; only `_detect_placement_eligibility_intent` has zero tests (M01 must be added before Phase 3B)
3. ⚠️ **Low coverage areas to defer to Phase 3B**: cache, TTS prep, out-of-KB detection, low-confidence guard, session pruning
4. ✅ **Realism**: 71% of tests score ≥4/5; artificial injection tests are properly marked
5. ✅ **Automation**: 94% automatable (69% fully, 25% semi); 6% manual (LiveKit infrastructure only)
6. ✅ **Duplicates**: 6.3% — 5 merges recommended, net reduction of 1 test

**Proceed to Phase 3B (P1 catalog) with 95 tests after applying the above changes.**
