# Release Checklist

## Pre-Release Verification

### Configuration
- [ ] `.env` contains `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY` (no default credentials)
- [ ] `.env` contains valid `GROQ_API_KEY`
- [ ] `.env` contains valid `SARVAM_API_KEY`
- [ ] `USE_NEW_FEE_ENGINE` env var set explicitly (`0` or `1`) — module-level constant `USE_NEW_FEE_ENGINE = False` is dead; only `_USE_NEW_FEE_ENGINE` env-var branch is active
- [ ] `MAX_VOICE_RESPONSE_CHARS`, `CACHE_TTL`, rate-limit env vars reviewed

### Build & Syntax
- [x] All 37 `.py` files parse without syntax errors
- [x] All production imports resolve successfully
- [x] No `ModuleNotFoundError` from deleted modules

### Tests
- [x] 265 tests pass (excluding 4 pre-existing failures)
- [x] `test_intent.py` removed (tests deleted API)
- [x] `TestConversationManagerIsolation` removed from `test_session_isolation.py`
- [ ] 4 pre-existing failures documented as known issues (see below)

### Security
- [ ] Health endpoint no longer leaks API key prefix (now returns `key_configured: bool`)
- [ ] Admin endpoints rate-limited (5–10/min depending on operation)
- [ ] Login rate-limited (5/min)
- [ ] Admin credentials default to empty string (no hardcoded defaults)
- [ ] Auth routes validate credential config before attempting login
- [ ] Database `busy_timeout=5000` added for SQLite concurrency safety

### Production Code Changes
- [ ] Dead modules removed (base.py, base_adapter.py, voice_session.py, query_logger.py, conversation/*.py)
- [ ] Dead symbols removed across 7 files (tool functions, constants, decorators)
- [ ] Unused imports removed across 12 files
- [ ] All deletions verified: no production code depended on removed symbols
- [x] No tracked source files accidentally deleted

## Known Issues (Pre-Existing, Not in Release Scope)
1. 3 normalization test failures: principal alias resolution, Hindi principal, BCREC TTS expansion
2. 1 regression test failure: `RETRIEVAL_CONFIDENCE_THRESHOLD` unused in `generate_response`
3. `_build_messages` was removed (confirmed dead)

## Blockers (Must Fix Before Release)

### P0 — CLARIFY_REPEAT_HI/BN Overwrite Bug (groq_service.py:698-701)
The new friendly Hindi/Bengali clarify-repeat messages at lines 698-699 are immediately overwritten by the old messages at lines 700-701. The final runtime values are the old, less helpful messages.
**Fix:** Remove lines 700-701 (the duplicate definitions).

### P1 — Dead `except ImportError` Block (groq_service.py:57-58)
Second `except ImportError:` block references non-existent variable `_FEE_ENGINE_AVAILABLE` instead of `_INTENT_CLASSIFIER_AVAILABLE`. This code path is unreachable (nested under the first except) but signals confusion.
**Fix:** Remove lines 57-58.

### P1 — Dual Fee Engine Feature Flags (groq_service.py:61 vs 723)
`USE_NEW_FEE_ENGINE = False` (module level, always False, unreferenced) coexists with `_USE_NEW_FEE_ENGINE = os.getenv(...)` (class-level, env-driven, used by dispatcher). The unused module-level flag is misleading.
**Fix:** Remove `USE_NEW_FEE_ENGINE = False` at line 61.

### P2 — Language Prefix Duplication
20-line `lang_prefix` + `lang_hint` construction is copy-pasted identically in `generate_response` and `stream_response`.
**Fix:** Extract into a shared helper method.

### P2 — LLM Timeout 30s → 6s
May cause excessive fallbacks under load. Consider making timeout configurable or staging at 15s.
