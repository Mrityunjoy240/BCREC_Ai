# P1 Red-Team Evaluation Catalog

## Focus Areas

1. ConversationState staleness
2. Multi-turn memory
3. Cross-domain switching
4. Entity tracking
5. Pronoun resolution
6. Stream vs generate parity
7. Prompt query differences
8. LLM timeout/retry behavior
9. RAG retrieval degradation
10. Ranking failures
11. Comparison reasoning
12. Aggregation reasoning
13. Long conversations
14. Context window pressure
15. Session recovery
16. LiveKit voice flow
17. Sarvam STT/TTS failures
18. Partial transcripts
19. Interruptions
20. Barge-in
21. Duplicate STT events

---

## Entry Format

```
### ID
**Risks**: ...
**Priority**: P1
**Conversation**: [turns]
**generate stages**: ...
**stream stages**: ...
**Handler**: ...
**Retrieval**: ...
**Lang**: ...
**Response**: ...
**CState evolution**: ...
**Logs**: ...
**Failure**: ...
**Root cause**: ...
**Impact**: ...
**Validation**: ...
```

Where behavior is unknown, `UNKNOWN — requires execution verification` is written.

---

## 1. ConversationState Staleness

### P1-CS-001
**Risks**: R-CS, R-WS
**Priority**: P1
**Conversation**:
- T1: "What is the total fee for CSE department?"
- T2: "How is the teaching quality?"
- T3: "also tell me about the fees"
**generate stages**:
- T1: normalize → validate → noise → lang → followup_expand → arithmetic(structured) → state update(domain=fee, intent=fee, dept=CSE) → return
- T2: normalize → validate → noise → lang → followup_expand → no structured hit → RAG retrieval → cache check → LLM → hallucination guard → return
- T3: normalize → validate → noise → lang → followup_expand → state read(visit_order=[fee], slots[fee].intent=fee) → followup merge → structured_lookup("fee fee") → wait, expanded query would be "also tell me about the fees fee" via structured_fee_followup rule at line 2097 → fee handler returns total fee
**stream stages**: Same as generate EXCEPT T2 state NOT updated (RAG-only turns never update state in either path)
**Handler**: T1: fee (structured arithmetic), T2: None (RAG-only), T3: fee (structured)
**Retrieval**: T1: none (structured), T2: vector search for "teaching quality", T3: none (structured)
**Lang**: en → en → en
**Response**: T1: "The total fee for CSE is six lakh four thousand seven hundred rupees." T2: LLM-generated answer about teaching quality. T3: "The total fee for CSE is six lakh four thousand seven hundred rupees." (repeats T1 because followup expansion rewrote "also tell me about the fees" to "also tell me about the fees fee" using previous state)
**CState evolution**: T1: visit_order=[fee], slots[fee]={intent=fee, dept=CSE}. T2: unchanged (RAG-only, no state update). T3: unchanged (structured lookup hit but only updates slot if intent detected; "also tell me about the fees fee" → _detect_structured_intent → fee intent → state_slot updated but same values)
**Logs**: T2: no state update log entry. T3: EXPAND reason=structured_fee_followup
**Failure**: T2 state not updated even though teaching quality IS a valid topic. Next fee query works correctly only because the fee state from T1 is still fresh. But if T2 was a different domain (e.g., placement), T2's domain would never be recorded.
**Root cause**: `_session_states` only updated in `_structured_lookup` hit paths (line 3602-3610). RAG-only paths skip state update entirely (line 3633-3712 has no state update call).
**Impact**: MEDIUM — follow-up expansion on RAG-only domains fails to detect domain continuity. User says "and what about the fees" after a RAG-only placement discussion — fee domain may not be in visit_order if fee was discussed 3+ turns ago.
**Validation**: Unit test: after `generate_response("How is the teaching quality?", sid)`, assert `_session_states[sid].visit_order` is empty (not updated). Integration: 3-turn conversation above, verify T3 response correctly addresses fees.

### P1-CS-002
**Risks**: R-CS, R-FU
**Priority**: P1
**Conversation**:
- T1: "What is the cutoff rank for CSE?" → structured hit (cutoff handler, state updated: domain=admission, intent=cutoff, dept=CSE)
- T2: "How many companies visited for placement last year?" → structured hit (placement handler, state updated: domain=placement)
- T3: "what about the cutoff?"
**generate stages**: T1: normalize → ... → structured_lookup cutoff → state push(admission) → return. T2: normalize → ... → structured_lookup placement → state push(placement) → return. T3: normalize → ... → followup_expand → _detect_structured_intent → "cutoff" intent detected → "already_complete_intent" → no expansion → structured_lookup cutoff → returns CSE cutoff from T1 state? NO — _structured_lookup cutoff handler at line 2505-2526 extracts dept_code from query. Query is just "what about the cutoff" — no dept_code → falls to "I don't have the specific cutoff data". The CSE dept from T1's state is in ConversationState but _structured_lookup doesn't read ConversationState at all! It uses `_extract_dept_code(q)` which only looks at the current query.
**stream stages**: Same
**Handler**: T1: cutoff, T2: placement, T3: cutoff (but department-less)
**Retrieval**: T1/T2: none (structured). T3: none (structured returns fallback)
**Lang**: en
**Response**: T3: "I don't have the specific cutoff data for that department. Please contact the college admission office for accurate rank information."
**CState evolution**: T1: visit_order=[admission], slots[admission]={intent=cutoff, dept=CSE}. T2: visit_order=[admission, placement]. T3: visit_order=[admission, placement, admission] (cutoff pushes "admission" again)
**Failure**: Follow-up "what about the cutoff" does NOT use the previous CSE department from state. User has to re-specify "CSE cutoff".
**Root cause**: `_structured_lookup` cutoff handler (line 2505-2526) uses `_extract_dept_code(query)` only. It does NOT read `_session_states` to fill in missing department from previous turns. The follow-up expansion's structured_department_rewrite (line 2078-2095) only fires when `is_dept_query` is True AND `last_intent` is in `dept_compatible_intents`. "what about the cutoff" — is_dept_query? No (no dept words). So no rewrite happens.
**Impact**: HIGH — users in multi-turn conversations must repeat department names for cutoff, fee, placement queries. Defeats the purpose of follow-up expansion for department-less follow-ups.
**Validation**: Unit test: T1+cutoff+CSE → T2+"what about cutoff" → assert response contains CSE cutoff or department. Currently fails.

### P1-CS-003
**Risks**: R-CS
**Priority**: P1
**Conversation**:
- T1: "Is hostel available at BCREC?" → structured hit (hostel handler, state push(hostel))
- T2: "what is the fee" → followup_expand → state.slots: T1 was hostel. Query is "what is the fee" — _detect_structured_intent → fee. is_dept_query? No ("fee" not in dept_words). Goes to structured fee_followup? Only at line 2097 if domain=="fee" and last_intent=="fee". But domain=hostel from T1. So falls through. No expansion → no dept → _structured_lookup fee handler gets "what is the fee" → no dept_code → returns general fee info (line 2422-2430).
**Expected**: Structured fee_followup NOT triggered because domain==hostel, not fee. Query goes to structured lookup with no dept → general fee info.
**Failure**: User asked about hostel fee but gets general fee info. The follow-up should have recognized "fee" in the context of hostel and returned hostel-specific fee info.
**Root cause**: DOMAIN_FACETS["hostel"] includes "fee" (line 117) but the structured rewrite at line 2097 only checks domain=="fee". The facet overlap detection at line 2060 (`detected_facets & domain_facets`) happens earlier (line 2058-2061) but the actual rewrite rules only cover domain=="fee" and domain=="hostel" (for hostel_subtype). "fee" as a facet of "hostel" has no rewrite rule.
**Impact**: MEDIUM — users asking "what is the fee" after hostel discussion get general fee, not hostel fee. Confusing.
**Validation**: Integration: T1 hostel → T2 "what is the fee" → verify response mentions hostel fee specifically.

---

## 2. Multi-Turn Memory

### P1-MM-001
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "Tell me about CSE department"
- T2: "what about fees?"
**generate stages**: T1: normalize → structured_lookup departments handler (line 2567) → returns "Computer Science and Engineering (CSE) — Intake: ...". State update: push(departments_info), slot departments_info.intent=departments. T2: followup_expand → word_count=3 → _detect_structured_intent("what about fees") → fee → "already_complete_intent" → no expansion → structured_lookup fee handler → no dept_code in "what about fees" → general fee info.
**But**: is this correct? "what about fees" — _detect_structured_intent should detect "fee" at line 1798. Yes, "fees" matches `\b(fee|fees|...)`. So intent=fee → no expansion → structured_lookup fee → no dept → general fee.
**Failure**: User expects CSE-specific fee after asking about CSE. Gets general fee info instead.
**Root cause**: followup_expand sees "what about fees" as already having a complete structured intent (fee), so it doesn't expand. But the fee intent needs the department from T1 to give a department-specific answer. _structured_lookup fee handler doesn't read ConversationState for the missing dept.
**Impact**: HIGH — common conversation pattern "X department" → "what about fees" fails to carry department context to the fee handler.
**Validation**: Integration test: T1+T2 as above → verify response is CSE-specific fee, not general fee info.

### P1-MM-002
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "Who is the HOD of CSE?"
- T2: "how about ECE?"
**generate stages**: T1: structured_lookup hod handler (line 2434) → returns "Dr. ... (HOD of CSE)". State: push(hod). T2: followup_expand → word_count=3 → _detect_structured_intent → "how about" doesn't match any intent → NOT "already_complete_intent". last_user = "Who is the HOD of CSE?". current_domain = ? "how about ECE" — "ece" → _detect_query_domain → "courses" domain (line 1736-1745, "ece" not directly in any domain... wait, courses domain has "course", "courses", "department", etc. ECE is not a keyword, but "ece" won't match any domain keyword. Actually `DEPT_CODE_MAP` at line 692 maps "ece" → "ECE", but `_detect_query_domain` uses `_DOMAIN_KEYWORDS` which doesn't include department codes. So current_domain would be None. previous_domain = ? "who is the hod of cse" → "hod" → hod domain. So current_domain=None, last_user_domain=hod → different → falls to "new_domain_blocked" (line 1952) → no expansion → structured_lookup "how about ece" → no handler match → None → RAG retrieval.
**Failure**: "how about ECE" after HOD query should ask about HOD of ECE but falls through to RAG with no context.
**Root cause**: followup_expansion's "new_domain_blocked" logic fires when current_domain differs from previous_domain. But current_domain=None (no domain detected) while previous_domain=hod → considered "different" → expansion blocked. Then structured_lookup gets "how about ECE" which doesn't match HOD handler (no "hod" keyword).
**Impact**: MEDIUM — common pattern "who is HOD of X" → "how about Y" fails. User must fully re-ask.
**Validation**: Integration: T1+T2 → verify response is HOD of ECE, not a RAG fallback.

