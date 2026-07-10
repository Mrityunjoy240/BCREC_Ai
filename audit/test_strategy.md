# Red-Team Test Strategy — BCREC AI Voice Assistant

## Deliverable 1: Risk Matrix

### P0 — Critical (immediate production risk)

| ID | Risk | Severity | Probability | Production Impact | Component | Symptom |
|----|------|----------|------------|-------------------|-----------|---------|
| R01 | **Stream hallucination guard is non-blocking** | Critical | Medium (requires LLM hallucination) | **HIGH** — voice users hear wrong fee amounts, phone numbers, names | `stream_response` hallucination guard | Wrong numbers in voice output, logged but not blocked |
| R02 | **Generate/Stream parity gap** | Critical | 100% (gap exists today) | **HIGH** — voice users miss 8+ features | `stream_response` (entire) | Voice users can't say "yes"/"no" after clarification, no greeting, no language switch replay, no multi-intent, no cache |
| R03 | **OOD false positives for college-adjacent queries** | High | High | **HIGH** — "python course", "college cricket team", "news about college" blocked | `_is_out_of_domain` | Legitimate queries rejected; "python" in coding category blocks college course inquiries |

### P1 — High (frequent or high-impact)

| ID | Risk | Severity | Probability | Production Impact | Component | Symptom |
|----|------|----------|------------|-------------------|-----------|---------|
| R04 | **ConversationState staleness after RAG-only turns** | High | High (every RAG-only turn) | **MEDIUM** — wrong follow-up expansion | `_expand_follow_up_query`, `_session_states` | "What about fees?" after a RAG-only answer → wrong domain expansion |
| R05 | **Stream lacks multi-intent splitting** | High | 100% (not implemented) | **MEDIUM** — compound queries return partial answers | `stream_response` structured lookup | "fee and hostel details" → only first handler matched |
| R06 | **No LLM timeout in non-SAFEPOINT mode** | High | Low (Groq rarely hangs) | **HIGH** — blocks request thread indefinitely | LLM call in `generate_response` | Request hangs >30s, no failover |
| R07 | **Stream prompt uses normalized query vs original query** | High | 100% (different code paths) | **MEDIUM** — LLM sees different text for same user input | `_build_messages` call in stream vs generate | Subtle answer differences between API and voice for same query |

### P2 — Medium (notable but contained)

| ID | Risk | Severity | Probability | Production Impact | Component | Symptom |
|----|------|----------|------------|-------------------|-----------|---------|
| R08 | **Rate limiter lacks circuit breaker** | Medium | Low (requires sustained 429s) | **HIGH** — every request retries 3× across models | `_rate_limiter` | Cascading latency when Groq is overloaded |
| R09 | **Structured lookup regex priority conflicts** | Medium | Medium | **MEDIUM** — wrong handler matched for ambiguous queries | `_structured_lookup` | "admission fee" matched by fee handler instead of admission handler |
| R10 | **Language-ignorant structured responses** | Medium | High | **MEDIUM** — Hindi/Bengali users get English responses for many handlers | `_structured_lookup` handlers | Contact info, HOD names, cutoff data always in English |
| R11 | **In-memory session state (not persistent)** | Medium | Low (single instance) | **HIGH** (clustered deployment fails) | `_sessions`, `_session_langs`, `_session_states` | Session loss on server restart; no cross-instance sharing |
| R12 | **Yes/No continuation missing from stream** | Medium | 100% | **LOW** — feature gap, not crash | `stream_response` | Voice users can't answer "Would you like..." prompts |
| R13 | **Greeting detection missing from stream** | Medium | 100% | **LOW** — missing feature | `stream_response` | Voice users get LLM response instead of greeting |
| R14 | **Language switch re-run missing from stream** | Medium | 100% | **LOW** — language switches don't replay previous answer | `stream_response` | "in bengali" switches language but doesn't replay |
| R15 | **TTS preparation missing from stream** | Medium | 100% | **LOW** — acronyms mispronounced in voice | `stream_response` | "CSE" pronounced as "see" instead of "C S E" |

