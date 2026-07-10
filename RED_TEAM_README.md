# BCREC Red-Team Test Framework

Automated evaluation of all P0 and P1 test cases against `generate_response` and `stream_response` pipelines.

## Quick Start

```bash
# List all test cases
python run_red_team.py --list

# Run all tests (excludes LLM-mock and voice tests by default)
python run_red_team.py

# Run P0 only
python run_red_team.py --p0

# Run specific group
python run_red_team.py --group A

# Run with LLM mock tests included
python run_red_team.py --with-mocks

# Save JSON report
python run_red_team.py --output report.json
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--p0` | P0 tests only |
| `--p1` | P1 tests only |
| `--group G` | Filter by group (A-I, CS, MM, PG, etc.) |
| `--with-mocks` | Include tests requiring LLM response injection |
| `--with-voice` | Include voice-specific tests |
| `--generate-only` | Run generate path only |
| `--stream-only` | Run stream path only |
| `--json` | JSON stdout output |
| `--output FILE` | Save report to file |
| `--list` | List all test cases |

## Architecture

```
backend/tests/red_team/
  __init__.py         # Package exports
  pipeline_hooks.py   # Monkey-patching context manager for stage capture
  cases.py            # 147 test case definitions (101 P0 + 46 P1)
  runner.py           # Test executor against generate + stream paths
  report.py           # Results aggregation and summary
run_red_team.py       # CLI entry point
```

### Pipeline Hooks

The framework monkey-patches 18 GroqService methods at runtime via `stage_capture_context()`:

- `_normalize_query`, `_validate_transcript`, `_detect_noisy_transcript`
- `_resolve_language`, `_is_greeting`, `_is_out_of_domain`
- `_detect_repeat_intent`, `_detect_on_topic_arithmetic`, `_split_multi_intent`
- `_expand_follow_up_query`, `_structured_lookup`, `_retrieve_context`
- `_build_messages`, `_validate_answer`, `_prepare_for_tts`
- `_append_session_turn`, `_detect_placement_eligibility_intent`

### Test Case Structure

Each `TestCase` contains:
- `id`, `priority`, `group`, `risk_ids`, `category`, `description`
- `turns`: list of `Turn(query, expected_handler, expected_source, expected_lang, ...)`
- `expected_generate_stream_parity`: whether generate and stream should match
- `requires_llm_mock` / `requires_voice`: execution flags

## Test Coverage

| Priority | Count | Includes |
|----------|-------|----------|
| P0 | 101 | Groups A-I: hallucination guard, missing stream features, OOD, normalization, language state, structured lookup, RAG, long multi-turn, failure injection |
| P1 | 46 | ConversationState, multi-turn memory, cross-domain, pronoun resolution, stream parity, LLM timeout, ranking, comparison, aggregation, voice, STT/TTS |
| **Total** | **147** | 14 require LLM mocking, 20 require voice setup |

## Risk Coverage

- **R01**: Stream hallucination guard non-blocking — 11+ tests
- **R02**: Generate/Stream parity gap — ~75 tests
- **R03**: OOD false positives — 19 tests
- **R04/R-CS**: ConversationState staleness — 5+ tests
- **R10**: Language-ignorant handlers — 6+ tests
- **R-FU**: Follow-up expansion — 8+ tests

## Extending

Add test cases to `backend/tests/red_team/cases.py`. Each test needs:
1. Assign a unique `id`
2. Define `turns` with expected handler/source per turn
3. Mark `requires_llm_mock=True` if LLM injection is needed
4. Set `expected_generate_stream_parity=False` if parity failure is expected
