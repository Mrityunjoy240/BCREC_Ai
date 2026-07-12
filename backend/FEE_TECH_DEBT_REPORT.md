# Fee Subsystem — Technical Debt Report

**Date:** 2026-07-13  
**Scope:** `groq_service.py`, `fee_engine.py`, `data/fee_structures/*.json`, `data/canonical/canonical_kb.json`  
**Method:** Static analysis + call-graph tracing  

---

## 1. Dead Code — `groq_service.py`

### 1.1 `USE_NEW_FEE_ENGINE = False` (line 54)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:54` |
| **Why dead** | Defined at line 54 but **never referenced** by any code path. The actual feature flag is `_USE_NEW_FEE_ENGINE` at line 729, which reads from the `USE_NEW_FEE_ENGINE` env var. The plain variable at line 54 is a shadow/leftover. |
| **Removal risk** | **None** — zero callers, zero tests reference it |
| **Cleanup benefit** | **Small** — removes confusion from two near-identical names (`USE_NEW_FEE_ENGINE` vs `_USE_NEW_FEE_ENGINE`) |

### 1.2 `_FEE_ENGINE_AVAILABLE` (lines 49, 51)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:49-51` |
| **Why dead** | Set `True` or `False` depending on import success, but **never read** anywhere in the codebase. No `if _FEE_ENGINE_AVAILABLE:` guard exists. |
| **Removal risk** | **None** — zero readers |
| **Cleanup benefit** | **Small** — 4 lines |

### 1.3 `_execute_tool` + all 12 `_tool_*` methods (lines 1349–1498)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:1349–1498` (entire tool dispatch system) |
| **Why dead** | `_execute_tool` is **defined at line 1349 but never called**. No caller exists in `generate_response` or anywhere else in the codebase. The entire tool dispatch dict (`get_fees`, `get_contact_info`, `get_principal_info`, `get_placement_info`, `get_branch_info`, `get_admission_process`, `get_hostel_info`, `get_scholarship_info`, `get_cutoff_info`, `get_hod_info`, `get_backlog_policy`, `get_college_info`) is orphaned. |
| **Removal risk** | **Low** — zero callers. However, verify that no external script or integration test references `_execute_tool`. |
| **Cleanup benefit** | **Large** — removes ~150 lines of dead code (dispatch + 12 tool method bodies + JSON function definitions at lines ~910–990) |

### 1.4 `_calculate_total_fees` (lines 4215–4225)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:4215–4225` |
| **Why dead** | Defined but **never called**. It reads from `FEE_GROUP_MAP` and formats a response, but the actual fee formatting is done by `_lang_fee_response` (old) and `_fmt_total_fee` (new). |
| **Removal risk** | **None** — zero callers |
| **Cleanup benefit** | **Small** — 11 lines |

### 1.5 `_calculate_semester_fees` (lines 4227–4241)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:4227–4241` |
| **Why dead** | Defined but **never called**. Same pattern as `_calculate_total_fees`. |
| **Removal risk** | **None** |
| **Cleanup benefit** | **Small** — 15 lines |

### 1.6 `_calculate_seat_total` (lines 4243–4261)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:4243–4261` |
| **Why dead** | Defined but **never called**. Seat calculations are done inline in `_structured_lookup`. |
| **Removal risk** | **None** |
| **Cleanup benefit** | **Small** — 19 lines |

---

## 2. Duplicated Formatting — `groq_service.py`

### 2.1 General fee info: old inline vs `_format_general_fee_info`

| Field | Value |
|-------|-------|
| **Locations** | Old: `groq_service.py:2810–2837` (inside `_handle_fee_query_old`); New: `groq_service.py:3056–3095` (`_format_general_fee_info`) |
| **Why duplicate** | Both format the exact same three amounts (`617700`, `567100`, `429100`) in three languages into natural-language fee overviews. The old one uses shorter phrasings (`"BCREC B.Tech fees vary by branch"`); the new one uses longer phrasings (`"BCREC offers B.Tech programs with total course fees ranging from..."`). Both hardcode the amounts and call `_format_inr`. When the flag is ON (new engine), the old version becomes dead. |
| **Duplicated lines** | ~55 lines (28 old + 40 new, with ~30 lines of near-identical structure across languages) |
| **Removal risk** | **Medium** — both are currently reachable depending on flag state. Removal requires flag flip or unification. |
| **Cleanup benefit** | **Medium** — consolidates to one source of truth; removes "alag se" risk from old version |

### 2.2 Per-branch fee formatting: `_lang_fee_response` vs 4 new `_fmt_*` methods