### P3 — Low (minor or rare)

| ID | Risk | Severity | Probability | Production Impact | Component | Symptom |
|----|------|----------|------------|-------------------|-----------|---------|
| R16 | **Bengali normalization missing from stream** | Low | 100% | **LOW** — "রুপি" not converted to "টাকা" | `stream_response` post-processing | Bengali TTS pronounces currency incorrectly |
| R17 | **Fee handler duplicated (arithmetic + structured_lookup)** | Low | Medium | **LOW** — redundant paths | `_structured_lookup` fee handler + arithmetic block | Fee queries take slightly different paths depending on dept_code presence |
| R18 | **Ambiguous word clarification quality** | Low | Low | **LOW** — wrong clarification prompt for edge cases | `_validate_transcript` AMBIGUOUS_WORDS | "course" → generic clarification instead of department-specific |
| R19 | **FEE_GROUP_MAP missing department** | Low | Low | **LOW** — fee calc fails for missing dept | `_calculate_total_fees` | New department added but fee map not updated |
| R20 | **Cache key includes context (first-turn only)** | Low | Low | **LOW** — even identical queries get cache miss if retrieval differs | `_cache_key` | Suboptimal cache hit rate |

---

## Deliverable 2: Coverage Matrix

| # | Pipeline Component | P0 Tests | P1 Tests | P2 Tests | P3 Tests | Total | Coverage Notes |
|---|-------------------|----------|----------|----------|----------|-------|----------------|
| 1 | **Normalization** (`normalize_query`) | 0 | 2 | 8 | 3 | **13** | STT alias edge cases, fuzzy match false positives, mixed-language |
| 2 | **Transcript Validation** (`_validate_transcript`) | 0 | 2 | 10 | 3 | **15** | Borderline transcripts, multilingual, ambiguous word clarifications |
| 3 | **STT Noise Detection** (`_detect_noisy_transcript`) | 0 | 0 | 5 | 0 | **5** | High non-alpha, repeated words, clean transcripts not flagged |
| 4 | **Yes/No Continuation** (generate only) | 0 | 0 | 10 | 0 | **10** | "yes"/"no" after clarification; parity test for stream absence |
| 5 | **Language Resolution** (`_resolve_language`) | 0 | 4 | 20 | 2 | **26** | Romanized Bangla/Hindi, code-switching, short follow-up inheritance, native script forcing |
| 6 | **Language Switch Tracking** | 0 | 0 | 5 | 0 | **5** | Explicit switch, re-run previous question; parity test for stream |
| 7 | **Greeting Detection** (`_is_greeting`) | 0 | 0 | 8 | 0 | **8** | Greeting+query combos; parity test for stream absence |
| 8 | **Out-of-Domain Detection** (`_is_out_of_domain`) | 15 | 5 | 5 | 0 | **25** | **College-adjacent queries** (P0: python course, college sports, education news); boundary cases; multilingual OOD |
| 9 | **Repeat Intent** (`_detect_repeat_intent`) | 0 | 0 | 5 | 0 | **5** | Standard repeat, no history, multilingual |
| 10 | **Placement Eligibility** (`_detect_placement_eligibility_intent`) | 0 | 0 | 8 | 0 | **8** | Edge case patterns, negative cases |
| 11 | **Conversation Replay** (`_detect_repeat_conversation_intent`) | 0 | 0 | 5 | 0 | **5** | "repeat everything", empty history |
| 12 | **Follow-up Expansion** (`_expand_follow_up_query`) | 0 | 15 | 15 | 0 | **30** | **State staleness** (P1: after RAG-only turns), cross-domain, department enrichment, ConversationState-based rewrites |
| 13 | **Multi-Intent Splitting** (`_split_multi_intent`) | 0 | 10 | 5 | 0 | **15** | Standard split, 3+ intents, comma-separated; **parity test for stream absence** (P1) |
| 14 | **Structured Arithmetic** | 0 | 0 | 8 | 2 | **10** | Semester/total/seat, missing dept code, fee map completeness |
| 15 | **Structured Lookup** (`_structured_lookup`) | 0 | 10 | 30 | 5 | **45** | **Regex priority conflicts** (P2), language-ignorant responses (P2), all 27 handlers, missing data fallback, multi-match queries |
| 16 | **RAG Retrieval** (`_retrieve_context`) | 0 | 3 | 12 | 2 | **17** | Empty results, section dedup, language-based ranking, low confidence |
| 17 | **Low-Confidence Guard** | 0 | 0 | 5 | 0 | **5** | Above/below/boundary threshold |
| 18 | **Cache** | 0 | 0 | 8 | 2 | **10** | Hit/miss, invalidation, cache key collision; **parity test for stream** (P2) |
| 19 | **Prompt Building** (`_build_messages`) | 0 | 5 | 5 | 0 | **10** | History window, language hint, context integration; **query difference parity test** (P1) |
| 20 | **LLM Call** | 0 | 5 | 8 | 0 | **13** | Rate limiting, model fallback, **timeout in non-SAFEPOINT** (P1), circuit breaker absence |
| 21 | **Response Truncation** | 0 | 0 | 5 | 0 | **5** | Sentence boundary (Dr. B.C. Roy), char-based truncation in stream |
| 22 | **Hallucination Guard** (`_validate_answer`) | 10 | 3 | 5 | 0 | **18** | **Non-blocking in stream** (P0: numbers hallucinated but not blocked), numbers present/absent, query exemption |
| 23 | **Out-of-KB Detection** | 0 | 2 | 5 | 0 | **7** | "I don't know" signals, phone presence; non-blocking in stream |
| 24 | **TTS Preparation** (`_prepare_for_tts`) | 0 | 0 | 5 | 2 | **7** | Acronym expansion, PIN code; **absent from stream** (P2) |
| 25 | **Bengali Normalization** | 0 | 0 | 0 | 2 | **2** | "রুপি" → "টাকা"; absent from stream |
| 26 | **Session Memory** | 0 | 0 | 5 | 0 | **5** | Session isolation, 12-turn cap, clear isolation, concurrent sessions |
| 27 | **SAFEPOINT Integration** | 0 | 0 | 5 | 0 | **5** | Pre-processing, handoff vs pre, post-processing |
| — | **Cross-Cutting: Generate vs Stream Parity** | 5 | 8 | 18 | 5 | **36** | Dedicated parity tests for every behavioral difference |
| — | **Cross-Cutting: Failure Injection** | 8 | 10 | 12 | 5 | **35** | STT, RAG, LLM, LiveKit, Sarvam, network, cache, state corruption |
| | **TOTAL** | **38** | **84** | **242** | **33** | **~397** | |

