# Conversation Quality Improvement — Engineering Report

Generated: 2026-07-01

**Data source:** 146 conversation logs (7202 events, 1023 turns)
**Live sessions:** 1 (`live-comprehensive-test`, 67 events, 14 turns)
**Simulated sessions:** 142 (across 30 scenario categories)
**Other sessions:** 3 test/debug sessions (`latency_test`, `session-lifecycle-test`, `test-debug-26736`)

---

## 1. Conversation Pattern Analysis

### 1.1 Most Common User Intents (Ranked by Frequency)

| Rank | Intent | Count | % of Turns |
|------|--------|-------|------------|
| 1 | Admission/Fees | 195 | 19.1% |
| 2 | Short/Ambiguous (1-2 words) | 182 | 17.8% |
| 3 | Placement/Internship | 108 | 10.6% |
| 4 | Academic/Courses/Branch | 73 | 7.1% |
| 5 | Greetings | 63 | 6.2% |
| 6 | Informational Questions (What/How) | 60 | 5.9% |
| 7 | Hostel/Mess | 34 | 3.3% |
| 8 | Labs/Research | 29 | 2.8% |
| 9 | Sports/Extracurricular | 23 | 2.2% |
| 10 | Scholarship | 20 | 2.0% |
| 11 | Out-of-KB Questions | 18 | 1.8% |
| 12 | Library/Facilities | 16 | 1.6% |
| 13 | Repeat Requests | 16 | 1.6% |
| 14 | Transport | 5 | 0.5% |
| 15 | Other (non-English script, uncategorized) | 176 | 17.2% |

**Key insight:** 17.8% of turns are short/ambiguous (1-2 words like "fees", "seats", "hostel") and 17.2% are non-English queries that don't match keyword patterns. Together, 35% of all turns are inherently ambiguous or difficult to route.

### 1.2 Most Common Follow-Up Questions

Follow-ups account for **161 SPECIAL_EVENTs** across **105 sessions**. Patterns:

| Rank | Follow-Up Type | Count | % of Follow-Ups |
|------|---------------|-------|-----------------|
| 1 | Deep-dive on same topic (fee → seats → placement) | 194 | 22.0% |
| 2 | New subtopic ("What about AIML?", "Tell me about hostel") | 167 | 19.0% |
| 3 | Broadening ("Also", "More", "Aur batao") | 98 | 11.1% |
| 4 | Repeat requests | 66 | 7.5% |
| 5 | Short/ambiguous follow-ups | 60 | 6.8% |
| 6 | Other miscellaneous | 295 | 33.5% |

**Typical follow-up chain (from simulated sessions):**
1. "Hello" → 2. "What is the fee for CSE?" → 3. "How many seats?" → 4. "What is the placement percentage?" → 5. "What about hostel?"

This pattern suggests users naturally **drill down** from general → specific within a topic.

### 1.3 Most Common Clarification Requests

- **Total: 32 clarification prompts** across **18 sessions** (3.13% of turns)
- Sessions with most: `sim_en_admission_b97931`, `sim_en_general_knowledge_48604f`, `sim_mx_confused_admission_26ea4a`, `sim_mx_short_queries_814257` (3 each)
- Top sessions correlate with sessions that also have errors (RETRIEVAL_ERROR, LLM_TIMEOUT), suggesting clarifications spike when the pipeline is failing

### 1.4 Most Common Failures

All 23 errors are **simulated** (injected by `simulate_conversations.py`):

| Rank | Error Type | Count | % of Errors | Affected Sessions |
|------|-----------|-------|-------------|-------------------|
| 1 | RETRIEVAL_ERROR | 7 | 30.4% | 7 |
| 2 | LLM_TIMEOUT | 6 | 26.1% | 6 |
| 3 | LLM_HTTP_ERROR | 4 | 17.4% | 3 |
| 4 | VALIDATION_FAILED | 4 | 17.4% | 4 |
| 5 | LLM_RATE_LIMIT | 2 | 8.7% | 2 |

**Important caveat:** All errors are synthetic. No real production errors exist in the data.

### 1.5 Most Common Repeated Questions

| Rank | Query | Repeats | Notes |
|------|-------|---------|-------|
| 1 | "hello" | 42 | Single-word greeting, low information |
| 2 | "fees" | 40 | Single-word, ambiguous (which fee?) |
| 3 | "seats" | 37 | Single-word, ambiguous |
| 4 | "hi" | 28 | Greeting |
| 5 | "principal" | 24 | Single-word |
| 6 | "repeat" | 12 | Repeat request |
| 7 | "হ্যালো" | 12 | Bengali greeting |
| 8 | "good morning" | 12 | Greeting |
| 9 | "placement" | 8 | Single-word |
| 10 | "hostel" | 8 | Single-word |
| 11 | "What is the fee for CSE?" | 7 | Template question |
| 12 | "Is there any scholarship for SC students?" | 7 | Template question |
| 13 | "Does the college have a swimming pool?" | 7 | Template question |
| 14 | "Tell me about the Mars mission internship" | 7 | Out-of-KB |

