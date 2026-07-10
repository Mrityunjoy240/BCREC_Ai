# Production Voice Failure Catalog

## Scope

Failures specific to the voice (LiveKit + Sarvam) path that cannot be discovered through chat/API testing alone. Each entry describes what happens when the failure occurs and how it propagates through the pipeline.

---

## V01 — Barge-In (User Speaks While Agent is Responding)

| Field | Value |
|-------|-------|
| **Scenario** | User: "What is the CSE fee?" → Agent starts streaming → User: "actually no, tell me about hostel" (overlapping) |
| **STT behavior** | LiveKit sends new transcript for the barge-in utterance. The previous stream_response may still be yielding tokens. |
| **Pipeline impact** | LiveKit cancels the previous agent response. New `stream_response` call starts with: (a) the barge-in transcript as the new query, (b) the session history may or may not include the PREVIOUS (interrupted) turn depending on timing |
| **Race condition** | `_append_session_turn` runs AFTER stream_response completes. If interrupted mid-stream, the session turn is NEVER appended. The barge-in starts with NO history of the interrupted turn. |
| **Testing needed** | 1. Verify session state after barge-in. 2. Verify no stale state from partial response. |
| **Priority** | P0 — occurs frequently in voice |

---

## V02 — Silence / Timeout

| Field | Value |
|-------|-------|
| **Scenario** | User connects but says nothing for 15+ seconds |
| **STT behavior** | Sarvam returns empty string or whitespace-only |
| **Pipeline impact** | `_validate_transcript("")` returns `CLARIFICATION_REPEAT_EN` → user hears "I didn't quite catch that" |
| **Edge case** | What if silence repeats 3+ times? Each time state gets a clarification turn appended. After 6 clarifications (12 turns), history is full of noise. |
| **Testing needed** | 1. Repeated silence recovery (5+ times). 2. History pruning behavior with all-clarification turns. |
| **Priority** | P1 |

---

## V03 — Duplicate STT / Packet Duplication

| Field | Value |
|-------|-------|
| **Scenario** | Network packet loss causes Sarvam to receive the same audio chunk twice → STT outputs "what is the CSE fee what is the CSE fee" |
| **Pipeline impact** | `normalize_query` may not deduplicate. `_validate_transcript`: word_count = 8, not ambiguous, no trailing pattern. **Passes through.** → `_detect_noisy_transcript`: tokens ≥4, unique ≤2? "what"(1), "is"(2), "the"(3), "CSE"(4), "fee"(5) = 5 unique > 2 → NOT detected as noise. → goes to structured_lookup/RAG |
| **Failure** | The duplicate query gets sent to LLM. LLM sees duplicate text → possible duplicate response. State records: same user query twice. |
| **Testing needed** | 1. Duplicate text detection. 2. Deduplication in normalization. 3. State impact. |
| **Priority** | P1 |

---

## V04 — Partial STT (Mid-Sentence Cutoff)

| Field | Value |
|-------|-------|
| **Scenario** | STT sends "what is the" before user finishes (streaming STT mid-utterance) |
| **STT behavior** | LiveKit may send partial transcripts as the user speaks. These are not final. |
| **Pipeline impact** | If LiveKit sends partial transcript as a separate turn: `_validate_transcript("what is the")` → word_count=3, ≤5 → trailing pattern `(what|where|...)\s*$` → "the" in trailing list → **clarification**. User hears "I didn't catch that" while they're still speaking. |
| **Testing needed** | 1. LiveKit final vs interim transcript handling. 2. Does agent wait for VAD (Voice Activity Detection) end before processing? |
| **Priority** | P1 |

---

## V05 — Emotional Caller (Angry/Frustrated)

| Field | Value |
|-------|-------|
| **Scenario** | "I ALREADY ASKED YOU THREE TIMES! WHAT IS THE CSE FEE?" (caps, exclamation) |
| **Pipeline impact** | `normalize_query`: caps preserved. `_validate_transcript`: word_count > 1, not ambiguous → passes. Language: English. OOD: "three" not OOD. → structured lookup returns fee (correctly). **BUT:** the ALL-CAPS query is stored in history. Next expansion may include "I ALREADY ASKED YOU THREE TIMES!" in the text merge. |
| **Failure** | History contamination → subsequent expansions include angry text → LLM sees aggressive context |
| **Testing needed** | 1. ALL-CAPS preservation in history. 2. Emotional context bleeding into LLM prompts. |
| **Priority** | P2 |

---

## V06 — Impatient Caller (Rapid Repetition)

| Field | Value |
|-------|-------|
| **Scenario** | "CSE fee CSE fee CSE fee CSE fee" (rapid repetition) |
| **Pipeline impact** | `_validate_transcript`: word_count=8, not ambiguous, no trailing pattern → passes. `_detect_noisy_transcript` tokens=8, unique tokens: "CSE"(1), "fee"(2) = 2 unique → ≤2. **Noise detected!** Returns clarification. |
| **Actual behavior** | Code correctly detects this as noise. User hears "I didn't catch that." |
| **But:** | If user says "CSE fee" 3 times in separate turns (not one utterance), each is a valid short query with history. Each appends to state. After 3 turns: history has 3 fee queries + 3 fee responses = 6 turns. |
| **Testing needed** | 1. Same query repeated 5+ times across turns — does state degrade? |
| **Priority** | P2 |

---

## V07 — Elderly / Non-Technical Caller