---

## Deliverable 3: Test Taxonomy

### Group A: Dual-Path Divergence (36 tests)
Tests that specifically probe differences between `generate_response` and `stream_response`.

```
A01-A05:  Blocking vs non-blocking guards (P0: R01)
A06-A08:  Missing yes/no continuation in stream (P2: R12)
A09-A10:  Missing greeting detection in stream (P2: R13)
A11-A12:  Missing language switch replay in stream (P2: R14)
A13-A15:  Missing multi-intent splitting in stream (P1: R05)
A16-A17:  Missing cache in stream (P2)
A18-A20:  Different prompt query (original vs normalized) (P1: R07)
A21-A23:  Missing TTS prep in stream (P2: R15)
A24:      Missing Bengali normalization in stream (P3: R16)
A25-A27:  Different truncation behavior (sentence vs char) (P2)
A28-A30:  Different error responses (phone number vs generic) (P2)
A31-A33:  SAFEPOINT pre vs handoff
A34-A36:  State update ordering differences
```

### Group B: State Contamination (40 tests)
Tests for conversation state corruption, staleness, cross-domain interference.

```
B01-B10:  ConversationState staleness after RAG-only turns (P1: R04)
          - Query "CSE fee" (structured hit → state updated)
          - Query "tell me about placements" (RAG-only → state NOT updated)
          - Follow-up "what are the seats?" (should use CSE, but state is stale)
B11-B15:  Cross-domain facet overlap
          - "fee" facet exists in fee domain AND admission domain
          - Follow-up after switching domains uses wrong domain
B16-B20:  Visit order deque overflow (>8 entries)
          - Visit 9+ domains; does expansion still work correctly?
B21-B25:  Session isolation (concurrent sessions)
          - Session A: CSE fee → Session B: hostel → verify no cross-talk
B26-B30:  Clear session mid-conversation
          - Clear + continue; does state reset properly?
B31-B35:  State slot overwrite
          - fee domain → admission domain → back to fee; is last_intent correct?
B36-B40:  Session ID edge cases
          - None, empty string, special chars, very long (>256 chars)
```

