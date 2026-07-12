# KNOWN_BUGS.md — Verified & Likely Issues

---

## VERIFIED (confirmed from source code)

### B1. Hardcoded CORS origins ignore the `CORS_ORIGINS` env var
- **File:** `backend/app/main.py:67-76`
- **Detail:** `CORS_ORIGINS` is defined in `config.py` Settings but `main.py` uses a hardcoded list of `localhost:*` origins. Any env-var override has zero effect.
- **Impact:** Cannot configure CORS via environment in production. Any non-localhost deployment requires a code change.

### B2. `nul` file in repo root is un-committable
- **File:** `./nul` (root directory)
- **Detail:** A zero-byte file named `nul` exists. On Windows, `nul` is a reserved DOS device name — Git refuses to track it (`fatal: invalid path 'nul'`). Causes `git add -A` to fail.
- **Impact:** Blocks clean `git add -A` workflows. Must use `git add --all -- ":!nul"` every time.

### B3. `voice_session.py` has no detectable consumer
- **File:** `backend/app/services/voice_session.py`
- **Detail:** The `VoiceSessionManager` class implements a Deepgram→Groq→Sarvam pipeline but no production module imports it. Neither `api/voice.py` nor `api/ws_voice.py` use it.
- **Impact:** Dead code path. The LiveKit agent handles voice directly.

### B4. `GEMINI_API_KEY` is defined but never used
- **File:** `backend/.env:4`, `backend/app/config.py:31`
- **Detail:** `gemini_api_key` is loaded into Settings but there is zero code in the entire project that reads `settings.gemini_api_key` or uses any Google Gemini API.
- **Impact:** Dead configuration. No functionality depends on this key.

### B5. Backup service is a placeholder
- **File:** `backend/app/services/backup.py`
- **Detail:** All three methods (`create_backup`, `list_backups`, `delete_backup`) create dummy files with `touch()` logic. No real backup is ever produced.
- **Impact:** The `/admin/backup/create` endpoint returns success but creates a meaningless empty file.

### B6. API version diff between `start_server.ps1` (8001) and `main.py`'s `__main__` (8000)
- **File:** `backend/start_server.ps1:4` vs `backend/app/main.py:139`
- **Detail:** `start_server.ps1` launches on port 8001; but `main.py`'s `if __name__ == "__main__"` block launches on port 8000. Both are used during development, creating confusion.
- **Impact:** Two different port conventions. The `start_agent_now.ps1` agent connects to server on port 8001, but `python backend/app/main.py` starts on 8000.

### B7. Multiple overlapping launcher scripts
- **Root:** `start_server.ps1` (8001)
- **scripts/:** `start_server.py`, `server_bg.py`, `start_backend.ps1`, `start_backend.bat`
- **Detail:** 5+ different ways to start the server, using different ports (8000 vs 8001), different Python environments (venv vs system), different log files.
- **Impact:** Difficult to know which launcher is "correct" for production.

### B8. `CORS_ORIGINS=*` in .env but hardcoded allow list in main.py
- **File:** `backend/.env:25` `CORS_ORIGINS=*`
- **Detail:** The env var says allow all origins `*`, but the code only allows localhost origins.
- **Impact:** Misleading configuration. The env var suggests wide-open CORS, but actual behavior is restrictive localhost-only.

### B9. CORS allow_origins uses `http://` only, no `https://`
- **File:** `backend/app/main.py:67-76`
- **Detail:** All hardcoded origins are `http://*`. When the app runs behind ngrok (HTTPS), the frontend origin is `https://*.ngrok-free.dev` — this will be blocked by CORS if the frontend makes API calls by origin.
- **Impact:** Potential CORS failures in ngrok/HTTPS deployments.

### B10. `ws_voice.py` only handles single-turn queries
- **File:** `backend/app/api/ws_voice.py`
- **Detail:** The WebSocket voice pipeline receives one query, streams one response, then sends "done" and exits. There is no loop for multi-turn conversation.
- **Impact:** After one Q&A, the WebSocket connection closes. The client must reconnect for each turn.

### B11. FastText model URL may 404
- **File:** `backend/app/utils/language_detect.py`
- **Detail:** FastText model is downloaded from `https://dl.fbaipublicfiles.com/fasttext/...`. If this URL changes or the model is removed, language detection silently falls back to keyword matching with reduced accuracy.
- **Impact:** Language detection degrades without warning.

