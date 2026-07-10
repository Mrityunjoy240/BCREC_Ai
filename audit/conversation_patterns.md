# Realistic Conversation Scenarios

## Purpose

Real callers do not ask single, well-formed questions. They interrupt themselves, change their mind, use vague references, and get frustrated. This catalog documents realistic conversational patterns that the P0/P1/P2/P3 test suites should cover.

---

## CP01 — Pronoun Reference

| Field | Value |
|-------|-------|
| **Scenario** | User: "What is the fee for CSE?" → Agent: "₹6,04,700" → User: "What about its placement?" |
| **Pronoun** | "its" → refers to CSE (previously mentioned department) |
| **Pipeline challenge** | `_expand_follow_up_query("its placement")` → "its" is not a dept word. `_detect_structured_intent("its placement")` → matches placement (has "placement"). Returns as-is "its placement". Structured lookup extracts dept code — "its" not in DEPT_CODE_MAP. → Overall placement returned (no dept-specific). |
| **Expected** | ConversationState has fee/CSE. "its" should resolve to CSE via state slot. |
| **Actual** | "its" not recognized as dept reference → falls to overall placement. |
| **Test needed** | P0 |

---

## CP02 — "That One" / "The First One"

| Field | Value |
|-------|-------|
| **Scenario** | User: "What departments are available?" → Agent: "CSE, IT, ECE, EE, ME, CE, CSD, AIML, DS, CY" → User: "Tell me about the first one" |
| **Reference** | "the first one" → CSE |
| **Pipeline challenge** | `_expand_follow_up_query("tell me about the first one")` → word_count=6 ≥6 → no expansion. → `_detect_structured_intent("tell me about the first one")` → "the first one" doesn't match any handler. → RAG. → LLM has no context about "first one" → confabulation. |
| **Expected** | Agent recognizes list references (first/second/next/previous/last) and resolves from last assistant response. |
| **Test needed** | P1 |

---

## CP03 — "Same as Before"

| Field | Value |
|-------|-------|
| **Scenario** | User: "CSE fee" → Agent gives fee → User asks hostel info → Agent gives hostel → User: "Same as before" |
| **Reference** | "same as before" → unclear intent. Could mean: (a) repeat last answer, (b) apply previous question's dept to current context |
| **Pipeline challenge** | `_detect_repeat_intent("same as before")` — not in REPEAT_PATTERNS. → falls through to expansion → text merge → "same as before hostel ..." → LLM confusion. |
| **Expected** | Either: (a) treated as repeat, or (b) recognized as context reference |
| **Test needed** | P2 |

---

## CP04 — Comparison Question

| Field | Value |
|-------|-------|
| **Scenario** | "Is CSE better than AIML?" |
| **Pipeline challenge** | OOD: "better" not in OOD keywords. → `_detect_structured_intent`: "better" doesn't match any handler. → "CSE" + "AIML" extract dept codes. → No handler matches "comparison". → RAG. → LLM must answer subjectively. **Hallucination risk** — LLM may invent comparison data. |
| **Failure** | No structured comparison data. LLM may: (a) say "both are good" (safe), (b) make up differences (hallucination), (c) decline to answer. |
| **Test needed** | P1 |

---

## CP05 — Reasoning Question

| Field | Value |
|-------|-------|
| **Scenario** | "Why is CSE fee higher than ME?" |
| **Pipeline challenge** | `_split_multi_intent("why is cse fee higher than me")` → no "and"/"or"/"," → [original]. Structured lookup: "fee" + CSE dept → returns CSE fee. But the "why" + "higher than ME" part is NOT answered. |
| **Failure** | Only fee amount returned; reasoning question ignored. User gets fee but not explanation. |
| **Test needed** | P2 |

---

## CP06 — Contradiction / Correction Chain

| Field | Value |
|-------|-------|
| **Scenario** | User: "I want CSE fee" → Agent: "₹6,04,700" → User: "No, AIML" → Agent: "₹5,54,100" → User: "Actually, both" |
| **Pipeline challenge** | Turn 1: CSE fee. State: fee/CSE. Turn 2: "No, AIML" → `_expand_follow_up_query("No, AIML")` → word_count=2, ambiguous check? "no" not in AMBIGUOUS_WORDS. "aiml" not in AMBIGUOUS_WORDS. → `_detect_structured_intent("no aiml")` → "no" doesn't match, "aiml" → fee matches → already_complete_intent. Returns as-is. → structured_lookup(fee, AIML). **Correct for AIML fee.** Turn 3: "Actually, both" → expansion: "both" → text merge → "both No, AIML" → LLM confusion. |
| **Failure** | "both" doesn't trigger multi-intent. State only has fee/AIML (last). Should return both CSE and AIML fee. |
| **Test needed** | P1 |

---

## CP07 — Topic Return After Many Turns