### Group C: Boundary Conditions (55 tests)
Tests at every pipeline stage's decision threshold.

```
C01-C05:  OOD word count boundary (<3 words bypass)
          - 2 words: "weather today" → NOT blocked
          - 3 words: "what is weather" → BLOCKED
          - College-adjacent: "python course" → CORRECTLY ALLOWED or BLOCKED? (P0: R03)
C06-C10:  Follow-up expansion word count boundary (>=6 words no expansion)
          - 5 words: expanded; 6 words: not expanded
C11-C15:  Language detection short query boundary (<=3 words inherits)
          - 2-word Bengali romanized query → inherits English if session is English
          - 3-word vs 4-word romanized Bangla: different behavior
C16-C20:  Transcript validation word count boundary (<2 words rejected, 1 word ambiguous)
          - 1 word "fees" → ambiguous clarification
          - 1 word "repeat" → passed through to repeat handler
          - 0 words (empty) → clarification
C21-C25:  Multi-intent split boundary (>=2 words each side)
          - "fee and hostel" → split (2+2 words)
          - "fee & hostel" → split? (& handling)
          - "fees and" → NOT split (right side <2 words)
C26-C30:  Retrieval confidence threshold (0.15)
          - 0.14 → low confidence guard triggered
          - 0.15 → proceeds to LLM
          - 0.16 → proceeds to LLM
C31-C35:  Response truncation boundary (400 chars)
          - 399 chars → no truncation
          - 401 chars with sentence boundary → truncated at last .
          - 401 chars without sentence boundary → truncated at last space
C36-C40:  Hallucination guard number detection
          - "6 lakh" in answer → 6 must be in context
          - Phone "0343-2501353" in answer → must be in context
C41-C45:  Session history cap (12 turns = 6 user + 6 assistant)
          - 13th turn → oldest turn evicted
          - 10th turn → all present
C46-C50:  Language switch keyword threshold (>=2 keyword markers)
          - 1 romanized Bangla word → no switch
          - 2 romanized Bangla words → switch
C51-C55:  OOD category match threshold (>=2 distinct categories or >=3 total)
          - 1 category, 2 matches → NOT blocked
          - 1 category, 3 matches → BLOCKED
          - 2 categories, 2 matches (1 each) → BLOCKED
```

### Group D: Resource Exhaustion (20 tests)
Tests for rate limiting, timeouts, cache, memory.