**Key insight:** 8 of the top 10 repeated queries are **1-2 word ambiguous queries**. These represent the single biggest category of input.

### 1.6 Hallucination Guard Triggers (8 total)

All 8 triggers are **simulated**, coinciding with low-confidence retrieval:

| Session | Turn | Query | Retrieval Confidence |
|---------|------|-------|---------------------|
| sim_en_admission_54071b | 5 | "Is there any scholarship for SC students?" | < 0.3 |
| sim_en_cse_fees_8acc38 | 5 | "Who is the principal of this college?" | < 0.3 |
| sim_en_cse_fees_b8408d | 2 | "What is the fee for CSE?" | < 0.3 |
| sim_en_cse_fees_b8408d | 5 | "Who is the principal of this college?" | < 0.3 |
| sim_en_ece_ee_bb78cb | 7 | "Tell me about the Mars mission internship" | < 0.3 |
| sim_mx_codeswitch_fees_04b30c | 5 | "Principal ke baare mein batao" | < 0.3 |
| sim_mx_codeswitch_fees_47dea9 | 5 | "Principal ke baare mein batao" | < 0.3 |
| sim_mx_codeswitch_fees_f5f519 | 5 | "Principal ke baare mein batao" | < 0.3 |

**Trigger pattern:** All 8 happen at confidence below 0.3 threshold. Queries about "principal" and out-of-domain topics.

### 1.7 Most Common Low-Confidence Retrievals (14 total, conf < 0.3)

| Rank | Query | Occurrences | Confidence Range |
|------|-------|-------------|-----------------|
| 1 | "Bhai Mars mission kaise join karein?" | 3 | 0.0932 |
| 2 | "Who is the CEO of Google?" | 3 | 0.1877 |
| 3 | "Tell me about the Mars mission internship" | 3 | 0.2195 |
| 4 | "Does the college have an NSS chapter?" | 2 | < 0.3 |
| 5 | "What is the capital of France?" | 1 | 0.0455 |
| 6 | "Mujhe admission lena hai. Kya karna hoga?" | 1 | < 0.3 |
| 7 | "What is the total number of seats?" | 1 | < 0.3 |

**Pattern:** All low-confidence queries are either **out-of-domain** (Mars, Google, France) or **code-switched Hindi** ("Bhai...kaise join karein?").

### 1.8 Average Conversation Length

- **Mean:** 7.2 turns/session (median: 7)
- **Range:** 1–14 turns
- **Distribution:** 94.4% of sessions have 6-8 turns
- **Avg session duration:** 93.5 seconds

The distribution is extremely uniform because 142/146 sessions are simulated with scripted turn counts.

### 1.9 Interruption Count

**0 interruptions recorded.** The telemetry has no interruption data (`interruptions: 0` in all SESSION_SUMMARY events). Either interruptions are not tracked or the simulator never generated them.

### 1.10 Language Switches

**0 language switches recorded.** This is likely a telemetry gap — the live session clearly shows language switching (English → Hindi → Bengali → English at turn 7), but the `language_switches` accumulator was never incremented.

---

## 2. Prioritized Issues (Impact × Frequency)

### Critical

| Issue | Frequency | Impact | Score | Evidence |
|-------|-----------|--------|-------|----------|
| Short/ambiguous 1-2 word queries | 182 turns (17.8%) | Leads to wrong retrieval, clarifications, low confidence | **HIGH** | 40× "fees", 37× "seats", 24× "principal" — no disambiguation context |
| Hallucination guard triggers on low-confidence retrieval | 8 events | Blocked responses = failed turns | **HIGH** | 8 blocked turns, all correlated with conf < 0.3 |
| High LLM latency (80.9% of pipeline) | 199 LLM calls | 4551ms avg = poor UX | **HIGH** | 80.9% of total pipeline time, P95 = 7788ms |
| Retrieval errors | 7 occurrences | Complete turn failure | **HIGH** | 30.4% of all errors, 7 sessions affected |

### High

| Issue | Frequency | Impact | Score |
|-------|-----------|--------|-------|
| Out-of-KB questions not handled gracefully | 18 queries | Hallucination risk, low confidence | HIGH |
| Code-switched Hindi queries have lowest confidence | hi: 0.5583 avg | Poor cross-lingual retrieval | HIGH |
| Repeat requests | 66 follow-ups (7.5%) | User frustration | MEDIUM |
| Clarification prompts | 32 (3.13% of turns) | User effort to rephrase | MEDIUM |

### Medium