| Field | Value |
|-------|-------|
| **Scenario** | 10-turn conversation: fee → hostel → placement → admission → scholarship → cutoff → campus → counselling → eligibility → **back to fee** |
| **Pipeline challenge** | Visit order deque has maxlen=8. After 9 domain visits, the 1st (fee) is evicted. When user returns to fee at turn 11, state has NO fee slot → expansion can't use structured state → fallback to text merge. |
| **Failure** | State loss after 8 domain visits. Fee is no longer in visit_order → no structured rewrite for fee follow-ups. |
| **Test needed** | P1 |

---

## CP08 — 25-Turn Conversation (Memory Exhaustion)

| Field | Value |
|-------|-------|
| **Scenario** | 25-turn conversation across 6 topics. Some turns are clarification loops. |
| **Pipeline challenge** | History capped at 12 turns = 6 user + 6 assistant. Turn 13+ evicts oldest. But evicted turns may contain critical context. |
| **Failure** | After turn 13, oldest context is lost. "As I mentioned earlier..." references fail because that turn was evicted. |
| **Test needed** | P1 |

---

## CP09 — Nested Follow-ups

| Field | Value |
|-------|-------|
| **Scenario** | User: "CSE fee" → "total" → "with hostel" → "for girls" → "what about ECE?" |
| **Pipeline challenge** | Turn 1: fee/CSE. Turn 2: "total" → `_detect_structured_intent("total")` → matches fee regex (total → fee). already_complete_intent → returns as-is → structured_lookup ("total" + history? No, as-is). → "total" alone → fee handler returns general fee info (no dept). **FAILS — loses CSE context.** |
| **Failure** | "total" after "CSE fee" should return CSE total fee. But `_detect_structured_intent` returns "fee" → stops expansion. Structured_lookup("total", lang) → `_extract_dept_code("total")` → None → general fee. |
| **Test needed** | P2 |

---

## CP10 — Entity Tracking Across Corrections

| Field | Value |
|-------|-------|
| **Scenario** | User: "What is the HOD of CSE?" → Agent: "Dr. X" → User: "No, I meant ECE" → Agent: "Dr. Y" → User: "And his phone number?" |
| **Pipeline challenge** | Turn 1: hod/CSE. Turn 2: "No, I meant ECE" → expansion: "ECE" is dept, last_intent=hod, dept_compatible → "ECE hod" → structured_lookup → ECE hod. State: hod/ECE. Turn 3: "And his phone number?" → "his" → pronoun resolution needed. |
| **Failure** | "his phone number" → `_detect_structured_intent("his phone number")` → matches contact ("phone") → returns college phone, not HOD's phone. State has hod/ECE but expansion doesn't use it for contact. |
| **Test needed** | P1 |

---

## CP11 — "What Was I Asking About?" (Memory Failure)

| Field | Value |
|-------|-------|
| **Scenario** | User: 5 turns of varied questions → "Sorry, what was I asking about?" |
| **Pipeline challenge** | No handler for meta-questions about conversation history. → RAG → LLM may summarize or guess. |
| **Test needed** | P3 |

---

## CP12 — Interrupted Answer → Follow-up

| Field | Value |
|-------|-------|
| **Scenario** | User: "Tell me about hostel facilities" → Agent starts listing → User interrupts: "and fees?" (barge-in) |
| **Pipeline challenge** | Barge-in (V01) means: (a) previous response cancelled, (b) "and fees?" sent as new query. Expansion: "and fees?" → word_count=2, `_detect_structured_intent("and fees")` → matches fee → already_complete_intent → as-is. Structured_lookup("and fees") → fee, no dept → general fee. **Lost hostel context.** |
| **Expected** | State has hostel (previous turn). "and fees?" should expand to "hostel fees" via state rewrite. |
| **Actual** | "and" is not a recognized facet. `detected_facets` = {"fee"} (from "fees"). `DOMAIN_FACETS["hostel"]` has "fee" → match! → `last_intent` = "hostel"? Wait, the PREVIOUS turn was RAG (hostel facilities → groq_rag) → **state NOT updated** → no hostel slot → no rewrite. |
| **Failure** | RAG-only turn doesn't update state → barge-in follow-up loses hostel context. **R04.** |
| **Test needed** | P0 |

---

## Summary

| ID | Pattern | Risk | Priority |
|----|---------|------|----------|
| CP01 | Pronoun reference ("its") | State doesn't resolve pronouns | P0 |
| CP02 | "That one" / "The first one" | List reference not resolved | P1 |
| CP03 | "Same as before" | Ambiguous intent not recognized | P2 |
| CP04 | Comparison ("better than") | Hallucination risk | P1 |
| CP05 | Reasoning ("why") | Reasoning question ignored | P2 |
| CP06 | Contradiction chain ("No, AIML... Actually both") | Multi-intent + correction interaction | P1 |
| CP07 | Topic return after 8+ domains | Visit order eviction | P1 |
| CP08 | 25-turn conversation | History cap eviction | P1 |
| CP09 | Nested follow-ups ("total" after "CSE fee") | Expansion stops at structured intent | P2 |
| CP10 | Entity tracking ("his phone number") | Pronoun + cross-domain | P1 |
| CP11 | Memory failure ("what was I asking?") | Meta-cognition not supported | P3 |
| CP12 | Barge-in follow-up ("and fees?") | RAG-only state staleness | P0 |