```
D01-D05:  Groq API rate limiting (429 responses)
          - Single 429 → retries with backoff
          - Sustained 429s → all models exhausted → RuntimeError
          - Circuit breaker absence: does it keep trying?
D06-D10:  LLM timeout behavior
          - SAFEPOINT mode: 6s timeout → filler response
          - Non-SAFEPOINT mode: NO timeout → indefinite hang (P1: R06)
D11-D15:  Cache exhaustion
          - TTL expiry → cache cleared
          - Max size reached → LRU eviction
          - KB file change → cache invalidation
          - Stream path: every request is a cache miss (uncached)
D16-D20:  Memory pressure
          - 1000+ concurrent sessions: memory growth
          - Long conversations (100+ turns): history pruning works
          - Large structured KB file: read performance
```

### Group E: Language Fidelity (35 tests)
Tests for language detection, switching, mixed-language, romanized script.

```
E01-E05:  Romanized Bangla detection (≥2 keyword markers)
          - "ami CSE te admission nite chai" → Bangla (3 markers)
          - "CSE fee koto" → Bangla (1 marker: koto) → inherits/en depending on context
E06-E10:  Romanized Hindi detection
          - "mujhe CSE mein admission chahiye" → Hindi
          - "CSE fees kya hai" → Hindi (1 marker) → edge case
E11-E15:  Native script forcing
          - Bengali script → force Bengali even if session is English
          - Devanagari script → force Hindi even if session is Bengali
          - Mixed script (Bengali query with English words)
E16-E20:  Explicit switch commands
          - "in bengali" → switches to Bengali
          - "hindi me" → switches to Hindi
          - "english e" → switches to English
          - "বাংলায় বলো" → switches to Bengali
E21-E25:  Short follow-up language inheritance
          - Session=Hindi, query="fees" (1 word) → answered in Hindi
          - Session=Bengali, query="hostel" (1 word) → answered in Bengali
E26-E30:  Code-switching mid-conversation
          - English query → English response
          - Bengali query → Bengali response
          - Back to English → English response (doesn't stick to Bengali)
E31-E35:  Language-ignorant structured responses
          - Hindi query for HOD → English response (P2: R10)
          - Bengali query for contact → English response (P2: R10)
          - Does _format_inr localize correctly for Hindi/Bengali?
```

### Group F: Retrieval Robustness (25 tests)
Tests for vector search edge cases.

```
F01-F05:  Empty/short retrieval
          - Query with no matching chunks → empty context, 0.0 confidence
          - Very short query (1-2 words post-expansion) → retrieval behavior
F06-F10:  Section-aware dedup
          - Multiple chunks from same section:subsection → only first kept
          - Chunks from same section but different subsections → all kept
          - Dedup key collision (section:subsection format)
F11-F15:  Language-based ranking
          - Query in Bengali → Bengali chunks ranked higher
          - Query in English → English chunks ranked higher (non-Bengali penalized -0.5)
F16-F20:  Semantic re-ranking correctness
          - semantic_anchor word matching boosts score
          - section name match in query gives +2 boost
F21-F25:  Low confidence scenarios
          - confidence=0.0 → empty context → low confidence guard
          - confidence=0.14 → below threshold → fallback
          - confidence=0.15 → at threshold → proceeds
```

### Group G: Hallucination Resistance (20 tests)
Tests for numeric entity validation, unknown entity handling.

```
G01-G05:  Number validation
          - Answer contains "6 lakh" → context must contain "6" or "600000"
          - Answer contains "0343-2501353" → context must contain phone
          - Answer contains year "2024" → context must contain "2024"
G06-G10:  Placement query exemption
          - "what is the placement rate" → NO numbers in query → exempt from validation
          - "what is the placement rate of CSE 2024" → HAS number → validated
G11-G15:  Non-blocking stream validation
          - Stream: hallucinated number → LOGGED but user hears it (P0: R01)
          - Generate: hallucinated number → BLOCKED, replaced with fallback
G16-G20:  Unknown entity handling
          - "who is professor Einstein" → no match → unknown fallback
          - "what is the college ranking" → no KB data → safe fallback
```

### Group H: Structured Knowledge Integrity (50 tests)
Tests for handler priority, regex conflicts, missing data, multi-intent.