| Issue | Frequency | Impact | Score |
|-------|-----------|--------|-------|
| No conversation memory between turns | Implicit | Each turn is isolated, no context carryover | MEDIUM |
| High clarification rate for ambiguous queries | 33 ambiguous (3.23%) | Users must rephrase | MEDIUM |
| LLM HTTP errors | 4 (17.4% of errors) | Poor error messaging | MEDIUM |

### Low

| Issue | Frequency | Impact | Score |
|-------|-----------|--------|-------|
| Language switches not tracked | 0 recorded (likely gap) | Can't measure multilingual UX | LOW |
| Interruptions not tracked | 0 recorded | Can't measure barge-in UX | LOW |

---

## 3. Root Cause Analysis

### Critical Issue 1: Short/Ambiguous 1-2 Word Queries

**Root cause: Conversation state + Retrieval**

The system does not use conversation context to disambiguate single-word queries. When a user says "fees" after previously asking about CSE, the retrieval likely re-embeds the isolated word "fees" rather than expanding it to "CSE department fees" using conversation history. Evidence:

- 40 queries = "fees" with no context enrichment
- 37 queries = "seats" with no context enrichment
- 24 queries = "principal" with no context enrichment
- The live session shows the user saying "fees" at turn 7 after multiple prior turns about CSE — the retrieval query logged as "fees" unmodified

### Critical Issue 2: Hallucination Guard Triggers on Low-Confidence Retrieval

**Root cause: Retrieval + Missing KB**

All 8 triggered guards coincide with retrieval confidence < 0.3. The queries are either:
- Out-of-domain (Mars mission, Google CEO, France capital)
- Low-quality retrieval (principal of college — potentially missing from KB)
- Code-switched Hindi ("Principal ke baare mein batao")

The low confidence triggers the guard, which blocks the response. This is working as designed, but the **underlying problem is that these queries should never have low confidence** — either the KB should cover "principal" or the system should gracefully handle out-of-domain queries.

### Critical Issue 3: High LLM Latency (4551ms avg)

**Root cause: LLM reasoning**

Average LLM call is 4551ms, comprising:
- TTFT: 898ms (waiting for first token)
- Generation: 3435ms (token generation)
- Post-processing: 751ms (response validation/formatting)

The model is `llama-3.1-8b-instant` for all calls. The average prompt is 852.5 tokens and output is 232.3 completion tokens at 33.9 tokens/sec. The weak correlation between prompt tokens and latency (0.0598) suggests latency is not primarily driven by prompt size but by model inference time.

### Critical Issue 4: Retrieval Errors (7 occurrences)

**Root cause: Application logic (simulated)**

All 7 RETRIEVAL_ERRORs have the message "Simulated RETRIEVAL_ERROR" from `simulate_conversations.py`. No real retrieval errors are in the data. However, the pattern of affected sessions (multi-language, multi-department) suggests this could be triggered by edge cases in input processing or KB connectivity.

### High Issue 1: Out-of-KB Questions Not Handled Gracefully

**Root cause: Missing KB + Conversation state**

18 queries are out-of-domain (Mars, Google CEO, France capital). The system has no mechanism to:
1. Detect out-of-domain queries before retrieval
2. Respond with a graceful "I don't know" without consuming LLM latency
3. Redirect to relevant topics

### High Issue 2: Code-Switched Hindi Has Lowest Confidence

**Root cause: Retrieval**

Hindi confidence (0.5583) is significantly lower than English (0.6622) and Bengali (0.7625). Code-switched "mx" (0.7734) and "hi-bn" (0.7793) have better confidence, likely because they're mixed with higher-confidence languages. The retrieval embedding likely underrepresents Hindi text.

### High Issue 3: Repeat Requests

**Root cause: Voice formatting + LLM reasoning**

66 repeat requests (7.5% of follow-ups) suggest users couldn't understand or hear the response. This could be:
- TTS speaking too fast or with poor prosody
- Response too long or complex
- Response didn't address the question

The repeat request "फिर से बोलिए" in the live session suggests non-English users need repeats more often.

---

## 4. Recommended Solutions

### R1: Conversation Context Enrichment for Short Queries

**Problem:** Single-word queries ("fees", "seats") lose context.

**Solution:** Before retrieval, expand the query using the last 2-3 user turns. If query is ≤3 words and a prior turn had a clear topic, prepend that context.
- Example: Previous turn: "What is the fee for CSE?" → Current turn: "seats" → Expanded: "How many seats in CSE?"
- Implementation: Simple heuristic in the retrieval pipeline, 20-30 lines of code

**Expected benefit:** 35-50% reduction in low-confidence retrievals for short queries
**Risk:** Low — context expansion can always fall back to the original query
**Effort:** Small (1-2 days)

### R2: Out-of-Domain Query Detection

