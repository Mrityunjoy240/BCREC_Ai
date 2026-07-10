# Architecture Audit — BCREC AI Voice Assistant

## 1. Full Pipeline: STT → TTS

```
User Voice → Sarvam STT → [LiveKit Agent] → GroqService → [LiveKit Agent] → Sarvam TTS → User Hears
                                     ↓                              ↑
                              stream_response                 generate_response
                              (voice path)                    (API path, /qa/query)
```

### Entry Points

| Entry | Method | Line | Return Type | Used By |
|-------|--------|------|-------------|---------|
| `generate_response` | `async def` | 3183 | `Dict[str, Any]` (answer, voice_text, source, ...) | REST API `/qa/query`, tests |
| `stream_response` | `async generator` | 4064 | `AsyncIterable[str]` (token-by-token) | LiveKit voice agent |

---

## 2. Pipeline Stage Analysis

### `generate_response` — Complete Stage Sequence

| # | Stage | Method/Step | Input | Output | Dependencies | State Mutations | Assumptions | Risk |
|---|-------|------------|-------|--------|--------------|-----------------|-------------|------|
| 0 | Normalization | `normalize_query()` | raw transcript | normalized text | entity_dictionary.json | None | STT errors are recoverable via alias map | LOW |
| 0.5 | Yes/No Continuation | inline check | query, history | re-routed query or ack response | `_get_last_assistant_response`, `_skip_ambiguous_validation_sessions` | `_skip_ambiguous_validation_sessions.add(sid)` | Last assistant response contains "Would you like" | MEDIUM |
| 0.75 | Transcript Validation | `_validate_transcript()` | query, session_id | None (pass) or clarification string | FILLER_ONLY_PATTERNS, AMBIGUOUS_WORDS, INCOMPLETE_TRAILING_PATTERNS | None | STT fragments match these patterns reliably | LOW |
| 0.5 | STT Noise Detection | `_detect_noisy_transcript()` | query | bool | None | None | Noise has high non-alpha ratio or repeated words | LOW |
| 1 | Language Resolution | `_resolve_language()` | session_id, query | lang code (en/hi/bn) | `_session_langs`, `detect_language()`, BANGLA_ROMAN_WORDS, HINDI_ROMAN_WORDS | `_session_langs[sid] = lang` | Session language persists correctly; romanized detection thresholds are right | MEDIUM |
| — | SAFEPOINT Pre | `_sp_enabled()` / `_sp_safe_pre()` | query, session_id, lang | optional intercepted response | safe_point module | None | SAFEPOINT is optional, disabled in production | LOW |
| — | Language Switch Tracking | inline check | query, history | re-routed query (previous question) | `_is_lang_switch()` | None | Language switch commands always carry no other intent | MEDIUM |
| 2 | Greeting Detection | `_is_greeting()` | query | bool | GREETING_PATTERNS | None | Greetings are single-turn, no follow-up needed | LOW |
| 2.25 | Out-of-Domain | `_is_out_of_domain()` | query | bool | OUT_OF_DOMAIN_CATEGORIES | None | >=3 words with >=2 keyword matches is OOD; short queries bypass | MEDIUM |
| 2.5 | Repeat Intent | `_detect_repeat_intent()` | query | bool | REPEAT_PATTERNS, history | None | Repeat without history falls through gracefully | LOW |
| 2.65 | Placement Eligibility | `_detect_placement_eligibility_intent()` | query | bool | hardcoded patterns | None | All variations of "if I don't study" are covered | LOW |
| 2.7 | Conversation Replay | `_detect_repeat_conversation_intent()` | query | "all" or None | history | None | "repeat everything" is unambiguous | LOW |
| 2.75 | Follow-up Expansion | `_expand_follow_up_query()` | query, history, session_id | (expanded_query, debug_info) | `_session_states`, `_detect_structured_intent`, ConversationState, DOMAIN_FACETS | None | State is fresh (updated on last structured hit); domain facet overlap is correct | **HIGH** |
| 2.8 | Structured Arithmetic | inline: semester/total/seat regex | retrieval_query | arith result string or None | FEE_GROUP_MAP, `_extract_dept_code()` | None | Department code is extractable; fee map covers all depts | LOW |
| 2.8 | Multi-Intent Split | `_split_multi_intent()` | retrieval_query | list of query segments | None | None | "and"/"or" join two >=2-word phrases | MEDIUM |
| 2.8 | Structured Lookup | `_structured_lookup()` | retrieval_query, lang | answer string or None | canonical_kb.json, 27 regex handlers | `_push_domain_visit()`, state slot update | Handler order is correct; no regex conflicts | **HIGH** |
| 3 | RAG Retrieval | `_retrieve_context()` | retrieval_query | (context_str, confidence) | vector_store (ChromaDB+BGE-M3), `_normalize_query()` | `_last_retrieval_data` | Vector search is reliable; dedup by section:subsection is correct | MEDIUM |
| 3.5 | Low-Confidence Guard | inline check | context, confidence | fallback or continue | RETRIEVAL_CONFIDENCE_THRESHOLD | None | Threshold (0.15) separates relevant from irrelevant | MEDIUM |
| 4 | Cache Lookup | inline | query, lang, context | cached hit or None | `_cache` (TTLCache) | `_cache_stats` | Caching first-turn only queries is safe | LOW |
| 5 | Prompt Building | `_build_messages()` | query, context, history, lang | messages list | SYSTEM_PROMPT, lang_hint map | None | 10-turn history fits in context window | LOW |
| 6 | LLM Call | Groq API | messages | completion | `_rate_limiter`, FALLBACK_MODELS | `_rate_limiter` state | 3 retries + model fallback chain works | MEDIUM |
| 6.5 | Response Truncation | inline | answer | truncated answer | MAX_VOICE_RESPONSE_CHARS (400) | None | Sentence-boundary detection works with Dr. B.C. Roy patterns | MEDIUM |
| 7 | Hallucination Guard | `_validate_answer()` | answer, context, query | (is_valid, reason) | `_extract_entities()`, `_context_contains()` | None | Numbers in answer must appear in context (or query) | **HIGH** |
| 7.5 | Out-of-KB Detection | inline | answer | fallback or continue | unknown_signals list | None | LLM says "I don't know" when it doesn't know | MEDIUM |
| 8 | Bengali Normalization | inline | answer | normalized answer | None | None | "রুপি" → "টাকা" is always correct | LOW |
| 8.5 | TTS Preparation | `_prepare_for_tts()` | answer, lang | voice_text | `clean_for_voice()`, `normalize_for_tts()` | None | Acronyms can be safely expanded | LOW |
| 10 | Session Append | `_append_session_turn()` | session_id, query, answer | None | `_sessions` dict | `_sessions[sid].append()` | 12-turn cap is correct | LOW |
| 11 | Cache Store | inline | cache_key, response | None | `_cache` | `_cache[cache_key]` | First-turn only, valid responses only | LOW |