```
H01-H10:  Handler priority conflicts
          - "admission fee" → should match fee handler (not admission)
          - "hostel fee" → should match hostel handler (checked before fee)
          - "safety in hostel" → should match safety (checked before hostel)
          - "installment for hostel fee" → should match installment (checked before fee)
          - "vice principal contact" → should match vice_principal (checked before principal)
H11-H20:  Regex conflict edge cases
          - "contact principal" → matches principal (checked before contact)
          - "professor contact" → matches contact (professor checked after contact? No, contact is checked before professor)
          - "hod placement" → matches hod (checked before placement)
          - Query with "fee" substring in another word (e.g., "coffee") → negative lookbehind needed?
H21-H25:  Missing data fallback
          - Department with no HOD data → _lang_hod_unknown
          - Department not in FEE_GROUP_MAP → no arithmetic result
          - KB file missing/corrupted → None returned
H26-H30:  Multi-intent composition (generate only)
          - "fee and hostel" → both parts answered
          - "fee and hostel and placement" → 3 parts (only splits on first "and")
          - "fee, hostel, placement" → comma-separated (max 2 commas)
H31-H35:  Structured arithmetic priority
          - "total fee CSE" → arithmetic returns before structured_lookup
          - "semester fee AIML" → arithmetic returns
          - "CSE fee" → no semester/total regex → falls through to structured_lookup fee handler
H36-H40:  Faculty name resolution
          - Exact match → found
          - Fuzzy match (typo) → found via alias map
          - Partial first name → found
          - Unknown name → None
H41-H45:  Language-specific handler output
          - Hindi query → handler returns English text with _format_inr Hindi
          - Bengali query → same
          - _format_inr for Hindi: "₹6,04,700" → should it be "६ लाख ४ हजार..."?
H46-H50:  All departments coverage
          - Fee query for CSE, IT, ECE, EE, AIML, DS, CY, CSD, ME, CE → each returns correct amount
          - HOD query for each department → each returns correct name
```

### Group I: External Dependency Failure (30 tests)
Tests for STT noise, LLM down, network, LiveKit, Sarvam.

```
I01-I05:  STT failure modes
          - Empty transcript → clarification
          - Single char noise ("a b c") → noise detection
          - Repeated filler ("yes yes yes") → filler filter
          - High non-alpha ("### $$ %") → noise detection
          - Mid-sentence cutoff ("what is the") → incomplete fragment
I06-I10:  Groq API failure modes
          - 500 Internal Server Error → Raise exception → error response
          - 429 Rate Limited → Retry with backoff → success on retry
          - 429 All retries exhausted → Model fallback → success on fallback
          - All models rate limited → RuntimeError → error response
          - Network timeout → ASL timeout (SAFEPOINT) or indefinite hang (non-SAFEPOINT)
I11-I15:  LiveKit failure modes
          - LiveKit host unreachable (DNS failure) → agent startup fails
          - Room not found → dispatch fails
          - Connection drops mid-session → cleanup
          - Job executor unresponsive → agent restart
I16-I20:  Sarvam failure modes
          - STT returns empty → normalization produces empty → transcript validation catches
          - TTS cold start (>5s) → "job executor is unresponsive" warning
          - TTS returns wrong language → user hears wrong language
I21-I25:  Network partition
          - Groq reachable, Sarvam down → LLM works, TTS fails
          - Sarvam reachable, Groq down → STT works, LLM fails
          - Intermittent packet loss → retry behavior
I26-I30:  Vector store failure
          - ChromaDB connection refused → exception caught → empty context
          - Embedding model fails → exception caught → empty context
          - Corrupted index → search fails → empty context
```

### Group J: Session Isolation & Lifecycle (20 tests)

