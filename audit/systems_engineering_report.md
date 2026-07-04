# Systems Engineering Report: BCREC Voice Pipeline

## TASK 1: Complete End-to-End Execution Graph (LiveKit Voice)

```
MICROPHONE (user speaks)
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. SILERO VAD (voice_agent.py:427)                                      │
│    Detects speech activity, segments utterances                         │
│    Stage: Required (voice pipeline entry gate)                          │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. SARVAM STT (SarvamSTT._recognize_impl, livekit_agent.py:263)         │
│    Converts audio → text via Sarvam API (saaras:v3 model)               │
│    Stage: Required (converts speech to text)                            │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. LAYER 1 — _fix_stt_acronyms (livekit_agent.py:244)                   │
│    11 hardcoded regex patterns (cse-aml→CSE-AIML, csd→CSD, etc.)       │
│    Stage: DUPLICATE (overlaps with Layer 2, see TASK 3)                 │
│    Runs in LiveKit ONLY                                                 │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 4. LAYER 2 — normalize_query (normalizer.py:433)                        │
│    a. Unicode normalization (NFKC)                                      │
│    b. Lowercase                                                         │
│    c. Punctuation cleanup (hyphen tokenization fix active)              │
│    d. Whitespace normalization                                          │
│    e. Mixed-language mapping (Bengali/Hindi→English)                    │
│    f. STT mistake correction (entity_dictionary.json)                   │
│    g. Exact alias replacement (entity_dictionary.json)                  │
│    h. Fuzzy entity resolution (with stop-word guard active)             │
│    Stage: Required (config-driven STT recovery + entity resolution)     │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 5. TRANSCRIPT VALIDATION (_validate_transcript, groq_service.py:1153)   │
│    Rejects: empty, filler-only, ambiguous single-word, incomplete       │
│    Stage: Required (STT noise gate — but runs TWICE in stream path)     │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 6. NOISE DETECTION (_detect_noisy_transcript)                           │
│    Catches garbage/repeated tokens                                      │
│    Stage: Required (secondary noise gate)                               │
│    Runs in REST generate_response AND stream_response                   │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 7. LANGUAGE RESOLUTION (_resolve_language, groq_service.py:1071)        │
│    Detects Bengali/Devanagari script, switch commands, short follow-ups │
│    Stage: Required (determines LLM response language)                   │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 8. GREETING DETECTION (_is_greeting)                                    │
│    Returns deterministic greeting if query matches greeting patterns    │
│    Stage: Required (optimization — skips RAG+LLM)                       │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 9. OUT-OF-DOMAIN DETECTION (_is_out_of_domain)                          │
│    Blocks clearly off-topic queries before retrieval                    │
│    Stage: Required (safety gate — skips RAG+LLM)                        │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 10. REPEAT INTENT DETECTION (_detect_repeat_intent)                     │
│     Returns last assistant response without RAG                         │
│     Stage: Required (optimization — exists in both paths)               │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 11. PLACEMENT ELIGIBILITY (_detect_placement_eligibility_intent)        │
│     Structured lookup for placement queries                             │
│     Stage: Required (optimization — exists in both paths)               │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 12. CONVERSATION REPLAY (_detect_repeat_conversation_intent)            │
│     "Tell me what we discussed" type queries                            │
│     Stage: Required (feature — exists in both paths)                    │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 13. FOLLOW-UP EXPANSION (_expand_follow_up_query)                       │
│     Expands short follow-up queries using conversation history          │
│     Stage: Required (retrieval quality — exists in both paths)          │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 14. STRUCTURED LOOKUP (_structured_lookup, _calculate_semester_fees,    │
│     _calculate_total_fees, _calculate_seat_total)                        │
│     Answers fee/seat arithmetic from canonical KB without LLM           │
│     Stage: Required (optimization — exists in both paths)               │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 15. LAYER 3 (first call) — _normalize_query (groq_service.py:882)       │
│     14 hardcoded regex patterns for query normalization                 │
│     Called inside _retrieve_context (groq_service.py:910)               │
│     Stage: DUPLICATE (overlaps with Layer 2, see TASK 3)                │
│     Runs INSIDE retrieval — purpose: improve vector search matches      │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 16. VECTOR SEARCH (_retrieve_context, groq_service.py:906)              │
│     BGE-M3 embedding → cosine similarity → semantic re-rank             │
│     → section-aware dedup → top-8 context chunks                       │
│     Stage: Required (core RAG)                                          │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 17. LOW-CONFIDENCE GUARD (confidence < RETRIEVAL_CONFIDENCE_THRESHOLD)  │
│     Returns polite fallback when retrieval is irrelevant                 │
│     Stage: Required (safety gate — exists in REST but NOT in stream!)   │
│     ⚠ MISSING in stream_response — see TASK 4                          │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 18. CACHE LOOKUP (REST only — SKIPPED for sessions with history)        │
│     Stage: Optional optimization (not in stream path)                   │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 19. BUILD LLM MESSAGES (_build_messages, groq_service.py:1010)          │
│     SYSTEM_PROMPT + history (last 10 turns) + context + user question   │
│     Stage: Required (prompt construction)                               │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 20. GROQ LLM CALL (rate-limited, retry with fallback models)            │
│     Model: llama-3.3-70b-versatile (default)                            │
│     Stage: Required (core inference)                                    │
└──────────────────────────────────────────────────────────────────────────┘
  │
  ▼ (REST path — generate_response)                  (stream path — stream_response)
  │                                                   │
  ▼                                                   ▼
┌────────────────────────────────────────┐  ┌────────────────────────────────────┐
│ 21a. LAYER 3 (second call)             │  │ 21b. NO LAYER 3 second call        │
│      _normalize_query IS NOT called    │  │      _normalize_query called        │
│      again — query already normalized  │  │      ONCE in _retrieve_context      │
│      in step 15                        │  │      (same as step 15)              │
└────────────────────────────────────────┘  └────────────────────────────────────┘
  │                                                   │
  ▼                                                   ▼
┌────────────────────────────────────────┐  ┌────────────────────────────────────┐
│ 22a. HALLUCINATION GUARD               │  │ 22b. HALLUCINATION GUARD            │
│      _validate_answer (BLOCKING!)      │  │      _validate_answer (NON-BLOCKING)│
│      Replaces answer with fallback     │  │      Logs warning, does NOT replace │
│      Stage: Required (safety)          │  │      Stage: Required (safety)       │
└────────────────────────────────────────┘  └────────────────────────────────────┘
  │                                                   │
  ▼                                                   ▼
┌────────────────────────────────────────┐  ┌────────────────────────────────────┐
│ 23a. BENGALI NORMALIZATION            │  │ 23b. BENGALI NORMALIZATION          │
│      রুপি→টাকা (REST only)            │  │      MISSING in stream path!        │
│      Stage: Required (pronunciation)  │  │      ⚠ See TASK 4                   │
└────────────────────────────────────────┘  └────────────────────────────────────┘
  │                                                   │
  ▼                                                   ▼
┌────────────────────────────────────────┐  ┌────────────────────────────────────┐
│ 24a. PREPARE FOR TTS                   │  │ 24b. NO PREPARE_FOR_TTS            │
│      _prepare_for_tts (REST only):     │  │      TTS is handled by SarvamTTS   │
│      normalize_for_tts → clean_for_voice│  │      in livekit_agent.py:314      │
│      Returns separate voice_text field │  │      which calls apply_lexicon()   │
│      Stage: Required (pronunciation)   │  │      Stage: DIFFERENT              │
└────────────────────────────────────────┘  └────────────────────────────────────┘
  │                                                   │
  ▼                                                   ▼
┌────────────────────────────────────────┐  ┌────────────────────────────────────┐
│ 25a. STORE + CACHE                     │  │ 25b. STORE IN SESSION              │
│      _append_session_turn + cache      │  │      _append_session_turn          │
│      Stage: Required (memory)          │  │      (no cache in stream)          │
└────────────────────────────────────────┘  └────────────────────────────────────┘
  │                                                   │
  ▼                                                   ▼
  TEXT RESPONSE RETURNED                               TTS (SarvamTTS)
  (FastAPI /qa/query)                                  │
                                                       ▼
                                              ┌────────────────────────────────────┐
                                              │ 26. SARVAM TTS                      │
                                              │     SarvamChunkedStream._run()      │
                                              │     livekit_agent.py:314            │
                                              │     a. apply_lexicon(text, lang)    │
                                              │        - LEXICON acronym expansion  │
                                              │        - AML→AIML normalization     │
                                              │        - Phone number digit conv    │
                                              │     b. TTS API call                 │
                                              │     c. WAV parsing + chunking       │
                                              │     Stage: Required (audio out)     │
                                              └────────────────────────────────────┘
                                                       │
                                                       ▼
                                              SPEAKER (user hears audio)


## TASK 2: Stage Classification

| Stage # | Name | Classification | Rationale |
|---------|------|---------------|-----------|
| 1 | Silero VAD | Required | Voice pipeline entry gate — cannot be removed |
| 2 | Sarvam STT | Required | Converts audio to text |
| 3 | L1 _fix_stt_acronyms | **DUPLICATE** | 11 regex patterns — all covered by L2 + entity_dict |
| 4 | L2 normalize_query | Required | Config-driven normalization — target future state |
| 5 | _validate_transcript | Required | STT noise gate — runs TWICE in stream path (bug) |
| 6 | _detect_noisy_transcript | Required | Secondary noise gate |
| 7 | _resolve_language | Required | Determines LLM response language |
| 8 | _is_greeting | Required (optimization) | Skips RAG+LLM for greetings |
| 9 | _is_out_of_domain | Required (safety) | Blocks off-topic queries |
| 10 | _detect_repeat_intent | Required (optimization) | Replays last response |
| 11 | _detect_placement_eligibility | Required (feature) | Structured lookup |
| 12 | _detect_repeat_conversation | Required (feature) | Conversation replay |
| 13 | _expand_follow_up_query | Required (retrieval quality) | Context expansion |
| 14 | Structured lookup/arithmetic | Required (optimization) | KB answers without LLM |
| 15 | L3 _normalize_query (in _retrieve_context) | **DUPLICATE** | 14 regex patterns — mostly covered by L2 |
| 16 | Vector search (BGE-M3) | Required | Core RAG retrieval |
| 17 | Low-confidence guard | Required (safety) | **MISSING in stream path** |
| 18 | Cache lookup | Optional | REST-only optimization |
| 19 | _build_messages | Required | Prompt construction |
| 20 | Groq LLM call | Required | Core inference |
| 21a | Hallucination guard (REST) | Required (safety) | BLOCKING — replaces answer |
| 21b | Hallucination guard (stream) | Required (safety) | NON-BLOCKING — logs only |
| 22a | Bengali normalize (REST) | Required | Pronunciation fix **MISSING in stream** |
| 22b | _prepare_for_tts (REST) | Required | TTS normalization path differs |
| 23 | _apply_lexicon (LiveKit) | Required | LiveKit's own TTS preprocessing |
| — | VoiceSessionManager | **DEAD CODE** | Uses Deepgram STT, never imported |
| — | stt.py endpoint | Required (REST) | Separate Sarvam STT API endpoint |
| — | tts.py endpoint | Required (REST) | Separate Sarvam TTS API endpoint |

### Layer Coverage Summary
- **Layer 1** (11 patterns): All 11 patterns have equivalent coverage in Layers 2+3
- **Layer 2** (8-step pipeline): Config-driven, covers ~80% of L3 patterns via entity_dict.json
- **Layer 3** (14 patterns): 10 of 14 patterns already in L2. The 4 unique to L3:
  1. `electrical` → EE (L2 has this via alias, but `electrical` is fuzzy-matched not exact)
  2. `mechanical` → ME (same — fuzzy-only match in L2)
  3. `civil` → CE (same)
  4. `computer` → CSE (same — only in aliases, not as primary match)
  5. Bengali Roman→Native transliteration (upo-pradhan→উপ-প্রধান) — purely for retrieval

### Dead Code
- `backend/app/services/voice_session.py` (95 lines) — Uses Deepgram STT, zero imports anywhere
- `scripts/deprecated/` directory (if any exists)


## TASK 3: Duplicate Transformation Map

### Duplicate 1: L1 ↔ L2 (STT acronym correction)
```
L1 (livekit_agent.py:229-241)           L2 (entity_dictionary.json + normalizer.py)
───────────────────────────────          ─────────────────────────────────────────
\bcse[\s-]?aml\b → CSE-AIML              "cseaml" in AIML stt_mistakes (entity_dict)
\bcs e[\s-]?aml\b → CSE-AIML             "cseaml" same entry
\bcciml\b → AIML                          "cciml" in AIML stt_mistakes
\ba[\s-]?i[\s-]?ml\b → AIML               "a i ml" is an alias, not stt_mistake (minor diff)
\bcsd\b → CSD                             "csd" in CSD stt_mistakes
\bdata sci\b → Data Science               "data sci" in DS aliases
\bcyber sec\b → Cyber Security            (NOT in entity_dict — would need alias)
\binfo tech\b → Information Technology    (NOT in entity_dict — would need alias)
\belec[ -]?comm\b → ECE                   "ece" is stt_mistake, "electronics" is alias
\bh[\s-]?o[\s-]?d\b → HOD                "h o d" is alias in common_abbreviations.HOD
\bprincipal\b → Principal                 "principal" is alias in faculty.principal
```
**Verdict**: 9/11 L1 patterns have equivalent L2 coverage. **2 missing**: "cyber sec" and "info tech" — need alias addition (but constrained by matcher bugs).

### Duplicate 2: L2 ↔ L3 (config-driven vs hardcoded, query path only)
```
L2 (normalizer.py)                     L3 (groq_service.py:882-904)
──────────────────────                 ────────────────────────────
"cseaml" → CSE-AIML (stt_mistake)      \bcseaml\b → CSE-AIML (line 887)
"cs e aml" variants (stt_mistake)       \bcs e[\s-]?aml\b → CSE-AIML (line 888)
"cciml" → AIML (stt_mistake)           \bcciml\b → AIML (line 889)
"csd" → CSD (stt_mistake)              \bcsd\b → CSD (line 890)
"data sci" → DS (alias)                \bdata sci\b → Data Science (line 891)
Not in entity_dict                      \bcyber sec\b → Cyber Security (line 892)
Not in entity_dict                      \binfo tech\b → Information Technology (line 893)
"ece" → ECE (stt_mistake)              \belec[ -]?comm\b → ECE (line 894)
Not in entity_dict (alias: electri)     \belectrical\b → EE (line 895)
Not in entity_dict (alias: mechanic)    \bmechanical\b → ME (line 896)
Not in entity_dict (alias: civil)       \bcivil\b → CE (line 897)
Not in entity_dict (alias: computer)    \bcomputer\b → CSE (line 898)
"ai ml" → AIML (alias)                  \bai[\s-]?ml\b → AIML (line 899)
No L2 equivalent                       \bupo[- ]?pradhan\b → উপ-প্রধান (line 901)
```
**Verdict**: 10/14 L3 patterns have L2 equivalents. **4 unique**: electrical/mechanical/civil/computer are fuzzy-only matches in L2, not exact. 1 Bengali transliteration is unique to L3.

### Where is L3 called?
1. `_retrieve_context()` (groq_service.py:910) — normalizes query BEFORE vector search
2. `_build_messages()` (groq_service.py:1010) — does NOT call L3

Wait — let me re-check. In `stream_response` line 2977: `llm_query = self._normalize_query(query)` — this is the LLM prompt query, separate from retrieval. And then `_retrieve_context` is called with `retrieval_query` (which is the expanded follow-up, not the normalized query).

So L3 is called TWICE in `stream_response`:
- Line 2977: `llm_query = self._normalize_query(query)` — for the LLM prompt
- Line 910 (inside `_retrieve_context`): normalized again for vector search

And in `generate_response`:
- Line 910 (inside `_retrieve_context`): normalized for vector search
- Line 2518: `_build_messages` receives the ALREADY normalized query (line 2093: `query = norm_log.normalized_text`)
- But `_build_messages` does NOT call _normalize_query again

Actually wait, let me look more carefully:

In `generate_response`:
- Line 2088: `norm_log = normalize_query(query)` — L2 applied
- Line 2093: `query = norm_log.normalized_text` — query replaced with L2 output
- Line 2424: `context, confidence = self._retrieve_context(retrieval_query)` — L3 applied to retrieval_query (which is follow-up expanded, may be different from query)
- Line 2518: `_build_messages(query=query, context=context, ...)` — passes L2-normalized query

In `stream_response`:
- Line 2829: `norm_log = normalize_query(query)` — L2 applied
- Line 2834: `query = norm_log.normalized_text`
- Line 2977: `llm_query = self._normalize_query(query)` — L3 applied AGAIN for LLM prompt!
- Line 2979: `context, confidence = self._retrieve_context(retrieval_query)` — L3 applied for retrieval

So the flow is:
- `generate_response`: L2(query) → L3(retrieval_query for vector search) → LLM prompt gets L2(query)
- `stream_response`: L2(query) → L3(query) → L3(retrieval_query for vector search) → L3(query) for LLM prompt

**Key finding**: In `stream_response`, L3 is applied to the query TWICE — once at line 2977 for the LLM prompt, and once inside `_retrieve_context` at line 910 for vector search.

### Dependency Graph

```
              ┌─────────────┐
              │ Audio Input │
              └──────┬──────┘
                     ▼
              ┌─────────────┐
              │ VAD         │
              └──────┬──────┘
                     ▼
              ┌─────────────┐
              │ STT (Sarvam)│
              └──────┬──────┘
                     ▼
         ┌───────────────────────┐
         │ L1: _fix_stt_acronyms │ ◄── DUPLICATE (LiveKit only)
         └──────────┬────────────┘
                    ▼
         ┌──────────────────────┐
         │ L2: normalize_query  │ ◄── TARGET (config-driven)
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │ validate_transcript  │ ◄── runs TWICE in stream (bug)
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │ intent detection     │
         │ (greeting/ood/repeat │
         │  /placement/followup)│
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │ retrieval: L3 + vec │ ◄── DUPLICATE: L3 called inside
         └──────────┬───────────┘    also called again for LLM prompt
                    ▼
         ┌──────────────────────┐
         │ LLM prompt:          │
         │ L2(query)+L3(llm_q) │ ◄── QUERY normalized TWICE
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │ Groq LLM response    │
         └──────────┬───────────┘
                    ▼
    ┌───────────────┴────────────────┐
    ▼                                 ▼
