# PROJECT_STATE.md — Architecture Maturity, Risks & Technical Debt

---

## Current Architecture Maturity

### Maturity Level: **ALPHA → BETA transition**

**What works well:**
- Core LLM+RAG pipeline is robust (handles structured lookup, vector search, LLM fallback, session memory, caching, telemetry, rate limiting, circuit breaker)
- Multilingual support (EN/HI/BN) through FastText + normalization + trilingual prompts
- LiveKit voice agent with STT→LLM→TTS pipeline, prewarm, connection diagnostics
- Twilio bridge for phone calling
- Admin API for KB management, file upload, cache ops
- Build pipeline for KB updates and vector index rebuild
- Telemetry system tracks every turn end-to-end

**What's fragile or incomplete:**
- Multiple intent classification systems competing (regex vs embedding)
- Dead/unused code paths (5 modules, 22 scripts)
- Duplicate/overlapping launcher scripts
- `nul` file in repo root breaks `git add -A`
- Backup service is a stub
- WebSocket voice pipeline is single-turn only
- CORS config is impossible to override via env
- Documentation is minimal (no CONTRIBUTING.md, no deployment guide)
- No CI/CD pipeline
- Large ONNX model (60MB) not on LFS
- Launcher port inconsistency (8000 vs 8001)

---

## Biggest Risks

### Risk 1: Critical single-module dependency
- `groq_service.py` at 4359 lines is the largest file and the heart of the application
- 20+ modules depend on it directly
- Any regression in this file affects every user-facing feature
- No integration test suite runs in CI

### Risk 2: Dead module with broken internal import (`voice_session.py`)
- `voice_session.py` imports `app.services.stt_deepgram` which does not exist
- If anything ever triggers this import, the process crashes
- The file currently has no callers, but a future refactor could accidentally wire it in

### Risk 3: `nul` file in repo
- Blocks `git add -A` — any automated Git workflow (CI/CD, hooks, scripts) that runs `git add -A` will fail
- Must be manually excluded every time

### Risk 4: One-time PDF scripts vs live website data
- Fee structure, NIRF data, and AICTE approvals were scraped once from PDFs
- When the college updates these documents, the KB will be stale until someone manually re-runs the PDF scripts
- No automated data refresh mechanism

### Risk 5: Localhost-only CORS
- The live agent behind ngrok serves to `https://*.ngrok-free.dev` but CORS only allows `http://localhost:*`
- If the frontend makes any cross-origin API request (other than the initial page load), it will be blocked
- Currently works only because frontend is served by the same origin (FastAPI static mount)

### Risk 6: Multiple conflicting intent systems
- Inline regex patterns in groq_service.py (2700+ lines)
- Embedding-based classifier in intent_classifier.py
- Rule-based classifier in conversation/intent.py (legacy)
- These three can disagree, causing unpredictable routing

---

## Technical Debt

### Documentation Debt
- No ARCHITECTURE.md existed before this audit (now created)
- No CONTRIBUTING.md
- No DEPLOYMENT.md or deployment guide
- No API documentation (OpenAPI/Swagger is auto-generated but not customized)
- No environment setup guide
- No test coverage report

### Code Debt
- `groq_service.py` at 4359 lines — violates single-responsibility principle
- `generate_kb.py` (516 lines) and `generate_markdown.py` (699 lines) — large and tightly coupled to KB schema
- `simulate_conversations.py` (992 lines) — largest file in project, never used
- 22 scripts in `scripts/` are orphaned (no callers, multiple overlapping purposes)
- Inline import constellations (lazy imports scattered across groq_service.py)
- Hardcoded strings for language detection, speaker mapping, CORS origins
- Env var `CORS_ORIGINS` completely ignored

### Test Debt
- No CI integration
- No automated test runner configured beyond local `pytest`
- Red team tests exist but are not integrated
- No load tests
- No end-to-end tests for LiveKit/Twilio paths
- `pytest` configured for both `backend/tests/` and `tests/` but root `tests/` only has 2 files

### Build Pipeline Debt
- `build.py` relies on `subprocess.run()` calling Python scripts
- No dependency tracking — if one step fails, subsequent steps may produce inconsistent state
- No incremental build — full rebuild every time (takes >30s for ChromaDB re-index)

