# New Discoveries — Phase 3B P1 Catalog Generation

---

## Discovery 1: `or True` bypass in generate arithmetic block

**File**: `backend/app/services/llm/groq_service.py:3503`
**Code**: `if self._detect_on_topic_arithmetic(query) or True:`

**What**: The `or True` clause makes EVERY query enter the arithmetic → multi-intent → structured_lookup chain before RAG, not just arithmetic queries. This is intentional (structured lookup as a pre-RAG fallback for ALL queries) but undocumented and differs from the stream path.

**Implication**: 
- All generate queries check structured_lookup before RAG (even non-arithmetic ones like "who is the principal")
- Stream only checks structured_lookup at line 4227 with a different priority: structured_lookup first, then arithmetic as fallback
- The comment says "Try arithmetic lookups first (Task 6)" but the code does much more: it also handles multi-intent, structured lookup, and state update

**Parity impact**: 
- Generate: structured_lookup is inside the `or True` block, so it ALWAYS runs
- Stream: structured_lookup is at line 4227, OUTSIDE any condition, so it ALSO always runs
- But generate checks arithmetic BEFORE structured_lookup; stream checks structured_lookup BEFORE arithmetic
- For a semester fee query with valid dept: generate path = arithmetic (hit); stream path = structured_lookup (fee handler returns total fee as default, NOT semester fee breakdown)

**Previously undocumented**: Yes. The architecture audit noted arithmetic priority differs but didn't identify this `or True` as the mechanism.

---

## Discovery 2: `fee_intent` variable scope bleed in `_structured_lookup`

**File**: `backend/app/services/llm/groq_service.py:2391, 2572`
**Code**: `fee_intent = re.search(...)` at line 2391 → checked at line 2572: `and not fee_intent`

**What**: The `fee_intent` local variable is defined inside the fee handler block (line 2391) and referenced in the departments handler (line 2572). This is a scope-bleed anti-pattern. In Python, local variables defined in an `if` block that doesn't execute are still `None` when referenced later (Python doesn't have block scope for `if` statements). So:
- If fee handler matched: `fee_intent` is a regex Match object → fee handler returns early → departments handler NEVER runs (dead check)
- If fee handler didn't match: `fee_intent` is None → `not fee_intent` is True → departments handler works

**Implication**: The `and not fee_intent` on line 2572 is essentially dead code. It can never trigger as a guard because if `fee_intent` matched, the handler returns before reaching line 2572. If `fee_intent` didn't match, the guard is always True.

**Hidden bug**: If a query matches `fee_intent` regex but NONE of the sub-conditions inside the fee handler return (line 2403-2431), execution falls through to line 2433 (HOD handler). `fee_intent` is non-None at this point. All subsequent handlers (hod, faculty, placement, seats, cutoff, establishment, timings, departments) check `and not fee_intent`. Since fee_intent is non-None, ALL of them are skipped. Execution reaches `return None` at line 2657.

This affects queries like: "what departments offer fee waivers for CSE"
- fee handler: dept_code=CSE, FEE_GROUP_MAP has CSE → returns CSE total fee (because "fee" matched and default branch returns total fee)
- User wanted "what departments offer fee waivers" → gets total fee instead

**Previously undocumented**: Yes.

---

## Discovery 3: FILLER_ONLY_PATTERNS missing common hesitation sounds

**File**: `backend/app/services/llm/groq_service.py:308-316`
**Code**: `FILLER_ONLY_PATTERNS`

**What**: "um", "uh", "er", "ah" are not in FILLER_ONLY_PATTERNS. These are the most common human hesitation sounds. "hmm" and "hm" ARE present, but "um" and "uh" (the most frequent) are missing.

**Impact**: 
- "um" → word_count=1, not in AMBIGUOUS_WORDS → falls to `<2 words` check at line 1595 → returns CLARIFICATION_REPEAT_EN ("I didn't quite catch that")
- Same for "uh", "er"
- Users hesitating with "um" or "uh" get a confusing clarification prompt

**Comparison**: "hmm" → matches FILLER_ONLY_PATTERNS → returns ACKNOWLEDGMENT_EN ("Got it. How else can I help you?")
"um" → no match → returns CLARIFICATION_REPEAT_EN ("I didn't quite catch that. Could you please repeat your question?")

Different handling for the same type of hesitation. Inconsistent.

**Previously undocumented**: Yes.

---

## Discovery 4: STT hardcoded confidence 0.95

**File**: `scripts/livekit_agent.py:308`
**Code**: `confidence=0.95`

**What**: Sarvam STT's actual confidence score from the API response is ignored. The `SpeechEvent` always uses the hardcoded `0.95` regardless of transcription quality.