### `stream_response` — Stage Sequence

| # | Stage | Present? | Notes |
|---|-------|----------|-------|
| 0 | Normalization | YES | Same as generate |
| 0.5 | Yes/No Continuation | **MISSING** | Voice users cannot say "yes"/"no" after clarification |
| 0.75 | Transcript Validation | YES | Same |
| 0.5 | STT Noise Detection | YES | Same |
| 1 | Language Resolution | YES | Same |
| — | Language Switch Tracking | **MISSING** | No re-run of previous question after language switch |
| — | SAFEPOINT Pre | Replaced with Handoff | Different SAFEPOINT function (`_sp_handoff`) |
| 2 | Greeting Detection | **MISSING** | Voice users don't get greeting responses |
| 2.25 | Out-of-Domain | YES | Same |
| 2.5 | Repeat Intent | YES | Same (with session append bypass when conversation_history provided) |
| 2.65 | Placement Eligibility | YES | Same |
| 2.7 | Conversation Replay | YES | Same |
| 2.75 | Follow-up Expansion | YES | Same |
| 2.8 | Structured Lookup | **PARTIAL** | Multi-intent splitting MISSING. Arithmetic is a fallback (checks only after structured fails), not primary |
| 3 | RAG Retrieval | YES | Same |
| 3.5 | Low-Confidence Guard | YES | Same |
| 4 | Cache Lookup | **MISSING** | No cache at all in stream path |
| 5 | Prompt Building | YES | Same but uses `llm_query` (normalized raw query) not the expanded retrieval_query |
| 6 | LLM Call | YES | Async streaming with same retry/fallback |
| 6.5 | Response Truncation | **DIFFERENT** | Character-count truncation DURING streaming (no sentence-boundary awareness) |
| 7 | Hallucination Guard | **NON-BLOCKING** | Logs violations but does NOT replace the answer |
| 7.5 | Out-of-KB Detection | **NON-BLOCKING** | Logs violations but does NOT replace the answer |
| 8 | Bengali Normalization | **MISSING** | No "রুপি" → "টাকা" normalization |
| 8.5 | TTS Preparation | **MISSING** | No TTS cleanup (acronym expansion, digit cleanup) |
| 10 | Session Append | YES | Conditional: only when `conversation_history is None` |

