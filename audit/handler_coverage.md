# Structured Handler Coverage Audit

## Handler Priority Order (from `_structured_lookup`)

| # | Handler | Regex | Line | P0 Tests | P0 Coverage | Existing Tests | Uncovered Scenarios | Multilingual Gap | Priority Conflicts |
|---|---------|-------|------|----------|-------------|----------------|---------------------|-----------------|-------------------|
| 1 | **vice_principal** | `\bvice[\s-]?principal\b` | 2274 | F08 (indirect) | ⚠️ 1 test via "professor contact" | 0 | Query with "vice principal" alone; vice principal name not in KB | Returns English only | Must fire before principal (OK) |
| 2 | **principal** | `\bprincipal\b` | 2282 | F08 (indirect) | ⚠️ 1 test via "professor contact" | Unknown | Query "principal" without "vice" prefix; phone number extraction; principal name not in KB | Returns English only | Must fire after vice_principal (OK) |
| 3 | **contact** | `\b(contact\|phone\|mobile\|call\|helpline)\b` | 2291 | B11, F08 | ✅ 2 tests | Yes | No phones in KB → empty response; multilingual phone request | Returns English only; no Hindi/Bengali phone formatting | "contact principal" → contact wins (principal fires first though because principal is checked first at #2!) WRONG: principal fires at #2 before contact at #3. So "contact principal" → principal handler fires |
| 4 | **admission_documents** | `\b(document\|require\|need\|list of).*(admission\|admit)\b` | 2305 | None | ❌ **Zero** | Unknown | Query "what documents needed for admission"; empty KB; Hindi/Bengali document requests | Returns English only | After contact — if query has both "contact" and "document", contact wins |
| 5 | **admission_office** | `\badmission\s*office\b` etc. | 2318 | None | ❌ **Zero** | Unknown | "talk to admission", "transfer to admission", "admission block" | Returns English only | Must fire before admission_general (OK) |
| 6 | **admission_general** | `\b(admission\s*process\|how\s*to\s*apply\|admissions?\|...)\b` | 2332 | F05, C15 | ✅ 2 tests | Unknown | "admission fee" → should fire fee but fires admission (F05 covers this); Bengali/Hindi "admission" query | Returns English only | "admission fee" → fires admission_general BEFORE fee handler (F05 documented) |
| 7 | **installment** | `\b(installments?\|emi\|payment\s*plan\|pay\s*in\s*part)\b` | 2349 | None | ❌ **Zero** | Unknown | "Can I pay fee in installments?"; "EMI option"; Hindi/Bengali installment query | Returns English only | "pay hostel fee in installments" → installment fires before hostel and fee (OK per priority) |
| 8 | **safety** | `\b(safety\|safe\|ragging\|security\|women.*safe)\b` | 2358 | F07 | ✅ 1 test | Unknown | "women safety in campus"; "anti-ragging committee"; Hindi/Bengali safety queries | Returns English for data, but `_lang_response_unknown(lang)` used for fallback | "safety in hostel" → safety fires before hostel (F07 confirms this is correct) |
| 9 | **hostel** | `\bhostel\b` | 2373 | F03, F04, F06, H02 | ✅ 4 tests | Yes | "hostel fee" → fires hostel, not fee (F06 covers); "girls hostel capacity"; hostel unavailable in KB | Returns English only | "hostel fee" → hostel fires before fee (F06: PRIORITY CONFLICT: user wants fee but gets hostel info) |
| 10 | **fee** | `\b(fee\|fees\|total\s*fee\|semester\s*fee\|admission\s*fee\|course\s*fee)\b` | 2391 | A01-A06, F05, F06, F10, E08, H01, H02 | ✅ 12 tests | Yes | Fee for dept not in FEE_GROUP_MAP; Bengali/Hindi "fee" query; `_format_inr` for Hindi/Bengali | `_format_inr` supports hi/bn! But FEE_GROUP_MAP dept names in English only | "admission fee" → admission_general fires before fee (F05). "hostel fee" → hostel fires before fee (F06). `fee_intent` variable reused in departments handler → side effect |
| 11 | **hod** | `\b(hod\|hods\|head\s*of\s*department\|department\s*head)\b` | 2434 | E04, E05, H02 | ✅ 3 tests | Yes | HOD name not in KB → `_lang_hod_unknown(lang)` — supports multilingual fallback!; "hod of CSE" extraction | `_lang_hod_unknown` supports hi/bn! But HOD names returned in English | "hod placement" → hod fires before placement (OK — user asks about HOD of placement) |
| 12 | **faculty** | `\b(professor\|faculty\|teacher\|sir\|madam\|dr\.?\|prof\.?)\b` | 2462 | F08 | ⚠️ 1 test via "professor contact" | Yes (fuzzy name resolution) | No faculty name in query → returns None; fuzzy match score thresholds; all alias variants | Returns English with name only | "professor contact" → contact fires before faculty (#3 vs #12). So F08 analysis is correct: contact wins |
| 13 | **placement** | `\b(placements?\|placed\|recruit\|package\|lpa\|job\|company)\b` | 2467 | A06, F09, G01, G04, G05 | ✅ 5 tests | Yes | Dept code not extracted → falls to overall placement but needs "overall/college/average" keyword; "placement eligibility" doesn't match this handler (caught earlier by `_detect_placement_eligibility_intent`) | Returns English only | "placement eligibility" handled by dedicated detector before this handler |
| 14 | **seats** | `\b(seats\|intake\|capacity)\b` | 2494 | A03, E03, H02 | ✅ 3 tests | Unknown | Total seats arithmetic (generate only); seat query with no dept → returns UNKNOWN_INFO_RESPONSE_EN only; Bengali/Hindi seat query | Returns English only; `UNKNOWN_INFO_RESPONSE_EN` used (not `_lang_response_unknown`) | "seat fee" → seats fires, but doesn't match fee intent; "capacity" may match in wrong contexts |
| 15 | **cutoff** | `\b(cutoff\|cut.off\|rank\|closing.rank\|opening.rank)\b` | 2505 | C17 | ⚠️ 1 test (wrong analysis) | Unknown | Dept not in `_CUTOFF_MAP` (AIML, DS, CSD, CY missing!); rank query for non-BCREC college; Bengali/Hindi cutoff query | Returns English only; `_CUTOFF_MAP` only covers CSE, IT, ECE, EE, ME, CE | "cutoff rank" → cutoff fires; but "rank" also matches eligibility handler's marks/percentage regex at #19! Actually eligibility fires at #19, cutoff fires at #15. Cutoff wins. |
| 16 | **establishment** | `\b(established\|founded\|started\|founding\|when.*start\|...)\b` | 2529 | I08 | ✅ 1 test | Unknown | "when was college established"; "college history" — does "history" match? No, `established` is not in query; but `_detect_structured_intent` has `established\|founded\|started` — "history" NOT in detection regex → _expand_follow_up would NOT recognize "history" as already_complete_intent | Returns English only | "established" after "college history" — expansion may produce text merge instead of structured hit |
| 17 | **computer_lab** | `\bcomputer\s*lab\|lab\s*timing\|lab\s*hours?\b` | 2540 | None | ❌ **Zero** | Unknown | "computer lab hours on Sunday"; "lab timing during exam" | Returns English only | "lab timing" after "placement" — expansion uses structured state? Visit order includes placement, not lab. Fallback to text merge. |
| 18 | **library** | `\blibrary\s*(timing\|hours?)\|reading\s*room\b` | 2548 | G06 (indirect via empty retrieval) | ⚠️ 1 test | Unknown | "library hours on Sunday" (empty retrieval → low confidence guard catches it in G06); "library book availability" | Returns English only | "library timing" — library fires before timings (#19), which is correct |
| 19 | **timings** | `\b(timings?\|office hours?\|...)\b` | 2556 | G06 (indirect) | ⚠️ 1 test | Unknown | "what time does college open"; "college hours during summer" | Returns English only | "library timing" → library fires before timings (#18). "computer lab timing" → computer_lab fires before timings (#17). OK. |
| 20 | **departments** | `\b(department\|branch\|course\|program\|...)\b` | 2567 | C01 (indirect, OOD) | ⚠️ 1 test (via OOD C01) | Unknown | All departments listed; department with no full_name in KB; Bengali/Hindi "course" query | Returns English only | `and not fee_intent` — if fee matches first, departments handler skipped. `fee_intent` variable is reused from earlier check — if query had "fee" even unrelated to fee intent, departments handler bypasses. |
| 21 | **scholarship** | `\bscholarship\b` | 2601 | None | ❌ **Zero** | Unknown | No scholarship schemes in KB; Hindi/Bengali scholarship query; "scholarship eligibility" | `_lang_response_unknown(lang)` used for fallback (supports hi/bn!) | "scholarship fee" → does it fire scholarship or fee? Scholarship handler fires at #21 with `\bscholarship\b`. Fee handler fires at #10 with `\bfee\b`. Fee fires FIRST → returns fee info, not scholarship info. **PRIORITY CONFLICT** |
| 22 | **counselling** | `\b(counselling\|counseling)\b` | 2629 | None | ❌ **Zero** | Unknown | "counselling process"; "WBJEE counselling"; Hindi/Bengali counselling query | `_lang_response_unknown(lang)` used for fallback | Low risk — no priority conflicts with earlier handlers |
| 23 | **eligibility** | `\b(eligibility\|eligible\|marks?\|percentage\|qualif)\b` | 2637 | C15 | ✅ 1 test | Unknown | "eligibility after diploma"; "minimum percentage for CSE"; "marks required" | Return text uses English only; `_lang_response_unknown(lang)` for fallback | "eligibility cutoff" → both eligibility and cutoff handlers could match; cutoff fires FIRST at #15. So "cutoff rank for CSE eligibility" → cutoff handler returns cutoff data, not eligibility. **PRIORITY CONFLICT** |
| 24 | **campus_visit** | `\bcampus\s*visit\b\|\bvisit\s*campus\b\|btour\b` | 2649 | None | ❌ **Zero** | Unknown | "I want to visit the campus"; "schedule a tour"; Hindi/Bengali visit query | Returns English only | "campus tour" → campus_visit fires; but `\btour\b` may match "tourist" in travel context. However travel OOD category would block this before reaching structured lookup. |

---

## Coverage Summary

| Coverage Level | Count | Handlers |
|---------------|-------|----------|
| ✅ 3+ tests | 5 | fee, placement, hostel, hod, seats |
| ⚠️ 1-2 tests | 11 | vice_principal, principal, contact, admission_general, safety, faculty, establishment, library (indirect), timings (indirect), departments (indirect), eligibility |
| ❌ Zero tests | 8 | admission_documents, admission_office, installment, computer_lab, scholarship, counselling, campus_visit |

---

## Specific Priority Conflicts Found

| Conflict | Query | Winner (code) | Expected (user) | Impact |
|----------|-------|--------------|-----------------|--------|
| admission_vs_fee | "admission fee" | admission_general (#6) | fee (#10) | User gets admission process instead of fee amount |
| hostel_vs_fee | "hostel fee" | hostel (#9) | fee (#10) | User gets hostel availability instead of fee |
| scholarship_vs_fee | "scholarship fee" | fee (#10) | scholarship (#21) | User gets fee info instead of scholarship info |
| eligibility_vs_cutoff | "eligibility cutoff rank" | cutoff (#15) | eligibility (#23) | User gets cutoff data instead of eligibility |
| contact_vs_faculty | "professor contact" | contact (#3) | faculty (#12) | User gets phone number instead of faculty info |
| scholarship_in_query | "tell me about fee and scholarship" | _split_multi_intent splits → fee handler returns only fee | both | In stream (no split), fee handler wins |

---

## Recommendations

1. **Fix fee_intent variable reuse** (line 2572): `fee_intent` from line 2394 is reused in departments handler condition `and not fee_intent`. If a previous query matched `\bfee\b`, this variable persists as the last regex match object (truthy), causing departments handler to be skipped incorrectly.

2. **Fix hostel_vs_fee conflict**: "hostel fee" should return hostel fee, not hostel availability. Either: (a) move a "hostel fee" sub-check before the general hostel handler, or (b) merge hostel fee into the fee handler with hostel context.

3. **Fix scholarship_vs_fee conflict**: "scholarship fee" is about scholarship, not fee. Move scholarship handler before fee and add `and not scholarship` to fee handler regex.

4. **Fix eligibility_vs_cutoff conflict**: "eligibility cutoff rank" — add eligibility sub-check in cutoff handler, or make cutoff handler context-aware.

5. **Add zero-coverage handler tests**: admission_documents, admission_office, installment, computer_lab, scholarship, counselling, campus_visit (8 handlers).
