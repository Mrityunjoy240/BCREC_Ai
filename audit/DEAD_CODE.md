# DEAD_CODE.md — Functions, Classes & Modules That Appear Unused

> Based on reverse-dependency analysis (grep across all .py files).  
> DO NOT DELETE — report only.

---

## Modules With No Production Imports

| File | Lines | Last Referenced | Notes |
|------|-------|-----------------|-------|
| `backend/app/services/llm/base.py` | 37 | Never | Abstract BaseLLM — no implementation inherits from it |
| `backend/app/services/conversation/responses.py` | 50 | Never | ResponseTemplates — groq_service.py has its own responses |
| `backend/app/services/query_logger.py` | 85 | Never | QueryLogger — superseded by conversation_logger.py |
| `backend/app/services/telephony/base_adapter.py` | 22 | Never | TelephonyAdapter — TwilioService doesn't extend it |
| `backend/app/services/voice_session.py` | 95 | Unknown | VoiceSessionManager — no reverse deps found in scan |

## Scripts With No Callers

| Script | Lines | Status |
|--------|-------|--------|
| `scripts/dispatch_agent.py` | 45 | UNUSED — manual dispatch tool |
| `scripts/energy_vad.py` | 199 | UNUSED — silero.VAD used instead |
| `scripts/validate_retrieval.py` | 345 | UNUSED — standalone QA tool |
| `scripts/performance_report.py` | 369 | UNUSED — standalone analysis |
| `scripts/simulate_conversations.py` | 992 | UNUSED — standalone test harness |
| `scripts/demo_readiness_test.py` | 402 | UNUSED — standalone test |
| `scripts/system_test.py` | 153 | UNUSED — standalone integration test |
| `scripts/test_15_quick.py` | 99 | UNUSED — standalone ad-hoc test |
| `scripts/test_faq_comprehensive.py` | 260 | UNUSED — standalone test |
| `scripts/test_rag_150.py` | 406 | UNUSED — standalone test runner |
| `scripts/test_vp_fix.py` | 34 | UNUSED — standalone debug script |

## Functions/Classes That May Be Unused (verify at runtime)

### In groq_service.py (4359 lines — hardest to verify statically):
- `RateLimiter` class — only used via inline `_check_rate_limit()` → `_rate_limit_data` pattern
- `ConversationState` dataclass — used by `_track_domain()` and domain-aware follow-up
- `DomainSlot` dataclass — used by cross-domain slot tracking
- `_update_semantic_anchor()` — only called from `/admin/kb/update-anchor` endpoint
- `_load_faq()` — only called from `/admin/kb/reload`
- `get_cache_stats()` — only called from `/admin/cache/stats`
- `clear_cache()` — only called from `/admin/cache/invalidate`
- `_ambiguity_detection()` — may be dead if coverage is incomplete
- `_apply_stt_corrections()` — may be dead if normalizer handles this

### In livekit_agent.py (712 lines):
- `SarvamSTT._fix_stt_acronyms()` — called within `speech_to_text()`, but may be subsumed by `normalizer.py`
- `_run_connection_diagnostics()` — called in `__main__` block, runs ONCE at startup
- `_gather_dns_evidence()` — called by `_run_connection_diagnostics()` only on DNS failure
- `convert_phone_numbers()` — called from `apply_lexicon()` which is called from `BCRECGroqLLM`

### In scripts/:
- `build.py:run_step()` — called only within build.py
- `generate_kb.py:generate_voice_answers()` — called from `build_output()` within the same file
- `generate_markdown.py:generate_department_md()` — called from `main()` within the same file
- `validate_kb.py:check_schema()`, `check_null_values()`, `check_cross_field()` — called from `main()`

## Orphaned Data Files
- `test_addr.json`, `test_comprehensive.json`, `test_full.json`, `test_groq.json`, `test_output.json`, `test_principal.json` — in project root, likely from prior test runs
- `kb_comparison.txt`, `kb_structure.txt` — documentation artifacts
- `tmp_verify_findings.py` — ad-hoc verification script in root

## Duplicate / Overlapping Launchers
- `scripts/start_backend.ps1` — overlaps with root `start_server.ps1`
- `scripts/start_backend.bat` — same as above, different format
- `scripts/start_agent.bat` — overlaps with root `start_agent_now.ps1`
- `scripts/server_bg.py` — overlaps with `scripts/start_server.py`
- `scripts/run_agent.py` — superseded by `scripts/start_agent.py` → `start_agent_now.ps1`
