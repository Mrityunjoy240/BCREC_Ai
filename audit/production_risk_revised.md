# Revised Production Risk Ranking

## Assumption

100,000 real voice conversations per day. Each conversation is 3-8 turns average. Mixed English/Hindi/Bengali. Mix of parent (non-technical) and student callers.

---

## Risk Scoring

Each risk is scored on 4 dimensions (1-5 scale):
- **Likelihood**: How often does this trigger per 100k conversations?
- **Impact**: Severity when it triggers (user harm, trust erosion, wrong info)
- **Detectability**: Can monitoring catch this before users complain?
- **Recovery**: Can user self-correct without leaving the conversation?

Total risk score = L × I × (D⁻¹ + R⁻¹) — higher = more dangerous

---

## Ranked Risks

| Rank | ID | Risk | Likelihood | Impact | Detectability | Recovery | Total Score | Daily Estimate |
|------|----|------|-----------|--------|--------------|----------|-------------|----------------|
| **1** | **NEW** | **OOD code bug: same-category 2-hits blocks legitimate queries** | 5 (5-10% of all queries contain 2 keywords from same OOD category) | 4 (legitimate query blocked → "I can only answer college questions") | 1 (not logged as false positive, looks like correct block) | 2 (user must rephrase with fewer keywords) | **35.0** | **5,000-10,000/day** |
| **2** | **R02** | Generate/Stream parity gap — 30 behavioral differences | 5 (100% of voice calls affected by at least one gap) | 3 (degraded experience but not wrong info for most gaps) | 3 (some gaps logged, most are invisible) | 3 (most gaps are subtle — user doesn't know they missed something) | **25.0** | **100,000/day** (every voice call) |
| **3** | **R05** | Multi-intent missing from stream | 4 (20-30% of voice calls ask compound questions) | 4 (half the answer missing — "fee and hostel" → only fee) | 2 (no log for "partial answer delivered") | 2 (user must ask separate follow-up) | **24.0** | **20,000-30,000/day** |
| **4** | **R04** | ConversationState staleness after RAG-only turns | 5 (40-50% of queries are RAG-only, each one misses state update) | 3 (follow-up expansion falls to text merge = LLM-dependent) | 2 (no metric for "state should have been updated") | 3 (user can rephrase) | **22.5** | **40,000-50,000/day** |
| **5** | **CP01** | Pronoun "its" not resolved to last department | 3 (10-15% of conversations have pronoun references) | 4 (wrong dept or overall data returned) | 1 (no pronoun detection logging) | 3 (user can repeat dept name) | **22.0** | **10,000-15,000/day** |
| **6** | **R01** | Stream hallucination guard non-blocking | 2 (requires LLM hallucination, ~1-3% of LLM calls) | 5 (user hears wrong fee/phone/intake numbers) | 4 (logged in telemetry as guard violation) | 1 (user believes wrong number unless they verify independently) | **21.7** | **1,000-3,000/day** |
| **7** | **V08** | Reconnect mid-conversation — session loss | 3 (10-20% of calls drop and reconnect) | 3 (user must re-ask everything) | 5 (new session_id logged) | 2 (frustrating but user can repeat) | **20.0** | **10,000-20,000/day** |
| **8** | **V01** | Barge-in — interrupted response | 4 (30-50% of voice calls have at least one interruption) | 2 (interrupted turn lost, but user corrects) | 2 (interrupted stream not logged as "incomplete") | 4 (user is actively correcting) | **18.0** | **30,000-50,000/day** |
| **9** | **R10** | Language-ignorant structured handlers | 4 (30-40% of calls are Hindi/Bengali) | 2 (user gets English answer to Hindi query — understandable but poor UX) | 3 (lang is logged, handler response lang is not) | 3 (English answer is still informative) | **16.7** | **30,000-40,000/day** |
| **10** | **R03** | OOD false negatives (health, news, travel) | 3 (5-10% of queries are OOD with no matching category) | 3 (LLM confabulates college answer) | 1 (no "OOD bypassed" log) | 2 (user may realize answer is confabulated) | **15.0** | **5,000-10,000/day** |
| **11** | **R14** | Language switch doesn't replay in stream | 3 (10-20% of non-English users switch language at least once) | 2 (previous answer not replayed — user asks again) | 3 (lang switch logged, but no "replay failed" metric) | 4 (user re-asks in new language) | **14.0** | **10,000-20,000/day** |
| **12** | **R11** | In-memory session (no persistence) | 2 (requires restart or scaling event) | 5 (all sessions lost on restart) | 5 (restart event is logged) | 1 (all user sessions in progress are gone) | **12.5** | **1-2 restart events/month; each affects ~1,000 sessions** |
| **13** | **R09** | Structured lookup priority conflicts | 2 (requires specific combination of keywords, ~2-5% of queries) | 3 (wrong handler returns wrong info) | 2 (no "priority conflict" log) | 2 (user must rephrase to get correct handler) | **12.0** | **2,000-5,000/day** |
| **14** | **R06** | No LLM timeout in non-SAFEPOINT mode | 1 (requires Groq to hang, very rare) | 5 (request hangs indefinitely — blocks worker thread) | 4 (timeout logged if SAFEPOINT enabled) | 1 (user must disconnect and call again) | **11.3** | **10-50/day** |
| **15** | **R08** | Rate limiter lacks circuit breaker | 1 (requires sustained Groq 429s) | 4 (all retries exhausted → error) | 3 (429s are logged, throughput drops visible) | 2 (user gets error, must call back) | **10.0** | **50-100/day** |
| **16** | **R15** | TTS preparation missing from stream | 4 (100% of voice calls have acronyms like "CSE") | 1 (CSE read as "see" instead of "C-S-E" — minor) | 1 (no "TTS quality" metric) | 5 (users still understand) | **8.3** | **100,000/day** (all voice calls) |
| **17** | **R07** | Stream prompt uses normalized query | 3 (100% of voice calls use normalized query) | 1 (subtle difference, rarely affects answer quality) | 1 (no comparison metric) | 5 (no recovery needed — answer is close enough) | **7.5** | **100,000/day** |
| **18** | **R13** | Greeting missing from stream | 4 (30-50% of calls start with greeting) | 1 (LLM greeting is still friendly) | 1 (no "greeting missed" log) | 5 (user doesn't notice) | **6.7** | **30,000-50,000/day** |
| **19** | **R12** | Yes/no continuation missing from stream | 2 (requires clarification prompt + "yes" response, ~5-10% of calls) | 2 ("yes" treated as filler → acknowledgment instead of intended query) | 2 (filler acknowledgment logged, but "should have been continuation" not tracked) | 3 (user re-asks the question) | **6.7** | **5,000-10,000/day** |
| **20** | **R16** | Bengali normalization missing from stream | 3 (30-40% of Bengali calls have "রুপি" responses) | 1 (TTS reads "রুপি" which is subtle) | 1 (no "normalization skipped" log) | 5 (users understand despite slight mispronunciation) | **5.0** | **100,000/day** (Bengali calls) |

---

## Key Findings

1. **OOD bug is the #1 production risk** — not hallucination. 5,000-10,000 legitimate queries blocked per day because the OOD code blocks on any 2 keyword hits, regardless of whether they're in the same category. The fact that C01 ("Does BCREC offer Python programming?") would be blocked is a daily occurrence.

2. **Parity gap #2 by volume not impact** — 100,000 calls/day affected by at least one gap, but most gaps are UX degradation rather than wrong information.

3. **Hallucination guard (#6) is high impact but low frequency** — 1,000-3,000 calls/day hear wrong numbers. When it happens it's damaging, but it doesn't happen every call.

4. **Pronoun resolution (#5) is a P0 gap** not previously identified. 10,000-15,000 calls/day have "its", "his", "that" references that fail.

5. **Barge-in (#8) is the most common voice failure** — 30,000-50,000 calls/day experience it. It's low-impact because the user corrects, but it creates negative UX.

6. **Recovery difficulty is the hidden multiplier** — hallucination guard violations are hard to detect (user doesn't know the number was hallucinated) and impossible to recover from (user believes the wrong number and acts on it). This makes it the highest per-incident cost even though it's lower frequency.

---

## Revised Priority Assignment

| Priority | Count | Risks |
|----------|-------|-------|
| **P0** (score ≥20) | 7 | OOD bug, Parity gap, Multi-intent, State staleness, Pronouns, Hallucination guard, Reconnect |
| **P1** (score 15-20) | 4 | Barge-in, Language-ignorant handlers, OOD false negatives, Language switch replay |
| **P2** (score 10-15) | 3 | Session persistence, Priority conflicts, LLM timeout |
| **P3** (score <10) | 6 | Rate limiter, TTS prep, Prompt query diff, Greeting, Yes/No, Bengali norm |