| Field | Value |
|-------|-------|
| **Locations** | Old: `groq_service.py:4543–4562` (`_lang_fee_response`); New: `groq_service.py:2844–2991` (`_fmt_total_fee`, `_fmt_admission_fee`, `_fmt_first_semester`, `_fmt_semester_fee`) |
| **Why duplicate** | Both format the same FEE_GROUP_MAP data (total, admission, per_sem) into English/Hindi/Bengali. The old one is a single generic function with `fee_type` branching; the new one has four specialized methods with detailed breakdowns (tuition, development fee, one-time charges, etc.). When the flag is ON, the old version is dead. |
| **Duplicated lines** | ~70 lines (20 old + 160 new, with ~50 lines of structurally identical EN/HI/BN branches) |
| **Removal risk** | **Medium** — requires flag flip or retirement of old engine |
| **Cleanup benefit** | **Medium** — eliminates the "alag se" phrase in old formatter; reduces maintenance surface |

### 2.3 INK formatting: `_format_inr` + three `_num_to_*` dicts

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:1134–1284` (`_NUM_WORDS_EN`: 100 entries; `_NUM_WORDS_HI`: 11 entries; `_NUM_WORDS_BN`: 11 entries; `_num_to_english`: 11 lines; `_num_to_hindi`: 2 lines; `_num_to_bengali`: 2 lines) |
| **Why not dead but worth noting** | The Hindi and Bengali dictionaries only go up to 10 (`दस`/`দশ`), while the English goes to 99. But `_format_inr` only calls these for numbers less than 100. For amounts like `76,000`, the thousands part is 76 — `_num_to_hindi(76)` falls back to `str(76)` since 76 is not in the dictionary. The Hindi/Bengali output for fee amounts above 10,000 falls back to digits (e.g., `"७६ हजार"` becomes `"76 हजार"`). This is a **incomplete localization**, not dead code. |
| **Removal risk** | N/A — actively used |
| **Cleanup benefit** | **Medium** — extending dictionaries to 99 would fix Hindi/Bengali digit fallback in fee responses |

---

## 3. Unreachable Branches

### 3.1 `fee_engine.py:754–756` — `if count == 0` in total fee computation

| Field | Value |
|-------|-------|
| **Location** | `fee_engine.py:754–756` |
| **Why unreachable** | Inside the `else` branch of `if not comp.applicable_semesters`. When the `else` is reached, `applicable_semesters` is guaranteed non-empty, so the `for sem in ...` loop (lines 747–753) **always increments count ≥ 1**. The condition `count == 0` can never be true. The intended fallback (`amount * duration`) is already handled at lines 744–746 for the empty-list case. |
| **Removal risk** | **Low** — the logic is correct and the dead branch is a no-op if hit |
| **Cleanup benefit** | **Small** — removes misleading dead code |

---

## 4. Dead Data-Model Surface — `fee_engine.py`

### 4.1 `FeeComponent` fields (lines 72–78)

| Field | Read count | Notes |
|-------|-----------|-------|
| `FeeComponent.refundable_at` (line 72) | 0 | Set during parsing (`fee_engine.py:499`), never read |
| `FeeComponent.effective_from_batch` (line 74) | 0 | Set during parsing (`fee_engine.py:501`), never read |
| `FeeComponent.discontinued_from_batch` (line 75) | 0 | Set during parsing (`fee_engine.py:502`), never read |
| `FeeComponent.availability` (line 78) | 0 | Set during parsing (`fee_engine.py:505`), never read |

**Removal risk:** **Low** — zero readers. These are aspirational fields from an extended schema that was never consumed.  
**Cleanup benefit:** **Small** — ~8 lines

### 4.2 `FeeComputed.eighth_semester_fee` (line 93)

| Field | Read count |
|-------|-----------|
| `FeeComputed.eighth_semester_fee` | 0 |
| `FeeComputed.first_semester_payable` | 2 (`groq_service.py:3007`) |
| `FeeComputed.regular_semester_fee` | 2 (`groq_service.py:3008`) |

**Why dead:** `eighth_semester_fee` is computed but never consumed by any formatter. The formatter for semester 8 reads directly from `engine.get_semester_fee(code, 8)`, not from this field.  
**Removal risk:** **Low**  
**Cleanup benefit:** **Small**

### 4.3 `FeeStructure` metadata (lines 132–135)

| Field | Read count |
|-------|-----------|
| `FeeStructure.published_date` | 0 |
| `FeeStructure.source` | 0 |
| `FeeStructure.supersedes` | 0 |
| `FeeStructure.superseded_by` | 0 |

**Removal risk:** **Low** — these are tracking/metadata fields written by the parser but never read.  
**Cleanup benefit:** **Small** — ~4 lines

### 4.4 `FeeEngine.get_structures_for_branch()` (line 525)

| Field | Value |
|-------|-------|
| **Location** | `fee_engine.py:525` |
| **Why dead** | Defined but **never called** in `groq_service.py` or any test file |
| **Removal risk** | **Low** |
| **Cleanup benefit** | **Small** — ~8 lines |

### 4.5 `FeeGroupData` helper methods (lines 112, 118, 121)

| Method | Read count |
|--------|-----------|
| `get_component()` | 0 |
| `get_compulsory_components()` | 0 |
| `get_optional_components()` | 0 |

**Removal risk:** **Low**  
**Cleanup benefit:** **Small** — ~12 lines

---

## 5. Duplicate / Obsolete JSON Data

### 5.1 Fee data in 3 independent sources

| Source | Location | Format | Used by |
|--------|----------|--------|---------|
| `FEE_GROUP_MAP` | `groq_service.py:711–725` | Hardcoded tuple `(total, admission, per_sem)` | Old handler (`_handle_fee_query_old`) |
| `fee_structures/*.json` | `backend/data/fee_structures/` | JSON with `groups`+`components` arrays | FeeEngine |
| `canonical_kb.json: fees_summary` | `backend/data/canonical/canonical_kb.json` | JSON with formatted strings (`"Rs. 617,700"`) | `_structured_lookup` (departments handler) |

| Field | Value |
|-------|-------|
| **Why duplicate** | All three contain the same core fee values (total, admission, per-semester for each branch). The formats differ: `FEE_GROUP_MAP` uses raw integers, `fee_structures/*.json` uses structured component breakdowns, `canonical_kb.json` uses display-ready strings with `"Rs."` prefix. A change to fee values requires updating **3 separate places**. |
| **Removal risk** | **High** — FEE_GROUP_MAP is actively used by the old handler (flag OFF path). fee_structures/ is the FeeEngine data source (flag ON path). canonical_kb.json is used by `_structured_lookup` for department info. Removing any one breaks a code path. |
| **Cleanup benefit** | **Large** — single source of truth would eliminate desynchronization risk. Estimated **6-8 hours** to unify. |

### 5.2 `fee_structures/*.json` vs `_FeeEngine` schema alignment

| Field | Value |
|-------|-------|
| **Why problematic** | The `fee_structures/*.json` files were created with a `groups`-based schema (`group_a: {branches: [...], ...}`). The `_FeeEngine._validate_program_file` (line 312) expects this format. However, the FeeEngine's `load_all()` currently returns invalid (causing fallback to old handler in `_handle_fee_query_new`). This suggests a **schema incompatibility** between the data files and the parser. The files and parser may have been written against different versions of the schema. |
| **Removal risk** | **High** — the FeeEngine is the Phase 3 flag-ON path and cannot be enabled until this mismatch is resolved |
| **Cleanup benefit** | **Large** — fixing this is a prerequisite for flipping `USE_NEW_FEE_ENGINE` to `True` in production |

---

## 6. Miscellaneous

### 6.1 `_lang_fee_response` "alag se" phrasing (lines 4548, 4550, 4551, 4554, 4556, 4557, 4559, 4561, 4562)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:4548–4562` |
| **Why problematic** | This method contains the banned "alag se" / "আলাদা" phrasing that the Phase 3 redesign explicitly removed. Every code path in this method (9 branches across 3 languages) uses phrasing like `"Admission and semester fees are separate"` or `"ভর্তি এবং সেমিস্টার ফি আলাদা"`. The method is only reachable when the flag is OFF. |
| **Removal risk** | **Medium** — old handler still active when flag OFF |
| **Cleanup benefit** | **Medium** — removes source of banned phrasing; method deleted when old handler is retired |

### 6.2 `DEPT_CODE_MAP` missing `"me"` alias (line 732–761)

| Field | Value |
|-------|-------|
| **Location** | `groq_service.py:732–761` |
| **Why problematic** | The alias `"me"` is intentionally absent because it's an ambiguous English word. This means queries like `"ME fee"` fall through to general fee info instead of returning ME-specific fees. Documented in multi-turn audit. |
| **Removal risk** | N/A — not dead, but deliberately limited |
| **Cleanup benefit** | Adding `"me"` with context-aware disambiguation would improve UX for ME branch queries |

---

## Summary

| Category | Count | Est. cleanup lines | Risk |
|----------|-------|--------------------|------|
| Dead code (methods) | 6 | ~220 lines | None–Low |
| Dead code (model fields) | 8 | ~15 lines | Low |
| Dead code (tool dispatch) | 12 methods + dict + JSON defs | ~150 lines | Low |
| Unreachable branch | 1 | 3 lines | Low |
| Duplicated formatting | 2 groups | ~125 lines | Medium |
| Triplicated JSON data | 3 sources | ~500 lines | High |
| Schema mismatch | FeeEngine ↔ fee_structures JSON | — | High |
| Incomplete localization | HI/BN dicts only up to 10 | — | Medium |
| **Total** | **~30 issues** | **~513 lines** | |

### Top 3 fixes by impact

1. **Fix FeeEngine ↔ fee_structures JSON schema mismatch** — unlocks the flag-ON path (Phase 3)
2. **Delete `_execute_tool` + 12 `_tool_*` methods** — removes 150 lines of dead dispatch code
3. **Unify fee data into single source** — eliminates desync risk across 3 locations

---

*Generated by `task.md` — static analysis of `groq_service.py`, `fee_engine.py`, and `data/fee_structures/*.json`*
