# Phase 3A — Corrected P0 Red-Team Catalog

## Corrections Applied

This document records all corrections to the original P0 catalog. Only corrected/added tests are shown; unchanged tests are omitted.

---

## 1. OOD Test Corrections (6 tests)

### Root Cause

The original catalog analyzed OOD behavior against the **comment-intended** logic (`>=2 distinct categories OR >=3 total keyword hits`), but the actual code (line 1650) uses `total_hits >= 2` without distinct-category checking. All affected tests are corrected below.

### C01 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "Does BCREC offer Python programming courses?" | Unchanged |
| Expected OOD verdict | CORRECTLY ALLOWED | **BLOCKED** (false positive) |
| Actual analysis | 2 hits in coding = NOT blocked (thought threshold was `>=2 distinct` or `>=3 total`) | Code does `total_hits >= 2`: python(1) + programming(1) = 2 → blocked |
| Failure symptom | False positive: legitimate Python-course query blocked |
| Likely root cause | OOD threshold too permissive in comment spec; code blocks on any 2+ hits |

### C05 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "Who won the IPL match yesterday?" | Unchanged |
| Expected OOD verdict | FALSE NEGATIVE (should be blocked) | **BLOCKED** (actually works) |
| Actual analysis | Claimed "ipl match" = 2 hits in 1 category, which per intended logic wouldn't block | Code does `total_hits >= 2`: ipl(1) + match(1) = 2 → blocked. This IS correct behavior |
| Failure symptom | None — code correctly blocks this query |
| New verdict | CORRECTLY BLOCKED |

### C07 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "Who is the chief minister of West Bengal?" | Unchanged |
| Expected OOD verdict | FALSE NEGATIVE | **BLOCKED** (actually works) |
| Actual analysis | Claimed "minister" needs regex match | Code: "minister"(1) + "chief minister"(1) = 2 hits in politics → blocked |
| Failure symptom | None — code correctly blocks this query |
| New verdict | CORRECTLY BLOCKED |

### C10 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "What is a good recipe for biryani?" | Unchanged |
| Expected OOD verdict | FALSE NEGATIVE | **BLOCKED** (actually works) |
| Actual analysis | Claimed 2 hits in 1 category (food) = not blocked per intended logic | Code: recipe(1) + biryani(1) = 2 → blocked |
| Failure symptom | None — code correctly blocks this query |
| New verdict | CORRECTLY BLOCKED |

### C18 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "Tell me a joke" | Unchanged |
| Expected OOD verdict | FALSE NEGATIVE (joke not in OOD) | **BLOCKED** (actually works) |
| Actual analysis | Claimed "joke" not in OOD categories | "tell me a joke"(1) + "joke"(1) = 2 hits in personal category → blocked. Both keywords exist in `personal` category |
| Failure symptom | Original analysis was wrong about both keyword presence and threshold |
| New verdict | CORRECTLY BLOCKED |

### C19 — Corrected

| Field | Original | Corrected |
|-------|----------|-----------|
| Query | "Tell me a joke about engineering" | Unchanged |
| Expected OOD verdict | Ambiguous/debatable | **BLOCKED** |
| Actual analysis | Claimed borderline | "tell me a joke"(1) + "joke"(1) = 2 hits in personal → blocked |
| Failure symptom | Engineering joke is blocked even though it's engineering-adjacent |
| New verdict | BLOCKED (false positive for legitimate "joke about engineering") |

---

## 2. Placement Eligibility Coverage — Removed False Gap

### Original Claim (p0_audit_report.md:238)

`_detect_placement_eligibility_intent` — "CRITICAL GAP — ZERO TESTS"

### Actual Coverage

5 unit tests + 1 integration test exist in `backend/tests/test_groq_service.py:561-599`:

| Test | Query | Type |
|------|-------|------|
| `test_if_not_study_placement` | "if I don't study will I get placement" | Unit |
| `test_without_studying_placement` | "without studying can I get placed" | Unit |
| `test_fail_exam_placement` | "I failed in exam can I still get placement" | Unit |
| `test_backlog_placement` | "I have backlog can I get placement" | Unit |
| `test_normal_placement_query_not_detected` | "what is the placement percentage for CSE" | Negative unit |
| `test_placement_eligibility_generate_response` | "if I don't study will I get placement" | Integration (generate path) |

### Action

- Remove M01 from missing-scenarios list
- Add note that stream path integration test is missing (generate has it, stream does not)
- M01 slot repurposed for genuine gap: **stream-specific placement eligibility integration test**

---

## 3. D05 — Reframed

### Original
"Ambiguous word validation runs BEFORE follow-up expansion; can't use history to disambiguate"

### Corrected
This is **intentional design** — transcript validation runs first to reject STT noise. The real gap is:
- No mechanism for context-aware ambiguous word resolution
- `_skip_ambiguous_validation_sessions` exists for yes/no continuation only (single-use)
- Should be extended to: "if history has unambiguous department/domain context, skip ambig check for matching domain words"

### New Test: D05b
Add a test where user says "CSE fee" then "fee" — should skip ambiguous clarification because history contains "CSE". Current code: clarification fires. Expected ideal: skip.

---

## 4. Pipeline Path Corrections