**Problem:** 18 out-of-domain queries trigger low confidence and hallucination guards.

**Solution:** Add a pre-retrieval "domain check" using a simple threshold on embedding similarity to KB content. If max similarity to any KB chunk is below a threshold, respond with "I can only answer questions about BCROCE college."
- No LLM call needed for out-of-domain responses
- Can be implemented using the existing embedding infrastructure

**Expected benefit:** Eliminates hallucination risk for out-of-domain queries, saves LLM cost
**Risk:** Low — false positives can be routed to LLM for a more graceful response
**Effort:** Small (1-2 days)

### R3: Conversation Memory for Follow-Up Resolution

**Problem:** Follow-ups ("What about AIML?") are treated as independent queries.

**Solution:** Maintain a lightweight conversation state dict per session:
- Last topic (department, fee, placement, etc.)
- Last entities mentioned (CSE, ECE, etc.)
- On new query, if it appears to be a follow-up (no subject, starts with "what about", "also"), inject the last topic

**Expected benefit:** Better retrieval relevance for 19% of follow-ups classified as "new subtopic"
**Risk:** Low — conversation state is already available in session_id
**Effort:** Small (2-3 days)

### R4: Hindi Retrieval Embedding Tuning

**Problem:** Hindi confidence (0.5583) is 15.6% lower than English.

**Solution:** 
1. Verify that the embedding model supports Hindi well
2. If yes, add Hindi-specific query preprocessing (normalize Devanagari, handle common spelling variations)
3. If no, consider a multilingual embedding model or transliteration-based fallback

**Expected benefit:** Hindi confidence improves from 0.56 to ~0.70
**Risk:** Medium — embedding model changes could affect all languages
**Effort:** Medium (3-5 days including evaluation)

### R5: Repeat Request Handling

**Problem:** 66 repeat requests.

**Solution:** When a repeat request is detected (key phrases: "repeat", "again", "फिर से"), the system should:
1. Re-read the previous response (optimally using the same TTS audio cache)
2. OR simplify the previous response if it was long
3. Detect if repeats happen on a specific topic consistently (could indicate a KB gap)

**Expected benefit:** Better UX for 7.5% of follow-ups
**Risk:** Low
**Effort:** Small (1-2 days)

### R6: Reduce LLM Latency

**Problem:** 4551ms avg LLM latency.

**Solution:** Multiple low-risk options:
- Option A: Reduce prompt size by pruning conversation history to last 3 turns (avg prompt: 852.5 tokens)
- Option B: Set a lower `max_tokens` limit if responses are consistently short (avg 57.8 chars ≠ 232.3 tokens suggests token waste)
- Option C: Implement response streaming to show partial results

**Expected benefit:** 20-30% latency reduction (1000-1500ms)
**Risk:** Medium — prompt changes could affect response quality
**Effort:** Small (Option A: 1 day, Option C: 3-5 days)

---

## 5. Prioritized Engineering Roadmap

| Priority | Improvement | Effort | Dependencies | UX Benefit | Risk |
|----------|------------|--------|-------------|------------|------|
| P0 | **Conversation context enrichment (R1)** | 1-2 days | None | High (35% of turns improved) | Low |
| P0 | **Out-of-domain detection (R2)** | 1-2 days | Embedding pipeline | High (prevents 18 failed turns) | Low |
| P1 | **Conversation memory for follow-ups (R3)** | 2-3 days | R1 context enrichment | Medium (19% of follow-ups) | Low |
| P1 | **Hindi retrieval tuning (R4)** | 3-5 days | Embedding evaluation | Medium (Hindi confidence +15%) | Medium |
| P2 | **Repeat request handling (R5)** | 1-2 days | None | Medium (7.5% of follow-ups) | Low |
| P2 | **LLM latency reduction (R6)** | 1-5 days | Prompt structure review | High (avg turn time -30%) | Medium |
| P3 | **Language switch telemetry fix** | 0.5 days | Telemetry schema | Low (measurement only) | Low |
| P3 | **Interruption tracking** | 1 day | Voice pipeline | Low (measurement only) | Low |

### Recommended Sprint Plan

**Sprint 1 (Week 1-2):** P0 items — Context enrichment + Out-of-domain detection
- Smallest code changes with highest impact
- No architectural changes
- No model changes

**Sprint 2 (Week 3-4):** P1 items — Conversation memory + Hindi retrieval
- Builds on Sprint 1 context infrastructure
- Targeted improvement for multilingual support

**Sprint 3 (Week 5-6):** P2 items — Repeat handling + Latency
- Address user frustration metrics
- Requires benchmarking before/after latency

**Backlog:** P3 items — Telemetry improvements for future analysis

---

*This report is based on analysis of 146 telemetry session files. 97.3% of data is from simulated conversations. Findings should be validated against real production traffic before prioritizing implementation.*