---

## 3. Parity Matrix

| Behavior | `generate_response` | `stream_response` | Impact |
|----------|-------------------|-------------------|--------|
| Yes/No continuation | ✅ Full | ❌ Missing | Voice users can't confirm/clarify after "Would you like" |
| Greeting response | ✅ Full | ❌ Missing | No greeting for voice users |
| Language switch re-run | ✅ Full | ❌ Missing | Switching language doesn't replay previous answer |
| Multi-intent splitting | ✅ Full | ❌ Missing | "fee and hostel" → only first matched handler |
| Arithmetic lookup priority | ✅ Primary (checked first) | ❌ Fallback (checked only after structured fails) | Different behavior for fee+arithmetic queries |
| Cache lookup | ✅ Full | ❌ Missing | Every voice request hits LLM (higher latency, higher cost) |
| Response truncation | ✅ Sentence-boundary aware | ❌ Raw char truncation | Voice output may be cut mid-word |
| Hallucination guard | ✅ Blocking (replaces answer) | ⚠️ Non-blocking (logs only) | Voice users may hear hallucinated content |
| Out-of-KB detection | ✅ Blocking (replaces answer) | ⚠️ Non-blocking (logs only) | Voice users may hear "I don't know" answers |
| Bengali normalization | ✅ Full | ❌ Missing | Bengali TTS may pronounce "রুপি" |
| TTS preparation | ✅ Full | ❌ Missing | Acronyms may be mispronounced |
| Prompt query used | raw `query` (original) | `llm_query` (normalized) | Different context fed to LLM |
| State update on structured hit | ✅ Full | ✅ Full | Both update ConversationState |
| DEMO_SAFEPOINT | ✅ Pre + Post | ⚠️ Handoff only | Different safepoint behavior |
| Error response | ✅ Phone number included | ❌ Generic "Sorry" | Voice users don't get fallback contact info |

---

## 4. Dependency Graph

```
normalize_query (no deps)
    │
    ▼
_validate_transcript (depends: FILLER_ONLY_PATTERNS, AMBIGUOUS_WORDS, GREETING_PATTERNS)
    │
    ▼
_detect_noisy_transcript (no deps)
    │
    ▼
_resolve_language (depends: _session_langs, detect_language, BANGLA/HINDI_ROMAN_WORDS)
    │
    ├──> _is_greeting (depends: GREETING_PATTERNS)
    │       │
    ├──> _is_out_of_domain (depends: OUT_OF_DOMAIN_CATEGORIES)
    │       │
    ├──> _detect_repeat_intent (depends: REPEAT_PATTERNS, _sessions history)
    │       │
    ├──> _detect_placement_eligibility_intent (no deps)
    │       │
    ├──> _detect_repeat_conversation_intent (no deps)
    │       │
    ├──> _expand_follow_up_query (depends: _session_states, _detect_structured_intent,
    │       │                      DOMAIN_FACETS, ConversationState)
    │       │
    │       ├──> [_structured_lookup / _calculate_*_fees / _split_multi_intent]
    │       │       │
    │       │       └──> _push_domain_visit → ConversationState (mutual dependency with expansion)
    │       │
    │       └──> _retrieve_context (depends: vector_store, _normalize_query)
    │               │
    │               └──> _build_messages (depends: SYSTEM_PROMPT, history, lang_hint)
    │                       │
    │                       └──> LLM Call (depends: _rate_limiter, FALLBACK_MODELS)
    │                               │
    │                               └──> _validate_answer (depends: _extract_entities, _context_contains)
    │                                       │
    │                                       └──> _prepare_for_tts (depends: clean_for_voice, normalize_for_tts)
    │
    └──> All early-return handlers (greeting/OOD/repeat/etc.) → _append_session_turn
```