**Impact**:
- Downstream consumers cannot use STT confidence to make routing decisions (e.g., low-confidence transcriptions should go to clarification, not LLM)
- Telemetry has no signal about STT quality
- Hard to detect STT degradation in production

**Arguably**: stream_response does its own transcript quality checks (_validate_transcript, _detect_noisy_transcript), so STT confidence isn't critical for correctness. But it's still a lost signal.

**Previously undocumented**: Yes.

---

## Discovery 5: No deduplication for duplicate STT events

**File**: `scripts/livekit_agent.py:273-316`

**What**: SarvamSTT produces FINAL_TRANSCRIPT events but does not deduplicate them. If LiveKit sends two identical FINAL_TRANSCRIPT events (possible in some VAD configurations), both are processed independently. Each triggers a separate `stream_response` call for the same session_id.

**Impact**: 
- Concurrent stream_response calls for the same session:
  - Race on `_session_states` (both read → both write → last write wins → first write's state update lost)
  - Race on `_sessions` in `_append_session_turn` (interleaved user/assistant entries → history corruption)
  - Double LLM cost for the same query

**LiveKit context**: SarvamSTT has `streaming=False` and `interim_results=False`. Only FINAL_TRANSCRIPT events are produced. But LiveKit's VoicePipelineAgent may send a FINAL_TRANSCRIPT event when VAD endpointing fires AND again when the next utterance starts if there's a pending transcript. This is a known LiveKit edge case.

**Previously undocumented**: Yes.

---

## Discovery 6: Single-word hesitation + keyword passes through without stripping

**File**: `backend/app/services/llm/groq_service.py:1530-1622`

**What**: "fee um" (2 words) passes _validate_transcript because:
- word_count=2 ≥ 2 → doesn't trigger "too short"
- Not in FILLER_ONLY_PATTERNS (2 words not matched)
- INCOMPLETE_TRAILING_PATTERNS: ends with "um" → not in trailing pattern list
- Passes through

The query "fee um" then goes to structured_lookup fee handler → no dept_code → general fee info. Works but the "um" noise token is in the query.

**Better approach**: Strip known hesitation words from the query before processing. This would also fix "CSE um fee" → "CSE fee" which would then get department-specific data.

**Impact**: LOW — functional but noisy. Query "um fee CSE" would fail dept extraction because "um" before "fee" doesn't affect _extract_dept_code (looks for department names, finds "CSE" → works). "fee um CSE" also works (finds "CSE").

**Previously undocumented**: Yes.

---

## Discovery 7: Comparison and aggregation queries have no structured support

**Verification**: Search for "compare", "better than", "vs", "versus", "which is better", "total seats", "all departments", "average" in `_structured_lookup`, `_detect_structured_intent`, and `_split_multi_intent`.

**Findings**:
- **Comparison**: Zero structured handler support. No handler for "better than", "vs", "compare", "versus", "which is better".
  - "Which has better placement, CSE or ECE?" → only first dept (CSE) extracted → single-department answer
  - "Is CSE better than ECE?" → no handler match → RAG → LLM may fabricate comparison
- **Aggregation**: Only `_calculate_seat_total` handles cross-department seat total (generate path only). No handler for:
  - "average placement of all departments" → partially handled by overall placement handler (if "average" keyword present)
  - "total fees for all departments" → no aggregate handler
  - "which department has the highest placement" → no handler
  - "minimum cutoff among all branches" → no handler

**Impact**: HIGH — users asking comparative or aggregate questions get:
  - Single-department data (from the first dept code extracted)
  - RAG fallback (LLM generates answer from limited context)
  - Fabricated data (LLM may invent comparisons not in context)

**Generate vs Stream**: 
- `_calculate_seat_total` only exists in generate path (inside arithmetic block)
- Stream has no aggregation fallback at all

**Previously undocumented**: Yes. The P0 audit focused on single-turn structured handlers. Comparison and aggregation gaps were not evaluated.

---

## Summary

| # | Discovery | Severity | Impact |
|---|-----------|----------|--------|
| 1 | `or True` bypass in arithmetic block | MEDIUM | Generate vs stream parity direction differs |
| 2 | `fee_intent` scope bleed / dead code | LOW | Latent bug, rare trigger |
| 3 | Missing hesitation words in filler patterns | LOW | "um"/"uh" users get clarification confused |
| 4 | STT confidence hardcoded to 0.95 | LOW | Lost telemetry signal |
| 5 | No STT event deduplication | HIGH | Concurrent stream_response = state corruption |
| 6 | Hesitation words not stripped from queries | LOW | Noisy but functional |
| 7 | No comparison/aggregation structured support | HIGH | Fabrication risk for compare queries |
