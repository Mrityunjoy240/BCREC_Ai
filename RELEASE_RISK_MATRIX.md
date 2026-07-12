# Release Risk Matrix

| # | Risk | File(s) | Probability | Impact | Mitigation |
|---|---|---|---|---|---|
| 1 | **CLARIFY_REPEAT_HI/BN overwritten** by old definitions | groq_service.py:698-701 | 100% | Low — users get old "clear roop se samajh" msg instead of friendlier "achhe se samajh" msg. Only affects repeat-clarify path. | Remove duplicate lines 700-701 |
| 2 | **LLM timeout 30s → 6s** causes fallback under load | groq_service.py | Medium | Medium — users see "sorry, having trouble connecting" if LLM takes >6s. During peak hours, fallback rate may increase. | Make configurable; monitor fallback rate post-release |
| 3 | **Language over-classification** — 80 new Banglish words may cause Hindi/English queries to be misclassified as Bengali | language_detect.py | Low | Low — `detect_language` requires `bn_count > hi_count`, so common words won't tip the scale. Bengali response to Hindi user is slightly confusing but not harmful. | None needed; existing guard prevents borderline cases |
| 4 | **Structured lookup intercepts LLM-bound queries** — regex patterns in `_structured_lookup` may match queries better handled by LLM | groq_service.py | Low-Medium | Medium — deterministic KB response may be wrong for nuanced queries. The `fee_intent` guard prevents fee→department misrouting. | Monitor structured_lookup hit rate; expand patterns conservatively |
| 5 | **Standalone yes/no short-circuit** — exact-match check intercepts "yes"/"no" before LLM | groq_service.py | Low | Low — only exact `"yes"`, `"yeah"`, `"no"` etc. match. Compound ("yes but") falls through to LLM. Correct behavior. | None needed |
| 6 | **Dead except block** (line 57-58) references wrong variable | groq_service.py | 0% (dead code) | None — code never executes. But signals confusion in import logic. | Remove dead block |
| 7 | **Dual feature flags** — `USE_NEW_FEE_ENGINE` (dead) vs `_USE_NEW_FEE_ENGINE` (live) | groq_service.py:61,723 | Low (maintenance) | Low — reader confusion. The live flag controls behavior correctly. | Remove dead module-level constant |
| 8 | **Health endpoint `key_prefix` → `key_configured`** breaks monitoring | health.py | Medium (if monitoring depends on partial key) | Low — monitoring should only check `True`/`False`, not partial key. | Verify downstream consumers |
| 9 | **Admin credentials empty by default** — server fails to start if `.env` missing credentials | config.py | High (for new deployments) | High — auth endpoints return 401 until `.env` is configured. | Document in deployment guide |
| 10 | **`DemoLogger` capped at 1000 entries** — old logs evicted | safe_point.py | Low | Low — demo logs are not user-facing. 1000 entries is generous. | None needed |
| 11 | **Rate-limited admin endpoints** — 5/min for heavy ops may throttle legitimate batch operations | admin.py | Low | Low — 5/min is reasonable for admin UIs. Batching scripts should add delays. | Document rate limits |
| 12 | **No tracked source files removed** | All | 0% | None — verified via `git diff --diff-filter=D -- *.py` | None needed |

## Risk Summary

| Severity | Count | Action Required |
|---|---|---|
| **Critical (P0)** | 1 | Fix before release (CLARIFY_REPEAT overwrite) |
| **High (P1)** | 2 | Fix before release (dead except, dual flags) |
| **Medium (P2)** | 2 | Fix before release or document as known tech debt |
| **Low** | 7 | Accept or monitor post-release |

## Verdict

**NOT READY** — One P0 bug (CLARIFY_REPEAT_HI/BN overwrite) and two P1 issues (dead except block referencing wrong variable, dual feature flags) must be fixed before the release is safe to merge.