**Circular dependency**: `_expand_follow_up_query` reads `_session_states`, which is ONLY updated when `_structured_lookup` hits. But `_expand_follow_up_query` runs BEFORE `_structured_lookup` in the pipeline. This means:
- Turn N: structured lookup hits → state updated
- Turn N+1: follow-up expansion reads state (correct)
- But if Turn N was RAG-only (no structured hit) → state is stale → expansion uses wrong context

---

## 5. Hidden Coupling & Fragile Assumptions

### 5.1 `_detect_structured_intent` / `_structured_lookup` coupling
- `_detect_structured_intent` (line 1768) is a mirror of `_structured_lookup`'s handler priority (line 2264)
- Used by `_expand_follow_up_query` to decide if a query is "already complete"
- If handler order diverges, expansion will classify intents incorrectly
- **28 regex checks** in priority order — fragile and order-dependent

### 5.2 ConversationState staleness
- `_session_states` is only updated when `_structured_lookup` returns a hit
- RAG-only responses (groq_rag source) do NOT update ConversationState
- Follow-up expansion on the next turn uses potentially stale state from 3 turns ago

### 5.3 Language-ignorant structured responses
- `_structured_lookup` receives `lang` parameter but many handlers return English-only strings
- `_format_inr` formats numbers but only for fee-related handlers
- HOD names, contact info, admission info — all returned in English regardless of user's language

### 5.4 Fee handler duplication
- Fee is handled in TWO places:
  1. **Structured arithmetic block** (line 3503-3563) — pre-retrieval, checks semester/total/seat regex
  2. **`_structured_lookup` fee handler** (line 2391-2431) — inside the 27-handler chain
- The arithmetic block runs first (with `_detect_on_topic_arithmetic(query) or True` — ALWAYS TRUE)
- This means fee queries ALWAYS enter the arithmetic block, and only fall through to structured_lookup if dept_code is None
- After structured_lookup's fee handler, ALL remaining handlers still run (no early return at the GroqService level)

### 5.5 Multi-intent location
- `_split_multi_intent` is called ONLY inside the arithmetic block (line 3566)
- In stream_response, it's NEVER called → "fee and hostel" returns only the first matched handler's result
- This means multi-intent works for generate_response but NOT for stream_response

### 5.6 OOD false positives for college-adjacent topics
- "python" is in OUT_OF_DOMAIN_CATEGORIES["coding"]
- A query like "does BCREC offer a python course" would be BLOCKED (has 3+ words, matches "python")
- "cricket" as a college sport query would be blocked
- Short queries (< 3 words) bypass OOD, but longer queries with college-adjacent terms are at risk

### 5.7 Cache inconsistency
- Cache is only checked when `not history` (first turn only)
- Cache key includes `context` (which changes per query) — so even first-turn repeats of the same query get a cache miss if the retrieval returned different chunks
- Cache is skipped entirely in stream_response, even for first-turn queries

### 5.8 Rate limiter + circuit breaker gap
- `_rate_limiter.acquire()` returns a wait time but has no hard cap — if rate limited repeatedly, it keeps retrying
- After 3 retries × multiple models, total wait can be significant
- No circuit breaker — once Groq starts failing, every request still tries 3× retries × fallback models
- In generate_response: DEMO_SAFEPOINT mode has a 6-second timeout per call; non-SAFEPOINT mode has NO timeout (blocks indefinitely)