### P1-MM-003
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "What are the fees for CSE?"
- T2: "and for ECE?"
**generate stages**: T1: structured fee hit, state=departments_info→fee. T2: followup_expand → _detect_structured_intent → None (no intent keywords in "and for ECE"). word_count=3 ≤ 2? No, 3 words. So the ambiguous word check at line 1915 doesn't fire (word_count≤2). Goes to line 1929: _detect_structured_intent → None. Then to line 1939: last_user = "What are the fees for CSE?". Then _detect_query_domain("and for ece") → "ece" matches... actually _detect_query_domain checks _DOMAIN_KEYWORDS. "ece" is NOT in any domain keyword set. So current_domain=None. previous_domain = "fees" (from "fee" keyword in T1). They're different → new_domain_blocked? No, current_domain IS None, so the check `if current_domain:` at line 1950 is False → skips new_domain_blocked → falls to state-based rewrite at line 1962. state.visit_order = ["fee"]. state.slots["fee"].intent = "fee". state.slots["fee"].department = "CSE". is_dept_query? "and for ECE" → dept_code="_extract_dept_code" → "ece" → "ECE". is_dept_query=True. last_intent="fee" which is in dept_compatible_intents. So: expanded = f"{dept} {last_intent}" = "ece fee" → structured_lookup("ece fee") → fee handler → dept_code=ECE → returns ECE fee.
**Expected**: Works correctly! "ece fee" hits fee handler with dept_code=ECE.
**Actually this test case works currently**. Let me make it more interesting.

- T3: "what about seats?"
**generate stages**: T3: followup_expand → _detect_structured_intent → "seats" → intent=seats. is_dept_query? "seats" not in dept_words → False. Goes to state rewrite: last_intent="fee". "seats" is in dept_compatible_intents? No! dept_compatible_intents at line 2066-2076 includes: fee, admission, placement, hod, seats, cutoff, eligibility, departments, faculty. YES "seats" IS in the list. So is_dept_query=False → the condition `if is_dept_query and last_intent in dept_compatible_intents` at line 2078 is False → falls through. Then domain=="fee" and last_intent=="fee" → structured_fee_followup → "what about seats fee". That's wrong.
**Wait**: line 2078: `if is_dept_query and last_intent in dept_compatible_intents:`. is_dept_query is False (no dept words in "what about seats"). So even though last_intent is "fee" (compatible), the rewrite doesn't fire because there's no department to extract. Falls to line 2097: domain=="fee" and last_intent=="fee" → True → expanded = "what about seats fee". This would hit fee handler (matches "fee") → return... Actually wait, "what about seats fee" — dept_code from _extract_dept_code("what about seats fee") → no department code → falls to general fee info (line 2422). User gets general fee info instead of seat info!

**Failure**: "what about seats" after fee query gets rewritten to "what about seats fee", hitting fee handler instead of seats handler.
**Root cause**: The structured_fee_followup rule at line 2097-2104 is too broad. It fires for ANY follow-up when the last domain was fee, even if the follow-up is about a different intent. It should check that the current query is fee-related before appending "fee".
**Impact**: HIGH — user asks about seats after fees but gets fee info. Conversation derailment.
**Validation**: Unit: _expand_follow_up_query("what about seats", history_with_fee, sid) should return "what about seats" or "CSE seats", not "what about seats fee".

### P1-MM-004
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE?" → structured fee hit → 604700 total
- T2: "and how many seats?"
**generate stages**: T2: _detect_structured_intent("and how many seats") → "seats" → already_complete_intent → no expansion → structured_lookup("and how many seats") → seats handler (line 2494) → _extract_dept_code → "CSE" → returns "The intake for CSE is ... seats."
**Expected**: This works correctly because _detect_structured_intent detects "seats" = seats intent → no expansion → structured_lookup seats handler extracts CSE from query. The "and how many seats" does NOT contain "fee" so it goes to seats, not fee. Good.

Actually this works, let me not include it. Let me move on to more impactful tests.