---

## LIKELY (strong evidence from code patterns)

### L1. `voice_session.py` imports `app.services.stt_deepgram` which may not exist
- **File:** `backend/app/services/voice_session.py` (referenced imports)
- **Detail:** The file imports `get_deepgram_service` from `app.services.stt_deepgram`. No `stt_deepgram.py` was found in the services directory. If this file is ever actually invoked, it will raise `ModuleNotFoundError`.
- **Impact:** Runtime crash if `voice_session.py` is ever imported/called.

### L2. Intent classification duelling — rule-based vs embedding-based
- **Files:** `groq_service.py` (inline `_classify_intent` regex) and `llm/intent_classifier.py` (embedding-based)
- **Detail:** There are TWO intent classification systems:
  1. Regex-based `_classify_intent()` in groq_service.py (2700+ lines of pattern matching)
  2. Embedding-based `IntentClassifier.classify()` in llm/intent_classifier.py
  They are used at different points in the pipeline and may disagree on intent.
- **Impact:** Inconsistent intent resolution depending on which classifier fires first.

### L3. Large ONNX model file exceeds GitHub limit
- **File:** `backend/models/en-US-amy-medium.onnx` (60.27 MB)
- **Detail:** Git push succeeded with a warning, but files >50MB are not recommended on GitHub without LFS.
- **Impact:** May hit push limits in future. CI/CD pipelines may fail.

### L4. `normalize_query()` imports but normalizer module has conditional entity dict load
- **File:** `backend/app/services/normalization/normalizer.py`
- **Detail:** Entity dictionary is loaded from `data/canonical/entity_dictionary.json` at import time. If the file is missing or malformed, the entire module crashes at import time.
- **Impact:** Server startup fails if entity dictionary is corrupt.

### L5. LiveKit agent greeting is hardcoded English
- **File:** `scripts/livekit_agent.py:500`
- **Detail:** The greeting `"Hello! BCREC AI assistant here. How can I help you today?"` is always in English. The safe_point greeting logic is commented out (lines 504-505).
- **Impact:** Non-English callers hear an English greeting regardless of their language.

### L6. `DEMO_SAFEPOINT` greets in English despite having Bengali/Hindi templates
- **File:** `backend/app/services/llm/safe_point.py`
- **Detail:** `GREETINGS` dict has Bengali and Hindi variants, but the `get_greeting()` function uses `random.choice(GREETINGS["en"])` without any language awareness.
- **Impact:** Safe point greeting is always English.

---

## NEEDS RUNTIME VERIFICATION

### R1. Does `_structured_lookup()` ever return None for valid queries?
- The handler chain has many `if re.search(...)` branches but no guarantee that a valid query matches any branch. If all branches miss, `_structured_lookup` returns `None`, and the query falls through to LLM. This is intentional for OOD queries but may cause structured data to be LLM-generated instead of looked up.

### R2. Does the tokenizer in `_resolve_faculty_name()` correctly handle "Dr. Raj Kumar Samanta"?
- The stop_words filter removes "professor", "faculty", "teacher" etc. But "dr" and "prof" are allowed through. The fuzzy matching uses `difflib.SequenceMatcher`. Need runtime verification that scores ≥0.7 correctly match multi-word names.

### R3. Does `_extract_dept_code()` correctly identify departments in Hindi/Bengali queries?
- `_DEPT_WORDS` is an English-only frozenset. Hindi/Bengali department names (e.g., "कंप्यूटर विज्ञान") would not match, causing structured department lookups to fail for non-English queries.

### R4. Is `voice_session.py` actually dead or just not detected?
- The audit found no reverse dependencies via grep. However, runtime import or dynamic dispatch could invoke it. Manual test: attempt to import `voice_session` and verify no caller exists.

### R5. Are `scripts/analytics/` or `scripts/logs/` directories functional?
- These directories exist in the `scripts/` tree but were not analyzed. May contain active tools or dead artifacts.

### R6. Does the Twilio WebSocket bridge (`/voice/stream`) actually work end-to-end?
- The bridge code is non-trivial (μ-law ↔ PCM, LiveKit room management, resampling). Requires a live Twilio phone number and LiveKit credentials to verify.

### R7. Is `test_analytics.py` in `tests/` functional or dead?
- The file exists but has no callers. May be a test that runs via pytest or orphaned code.