### 5.9 Stream response prompt uses different query
- `generate_response` passes `query` (original user query) to `_build_messages`
- `stream_response` passes `llm_query` (which is `self._normalize_query(query)`) to `_build_messages`
- This means the LLM sees different text for the same user input depending on the path

---

## 6. Highest-Risk Components

| Component | Risk Score | Regression Probability | Blast Radius | Maintenance Complexity | Production Impact |
|-----------|-----------|----------------------|--------------|----------------------|-------------------|
| **Generate/Stream parity gap** | **CRITICAL** | HIGH (every new feature widens gap) | HIGH (voice users = different experience) | EXTREME (manually sync 2 paths) | **HIGH** — voice users miss features |
| **GroqService god class** | **CRITICAL** | HIGH (62 methods, 4554 lines) | HIGH (single change affects many paths) | EXTREME (no separation of concerns) | **HIGH** — fragile, hard to debug |
| **Non-blocking hallucination guard (stream)** | **HIGH** | MEDIUM | HIGH (users hear wrong numbers) | LOW (intentional design) | **HIGH** — trust erosion |
| **Regex structured lookup** | **HIGH** | HIGH (regex conflicts, order) | MEDIUM (wrong answers for 1 domain) | HIGH (27 handlers, all regex) | **MEDIUM** — wrong answers |
| **ConversationState staleness** | **HIGH** | MEDIUM | MEDIUM (wrong follow-up expansion) | HIGH (state update only on structured hit) | **MEDIUM** — confusing conversations |
| **OOD false positives** | **MEDIUM** | HIGH (college + off-topic keywords) | LOW (single query blocked) | MEDIUM (keyword list management) | **MEDIUM** — legitimate queries blocked |
| **In-memory session state** | **MEDIUM** | LOW (works for single instance) | HIGH (clustered deployment fails) | LOW | **MEDIUM** — scaling blocker |
| **Language-ignorant responses** | **MEDIUM** | MEDIUM | MEDIUM (Hindi/Bengali users get English) | MEDIUM (per-handler translation) | **MEDIUM** — poor UX for non-English |
| **Cache inconsistency** | **LOW** | LOW | LOW | LOW | **LOW** — just higher latency |
| **No timeout in non-SAFEPOINT mode** | **MEDIUM** | LOW (timeout exists in SAFEPOINT) | MEDIUM (blocks request thread) | LOW | **MEDIUM** — hung requests |

---

## 7. Summary of Architectural Findings

### 7.1 What Works Well
- Normalization pipeline handles STT errors effectively
- Transcript validation catches noise before LLM
- Structured arithmetic prevents LLM fee hallucinations
- Hallucination guard (blocking) in generate_response prevents wrong numbers
- ConversationState design is sound (when state is fresh)
- Telemetry/logging is comprehensive

### 7.2 Critical Issues
1. **Dual-path architecture is unsustainable** — every feature must be implemented twice
2. **Stream path is a degraded experience** — 8+ missing features vs generate path
3. **God class prevents safe refactoring** — 4554-line class with 62 methods
4. **Non-blocking guards in stream** mean voice users get unvalidated LLM output
5. **ConversationState staleness** undermines follow-up expansion reliability
6. **Regex handler chain is fragile** — order-dependent, 28 regex checks, easy to break

### 7.3 Next Steps for Red-Team Evaluation
The evaluation suite should target, in priority order:
1. **Parity gap exploits** — queries that behave differently on generate vs stream
2. **OOD boundary cases** — college-adjacent topics that should/shouldn't be blocked
3. **Language switching edge cases** — romanized Bangla/Hindi, code-switching mid-conversation
4. **ConversationState contamination** — multi-domain cross-talk, stale state follow-ups
5. **Multi-intent failures in stream** — "fee and hostel" style queries via voice
6. **Hallucination guard bypass** — answers with numbers that pass/fail validation
7. **Structured lookup priority conflicts** — queries that match multiple handlers
8. **Cache inconsistency** — first-turn cache miss scenarios