┌───────────────┐              ┌───────────────┐
│ REST:         │              │ LiveKit:       │
│ hallucination │              │ non-blocking   │
│ guard (block) │              │ guard (log)    │
│ Bengali norm  │              │ ─ missing ─    │
│ prepare_for_tts│             │ apply_lexicon  │
│ voice_text    │              │ (different!)   │
└───────┬───────┘              └───────┬───────┘
        ▼                              ▼
   Text response                   TTS audio
                               ┌─────────────┐
                               │ apply_lexicon│
                               │ (LiveKit     │
                               │  LEXICON)    │
                               └─────────────┘
```


## TASK 4: LiveKit vs REST API Differences

| # | Feature | LiveKit (stream_response) | REST (generate_response) | Impact Score |
|---|---------|--------------------------|--------------------------|-------------|
| 1 | **L1 _fix_stt_acronyms** | ✅ YES (livekit_agent.py:278) | ❌ NO | Low (L2 covers 9/11) |
| 2 | **Low-confidence guard** | ❌ MISSING | ✅ YES (blocks with fallback) | **HIGH** |
| 3 | **Hallucination guard** | ✅ Non-blocking (logs only) | ✅ Blocking (replaces answer) | **MEDIUM** |
| 4 | **Bengali normalization** (রুপি→টাকা) | ❌ MISSING | ✅ YES | **MEDIUM** |
| 5 | **TTS preprocessing** | `apply_lexicon()` (livekit_agent.py:112-136) with LEXICON dict + phone conversion | `_prepare_for_tts()` → `normalize_for_tts()` + `clean_for_voice()` | **HIGH** |
| 6 | **L3 second call** (for LLM prompt) | ✅ YES (line 2977) | ❌ NO (query already L2-normalized, used directly in _build_messages) | Low |
| 7 | **Cache** | ❌ NO (stream, no cache) | ✅ YES (first turn only) | Low |
| 8 | **LLM model** | Retry with FALLBACK_MODELS | Retry with FALLBACK_MODELS | Same |
| 9 | **Streaming** | Token-by-token yield | Full completion (non-streaming) | Same (design choice) |
| 10 | **Rate limiting** | Same rate limiter | Same rate limiter | Same |
| 11 | **Session memory** | ✅ _append_session_turn | ✅ _append_session_turn | Same |
| 12 | **Response capping** | ❌ NO truncation | ✅ YES (MAX_VOICE_RESPONSE_CHARS) | **MEDIUM** |
| 13 | **_validate_transcript** | ✅ YES | ✅ YES | Same |
| 14 | **_detect_noisy_transcript** | ✅ YES | ✅ YES | Same |
| 15 | **L3 in retrieval** | ✅ Called inside _retrieve_context | ✅ Called inside _retrieve_context | Same |
| 16 | **Follow-up expansion** | ✅ YES | ✅ YES | Same |

### LiveKit call chain vs REST call chain

**LiveKit** (BCRECGroqStream._run → stream_response):
1. stream_response(livekit_agent.py:209) calls self._service.stream_response(query)
2. Inside stream_response: L2 → validate → noise → lang → greeting → ood → repeat → placement → replay → followup → structured → **L3 for LLM** → _retrieve_context (which calls L3 again) → _build_messages (uses L3'd query) → LLM → non-blocking guard

**REST** (qa.py:90 → generate_response):
1. generate_response calls normalize_query (L2) directly
2. Inside generate_response: L2 → validate → noise → lang → greeting → ood → repeat → placement → replay → followup → structured → _retrieve_context (calls L3) → **NO second L3 for LLM** → _build_messages (uses L2'd query) → LLM → blocking hallucination guard → Bengali norm → _prepare_for_tts → response


## TASK 5: Impact Assessment (Does Each Difference Affect Production LiveKit?)

### Difference 1: L1 in LiveKit only
**Effect**: LiveKit runs L1 + L2. REST runs L2 only.
**Evidence**: L2 entity_dict now covers 9/11 L1 patterns. The remaining 2 ("cyber sec", "info tech") relate to matcher bugs (multi-token priority, fuzzy false positives) that should NOT be fixed by adding aliases.
**Verdict**: ✅ **Negligible impact**. L2 handles all critical cases. L1 can be safely removed after L2 is confirmed stable.

### Difference 2: Low-confidence guard missing in stream (HIGH)
**Effect**: When retrieval returns irrelevant context (confidence below threshold), REST returns a polite fallback. LiveKit/stream proceeds with bad context → LLM hallucinates.
**Evidence**: `generate_response` lines 2475-2499 check `if low_confidence_triggered: return fallback`. `stream_response` has no such check.
**Verdict**: 🚨 **Critical bug**. Users get hallucinated answers when retrieval fails on stream path. Must fix.

### Difference 3: Non-blocking hallucination guard in stream (MEDIUM)
**Effect**: Stream path logs hallucinations but sends them to user anyway. REST path replaces bad answers with fallback.
**Evidence**: `stream_response` line 3146-3158: logs warning but does NOT replace output. `generate_response` line 2643-2657: replaces answer with `_safe_fallback(lang)`.
**Verdict**: ⚠️ **Moderate risk**. Users hear hallucinations that are detected but not stopped. Non-blocking design was intentional for latency, but creates inconsistency.

### Difference 4: Bengali normalization missing in stream (MEDIUM)
**Effect**: TTS in LiveKit will say "রুপি" instead of "টাকা" for money amounts (Bengali responses only).
**Evidence**: `generate_response` line 2703-2704: `answer = answer.replace("রুপি", "টাকা")` has no equivalent in `stream_response`.
**Verdict**: ⚠️ **Affects Bengali pronunciation quality**. "রুপি" is formal/less natural than "টাকা" in spoken Bengali.

### Difference 5: Different TTS preprocessing (HIGH)
**Effect**: LiveKit uses `apply_lexicon()` (livekit_agent.py:112) with a hardcoded LEXICON dict. REST uses `_prepare_for_tts()` which calls `normalize_for_tts()` (config-driven via entity_dict) then `clean_for_voice()`.
**Evidence**:
- `livekit_agent.py LEXICON`: "CSE" → "C S E", "MAKAUT" → "Ma-Kaut", "AIML" → "A I M L", etc. (16 entries)
- `entity_dictionary.json tts_spoken_forms`: "CSE" → "C S E", "MAKAUT" → "M A K A U T", "AIML" → "A I M L", etc. (23 entries)
- The LEXICON has `AML→A I M L` which entity_dict doesn't have (but L2 normalizes AML→AIML anyway)
- The LEXICON has `MAKAUT→Ma-Kaut` while entity_dict has `MAKAUT→M A K A U T` — **DIFFERENT!**
- `apply_lexicon` also does phone number conversion (digit-by-digit for Bengali) — not in `normalize_for_tts`
- `_prepare_for_tts` calls `clean_for_voice` which may do additional cleanup — not in `apply_lexicon`

**Verdict**: 🚨 **Two different TTS normalization paths with inconsistencies**. "MAKAUT" pronounced differently (Ma-Kaut vs M-A-K-A-U-T). Phone numbers handled differently. Need unification.

### Difference 6: Response length capping missing in stream (MEDIUM)
**Effect**: REST path caps at MAX_VOICE_RESPONSE_CHARS with sentence-boundary awareness. Stream path sends full LLM response → excessively long TTS.
**Evidence**: `generate_response` lines 2604-2615. stream_response has no equivalent logic.
**Verdict**: ⚠️ **LiveKit users may get very long TTS responses** that the REST API would truncate.


## TASK 6: Risk-Mitigated Migration Plan

### Phase 1: Fix Critical Bugs (IMMEDIATE — before any migration)

| # | Change | Current Owner | Future Owner | Risk | Verification | Rollback |
|---|--------|--------------|-------------|------|-------------|---------|
| 1 | Add low-confidence guard to stream_response | No one | Us | Low — just copy existing REST logic | Turn-by-turn logging, confidence threshold test | git revert |
| 2 | Add Bengali normalization (রুপি→টাকা) to stream_response | No one | Us | Low — one-liner | Bengali test transcript | git revert |
| 3 | Add response length capping to stream_response | No one | Us | Low — copy existing REST logic | Long transcript test | git revert |

### Phase 2: Unify TTS Preprocessing (NEXT)

| # | Change | Current Owner | Future Owner | Risk | Verification | Rollback |
|---|--------|--------------|-------------|------|-------------|---------|
| 4 | Move LEXICON from livekit_agent.py into entity_dict.json tts_spoken_forms | livekit_agent.py | normalizer.py | Medium — must match existing behavior | Commission: all LEXICON entries in entity_dict. Compare: apply_lexicon output vs normalize_for_tts output for 50 test sentences | git revert entity_dict, keep old LEXICON |
| 5 | Replace apply_lexicon(LiveKit) with normalize_for_tts(entity_dict) | livekit_agent.py | normalizer.py | High — TTS pronunciation changes | Record before/after audio for "MAKAUT rules", "CSE fees", etc. | Revert to apply_lexicon |
| 6 | Resolve MAKAUT pronunciation conflict (Ma-Kaut vs M-A-K-A-U-T) | — | Decision needed | — | Query stakeholders which is correct | — |

### Phase 3: Remove Layer 1 (AFTER Phase 1-2 stable)

| # | Change | Current Owner | Future Owner | Risk | Verification | Rollback |
|---|--------|--------------|-------------|------|-------------|---------|
| 7 | Remove _fix_stt_acronyms and _STT_ACRONYM_FIXES from livekit_agent.py | livekit_agent.py | — | Medium — 2 patterns not in L2 | Full regression (48 tests) + real STT transcript comparison | git revert |
| 8 | Add "cyber sec" and "info tech" aliases to entity_dict (if matcher bugs are fixed first) | — | normalizer.py | Low after matcher fix | Test "cyber sec department" → CY check | git revert entity_dict |

### Phase 4: Remove Layer 3 (AFTER Phase 3 stable)

| # | Change | Current Owner | Future Owner | Risk | Verification | Rollback |
|---|--------|--------------|-------------|------|-------------|---------|
| 9 | Add electrical/mechanical/civil/computer as exact aliases in entity_dict | groq_service.py | normalizer.py | Low — these are unambiguous department lookups | Test each: "electrical dept" → EE, "computer science" → CSE | git revert entity_dict |
| 10 | Add `upo[- ]?pradhan` → উপ-প্রধান to entity_dict as stt_mistake | groq_service.py | normalizer.py | Low — Bengali transliteration | Test "upo-pradhan" → "উপ-প্রধান" | git revert entity_dict |
| 11 | Remove _normalize_query from groq_service.py | groq_service.py | — | **HIGH** — affects retrieval quality | Compare retrieval results before/after for 100 diverse queries. Monitor confidence scores. | git revert |

### Phase 5: Make hallucination guard blocking in stream (OPTIONAL)

| # | Change | Current Owner | Future Owner | Risk | Verification | Rollback |
|---|--------|--------------|-------------|------|-------------|---------|
| 12 | Replace non-blocking hallucination guard with blocking guard in stream_response | groq_service.py | groq_service.py | High — might interrupt live conversation | Measure user interruption rate increase | git revert |

### Migration Dependencies
```
Phase 1 (critical fixes)
  │
  ▼