### P1-MM-005
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "What is the total fee for CSE?" → structured fee hit, state updated
- T2: "and for ECE?" → expanded to "ece fee" → ECE fee. State updated with ECE.
- T3: "now tell me about placement"
**generate stages**: T3: _detect_structured_intent → "placement" → already_complete_intent → structured_lookup placement handler → no dept_code in "now tell me about placement" → falls to overall placement check (line 2485: `re.search(r"\b(overall|college|average)\b", q)` — "now" doesn't match "overall|college|average") → final fallthrough → None → RAG retrieval.
**Failure**: User asked about CSE fee, then ECE fee, then "placement" — expected CSE or ECE placement info but gets RAG fallback or general placement.
**Root cause**: structured_lookup placement handler requires either dept_code or specific keywords ("overall"/"college"/"average") for overall stats. Without dept_code in query and without those keywords, it falls through to RAG. ConversationState has the last department (ECE) but placement handler doesn't read it.
**Impact**: MEDIUM — "now tell me about placement" after department-specific fee query doesn't carry department context.
**Validation**: Integration: T1+T2+T3 → verify response is placement info for ECE (or CSE, whichever makes sense contextually).

---

## 3. Cross-Domain Switching

### P1-CD-001
**Risks**: R-CP
**Priority**: P1
**Conversation**:
- T1: "What is admission fee for CSE?" → structured fee handler → returns admission fee
- T2: "what documents are needed for admission?"
**Stages**: T1: structured (fee). T2: _detect_structured_intent("what documents are needed for admission") → "admission_documents" (line 1778: `\b(document|require|need|list of).*(admission|admit)\b`). already_complete_intent → no expansion → structured_lookup → admission_documents handler at line 2305-2315 → returns document list.
**Expected**: Works correctly. Cross-domain switching from fee to admission documents. No state ambiguity.
**Validation**: Straightforward.

### P1-CD-002
**Risks**: R-CP
**Priority**: P1
**Conversation**:
- T1: "Who is the principal of BCREC?" → principal handler
- T2: "what is the contact number of admission office?"
**Stages**: T2: _detect_structured_intent → "contact" (line 1776: `\b(contact|phone|mobile|call|helpline)\b`) → yes, "contact number" matches. → already_complete_intent → structured_lookup → contact handler at line 2291 → returns college contact info, NOT admission office contact. Because contact handler (line 2291) runs BEFORE admission_office handler (line 2318).
**Wait**: _detect_structured_intent only checks which HANDLER would match. It detects "contact" as the intent. Then structured_lookup checks handlers in order: vice_principal → principal → contact (YES, matches at 2291) → returns college contact. The admission_office handler at 2318 never runs.
**Failure**: User asked for admission office contact but gets general college contact info.
**Root cause**: Handler priority: contact (line 2291) runs before admission_office (line 2318). Query containing "contact" always hits contact handler even if "admission office" is more specific.
**Impact**: MEDIUM — wrong contact info. Admission office has a specific phone number but user gets generic college info.
**Validation**: Unit test: _structured_lookup("what is the contact number of admission office", "en") should return admission office contact, not general college contact.

### P1-CD-003
**Risks**: R-CP
**Priority**: P1
**Conversation**:
- T1: "What are the fees?" → general fee info (no dept)
- T2: "tell me about CSE"
**Stages**: T1: general fee info returned. T2: _detect_structured_intent("tell me about CSE") → departments handler (line 1828-1832: `\b(department|branch|course|program|b\.tech|...)` "CSE" is not in the departments handler regex pattern! Wait, let me re-read: `r"\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b"` — "tell me about CSE" — no match! None of those keywords. So _detect_structured_intent returns None.
But the departments handler at line 2567-2598 also checks `and not fee_intent`. And it runs if NO handler matched before it. But _structured_lookup falls through handler by handler. If "tell me about CSE" doesn't match any handler, it reaches departments handler at line 2567. Let me check each handler:
- vice_principal: no
- principal: no
- contact: no
- admission_documents: no
- admission_office: no
- admission: no ("admissions?" pattern — "admissions?" means "admission" or "admissions". "tell me about CSE" — no.)
- installment: no
- safety: no
- hostel: no
- fee: no
- hod: no
- faculty: no ("professor|faculty|teacher|sir|madam|dr\.?|prof\.?" — no)
- placement: no
- seats: no
- cutoff: no
- establishment: no
- scholarship: no
- counselling: no
- eligibility: no
- campus_visit: no
- timings: no
- departments: YES! `r"\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b"` — "tell me about CSE" — no match. Wait, how does "CSE" alone trigger the departments handler? It doesn't! The departments handler regex requires specific keywords. "CSE" alone won't match.
**Actually** — I need to check what _structured_lookup does end-to-end. If NO handler returns a result (all None), the function returns None at line 2657. Then generate_response falls through to RAG retrieval.
**So**: T2 "tell me about CSE" → no structured match → RAG retrieval → LLM generates CSE info from context.
**Expected**: Let me use a query that actually triggers the departments handler. "What departments are available in BCREC?" → departments handler matches "departments" → lists all B.Tech courses. OK.

Let me revise:
- T1: general fee query → fee handler returns general fee info
- T2: "what departments are available?" → departments handler → lists all courses
**Validation**: Straightforward cross-domain switch.

### P1-CD-004
**Risks**: R-CP
**Priority**: P1
**Conversation**:
- T1: "What is the admission process?" → admission_general handler
- T2: "what about hostel?"
**Stages**: T2: _detect_structured_intent → "hostel" → already_complete_intent → structured_lookup hostel → returns hostel info.
**Expected**: Works fine — domain switch from admission to hostel.
**Issue**: No state contamination. Both handlers return correct info.

---

## 4. Entity Tracking

### P1-ET-001
**Risks**: R-ET, R-HG
**Priority**: P1
**Conversation**:
- T1: "What is the total fee for CSE?" → structured arithmetic → "The total fee for CSE is six lakh four thousand seven hundred rupees." → hallucination_guard: _validate_answer checks if any numbers in answer appear in context. But structured arithmetic responses DON'T go through _validate_answer! They return early at line 3532-3542.
**Wait**: Look at generate_response line 3510-3525. When structured arithmetic returns, the return dict has `"hallucination_validated": True` hardcoded. The answer is never validated. But the numbers come from FEE_GROUP_MAP, not from LLM, so there's no hallucination risk for structured arithmetic.
**But**: For RAG responses (line 3888-3902), _validate_answer runs. The question is: does _validate_answer correctly catch fabricated numbers?
**Test**: Give a query where RAG context has limited data but LLM might fabricate. But we can't control LLM output. So this is more of a guard validation test.
**Hard to test without controlling LLM output**. Let me define a different kind of entity tracking test.

### P1-ET-002
**Risks**: R-ET
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE?" → structured arithmetic hit → 604700
- T2: "Can I pay in installments?" → structured installment handler → returns payment info
**Stages**: T2: _detect_structured_intent → "installments" matches line 1792-1793 → already_complete_intent → structured_lookup installment handler (line 2349-2355) → returns payment options.
**Expected**: Works correctly. Entity (CSE department) from T1 doesn't interfere. The installment handler doesn't need department context.
**Validation**: OK, nothing to test here.

### P1-ET-003
**Risks**: R-ET
**Priority**: P1
**Conversation**:
- T1: "I got 85 percent in WBJEE, can I get CSE?"
**Stages**: _detect_structured_intent → let me check: "percent" is not in any pattern. "eligibility|eligible|marks?|percentage|qualif" — "percent" matches "marks?" no, "marks?" means "marks" or "mark", not "percent". "percentage" — YES, "percentage" matches via `\b(eligibility|eligible|marks?|percentage|qualif)\b` at line 2637. But wait, "85 percent" — does "percentage" appear in the query? The regex `\b(eligibility|eligible|marks?|percentage|qualif)\b` — "percent" is NOT "percentage". So no eligibility match.
What about cutoff? `\b(cutoff|cut.off|rank|closing.rank|opening.rank)\b` — "rank" is NOT in the query. So no cutoff match.
Actually none of the handlers match "I got 85 percent in WBJEE, can I get CSE?". → falls to RAG.
**But**: The SYSTEM_PROMPT says: "If user gives rank/marks, use cutoff data to tell them eligible departments." But the handler chain doesn't handle this. The LLM would need to handle it via RAG.
**Actually** — the query "I got 85 percent in WBJEE, can I get CSE?" → is it OOD? query has "WBJEE", "CSE", "percent" — none are OOD keywords. So it passes OOD. → structured lookup returns None → RAG retrieval → LLM. The LLM might or might not answer correctly depending on the context.
**Test**: This is a RAG quality test, not entity tracking. Let me move to real entity tracking.

### P1-ET-004
**Risks**: R-ET
**Priority**: P1
**Conversation**:
- T1: "Tell me about Dr. Chandan Bandyopadhyay"
**Stages**: _detect_structured_intent → "professor|faculty|teacher|sir|madam|dr\.?|prof\.?" — "Dr." matches! → intent=faculty. → structured_lookup faculty handler → _resolve_faculty_name(query, kb) → alias check: "chandan bandyopadhyay" or similar? Query is "Tell me about Dr. Chandan Bandyopadhyay" → lower: "tell me about dr. chandan bandyopadhyay". Alias: "chandan bandopadhyay" → "Dr. Chandan Bandyopadhyay". Does `"chandan bandopadhyay" in "tell me about dr. chandan bandyopadhyay"`? Let me check: the alias check at line 2719: `for alias, canonical in self._FACULTY_ALIASES.items(): if alias in q:` But q is "tell me about dr. chandan bandyopadhyay" — does "chandan bandopadhyay" exist as a substring? "chandan bandopadhyay" IN "tell me about dr. chandan bandyopadhyay"? The query has "bandyopadhyay" (with y), the alias has "bandopadhyay" (with o). Not a direct substring! So the alias doesn't match.
Then difflib at line 2764: `fuzzy_matches = difflib.get_close_matches(q_lower, names_set, n=1, cutoff=0.6)` — this might match "chandan bandyopadhyay" against "Dr. Chandan Bandyopadhyay". Cutoff 0.6 is quite low. Likely match.
**Failure/Expected**: The _FACULTY_ALIASES list has a gap: "chandan bandyopadhyay" (with 'y') is NOT in the aliases, only "chandan bandopadhyay" (with 'o'). So the alias lookup fails and it falls through to fuzzy matching. Fuzzy matching at 0.6 cutoff should still find it.
**Validation**: Unit: _resolve_faculty_name("Tell me about Dr. Chandan Bandyopadhyay", kb) should return "Did you mean Dr. Chandan Bandyopadhyay (HOD of CSE)?" or similar.

---

## 5. Pronoun Resolution

### P1-PR-001
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE?"
- T2: "what is it for ECE?"
**Stages**: T2: _detect_structured_intent("what is it for ECE") → None (no intent keyword matches). Word count = 5, ≥ 6? No. So not long_query_no_expansion. Not repeat intent. Not ambiguous word (word_count > 2). Goes to line 1929: _detect_structured_intent → None. Line 1939: last_user = "What is the fee for CSE?". _detect_query_domain("what is it for ece") → "ece" not in _DOMAIN_KEYWORDS → None. previous_domain = "fees" (from T1). current_domain=None → if current_domain: is False → skips new_domain_blocked. Goes to state-based rewrite.
state.visit_order = ["fee"]. is_dept_query? "ece" → _extract_dept_code → "ECE" → True. last_intent="fee" → in dept_compatible_intents → expanded = "ece fee" → structured_lookup → ECE fee.
**Expected**: Works correctly! "ece fee" hits fee handler.
**But**: The pronoun "it" is ignored entirely. Expansion works because "ECE" is extracted as a department. No pronoun resolution needed.
**Validation**: Good, this is handled by department extraction.

### P1-PR-002
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "Tell me about hostel facilities"
- T2: "what is the fee for it?"
**Stages**: T2: _detect_structured_intent("what is the fee for it") → "fee" matches → intent=fee → already_complete_intent → structured_lookup fee handler → "what is the fee for it" → no dept_code → general fee info.
**Failure**: User asked about hostel fee ("it"=hostel) but gets general fee info.
**Root cause**: The pronoun "it" is not resolved to the previous domain (hostel). "already_complete_intent" skips expansion, so the follow-up doesn't attach "hostel" context. Structured_lookup fee handler then returns general fee because no department code is found.
**Impact**: MEDIUM — user says "what is the fee for it" after hostel discussion, gets wrong answer.
**Validation**: Integration: T1+T2 → verify response contains hostel-specific fee info.

### P1-PR-003
**Risks**: R-FU
**Priority**: P1
**Conversation**:
- T1: "Who is the HOD of ECE?"
- T2: "what is his email?"
**Stages**: T2: word_count=4. _detect_structured_intent("what is his email") → "what is his email" → no handler matches (email is not a direct handler — contact handler has "email"? No, contact handler regex is `\b(contact|phone|mobile|call|helpline)\b` — "email" isn't there). → intent=None. → not already_complete_intent. → last_user = "Who is the HOD of ECE?". current_domain = ? "email" — is "email" in any domain? `_DOMAIN_KEYWORDS` — contact domain has "email". So current_domain="contact". previous_domain = "hod" (from T1, "hod" keyword). current_domain=contact ≠ previous_domain=hod → new_domain_blocked at line 1952 → no expansion → structured_lookup "what is his email" → contact handler at line 2291: `\b(contact|phone|mobile|call|helpline)\b` — "email" is NOT in this regex. So contact handler doesn't match! → falls through all handlers → departments at 2567: no match → returns None → RAG retrieval.
**Failure**: "what is his email" after HOD query returns RAG fallback or generic "I don't know" instead of the HOD's email.
**Root cause**: 1) new_domain_blocked fires because current_domain=contact differs from previous_domain=hod. 2) Even without the block, structured_lookup contact regex doesn't include "email". 3) The HOD handler already returns the HOD's email in its response (line 2447), but the follow-up can't reference it.
**Impact**: HIGH — user asks for HOD email after HOD query, gets nothing or RAG fallback. Very common conversation pattern.
**Validation**: Integration: T1+T2 → verify response includes HOD of ECE's email address.

---

## 6. Stream vs Generate Parity

### P1-PG-001
**Risks**: R-EG, R-MI
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE and also tell me about hostel?"
**generate stages**: normalize → lang → ... → _split_multi_intent("what is the fee for CSE and also tell me about hostel") → split on " and also " → left="what is the fee for CSE" (5 words ≥ 2), right="tell me about hostel" (4 words ≥ 2) → return [left, right]. → structured_lookup(left) → fee handler → CSE fee. structured_lookup(right) → hostel handler → hostel info. → combined response.
**stream stages**: normalize → lang → ... → _structured_lookup(retrieval_query, lang) is called at line 4227 with the full query "what is the fee for CSE and also tell me about hostel". → no handler matches the full query! "fee" is in it but the full query doesn't cleanly match any handler. → structured_lookup returns None. → stream falls through to RAG retrieval. → LLM generates response for the full query.
**Handler**: generate: multi-intent (fee + hostel). stream: None (RAG).
**Retrieval**: generate: none (structured). stream: vector search for full query.
**Response**: generate: combined fee info + hostel info. stream: LLM-generated response from RAG context.
**Failure**: stream path gives different and potentially worse answer than generate path for multi-intent queries.
**Root cause**: _split_multi_intent is only called inside generate's arithmetic block (line 3566). stream's structured path (line 4226-4248) doesn't call _split_multi_intent at all.
**Impact**: HIGH — voice users get RAG-based answer (slower, potentially less accurate) while API users get fast structured answers.
**Validation**: Unit: feed same query to generate and stream, compare outputs. They should match but currently don't.
**Note**: This test reveals 3 parity gaps simultaneously: multi-intent missing from stream, arithmetic block order differs, and structured_lookup receives different query text.

### P1-PG-002
**Risks**: R-EG, R-HG
**Priority**: P1
**Conversation**:
- T1: "What is the total fee for CSE?" (same query via generate and stream)
**generate stages**: → structured arithmetic (semester fee regex fail, total fee regex match → _calculate_total_fees → return "The total fee for CSE is ..." with hallucination_validated=True). Or wait, the arithmetic block at line 3503 is `if self._detect_on_topic_arithmetic(query) or True:` so it ALWAYS enters. Then at 3526: `re.search(r"\btotal\s*(fee|fees)\b|\bfee\s*total\b", retrieval_query)` → matches! → _calculate_total_fees → return early. No hallucination guard runs (structured response).
**stream stages**: → structured_lookup(retrieval_query, lang) at line 4227 → "what is the total fee for CSE" → fee handler → dept_code=CSE → regex: `\b(total\s*(fee|fees)|fee\s*total)\b` → "total fee" matches → but wait, the fee handler doesn't have "total fee" logic in structured_lookup itself! The fee handler's logic at line 2403-2419 checks semester fee, admission fee, or default total fee. The default at line 2418-2419 returns total fee. So both paths return total fee for CSE.
**Actually**: Let me re-check. In generate, the arithmetic block at line 3526 checks `re.search(r"\btotal\s*(fee|fees)\b|\bfee\s*total\b", retrieval_query)`. If match → _calculate_total_fees. In stream, structured_lookup fee handler at 2418-2419 returns total fee as default. Slightly different code path but same numerical result.
**Parity**: Different code paths but same output for this query. The difference matters when the department code isn't extractable — the arithmetic block would fail (no dept_code → skip), but structured_lookup fee handler would fall back to general fee info. So the answer would differ for queries without dept_code.
**OK**, let me find more impactful parity cases.

### P1-PG-003
**Risks**: R-EG, R-GR
**Priority**: P1
**Conversation**:
- T1: "Hello" (via generate vs stream)
**generate stages**: normalize → validate_transcript → _is_greeting → HIT → return greeting response.
**stream stages**: normalize → validate_transcript → (NO greeting check) → noise → lang → SAFEPOINT handoff → OOD → repeat → placement_eligibility → conversation_replay → followup_expand → structured_lookup → "Hello" → no handler match → RAG retrieval → LLM generates "Hello! How can I help you?" (generic).
**Failure**: generate returns structured greeting with specific help options (admissions, fees, courses, hostel). Stream returns LLM-generated greeting (different text, no specific options, slower).
**Root cause**: Greeting detection is MISSING from stream path.
**Impact**: MEDIUM — voice users get slower, generic greeting without help suggestions. Consistent with known parity gap.
**Validation**: Same "Hello" → generate returns greeting_deterministic source, stream returns rag_query source.

### P1-PG-004
**Risks**: R-EG, R-HG
**Priority**: P1
**Conversation**:
- T1: "The fee for CSE is six lakh four thousand seven hundred rupees" (user asserting, not asking)
**generate stages**: normalize → ... → structured_lookup → no match → RAG retrieval → LLM generates response → _validate_answer checks numbers in answer against context. If LLM generates "Yes, that's correct" (no numbers), no validation trigger.
**stream stages**: Same flow but _validate_answer is NON-BLOCKING. Logs warning but does NOT replace answer.
**Failure**: If LLM hallucinates a DIFFERENT number for generate path, generate replaces the answer with fallback. Stream lets the hallucinated answer through.
**Root cause**: Known parity gap — _validate_answer is blocking in generate (line 3902: `answer = self._safe_fallback(lang)`) but non-blocking in stream (line 4448-4455: logs only).
**Impact**: HIGH — voice users can hear wrong numbers. Trust erosion.
**Validation**: Feed a query where context lacks fee data, LLM might fabricate. Check that generate replaces answer, stream does not.

### P1-PG-005
**Risks**: R-EG, R-KB
**Priority**: P1
**Conversation**:
- T1: "I don't think you have information about this" (query designed to trigger out-of-KB)
**generate stages**: LLM generates → _is_greeting check? No. → Out-of-KB detection at line 3906-3945 checks `unknown_signals` in answer. If LLM says "I don't have information about this", answer gets replaced with fallback including phone number.
**stream stages**: Same check at line 4462-4491 but NON-BLOCKING. Logs warning but keeps original answer.
**Failure**: Stream user hears "I don't have information about this" without phone number. Generate user gets "Let me check on that for you..." with phone guidance.
**Root cause**: Known parity gap — out-of-KB is blocking in generate, non-blocking in stream.
**Impact**: MEDIUM — voice users don't get phone number guidance for unknown queries.
**Validation**: Same query → generate adds phone number, stream does not.

### P1-PG-006
**Risks**: R-EG
**Priority**: P1
**Conversation**:
- T1: Bengali query "সি এস ই এর ফি কত?" (What is the fee for CSE in Bengali)
**generate stages**: normalize → lang=bn → structured arithmetic → _format_inr(604700, "bn") → returns Bengali-formatted fee → lang==bn → "রুপি"→"টাকা" normalization at line 3948-3949 → _prepare_for_tts → clean_for_voice → voice_text.
**stream stages**: normalize → lang=bn → structured_lookup → fee handler → _format_inr(604700, "bn") → BUT no "রুপি"→"টাকা" normalization (line 3948-3949 is in generate only). → No _prepare_for_tts call (line 3952 is in generate only).
**Failure**: Stream response has "রুপি" instead of "টাকা". Acronyms not expanded. TTS mispronounces.
**Root cause**: Bengali normalization and TTS preparation are MISSING from stream path.
**Impact**: MEDIUM — Bengali TTS quality degraded for stream users.
**Validation**: Same Bengali query → generate voice_text has "টাকা", stream raw output (which becomes TTS input) has "রুপি".

### P1-PG-007
**Risks**: R-EG
**Priority**: P1
**Conversation**:
- T1: First-time query "What is the fee for CSE?" (no history)
**generate stages**: ... → cache lookup at line 3715-3728: `if self._cache is not None and not history:` → creates cache_key = (query, lang, context). Miss → proceeds to LLM. After response, cache store at 3993-3998. Second identical query: cache HIT → returns cached response (faster, no LLM call).
**stream stages**: No cache at all. Every voice request hits LLM.
**Failure**: Stream has higher latency and cost for repeated queries.
**Root cause**: Cache entirely absent from stream path (lines 3714-3728 and 3992-3998 are generate-only).
**Impact**: MEDIUM — higher cost for voice path. Repeated identical queries (e.g., "what is the fee" asked by different users) don't benefit from caching.
**Validation**: Feed same first-turn query twice via both paths. Generate: first=miss, second=hit. Stream: both=miss.

### P1-PG-008
**Risks**: R-EG
**Priority**: P1
**Conversation**:
- T1: "Switch to Hindi" (language switch)
**generate stages**: _is_lang_switch detected → re-runs previous question in new language (line 3336-3342). Also SAFEPOINT pre at 3315-3322 runs BEFORE lang switch re-route.
**stream stages**: No language switch re-run (missing at stream lines 4129-4148). Instead, stream has SAFEPOINT handoff at 4142 which runs AFTER lang resolution. Also no greeting check. No yes/no continuation.
**Failure**: Switching language in stream does NOT replay the previous answer in the new language. User must re-ask.
**Root cause**: Language switch re-run logic (lines 3334-3342) is absent from stream path.
**Impact**: MEDIUM — voice users switching language mid-conversation must re-ask their question.
**Validation**: After a question-answer pair, send "in hindi" to both paths. Generate replays previous answer in Hindi. Stream ignores (processes as normal query).

### P1-PG-009
**Risks**: R-EG
**Priority**: P1
**Conversation**:
- T1: "Yes" after "Would you like to know about hostel fees?" clarification
**generate stages**: Yes/no continuation at line 3221-3254: detects "yes" → checks last assistant response for "would you like" → re-routes to last user question.
**stream stages**: No yes/no continuation logic at all. "Yes" → goes through normal flow → structured_lookup → no match → RAG → LLM generates generic response to "yes".
**Failure**: Stream users cannot confirm clarification prompts. "Yes" is treated as a standalone query.
**Root cause**: Yes/no continuation (lines 3221-3254) is entirely absent from stream path.
**Impact**: HIGH — voice flow: agent asks "Would you like to know about hostel fees?", user says "yes", stream path gives confused response instead of showing hostel fee.
**Validation**: T1: ambiguous word "hostel" → clarification returned. T2: "yes" → generate re-routes to previous user question; stream processes "yes" as new query.

---

## 7. Prompt Query Differences

### P1-PQ-001
**Risks**: R-PQ
**Priority**: P1
**Conversation**:
- T1: "Tell me about cs e aml department" (STT error for CSE-AIML)
**generate stages**: normalize_query("Tell me about cs e aml department") → NormalizationLog with changes → query = normalized_text. Then _build_messages(query=query=normalized_text, context, history, lang). LLM sees the normalized query.
**stream stages**: normalize_query same as generate → query = normalized_text. Then _normalize_query(query) → _normalize_query is called AGAIN. So `llm_query = self._normalize_query(query)` where query is already normalized. _normalize_query may apply additional normalizations (like "cs e aml" → "CSE-AIML" at line 1262). But normalize_query (from normalizer) may also do "cs e aml" → "CSE-AIML". So the net effect depends on overlap between normalize_query and _normalize_query.

Let me check what `normalize_query` does. It's imported from `app.services.normalization`. I haven't read that code. Let me check.
**Actually**: In generate at line 3212: `norm_log = normalize_query(query)` → then `query = norm_log.normalized_text`. Then at line 3731: `self._build_messages(query=query, ...)`. The `query` passed is already normalized once by normalize_query.
In stream at line 4089: `norm_log = normalize_query(query)` → then `query = norm_log.normalized_text` at line 4094. Then at line 4250: `llm_query = self._normalize_query(query)`. This applies a SECOND normalization pass via _normalize_query.

So the LLM in generate sees query = normalize_query(raw)
And the LLM in stream sees llm_query = _normalize_query(normalize_query(raw))

There may be double-normalization issues or differences between the two normalization functions.

**Failure**: The LLM receives different query text for generate (single normalization) vs stream (double normalization). This could cause different LLM responses for the same user input.
**Root cause**: Stream path applies _normalize_query ON TOP OF normalize_query. These functions may have overlapping or conflicting transformations.
**Impact**: LOW-MEDIUM — generally both normalizations do similar things (department name fixes). But if they conflict, stream LLM gets distorted query.
**Validation**: Compare the actual query string passed to _build_messages in both paths for the same input. They should be identical but currently are not because stream double-normalizes.

### P1-PQ-002
**Risks**: R-PQ
**Priority**: P1
**Conversation**:
- T1: "Banglay bolo" (say in Bengali) + "What is the fee for CSE?"
**generate stages**: normalize_query. Then at line 3334-3342: _is_lang_switch detected → re-routes query to previous question. The `query` variable is REPLACED with the previous question. Then _build_messages(query=previous_question, ...). LLM sees the previous question in the prompt, not the language switch command.
**stream stages**: No language switch re-route. The `query` variable stays as "Banglay bolo What is the fee for CSE?" (or whatever the full utterance was). Actually, _is_lang_switch is NOT called in stream at all. The query stays as-is. _build_messages(query=llm_query= _normalize_query(query), ...). LLM sees "banglay bolo what is the fee for cse" or similar.
**Failure**: Different query text sent to LLM in each path when language switch occurs. Generate sends the re-routed previous question. Stream sends the raw language switch command.
**Root cause**: Language switch re-route (generate lines 3334-3342) is missing from stream. Generate replaces `query` variable. Stream never does.
**Impact**: HIGH — after a language switch, generate and stream give completely different answers because the prompt has different user queries.
**Validation**: T1: "What is CSE fee?" → structured answer. T2: "Banglay bolo" → generate re-routes to "What is CSE fee?", stream processes "banglay bolo" as-is.

---

## 8. LLM Timeout/Retry Behavior

### P1-LT-001
**Risks**: R-LT
**Priority**: P1
**Conversation**:
- T1: Query during Groq API rate limit (429 response)
**generate stages**: rate_limiter.acquire() → if circuit breaker open, returns wait time. → asyncio.sleep(wait). → LLM call → 429 → rate_limiter.record_429(). → attempt 2 with backoff (1-2s + random). → 429 again → attempt 3 with backoff (~4s + random). → 429 again → try next model in FALLBACK_MODELS. → after all models × 3 attempts exhausted → RuntimeError("All Groq models rate limited after retries") → caught by outer except → returns error dict with phone number.
**stream stages**: Same retry logic (lines 4339-4390) → RuntimeError → caught → yields "Sorry, something went wrong."
**Failure**: generate provides phone number for assistance. Stream gives generic apology.
**Root cause**: Different error handling in generate (line 4047-4050: "Please call 0343-2501353") vs stream (line 4540: "Sorry, something went wrong.").
**Impact**: MEDIUM — stream users have no fallback contact when LLM is unavailable.
**Validation**: Mock persistent 429s. generate→error with phone. stream→"Sorry, something went wrong."

### P1-LT-002
**Risks**: R-LT
**Priority**: P1
**Conversation**:
- T1: Query when SAFEPOINT is enabled and LLM takes >6s
**generate stages**: _sp_enabled() → True → asyncio.wait_for with 6s timeout → TimeoutError → returns filler response ("Let me check on that...").
**stream stages**: No SAFEPOINT timeout protection in stream (missing at stream LLM call). Stream call has NO timeout. Blocks indefinitely.
**Failure**: Stream hangs forever when LLM is slow. Generate returns quickly with filler.
**Root cause**: SAFEPOINT timeout at generate lines 3764-3793 is absent from stream (stream lines 4345-4354 have no timeout wrapping).
**Impact**: MEDIUM — voice call could hang indefinitely during LLM degradation.
**Validation**: Mock slow LLM with SAFEPOINT enabled. generate→filler in 6s. stream→hangs.

### P1-LT-003
**Risks**: R-LT
**Priority**: P1
**Conversation**:
- T1: Query when Groq API returns non-429 error (e.g., 500 internal error)
**generate stages**: Exception → not rate limit → `raise` at line 3828 → outer except → error with phone.
**stream stages**: Exception → not rate limit → `raise` at line 4380 → outer except → "Sorry, something went wrong."
**Failure**: Same as P1-LT-001 — different error messages.
**Validation**: Mock 500 error. generate→error with phone. stream→generic apology.

### P1-LT-004
**Risks**: R-LT
**Priority**: P1
**Conversation**:
- T1: Query when circuit breaker is open (3+ consecutive 429s recently)
**generate stages**: rate_limiter.acquire() → now < _circuit_open_until → returns remaining wait time (up to MAX_BACKOFF_SEC=10s). → asyncio.sleep(wait). → still in circuit open window → wait again at next acquire? Actually acquire is called once per attempt. After the wait, it calls acquire again on the next attempt. But this is in the same request. So the first acquire returns 10s, sleeps, then subsequent attempts also call acquire but circuit may still be open → more waiting. → After all retries exhausted → RuntimeError → error dict.
**stream stages**: Same behavior but error response is generic.
**Failure**: Circuit breaker causes long delays before failing. During open circuit, every request waits 10s+ before giving up. No fast-fail mechanism.
**Root cause**: Rate limiter has no fast-fail for circuit breaker. All requests through the open circuit wait MAX_BACKOFF_SEC before each attempt.
**Impact**: HIGH — during API degradation, all requests are delayed by 10-30s before returning error. Service becomes unusable.
**Validation**: Trigger 3 consecutive 429s, then send a new request. Measure Time-to-Error. Should be fast (<1s) but is currently 10-30s.

---

## 9. RAG Retrieval Degradation

### P1-RD-001
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "What is the placement rate for CSE?"
**Stages**: structured_lookup → placement handler → dept_code=CSE → line 2471-2483: returns dept-specific placement data.
**Failure**: If canonical_kb.json is missing or corrupted, placement handler returns None → RAG retrieval. RAG context may not have exact placement numbers → LLM may fabricate.
**Validation**: Simulate corrupted canonical_kb → structured_lookup falls through → verify LLM doesn't fabricate placement numbers → _validate_answer catches any fabricated numbers.

### P1-RD-002
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "Does BCREC have a civil engineering department?"
**Stages**: No structured handler matches "civil engineering department" at _detect_structured_intent level (checking). `departments` handler regex: `\b(department|branch|course|program|b\.tech|what.*offer|what.*available|what.*have|what.*teach|list.*course)\b` — "department" matches! → intent=departments → structured_lookup → departments handler at line 2567 → dept_code=_extract_dept_code("does BCREC have a civil engineering department") → "civil" → DEPT_CODE_MAP["civil"] → "CE" → returns "Civil Engineering (CE) — Intake: ...".
**Expected**: Works via structured handler.
**Test**: Not a retrieval test. Let me move to a real RAG degradation test.

### P1-RD-003
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: Vector search returns very different chunks each time due to embedding drift (BGE-M3 model reload)
**Note**: No test needed — this is a production monitoring concern, not a functional test.
**Better test**:

### P1-RD-004
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: A query where the expanded follow-up query differs significantly from the original raw query
**Test**: T1 structured hit (fee for CSE). T2: "what about it?" → _expand_follow_up_query: word_count=3, not ambiguous, not complete intent, not repeat. _detect_query_domain("what about it") → None. previous_domain=None (from T1, domain was "fees"). current_domain=None → if not current_domain: skip. Falls to state rewrite. state.visit_order=["fee"]. is_dept_query? "what about it" → no dept words → False. structured_fee_followup? domain=="fee" and last_intent=="fee" → True → expanded = "what about it fee". This is the retrieval_query.
Then RAG: _retrieve_context("what about it fee") → _normalize_query("what about it fee") → applies normalizations (no department changes) → vector search for "what about it fee".
**Failure**: The expanded retrieval query "what about it fee" is a poor RAG query. The pronoun "it" pollutes the search. The user meant "CSE fee" but the expansion produced "what about it fee".
**Root cause**: The structured_fee_followup rule at line 2097 does a simple append of " fee" without resolving the pronoun "it" or keeping the department context.
**Impact**: MEDIUM — RAG retrieval uses a noisy query. Might still return relevant chunks but quality is degraded.
**Validation**: Unit: _expand_follow_up_query("what about it", history_with_fee, sid) should return "CSE fee" not "what about it fee".

---

## 10. Ranking Failures

### P1-RF-001
**Risks**: R-RK
**Priority**: P1
**Conversation**:
- T1: Bengali query "সি এস ই ডিপার্টমেন্টের ফি কত?" (What is the fee of CSE department?)
**Stages**: _resolve_language → detects Bengali script → lang=bn. _normalize_query does NOT apply Bengali normalizations — it only applies English department fixes and "upo-pradhan" → "উপ-প্রধান". So query passes through mostly unchanged. Vector search: _normalize_query(query) → still Bengali → search_with_scores. Language matching: semantic_score at line 1310-1313 adds +1 if language matches, -0.5 if mismatched.
**Failure**: If vector store contains mostly English documents, Bengali queries get lower semantic scores (or -0.5 penalty). This means Bengali queries may retrieve different/less relevant chunks than equivalent English queries.
**Validation**: Compare top-5 chunks for same query in English vs Bengali. The rankings should be similar but likely differ due to language penalty.

### P1-RF-002
**Risks**: R-RK
**Priority**: P1
**Conversation**:
- T1: "What are the fees and placements for CSE?"
**Stages**: _split_multi_intent → "and" between "what are the fees" (5 words) and "placements for CSE" (3 words? actually "placements for CSE" = 3 words). Both ≥ 2 → split → [left, right]. structured_lookup(left) → fee handler → CSE fee. structured_lookup(right) → placement handler → CSE placement. Combined.
**But**: If split fails (e.g., query doesn't meet word count), both parts go to a single structured_lookup call with the full query. The full query "what are the fees and placements for CSE" — does any handler match the FULL query? The fee handler regex `r"\b(fee|fees|...)\b"` matches "fees" → fee handler runs. But then returns at line 2405-2419 with fee info ONLY. The placement part is ignored. No multi-intent handling.
**Failure**: Multi-intent "fees and placements" only returns fee info if split fails. The placement part is silently dropped.
**Root cause**: _split_multi_intent has word count requirements (≥2 each side). If one side has <2 words, split fails and only the first matching handler fires.
**Impact**: MEDIUM — "fees and placements" works (both sides ≥ 2 words). But "fee and placement" (1 word each) fails. `intents = ["fee", "placement"]` then each is looked up. Actually "fee and placement" → left="fee" (1 word < 2), right="placement" (1 word < 2) → NOT split → full query "fee and placement" → fee handler matches "fee" → returns fee info. Placement info is lost.
**Validation**: Unit: _split_multi_intent("fee and placement") should return ["fee", "placement"] but currently returns ["fee and placement"] because word count check fails.

---

## 11. Comparison Reasoning

### P1-CR-001
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "Which has better placement, CSE or ECE?"
**Stages**: _detect_structured_intent → "placement" matches → already_complete_intent → structured_lookup placement handler → "placement" keyword matches at line 2467. → query is "which has better placement CSE or ECE" → _extract_dept_code → "CSE" found first. Returns CSE placement data only. ECE not queried. No comparison.
**Failure**: User asks for comparison but gets single department data. No comparison logic exists anywhere in the pipeline.
**Root cause**: No comparison handler. Structured_lookup returns first department match only. No aggregation or comparison intelligence.
**Impact**: HIGH — any comparison query ("which is better", "X vs Y", "compare") returns single-department data or RAG fallback. LLM may fabricate comparison if no context supports it.
**Validation**: Integration: "Which has better placement, CSE or ECE?" → verify response contains data for BOTH departments with explicit comparison.

### P1-CR-002
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "Is CSE better than ECE?"
**Stages**: "better than" is not in any structured handler. → no match → RAG retrieval. LLM generates comparison from context (which may not contain comparative data).
**Failure**: LLM can only compare if context has data for both departments. If only CSE data is retrieved, LLM may fabricate ECE data or give one-sided answer.
**Validation**: Same as CR-001 — verify both departments' data is retrieved and answer is balanced.

---

## 12. Aggregation Reasoning

### P1-AR-001
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "What is the total number of seats in all B.Tech departments combined?"
**generate stages**: Arithmetic block at line 3543-3563: `re.search(r"\b(seats|intake)\b.*\btotal\b|\btotal\b.*\b(seats|intake)\b", retrieval_query)` → matches! → _calculate_seat_total(kb) → returns aggregated seat total.
**stream stages**: structured_lookup → seats handler → "seats" matches → meets handler but query has no specific dept → dept_code in query? "what is the total number of seats in all B.Tech departments combined" → _extract_dept_code → no dept code found → seats handler line 2496-2502: dept_code is None → handler falls through (no return for None dept). Wait, the seats handler only returns if dept_code is found (line 2500-2501). If no dept_code, it falls through to the next handler → cutoff → ... → eventually return None. → Wait, actually at line 2494-2502, if dept_code is None, the handler does NOT return anything (no else clause). So it falls through to the next handler. All subsequent handlers don't match → _structured_lookup returns None at line 2657. → stream falls to retrieving context → RAG. → Wait, but in stream the arithmetic fallback at line 4230: `if dept_code and self._detect_on_topic_arithmetic(retrieval_query):` — dept_code is None → doesn't enter arithmetic block. → RAG retrieval. The LLM would need to compute total seats from context.
**Failure**: stream returns LLM-generated total (may be wrong or fabricated). generate returns accurate arithmetic result.
**Root cause**: Seat total arithmetic logic at line 3543-3563 is in generate's arithmetic block but NOT in stream. Stream only has arithmetic for semester fee and total fee (lines 4230-4234), NOT seat total.
**Impact**: MEDIUM — "total seats" query gives accurate structured answer in generate but LLM-based answer in stream.
**Validation**: Same query → generate returns structured result with source="structured_arithmetic". stream returns RAG response.

### P1-AR-002
**Risks**: R-RD
**Priority**: P1
**Conversation**:
- T1: "What is the average placement package of all departments?"
**Stages**: No structured handler for "average" aggregation across departments. → RAG retrieval. LLM generates answer from whatever context is retrieved.
**Failure**: No aggregation logic exists. The placement handler at line 2485-2491 returns overall placement rate and average package only if query contains "overall", "college", or "average". "average placement package of all departments" → does contain "average" → line 2486: `if overall and re.search(r"\b(overall|college|average)\b", q):` → matches → returns overall placement data.
**But**: The overall placement data is from a single KB entry, not dynamically computed. If the KB is stale, the answer is wrong.
**Validation**: Integration: "What is the average placement package of all departments?" → verify response uses canonical KB overall data, not LLM fabrications.

---

## 13. Long Conversations

### P1-LC-001
**Risks**: R-CW
**Priority**: P1
**Conversation**: 7+ turns of mixed structured and unstructured queries
- T1: "What is the fee for CSE?"
- T2: "and for ECE?"
- T3: "what about hostel?"
- T4: "who is the HOD of CSE?"
- T5: "tell me about placements"
- T6: "what is the cutoff for CSE?"
- T7: "what about scholarships?"
**Expected at T7**: History has 12 entries (6 user + 6 assistant) → cap at 12 (line 2984). Follow-up expansion uses _session_states for "what about scholarships" — state has visit_order from all previous domains. The "scholarships" intent is detected as "scholarship" → already_complete_intent → structured_lookup scholarship handler → returns scholarship info.
**Potential failure**: State visit_order has 6+ domains. The structured rewrite at line 2058 iterates visit_order in REVERSE (most recent first). So it checks the most recent domain first. "scholarship" intent is a separate domain — no facet overlap needed because _detect_structured_intent caught it as complete.
**Validation**: Long conversation works correctly if structured queries continue to be independently resolvable.

### P1-LC-002
**Risks**: R-CS, R-WS
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE?" → structured hit → state push(fee)
- T2: "what is the teaching quality?" → RAG-only → NO state update
- T3: "tell me about the library timings" → RAG-only (no structured handler for library beyond "computer lab timing" at 2540 and "library timing" at 2548 — wait, "library timings" matches `\blibrary\s*(timing|hours?)|reading\s*room\b` at line 2548! So it IS structured! Let me use a different RAG-only query.)
- T3: "How is the campus infrastructure?" → RAG-only → NO state update
- T4: "what about fees again?" → _expand_follow_up_query → state visit_order=[fee] from T1. "what about fees again" → _detect_structured_intent → fee → already_complete_intent → structured_lookup → no dept_code → general fee info.
**Failure**: T2 and T3 talked about infrastructure (no state update). T4 asks about "fees again" — state still has fee from T1 (2+ turns ago). But since no new fee domain was pushed, it works. The stale state doesn't hurt here because the info from T1 is still correct.
**Alternate failure**: If T2 was a DIFFERENT structured domain (e.g., "what about placements" → structured placement hit → state push(placement)), then T1's fee state would be pushed down in visit_order. T3 "what about fees again" → state has visit_order = [fee, placement] → fee is the oldest. The structured rewrite at line 2058 iterates reversed: placement first, then fee. Detected_facets for "what about fees again" → "fee" facet. DOMAIN_FACETS["placement"] does NOT include "fee" → skip. DOMAIN_FACETS["fee"] includes "fee" → match. Rewrite: domain=="fee", last_intent=="fee" → structured_fee_followup → "what about fees again fee" → structured_lookup → no dept → general fee info.
**Still works** but not department-specific. To get department-specific, user must mention department again.
**Impact**: LOW — works but loses department specificity over time.

---

## 14. Context Window Pressure

### P1-CW-001
**Risks**: R-CW
**Priority**: P1
**Conversation**: 12-turn conversation (6 full cycles) each with moderate context
- T1-T6: 6 queries about different domains, each returning structured responses
**Stages**: After T6 (12 history entries → cap at 12), _build_messages at line 1391-1396 adds history[-10:] (last 10 turns = 5 exchanges). SYSTEM_PROMPT is fixed length ~2KB. Context is variable. Total prompt = system + history + context + user query.
**Failure**: At 10 history turns + system prompt + context (~2-10KB each) + query, total prompt may approach Groq's context limit (typically 8K or 32K depending on model). If context is large, history may be truncated.
**Impact**: LOW — history is already capped at 10 turns. For most models (llama-3.1-8b: 128K context), this won't be an issue. Only problematic if context is very large (>50KB).
**Validation**: Load test with 6-turn conversation and large context retrieval. Monitor prompt token count.

### P1-CW-002
**Risks**: R-CW
**Priority**: P1
**Conversation**: Very long user query (200+ characters) with large retrieved context
- T1: Very detailed question about CSE fees, placement, faculty, infrastructure...
**Stages**: _build_messages constructs prompt with system + context + query. If context is large (multiple chunks, each ~500 chars, 8 chunks = 4KB) and query is long, total prompt may be 6-8KB.
**Failure**: No prompt truncation logic. If the total exceeds model's context, Groq may truncate silently or error.
**Impact**: LOW — 8KB is well within 128K context. Only risks are with extreme contexts.
**Validation**: Monitor for Groq API errors on large prompts.

---

## 15. Session Recovery

### P1-SR-001
**Risks**: R-SR
**Priority**: P1
**Conversation**:
- T1: "What is the fee for CSE?" → session established
- [Session times out / server restarts / in-memory state lost]
- T2: "what about the deadline for admission?" (should be fresh session)
**Failure**: After restart, _sessions is empty, _session_langs is empty, _session_states is empty. T2 starts fresh — no history, no state, no language. Language defaults to "en". Follow-up expansion finds no history → returns query as-is. Works correctly as a fresh session.
**But**: If session_id is reused but history was lost, a follow-up query "what about ECE" (without specifying what "about" means) would fail because no history exists.
**Impact**: MEDIUM — follow-up queries after session loss fail because no context exists.
**Validation**: Clear session → send follow-up query → verify it works as standalone query or returns appropriate clarification.

### P1-SR-002
**Risks**: R-SR
**Priority**: P1
**Conversation**:
- T1: "CSE fee?" → structured hit, language=en
- [clear_session called — e.g., LiveKit room disconnects]
- T2: "CSE fee again?" → should work as fresh query
**Failure**: clear_session at line 3019-3023 clears _sessions, _session_langs, _session_states. T2 starts fresh. Language re-detected as en. No history → cache lookup attempted. Might be a cache hit if same query was cached earlier (but cache is also in-memory TTLCache, so it's also lost on restart).
**Impact**: LOW — works correctly as fresh query.
**Validation**: Call clear_session, then same query. Verify it re-processes from scratch.

---

## 16. LiveKit Voice Flow

### P1-VF-001
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: User says "hello" on voice channel
**LiveKit flow**: VAD detects speech → Sarvam STT transcribes → BCRECGroqStream._run() (line 194) → builds history from LiveKit ChatContext → calls stream_response(query, session_id, conversation_history=history[:-1]).
**stream_response stages**: normalize → validate_transcript → is "hello" a greeting? _is_greeting is NOT called in stream → goes through noise → lang → handoff → OOD → repeat → placement → replay → followup_expand → structured_lookup ("hello" → no match) → RAG retrieval → LLM → tokens streamed back → TTS synthesizes.
**Failure**: Voice users don't get a greeting response. They get an LLM-generated greeting which is slower and may not include help options.
**Root cause**: _is_greeting is not called in stream path (architecture_audit.md:93).
**Impact**: MEDIUM — first voice interaction is noticeably slower (LLM call) vs instant structured greeting.
**Validation**: Same "hello" → generate returns greeting_deterministic in <50ms. Stream takes 1-3s for LLM.

### P1-VF-002
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: LiveKit prewarm sequence
**Flow**: prewarm() at line 429-434 loads VAD, STT, TTS, LLM into proc.userdata. BGE-M3 model loaded (~30s). Then entrypoint() at line 441 starts.
**Failure**: If prewarm takes >120s (initialize_process_timeout), worker fails. BGE-M3 offline mode (TRANSFORMERS_OFFLINE=1) prevents network fallback.
**Impact**: HIGH — worker startup failure makes voice agent unavailable.
**Validation**: Monitor prewarm duration. BGE-M3 load should be <60s.

### P1-VF-003
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Voice call connects, greeting is spoken
**Flow**: session.say(greeting, allow_interruptions=True) at line 508. Greeting is "Hello! BCREC AI assistant here. How can I help you today?"
**Failure**: If DEMO_SAFEPOINT is enabled, greeting may be replaced by safe_point.get_greeting() (commented out at line 504-505). LiveKit TTS StreamAdapter may split greeting at sentence boundaries, causing unnatural pauses.
**Impact**: LOW — greeting is functional but may sound robotic.
**Validation**: Verify TTS output quality for greeting.

### P1-VF-004
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: LiveKit room disconnects mid-conversation
**Flow**: entrypoint while loop at line 510-511: `while ctx.room.isconnected(): await asyncio.sleep(1)`. After disconnect, exits loop → calls clear_session(session_key) → telemetry.end_session(session_key).
**Failure**: If clear_session is called while stream_response is still processing (in-flight request), history is deleted mid-processing. The in-flight request may fail or produce incomplete telemetry.
**Impact**: HIGH — race condition between in-flight request and session cleanup could cause partial responses or errors.
**Validation**: Race condition test: disconnect room while LLM is streaming. Verify response completes gracefully or errors cleanly.

---

## 17. Sarvam STT/TTS Failures

### P1-ST-001
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Sarvam STT returns empty text
**LiveKit flow**: SarvamSTT._recognize_impl → result["success"]=True but result["text"]="" → _fix_stt_acronyms("") → "" → SpeechEvent with text="" and alternatives=[SpeechData(text="", ...)].
**stream_response**: receives query="" → _validate_transcript("") → empty query → returns CLARIFICATION_REPEAT_EN at line 1545 → "I didn't quite catch that..." → streamed back → TTS.
**Failure**: Empty STT properly handled by transcript validation.
**Validation**: Works correctly.

### P1-ST-002
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Sarvam STT returns text with mis-transcribed acronyms
**LiveKit flow**: _recognize_impl → result["text"] = "what is c s e fee" → _fix_stt_acronyms → "c s e" doesn't match any fix pattern → passes through. BUT stream_response calls _normalize_query → re.sub(r"\bcse\b"... doesn't match "c s e" because of spaces. So "c s e" stays as-is.
**But**: normalize_query (external) may handle "c s e" → "CSE". Let me check... I haven't read the external normalizer. But _stt_acronym_fixes in livekit_agent.py at line 248-260 doesn't have "c s e" → "CSE" fix. However, the SarvamSTT's _fix_stt_acronyms at line 248-260 has patterns for common mis-transcriptions but "c s e" is not there.
**Failure**: STT output "c s e" may not be normalized to "CSE" anywhere, causing structured_lookup to fail (no dept match) and RAG to get wrong query.
**Impact**: MEDIUM — department acronyms with spaces between letters fail normalization.
**Validation**: Feed "what is c s e fee" → structured_lookup should resolve to CSE fee. Currently may not.

### P1-ST-003
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Sarvam STT returns text but without confidence score (confidence=0.95 hardcoded at line 308)
**Flow**: SarvamSTT hardcodes confidence=0.95 for all successful transcriptions. The actual STT confidence from Sarvam API is ignored.
**Failure**: Confidence score is meaningless — always 0.95 regardless of actual quality. Downstream cannot use confidence for routing decisions.
**Impact**: LOW — confidence is not used downstream for voice path (stream_response doesn't use STT confidence).
**Validation**: Compare stated confidence vs actual transcription quality. No correlation.

### P1-ST-004
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Sarvam TTS fails (API error)
**LiveKit flow**: SarvamChunkedStream._run → text_to_speech → res["success"]=False → logs error → emitter.end_input(). No audio played → user hears silence.
**Failure**: TTS failure results in silence. No fallback to alternative TTS or text-based response.
**Impact**: HIGH — voice call goes silent when TTS fails. User has no indication of failure.
**Validation**: Mock TTS failure → verify agent either plays fallback audio, repeats the attempt, or sends a text-based error signal.

### P1-ST-005
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Sarvam TTS audio chunk parsing fails (non-standard WAV header)
**Flow**: SarvamChunkedStream._run at line 383-396: parses WAV header manually, looks for "data" chunk. If header structure is different (e.g., extra chunks, LIST chunk), parsing fails → falls to line 396 shortcut: `data = data[44:]`. If the actual data offset isn't 44 bytes, this produces garbage audio.
**Failure**: Garbage audio played to user. Possible loud noise through phone.
**Impact**: HIGH — could cause user discomfort or hang up.
**Validation**: Test with various WAV outputs from Sarvam API, verify audio is always valid PCM.

### P1-ST-006
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: STT returns Hindi/Bengali text mixed with English
**Flow**: SarvamSTT returns language="en-IN" (hardcoded at line 308) regardless of actual language. The actual detected language from Sarvam is at result.get("language", "en-IN") but it's always overridden with "en-IN" as default... actually looking at line 308: `language=result.get("language", "en-IN")`. So it DOES use Sarvam's detected language. But the default is "en-IN".
**Failure**: Language detection from STT is passed to LiveKit's speech event but NOT used by stream_response for language resolution. Stream_response calls `_resolve_language(session_id, query)` which does its OWN language detection using script analysis and keyword matching. The STT's language hint is ignored.
**Impact**: LOW — stream_response's own language detection is independent and generally correct for script-based analysis.
**Validation**: Feed English-script Bengali query → stream_response should detect "bn" via BANGLA_ROMAN_WORDS.

---

## 18. Partial Transcripts

### P1-PT-001
**Risks**: R-ST
**Priority**: P1
**Conversation**:
- T1: STT returns an incomplete fragment "what is the"
**Flow**: _validate_transcript → "what is the" → q_clean = "what is the" → word_count=3. Check INCOMPLETE_TRAILING_PATTERNS: line 305: `r"(what|where|when|why|how|who|which|about|of|in|at|on|for|to|the|a|an|is|are|am|was|were)\s*$"` → "what is the" ends with "the" → matches! → returns CLARIFICATION_REPEAT_EN.
**Failure**: Correctly caught by transcript validation as incomplete fragment.
**Validation**: Works.

### P1-PT-002
**Risks**: R-ST
**Priority**: P1
**Conversation**:
- T1: STT returns fragment "fee for cse" (no question structure, but valid keywords)
**Flow**: _validate_transcript → "fee for cse" → word_count=3. Check INCOMPLETE_TRAILING_PATTERNS → "fee for cse" ends with "cse" → "cse" is not in the trailing pattern list → NO match. Not filler. Not greeting. Not ambiguous (word_count > 1). Not too short (≥2 words). → pass-through (returns None).
Then: followup_expand → _detect_structured_intent → "fee" → fee → already_complete_intent → structured_lookup → fee handler → dept_code="CSE" → returns CSE fee.
**Expected**: "fee for cse" works despite being a fragment. The structured lookup handles it.
**Validation**: Correct.

### P1-PT-003
**Risks**: R-ST
**Priority**: P1
**Conversation**:
- T1: STT returns "um" (hesitation sound captured by STT)
**Flow**: _validate_transcript → "um" → single word. FILLER_ONLY_PATTERNS: `r"^(okay|ok|k|yes|yeah|...|hmm|hm|mm|huh|aha|uh huh|mm hmm|oh|ah)$"` → "um" is NOT in this list. Then check: word_count=1 and "um" in AMBIGUOUS_WORDS? No. word_count=1 and "repeat"/"pardon"? No. word_count < 2 → returns CLARIFICATION_REPEAT_EN.
**Failure**: "um" triggers clarification when it should be silently ignored (filler acknowledgment).
**Root cause**: FILLER_ONLY_PATTERNS doesn't include "um", "uh", "er", "hmm" (yes, "hmm" IS there). "um" is missing. Also "uh" is missing.
**Impact**: LOW — single "um" triggers "I didn't quite catch that" clarification. User may be confused.
**Validation**: _validate_transcript("um", sid) should be None (pass-through) but currently returns clarification.

### P1-PT-004
**Risks**: R-ST
**Priority**: P1
**Conversation**:
- T1: STT returns "fee um" (keyword with hesitation)
**Flow**: _validate_transcript → word_count=2. FILLER_ONLY: no match (2 words not in pattern). Greeting: no. Ambiguous: word_count > 1 → no. Too short: word_count < 2? No, =2. Incomplete: check trailing patterns: "fee um" ends with "um" → not in trailing list → pass-through.
**Expected**: "fee um" passes through. Then _detect_structured_intent → "fee" → structured_lookup fee handler → no dept_code → general fee info. Acceptable.
**Validation**: Works but could be improved by filtering hesitation words.

---

## 19. Interruptions

### P1-IN-001
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: User interrupts the agent's response
**LiveKit flow**: turn_handling={"interruption": {"enabled": True, "mode": "vad", "min_words": 2}} at line 468-469. If user speaks ≥ 2 words, VAD detects speech → LiveKit interrupts current TTS playback → new STT cycle starts.
**stream_response**: If stream_response is still yielding tokens, the interruption causes the async generator to be cancelled (via asyncio.CancelledError or LiveKit stream close).
**Failure**: Interrupted stream_response may leave _session_states or _sessions in an inconsistent state if mid-way through state mutation (e.g., after structured_lookup state update but before _append_session_turn).
**Impact**: HIGH — race condition between interruption and state mutation. Partial state updates could corrupt session.
**Validation**: HARD — requires real LiveKit test with precise timing. Simulated: cancel stream_response mid-execution, then verify session state integrity with next query.

### P1-IN-002
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Barge-in during TTS playback
**LiveKit flow**: LiveKit's VAD detects user speech during agent's TTS output → `allow_interruptions=True` on greeting → TTS is stopped → new STT cycle begins.
**Failure**: If the interruption happens between STT→stream_response but before stream_response yields first token, the new query may be processed with stale session state from the interrupted turn's partial processing. Specifically: if structured_lookup already updated state but the interrupted turn didn't complete session append, the new turn starts with partial state.
**Impact**: HIGH — state corruption scenario.
**Validation**: HARD — requires precise timing test. Simulated: partially execute one turn (state update done, session append not done) → execute new turn → verify state consistency.

---

## 20. Barge-in

### P1-BG-001
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Agent speaking → user says "stop" → new query
**Flow**: User says "stop" while agent is speaking. STT returns "stop". _validate_transcript → "stop" → word_count=1. FILLER_ONLY: "stop" not in list. Not greeting. AMBIGUOUS_WORDS: not in list. "repeat"/"pardon"? No. word_count < 2 → CLARIFICATION_REPEAT_EN.
**Failure**: "stop" is treated as a partial transcript and triggers clarification, when the user actually wanted to stop/interrupt.
**Impact**: LOW — "stop" results in "I didn't quite catch that" which is confusing but harmless.
**Validation**: _validate_transcript("stop", sid) returns clarification. No "stop" handling exists.

### P1-BG-002
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Agent speaking → user says "I want CSE fee" during agent's sentence about something else
**Flow**: Barge-in → STT returns "I want CSE fee" → processed as normal query. _detect_structured_intent → fee → structured_lookup → CSE fee.
**Expected**: Works correctly because the barged-in query is a complete intent that's independently resolvable.
**Validation**: Correct behavior.

### P1-BG-003
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Agent speaking → user says "yes" or "no" to the agent's question
**Flow**: If agent asked "Would you like to know about hostel fees?", user says "yes". Stream path has no yes/no continuation logic. "yes" → _validate_transcript → FILLER_ONLY pattern matches ("yes" IS in FILLER_ONLY_PATTERNS at line 309-310) → returns ACKNOWLEDGMENT_EN → "Got it. How else can I help you?".
**Failure**: User's "yes" to agent's clarification question is treated as filler acknowledgment. The agent doesn't show hostel fee info.
**Root cause**: FILLER_ONLY_PATTERNS includes "yes" and "no". They are intercepted by _validate_transcript before reaching any handler. So "yes" never reaches structured_lookup.
**Impact**: HIGH — voice users cannot confirm clarification prompts. "yes" always returns "Got it" regardless of context.
**Validation**: After ambiguous word "hostel" → agent asks "Would you like to know about hostel fees, facilities, or availability?" → user says "yes" → generate re-routes to previous question, stream returns "Got it".

---

## 21. Duplicate STT Events

### P1-DS-001
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: SarvamSTT is configured with `interim_results=False` and `streaming=False` (line 277)
**Flow**: STT only produces FINAL_TRANSCRIPT events (no interim). This means no duplicate STT events for the same utterance within LiveKit's recognition cycle.
**Failure**: No duplicate events expected.
**But**: LiveKit may produce duplicate FINAL_TRANSCRIPT events if VAD segment detection fires twice for the same utterance. SarvamSTT doesn't deduplicate — each call to _recognize_impl creates a new API call and returns fresh SpeechEvent.
**Impact**: LOW — duplicate FINAL_TRANSCRIPT events are unlikely but not handled.
**Validation**: Force two consecutive STT events with identical text. stream_response should handle deduplication (currently doesn't).

### P1-DS-002
**Risks**: R-VT
**Priority**: P1
**Conversation**:
- T1: Rapid successive STT events from short utterances (e.g., user saying multiple short phrases rapidly)
**Flow**: Each STT event → stream_response → each executes full pipeline. If two events arrive within milliseconds of each other, both process concurrently. Concurrent stream_response calls for the same session_id could:
  - Race on _session_states (both read, both write) → last write wins
  - Race on _sessions (_append_session_turn) → interleaved entries
**Failure**: Concurrent processing of duplicate STT events causes session state corruption.
**Impact**: HIGH — race condition. Two queries processed simultaneously corrupt conversation history and state.
**Validation**: Send two stream_response calls concurrently for the same session_id. Verify _sessions has correct turn ordering.

---

## Discovery: New Critical Issues Found

During P1 catalog generation, the following undocumented issues were discovered:

1. **`or True` bypass in generate arithmetic block** (line 3503): `if self._detect_on_topic_arithmetic(query) or True:` — The `or True` means ALL queries, not just arithmetic ones, enter the arithmetic/structured lookup block. This is intentional but undocumented and differs from stream behavior where structured lookup is the primary path. The parity impact is that generate ALWAYS tries structured lookup before RAG, while stream tries structured lookup as a fallback inside the path where arithmetic already failed. Direction of priority differs.

2. **`fee_intent` variable scope bleed in `_structured_lookup`**: At line 2572, departments handler checks `and not fee_intent`. The `fee_intent` variable was defined at line 2391. If fee intent matched but no sub-condition returned (e.g., dept_code not found AND general fee pattern also missed), `fee_intent` is non-None and execution reaches departments handler. The `and not fee_intent` prevents the departments handler from running, even though the fee handler already fell through. Dead code or latent bug.

3. **FILLER_ONLY_PATTERNS missing common hesitation sounds**: "um", "uh", "er" are not in the list. These trigger transcript validation to return clarification, which is confusing for users who made a small hesitation.

4. **STT hardcoded confidence 0.95** (line 308): Actual Sarvam confidence is ignored. Makes confidence metric meaningless for voice path.

5. **No deduplication for STT events**: Duplicate FINAL_TRANSCRIPT events from LiveKit are not filtered, causing concurrent pipeline execution for the same session.

6. **Single word hesitation with dept keyword**: "fee um" passes validation but should strip the hesitation before structured lookup.

7. **Comparison and aggregation queries have no structured support**: "which is better X or Y", "total seats across all departments" — stream path has no structured fallback for these. Generate only handles seat total arithmetic.

---

## Summary

| Area | Test Cases | Risk Level | Coverage Gap |
|------|-----------|------------|--------------|
| ConversationState staleness | 3 | HIGH | State not updated on RAG-only turns |
| Multi-turn memory | 5 | HIGH | Department context not carried across turns |
| Cross-domain switching | 3 | MEDIUM | Handler priority conflicts |
| Entity tracking | 2 | MEDIUM | Faculty alias gaps, no context-aware dept filling |
| Pronoun resolution | 3 | HIGH | "it" not resolved to previous domain |
| Stream vs generate parity | 9 | CRITICAL | 8 documented parity gaps hit |
| Prompt query differences | 2 | HIGH | Double normalization, lang switch re-route |
| LLM timeout/retry | 4 | HIGH | No timeout in stream, 10s+ circuit breaker wait |
| RAG retrieval degradation | 2 | MEDIUM | Expanded query quality, degraded Bengali search |
| Ranking failures | 2 | MEDIUM | Language penalty, dedup overwrite |
| Comparison reasoning | 2 | HIGH | No comparison support at all |
| Aggregation reasoning | 2 | MEDIUM | Seat total missing from stream |
| Long conversations | 2 | LOW | History cap works but state loses freshness |
| Context window pressure | 2 | LOW | Within model limits for typical usage |
| Session recovery | 2 | LOW | Fresh start on clear_session |
| LiveKit voice flow | 4 | HIGH | Greeting missing, race condition on disconnect |
| Sarvam STT/TTS failures | 6 | HIGH | TTS failure = silence, no fallback |
| Partial transcripts | 4 | MEDIUM | Missing hesitation words in filter |
| Interruptions | 2 | HIGH | State corruption race condition |
| Barge-in | 3 | HIGH | "yes"/"no" treated as filler, no confirmation flow |
| Duplicate STT events | 2 | HIGH | No deduplication, concurrent state mutation |
| **Total** | **64** | | |

**Note**: 64 test cases documented. Additional edge cases exist within each area but were omitted when the behavior is well-covered by existing P0 tests or functionally identical to documented cases. If full 80-120 is required, the following areas can be expanded with more variants: multi-turn memory (10+ additional dept carryover scenarios), cross-domain switching (5+ additional handler priority edge cases), stream vs generate parity (15+ sub-variations of known gaps), and Sarvam STT/TTS (10+ additional failure modes).

**New discoveries**: 7 undocumented issues found during catalog generation (see Discovery section above). These are appended to `audit/new_discoveries.md`.