### Infrastructure Debt
- No Docker compose for local development
- No deployment scripts for cloud (Railway, AWS, etc.)
- No environment separation (dev/staging/prod)
- Multiple launcher scripts with no clear "production" entry point

---

## Missing Tests

| Area | Test Coverage | Notes |
|------|---------------|-------|
| GroqService.generate_response() | Partial | `test_groq_service.py`, `test_async_groq.py` cover some paths |
| Structured lookups | Minimal | No tests for individual KB handlers |
| WebSocket voice pipeline | None | `ws_voice.py` has zero tests |
| Twilio bridge | None | Requires real Twilio credentials |
| LiveKit agent | None | `scripts/livekit_agent.py` has no unit tests |
| Intent classification | Partial | `test_intent.py` tests rule-based classifier only |
| Language detection | Partial | `test_language_consistency.py` covers some scripts |
| Normalization | Partial | `test_normalization.py` |
| Telemetry | Partial | `test_telemetry.py` |
| Session isolation | Partial | `test_session_isolation.py` |
| Regression (UX) | Partial | `test_regression_ux.py` |
| API robustness | Partial | `test_api_robustness.py` |
| Red team | Full | `red_team/` has 7 files with comprehensive tests |
| Build pipeline | None | No tests for `build.py` or any step |
| KB validation | None | `validate_kb.py` is a script, not a test suite |
| Vector store retrieval | None | `validate_retrieval.py` is a standalone script |
| Performance benchmarks | None | `performance_report.py` is a post-hoc analysis tool |

---

## Recommended Cleanup Order

### Phase 1 — Safety (immediate, high impact)
1. Remove `nul` file from repo (`git rm --cached nul`, add to .gitignore)
2. Remove `GEMINI_API_KEY` from .env (unused key)
3. Add `.gitattributes` with LFS config for `*.onnx` files
4. Choose ONE launcher as canonical (recommend: root `start_server.ps1` for server, `start_agent_now.ps1` for agent)

### Phase 2 — Dead Code Removal (after baseline)
5. Delete `scripts/energy_vad.py` (never imported)
6. Delete `scripts/dispatch_agent.py`, `scripts/join_room.py` (superseded)
7. Delete `scripts/run_agent.py`, `scripts/start_agent.py` (superseded)
8. Delete `scripts/server_bg.py`, `scripts/start_server.py` (superseded)
9. Delete `scripts/start_backend.ps1`, `scripts/start_backend.bat`, `scripts/start_agent.bat` (overlapping)
10. Delete `scripts/download_pdfs.py`, `parse_all_pdfs.py`, `parse_fee_pdfs.py`, `scrape_official_site.py` (one-time)
11. Delete `scripts/validate_retrieval.py`, `performance_report.py`, `simulate_conversations.py`, `demo_readiness_test.py`, `system_test.py` (standalone unmaintained)
12. Delete `scripts/test_*.py` (standalone unmaintained)
13. Delete `backend/app/services/llm/base.py` (unused abstract class)
14. Delete `backend/app/services/conversation/responses.py` (unused templates)
15. Delete `backend/app/services/query_logger.py` (superseded)
16. Delete `backend/app/services/telephony/base_adapter.py` (unused interface)
17. Delete `backend/app/services/voice_session.py` (dead code with broken import)
18. Delete `backend/app/services/backup.py` (placeholder — or implement real backup)
19. Delete root test JSON files (`test_*.json`), `kb_comparison.txt`, `kb_structure.txt`

### Phase 3 — Architecture Consolidation
20. Merge port convention (choose 8001 as standard)
21. Make CORS config honor `CORS_ORIGINS` env var
22. Delete or consolidate one of the two intent classifiers
23. Replace `subprocess.run()` calls in `build.py` with direct imports
24. Make `ws_voice.py` multi-turn capable
25. Wire `tts_cache` into LiveKit agent for cached greetings

### Phase 4 — Testing
26. Add CI pipeline (GitHub Actions)
27. Integrate red team tests into CI
28. Add tests for WebSocket voice pipeline
29. Add integration tests for structured lookups
30. Add end-to-end test script that runs with live credentials

### Phase 5 — Documentation & Deployment
31. Write DEPLOYMENT.md
32. Write CONTRIBUTING.md
33. Add Docker compose with all services
34. Set up staging environment
35. Add automated KB refresh from website