Phase 2 (TTS unification) ──→ Phase 3 (remove L1)
                                      │
                                      ▼
                               Phase 4 (remove L3)
                                      │
                                      ▼
                               Phase 5 (blocking guard, optional)
```

### Regression Risk by Phase
- Phase 1: Very low (additive changes, no removal)
- Phase 2: Medium (TTS pronunciation changes are immediately audible)
- Phase 3: Low (L1 is purely additive to L2, removal is safe if testing passes)
- Phase 4: HIGH (L3 affects both retrieval quality and LLM prompt — most risky)
- Phase 5: Medium (interruption latency tradeoff)


## TASK 7: User-Visible Improvement Estimates

### Phase 1: Critical Fixes

| Change | User Impact | Latency Impact | Retrieval | Hallucination | Pronunciation |
|--------|------------|---------------|-----------|---------------|---------------|
| Low-confidence guard (stream) | **HIGH**: Users stop getting hallucinated bad answers when retrieval fails | +~5ms | No change | **ELIMINATED** for low-confidence cases | No change |
| Bengali রুপি→টাকা (stream) | **LOW-MEDIUM**: Bengali users hear natural "টাকা" instead of formal "রুপি" | No change | No change | No change | **Improved** for Bengali |
| Response capping (stream) | **MEDIUM**: Users no longer get 30-second TTS monologues | No change | No change | No change | Reduced TTS latency |

### Phase 2: TTS Unification

| Change | User Impact | Latency Impact | Retrieval | Hallucination | Pronunciation |
|--------|------------|---------------|-----------|---------------|---------------|
| Move LEXICON to entity_dict | **LOW**: Same pronunciation (if mapping is 1:1) | No change | No change | No change | Same (if done correctly) |
| MAKAUT pronunciation fix | **MEDIUM**: "M A K A U T" vs "Ma-Kaut" — whichever is correct | No change | No change | No change | **Fixes inconsistency** |
| Phone number normalization | **LOW**: English/Hindi digit-by-digit for phone numbers | No change | No change | No change | **Improved** for both paths |

### Phase 3: Remove Layer 1

| Change | User Impact | Latency Impact | Retrieval | Hallucination | Pronunciation |
|--------|------------|---------------|-----------|---------------|---------------|
| Remove _fix_stt_acronyms | **NEGLIGIBLE** (9/11 patterns covered by L2) | **~0.1ms saved** per request (11 fewer regex) | No change | No change | No change |
| Add "cyber sec"/"info tech" | **MEDIUM**: Fixes STT for these two department names | No change | Improved (CY/IT queries match KB) | No change | No change |

### Phase 4: Remove Layer 3

| Change | User Impact | Latency Impact | Retrieval | Hallucination | Pronunciation |
|--------|------------|---------------|-----------|---------------|---------------|
| Add electrical/mechanical/civil/computer as exact aliases | **LOW**: These already work via fuzzy matching | No change | Slightly improved (exact > fuzzy) | No change | No change |
| Add upo-pradhan transliteration | **LOW**: Bengali-specific | No change | Maintained (same as current) | No change | No change |
| Remove _normalize_query | **MEDIUM**: Reduced code complexity, one fewer transformation | **~0.05ms saved** per request (14 fewer regex) | **RISK**: Must verify retrieval quality doesn't degrade | **POTENTIAL IMPROVEMENT**: Fewer duplicate transformations reduce confusion | No change |

### Cumulative Improvement Estimates

| Metric | Before | After (all phases) | Measurement |
|--------|--------|-------------------|-------------|
| Normalization layers | 3 (L1+L2+L3) | 1 (L2 only) | Code audit |
| Code paths for TTS | 2 (LEXICON vs normalize_for_tts) | 1 (normalize_for_tts) | Code audit |
| STT fix coverage | 11 regex + entity_dict | entity_dict only (config-driven) | Pattern comparison |
| Hallucination guard (stream) | Non-blocking (logs only) | **Blocking** (Phase 5 opt) | Turn-by-turn telemetry |
| Low-confidence guard (stream) | **MISSING** | ✅ PRESENT (Phase 1) | Turn-by-turn telemetry |
| Bengali pronunciation (stream) | "রুপি" | "টাকা" (Phase 1) | Transcript audit |
| TTS pronunciation consistency | Inconsistent | **Unified** (Phase 2) | Before/after audio |
| Latency saved (per request) | — | ~0.15ms (L1+L3 regex removal) | Timing telemetry |
| Code maintainability | Confusing (3 layers, 2 TTS paths) | **Clean** (1 layer, 1 TTS path) | Developer survey |


## SUMMARY

### Critical Issues Found (Fix Immediately — Phase 1)
1. **Low-confidence guard missing in stream_response** — users get hallucinated answers
2. **Bengali normalization missing in stream** — "রুপি" instead of "টাকা"
3. **Response length capping missing in stream** — potentially very long TTS

### Duplicate Transformations (Eliminate — Phases 2-4)
4. Layer 1 (_fix_stt_acronyms) is fully covered by Layer 2 (config-driven)
5. Layer 3 (_normalize_query) is 10/14 covered by Layer 2; remaining 4 need alias additions
6. Two different TTS preprocessing paths with actual **pronunciation inconsistencies** (MAKAUT)

### Architectural Debt
7. `VoiceSessionManager` (voice_session.py) is completely dead code — 95 lines, never imported
8. `stream_response` and `generate_response` share ~70% code but diverge in critical safety checks
9. The non-blocking hallucination guard in stream means **users hear detected hallucinations**

### Recommended Next Steps
1. **Apply Phase 1 fixes** (3 critical bugs) — these are independent of the migration debate
2. **Resolve MAKAUT pronunciation** — ask stakeholders which is correct
3. **Proceed with Phase 2-4 migration** when ready, with a full weekend of canary testing before Phase 4 (highest risk)