```
J01-J05:  Concurrent session isolation
          - Session A: CSE fee → Session B: hostel → Session A: repeat → should get CSE fee answer
          - 50 concurrent sessions → no cross-talk
J06-J10:  Session lifecycle
          - New session → empty history → cache checked
          - Existing session → history loaded → cache skipped
          - Session cleared → history empty → behaves like new session
J11-J15:  Language state lifecycle
          - Session A: Bengali → Session B: English → Session A: query → Bengali
          - Session cleared → language reset to English
J16-J20:  ConversationState lifecycle
          - Session created → state empty
          - Structured hit → state populated
          - Session cleared → state cleared
```

---

## Deliverable 4: Failure Injection Plan

### Injection Point 1: STT Layer (before normalize_query)

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Empty string `""` | Pass empty query | `_validate_transcript` returns clarification | I01 |
| Whitespace-only `"   "` | Pass whitespace query | clarification | I01 |
| Single chars `"a b c d e f"` | Pass noisy query | `_detect_noisy_transcript` returns true | I02 |
| Repeated words `"yes yes yes yes"` | Pass filler query | filler acknowledgment | I03 |
| Non-alpha `"### $$ %%"` | Pass symbol query | noise detection | I04 |
| Fragment `"what is the"` | Pass fragment | incomplete fragment detection | I05 |
| Bengali STT error (English chars with Bangla meaning) | Already handled by normalize_query | alias resolution normalizes | R17 |
| Mid-sentence cutoff `"tell me about"` | Pass cutoff | incomplete fragment | I05 |

### Injection Point 2: Normalization Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Unknown word `"xyzabc"` | Pass unknown word | unchanged (no fuzzy match) | — |
| STT mistake `"iml"` | Pass "iml" | resolved to "AIML" | — |
| Alias `"ai ml"` | Pass "ai ml" | resolved to "AIML" | — |
| Fuzzy match `"chandan bandopadhyay"` | Pass misspelling | fuzzy resolved | H36 |

### Injection Point 3: Transcript Validation Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Single ambig word `"fees"` | Pass "fees" | clarification prompt | C16-C20 |
| Single ambig word `"professor"` | Pass "professor" | department-specific clarification | R18 |
| Word-count boundary `1 word` | Pass non-ambig word | <2 words → clarification | C16 |
| Word-count boundary `2 words` | Pass 2 words | passes through | C16 |
| 5-word fragment with trailing word | Pass trailing pattern | fragment detection | C16 |

### Injection Point 4: Language Resolution Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Romanized Bangla 1 marker | `"CSE fee koto"` (1 marker: koto) | inherits session lang | E01-E05 |
| Romanized Bangla 2+ markers | `"ami CSE te admission nite chai"` (3 markers) | switches to Bengali | E01-E05 |
| Romanized Hindi 1 marker | `"fees kya hai"` (1 marker: kya) | inherits session lang | E06-E10 |
| Romanized Hindi 2+ markers | `"mujhe CSE mein admission chahiye"` (2 markers) | switches to Hindi | E06-E10 |
| Native Bengali script | `"সি এস ই ফি কত?"` | force Bengali | E11-E15 |
| Native Devanagari script | `"सीएसई शुल्क कितना है?"` | force Hindi | E11-E15 |
| Explicit switch `"in bengali"` | language switch command | switches + re-runs prev question (generate) | E16-E20 |
| Short follow-up `"fees"` after Hindi session | 1-word query | inherits Hindi | E21-E25 |

### Injection Point 5: Conversation State Corruption

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Structured hit → RAG hit → follow-up | 3-turn sequence | follow-up uses stale state | B01-B10, R04 |
| 9 domain visits | visit 9 different domains | visit order deque caps at 8 | B16-B20 |
| Session ID collision | same ID, two concurrent requests | undefined behavior (race) | B36-B40 |
| Cross-domain facet overlap | "fee facet" in fee + admission domains | expansion picks most recent | B11-B15 |
| Clear then continue | clear mid-conversation, then query | state reset, history reset | B26-B30 |