| Field | Value |
|-------|-------|
| **Scenario** | "Beta, mujhe CSE ke baare mein batao" (Hindi, informal) |
| **Pipeline impact** | Language detection: "beta" not in HINDI_ROMAN_WORDS, "mujhe" in hi_kw, "baare" in hi_kw, "mein" in hi_kw, "batao" in hi_kw. ≥2 markers → switches to Hindi. BUT "beta" may not be recognized → partial match. |
| **Failure** | If insufficient markers, query stays English → English response to Hindi query |
| **Testing needed** | 1. Informal Hindi query with regional vocabulary. 2. Terms of respect ("beta", "ji", "sahab"). 3. Slow speech with long pauses between words. |
| **Priority** | P2 |

---

## V08 — Reconnect Mid-Conversation

| Field | Value |
|-------|-------|
| **Scenario** | Network drops → LiveKit disconnects → user calls back within 30 seconds |
| **Pipeline impact** | In-memory session is LOST (R11). New session starts fresh. User must re-ask everything. |
| **Failure** | All context from previous call gone. User must repeat their entire query chain. |
| **Testing needed** | 1. Reconnect within session TTL (none exists). 2. Session persistence across disconnects. |
| **Priority** | P0 |

---

## V09 — Sarvam TTS Cold Start

| Field | Value |
|-------|-------|
| **Scenario** | First voice query after agent has been idle for 30+ minutes |
| **Pipeline impact** | Sarvam TTS endpoint may need cold start. First token latency: 2-5 seconds instead of <500ms. |
| **Failure** | User hears silence for 2-5 seconds after their query. May repeat or hang up thinking system is broken. |
| **Testing needed** | 1. TTFT measurement after idle period. 2. Warm-keepalive mechanism (none exists). |
| **Priority** | P2 |

---

## V10 — Packet Loss / Audio Glitching

| Field | Value |
|-------|-------|
| **Scenario** | Intermittent network → STT receives "what is the C-fee" (dropped "SE" from "CSE") |
| **Pipeline impact** | "c fee" → `_normalize_query` doesn't match any known pattern ("c" ≠ "CSE"). → structured_lookup fails (no dept code). → RAG. |
| **Failure** | Failed STT passes through normalization unchanged → wrong answer or clarification |
| **Testing needed** | 1. STT errors that produce single-letter department names ("c fee", "e fee"). 2. Recovery: does follow-up correction work? |
| **Priority** | P1 |

---

## V11 — Repeated STT Noise After Recovery

| Field | Value |
|-------|-------|
| **Scenario** | Background noise → "uh" → clarification → "um" → clarification → "ah" → clarification → user frustrated |
| **Pipeline impact** | Each clarification turn appends to history. After 3 noise → 3 clarification → 3 noise → 3 clarification = 12 turns (history cap). User's actual query never gets processed. |
| **Failure** | User trapped in clarification loop. No mechanism to detect repeated noise pattern and escalate. |
| **Testing needed** | 1. 5+ consecutive noise detection → different behavior? 2. Escalation: "I'm having trouble understanding. Please call 0343-2501353." |
| **Priority** | P1 |

---

## V12 — Code-Switching Mid-Utterance

| Field | Value |
|-------|-------|
| **Scenario** | "CSE fee kitna hai and hostel details batao" (English + Hindi + English + Hindi in one sentence) |
| **Pipeline impact** | Language detection: Hindi markers present -> switches to Hindi. OOD: no match. Expansion: `_split_multi_intent` looks for "and" → "CSE fee kitna hai"(4≥2) and "hostel details batao"(3≥2) → SPLITS! → 2 structured lookups (fee + hostel). Both in lang=hi → but handlers return English. |
| **Failure** | Compound query works via split, but result is in English despite Hindi query. (R10) |
| **Testing needed** | 1. English/Hindi code-switch compound query. 2. Bengali/English code-switch. 3. 3-language code-switch. |
| **Priority** | P1 |

---

## V13 — Background Noise (Non-Speech)

| Field | Value |
|-------|-------|
| **Scenario** | Construction noise, TV, or other people talking in background |
| **Pipeline impact** | Sarvam STT may output: (a) empty string, (b) fragment of actual speech + garbage, (c) pure garbage text |
| **Testing needed** | 1. Empty → clarification. 2. Fragment + garbage → partial match → wrong answer. 3. Pure garbage → `_detect_noisy_transcript` catches (non-alpha ratio > 0.5). |
| **Priority** | P2 |

---

## V14 — Speech Rate Extremes

| Field | Value |
|-------|-------|
| **Scenario** | Very fast speech: "whatisthetotalfeeofcse" (no spaces) |
| **Pipeline impact** | STT may produce run-together words. `normalize_query`: no space between words → no alias matching → `_extract_dept_code` fails. Structured lookup fails. |
| **Testing needed** | 1. Fast speech STT with no word boundaries. 2. Does normalize_query handle concatenated words? |
| **Priority** | P3 |

---

## V15 — Multiple Speakers

| Field | Value |
|-------|-------|
| **Scenario** | Parent and student both speaking near phone |
| **Pipeline impact** | Sarvam may output: (a) combined transcript with both voices, (b) alternating fragments, (c) one speaker only |
| **Testing needed** | 1. Combined STT with contradictory questions. 2. Does the agent handle multi-speaker input gracefully? |
| **Priority** | P2 |

---

## Summary: Voice Failures by Priority

| Priority | Count | IDs |
|----------|-------|-----|
| P0 | 2 | V01 (barge-in), V08 (reconnect) |
| P1 | 5 | V02 (silence), V03 (duplicate), V04 (partial), V10 (packet loss), V11 (noise loop), V12 (code-switch) |
| P2 | 5 | V05 (emotional), V06 (impatient), V07 (elderly), V09 (cold start), V13 (background), V15 (multi-speaker) |
| P3 | 1 | V14 (speech rate) |
| **Total** | **15** | |