### A01 — Arithmetic ordering
Original: "Stream checks arithmetic only as structured_lookup fallback"
Code verification (line 4228-4248): Stream checks structured_lookup first, THEN arithmetic as fallback. **Confirmed.**

### A03 — Seat arithmetic regex
Original claimed `re.search(r"\b(seats|intake|capacity)\b", q)` for structured_lookup seats handler vs `seats.*total|total.*seats` for arithmetic block.
Code verification: arithmetic block at line 3543 uses `\b(seats|intake)\b.*\btotal\b|\btotal\b.*\b(seats|intake)\b`. Seats handler at line 2494 uses `\b(seats|intake|capacity)\b`. The structured lookup fires first (more generic), then arithmetic (more specific). **Confirmed: different coverage.**

### F01 — Multi-intent split threshold
Original: "Requires ≥2 words on each side"
Code verification (line 2247): `" and also ", " and ", " or ", " & "` checked with `len(left_words) >= 2 and len(right_words) >= 2`. For "fee and hostel and placement", left="fee"(1 word) → fails. **Confirmed.**
Also: comma split (line 2258-2261): requires `", " in q`, `count(", ") <= 2`, `all(len(p.split()) >= 2 for p in parts)`. F01 uses "and" path not comma path. **Confirmed correct.**

---

## 5. New Undocumented Parity Gaps

| ID | Gap | Generate | Stream | Impact |
|----|-----|----------|--------|--------|
| N01 | SAFEPOINT function | `_sp_safe_pre(self,q,sid,lang)` — full pre-processing | `_sp_handoff(query)` — handoff only | Stream has less SAFEPOINT capability |
| N02 | Hallucination guard query after lang switch | Validates against RE-ROUTED query (previous question with possible numbers) | Validates against ORIGINAL query (switch command, no numbers) | Generate may skip validation when rerouted query has numbers |
| N03 | Out-of-KB greeting exemption | Skips out-of-KB check if query is a greeting | No greeting check before out-of-KB | Stream logs false warnings for greeting "I don't know" responses |

---

## 6. Revised Test Count

| Change | Count | Detail |
|--------|-------|--------|
| Original | 96 | As delivered |
| Merges | -5 | A10→G09, G02→A08, I02→I01, I08→I07, F02→F01 |
| Splits | +2 | A04→A04a+A04b, A05→A05a+A05b |
| Removal of M01 | -1 | Placement eligibility NOT a gap |
| Add M01-replacement | +1 | Stream-path placement eligibility test |
| Add N01-N03 tests | +3 | New parity gap tests |
| Add D05b | +1 | Context-aware ambig word test |
| Remove C19 | -1 | Joke about engineering = duplicate mechanism of C18 |
| **Revised total** | **96** | Net 0 change after corrections |

---

## 7. Coverage Matrix (Corrected, P0 Only)

| Pipeline Stage | Tests (corrected) | Verdict |
|---------------|-------------------|---------|
| `normalize_query` | 96 | ✅ Every test |
| `_validate_transcript` | 14 | ✅ Adequate |
| `_detect_noisy_transcript` | 2 | ❌ Still low (add to voice catalog) |
| `yes_no_continuation` | 2 | ✅ Single feature |
| `_resolve_language` | 21 | ✅ Well covered |
| `_is_greeting` | 4 | ✅ Covered |
| `_is_out_of_domain` | 20 | ✅ Covered (corrected analysis) |
| `_detect_repeat_intent` | 5 | ✅ Simple feature |
| `_detect_placement_eligibility` | 6 existing + 0 in catalog | ✅ Covered by existing tests |
| `_detect_repeat_conversation` | 1 | ⚠️ Minimal |
| `_expand_follow_up_query` | 12 | ⚠️ Low |
| `_split_multi_intent` | 6 | ✅ Covered |
| `_detect_on_topic_arithmetic` | 16 | ✅ Well covered |
| `_structured_lookup` | 43 | ✅ Most tested |
| `_retrieve_context` | 39 | ✅ Well covered |
| `low_confidence_guard` | 4 | ⚠️ Low |
| `_build_messages` | 6 | ⚠️ Low |
| LLM call | 16 | ⚠️ Moderate |
| `_validate_answer` | 9 | ✅ Covered |
| `out_of_KB_detection` | 3 | ⚠️ Minimal |
| `_prepare_for_tts` | 2 | ⚠️ Low (parity gap) |
| `_append_session_turn` | 4 | ⚠️ Low |
| `_sp_safe_pre` / `_sp_handoff` | 1 | ❌ New gap N01 |
| Hallucination guard query diff | 0 | ❌ New gap N02 |
| Out-of-KB greeting check | 0 | ❌ New gap N03 |

---

## 8. Remaining P0 Gaps (After Corrections)

| # | Gap | Priority | Reason Not Blocking |
|---|-----|----------|---------------------|
| G01 | OOD code != comment threshold | MUST FIX | Code blocks 2 same-category hits; comment says it shouldn't. Either fix code or fix comment |
| G02 | Stream placement eligibility integration test | P0 | Only generate has integration test |
| G03 | Context-aware ambiguous word resolution | P0 | D05b scenario hits real users daily |
| G04 | Voice-specific: silence/barge-in/overlap | P0 | Not tested at all |
| G05 | 20+ turn conversations | P0 | Max 7 turns in catalog |