### Injection Point 6: RAG/Vector Store Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| ChromaDB unavailable | Stop ChromaDB process | exception → empty context, 0.0 confidence | I26-I30 |
| Empty result set | Query with no matching chunks | empty context, 0.0 confidence | F01-F05 |
| Low confidence (0.14) | Threshold at 0.15 | guard triggered → fallback | F21-F25 |
| Section dedup collision | Same section:subsection | dedup keeps first, discards rest | F06-F10 |
| Language mismatch | English query, only Bengali chunks | -0.5 penalty, different ranking | F11-F15 |

### Injection Point 7: LLM/Groq Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| HTTP 429 response | Mock Groq rate limit | retry with backoff (3 attempts per model) | D01-D05 |
| HTTP 500 response | Mock Groq server error | raise → outer exception → error response | I06-I10 |
| Sustained 429s (all models) | Mock rate limit on all models | RuntimeError → error response | D01-D05 |
| Timeout >6s (SAFEPOINT) | Slow mock | filler response | D06-D10 |
| Timeout indefinite (non-SAFEPOINT) | Slow mock, SAFEPOINT off | indefinite hang | R06 |
| Hallucinated number | Mock response with wrong fee | generate: blocked; stream: logged only | G01-G15 |

### Injection Point 8: Post-Processing Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| "I don't know" without phone | Mock LLM response | out-of-KB detection → fallback | R01 |
| Numbers not in context | Mock response with "6 lakh" | hallucination guard blocks | G01-G05 |
| Response >400 chars | Long mock response | truncated at sentence boundary | C31-C35 |
| "Dr. B.C. Roy" in truncation zone | Response with "Dr." near boundary | sentence-boundary detection handles it | C31-C35 |
| Bengali response without normalization | Mock Bengali response | "রুপি" → "টাকা" | R16 |

### Injection Point 9: Cache Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| Identical query (first turn) | Same query, no history | cache hit on second call | D11-D15 |
| KB file change | Modify KB file mid-operation | cache invalidation | D11-D15 |
| Cache disabled | No cachetools | cache skipped, stats show disabled | D11-D15 |
| Stream path | streaming same query | always cache miss | A16-A17 |

### Injection Point 10: LiveKit/Sarvam Layer

| Injection | Method | Expected Outcome | Risk Validated |
|-----------|--------|-----------------|----------------|
| LiveKit DNS failure | Bad LIVEKIT_URL | agent startup fails | I11-I15 |
| Sarvam STT error | Mock STT failure | empty transcript → validation catches | I16-I20 |
| Sarvam TTS cold start | First TTS call after idle | delayed first token | I16-I20 |
| Room disconnection mid-stream | Force disconnect | cleanup, agent exits | I11-I15 |

---

## Next Step: Generate Red-Team Evaluation Catalog

The catalog will be generated as a structured JSON/CSV file with ~300-400 entries, each specifying:

```
{
  "id": "A01",
  "group": "Dual-Path Divergence",
  "risk_ids": ["R01"],
  "priority": "P0",
  "query": "What is the total fee for CSE?",
  "session_setup": [],
  "stage_under_test": "hallucination_guard",
  "expected_pipeline": [
    "normalize_query →",
    "_validate_transcript (pass) →",
    "_resolve_language (en) →",
    "_is_greeting (false) →",
    "_is_out_of_domain (false) →",
    "_expand_follow_up_query (no expansion, >=6 words) →",
    "_detect_on_topic_arithmetic (true) →",
    "_extract_dept_code (CSE) →",
    "_calculate_total_fees (arithmetic result) → return"
  ],
  "expected_source": "structured_arithmetic",
  "expected_language": "en",
  "expected_response_contains": ["CSE", "lakh"],
  "failure_symptoms": "generate: structured_arithmetic source. stream: falls through to LLM",
  "likely_root_cause": "Stream path missing arithmetic pre-check ordering",
  "injection": "None (natural query)"
}
```
