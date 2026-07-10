"""Red-team test case definitions — all P0 (96) and P1 (64) cases.

Each TestCase captures the expected pipeline behavior for generate and stream
paths, including per-turn handler routing, stage sequence, and expected source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    query: str
    expected_handler: str | None = None
    expected_source: str | None = None
    expected_lang: str | None = None
    expected_stages: list[str] | None = None
    expected_response_contains: list[str] | None = None
    expected_stream_response_contains: list[str] | None = None
    injection: dict[str, Any] | None = None


@dataclass
class TestCase:
    id: str
    priority: str  # "P0" or "P1"
    group: str  # "A", "B", "C", etc.
    risk_ids: list[str]
    category: str
    description: str
    turns: list[Turn]
    expected_handler: str | None = None
    expected_source: str | None = None
    expected_lang: str | None = None
    expected_generate_stream_parity: bool = True
    requires_llm_mock: bool = False
    requires_voice: bool = False


# ---------------------------------------------------------------------------
# Helper to build a single-turn test case
# ---------------------------------------------------------------------------


def _t(
    query: str,
    handler: str | None = None,
    source: str | None = None,
    lang: str | None = None,
    stages: list[str] | None = None,
    response_contains: list[str] | None = None,
    stream_response_contains: list[str] | None = None,
    injection: dict[str, Any] | None = None,
) -> Turn:
    return Turn(
        query=query,
        expected_handler=handler,
        expected_source=source,
        expected_lang=lang,
        expected_stages=stages,
        expected_response_contains=response_contains,
        expected_stream_response_contains=stream_response_contains,
        injection=injection,
    )


# ---------------------------------------------------------------------------
# P0 — Group A: Dual-Path Divergence — Hallucination Guard
# ---------------------------------------------------------------------------

P0_GROUP_A: list[TestCase] = [
    TestCase(
        id="A01",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Fee arithmetic ordering: generate checks arithmetic first, stream falls through to structured_lookup",
        turns=[
            _t(
                "What is the total fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
                stages=[
                    "_normalize_query",
                    "_validate_transcript",
                    "_resolve_language",
                    "_is_greeting",
                    "_is_out_of_domain",
                    "_detect_on_topic_arithmetic",
                ],
                response_contains=["6,04,700"],
            ),
        ],
        expected_handler="structured_arithmetic",
        expected_source="structured_arithmetic",
        expected_lang="en",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A02",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Semester fee for AIML: arithmetic primary in generate, fallback in stream",
        turns=[
            _t(
                "semester fee for AIML",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
                response_contains=["91,900"],
            ),
        ],
        expected_handler="structured_arithmetic",
        expected_source="structured_arithmetic",
        expected_lang="en",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A03",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Seat arithmetic: different regex coverage between generate arithmetic and structured_lookup seats handler",
        turns=[
            _t(
                "How many total seats in CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
                response_contains=["120"],
            ),
        ],
        expected_handler="structured_arithmetic",
        expected_source="structured_arithmetic",
        expected_lang="en",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A04",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Roman Hindi language detection threshold (single marker query)",
        turns=[
            _t(
                "CSE me kitne seats hain?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
                response_contains=["120"],
            ),
        ],
        expected_handler="structured_lookup",
        expected_source="structured_lookup",
        expected_lang="hi",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A05",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Roman Bengali language-ignorant handler: structured lookup ignores lang param",
        turns=[
            _t(
                "ami CSE te admission nite chai",
                handler="structured_lookup",
                source="structured_lookup",
                lang="bn",
            ),
        ],
        expected_handler="structured_lookup",
        expected_source="structured_lookup",
        expected_lang="bn",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A06",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="State staleness: RAG-only turn does not update ConversationState",
        turns=[
            _t(
                "What is the placement rate for CSE?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
                response_contains=["95%"],
            ),
            _t(
                "What about EE?", handler="structured_lookup", source="structured_lookup", lang="en"
            ),
        ],
        expected_handler="structured_lookup",
        expected_source="structured_lookup",
        expected_lang="en",
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="A07",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="blocking_vs_nonblocking",
        description="Hallucination guard: generate BLOCKS, stream LOGS only — fee hallucination",
        turns=[
            _t(
                "What is the total fee for CSE?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"llm_response": "The total fee for CSE is 5,00,000 rupees."},
            ),
        ],
        expected_handler="groq_rag",
        expected_source="groq_rag",
        expected_lang="en",
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="A08",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="blocking_vs_nonblocking",
        description="Hallucination guard: generate BLOCKS, stream LOGS only — phone hallucination",
        turns=[
            _t(
                "What is the college phone number?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"llm_response": "Contact the principal Dr. X at 99999-99999"},
            ),
        ],
        expected_handler="groq_rag",
        expected_source="groq_rag",
        expected_lang="en",
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="A09",
        priority="P0",
        group="A",
        risk_ids=["R01", "R02"],
        category="hallucination_guard",
        description="Admission fee: arithmetic block has admission_fee regex but structured_lookup fee handler may not",
        turns=[
            _t(
                "What is the admission fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
                response_contains=["98,225"],
            ),
        ],
        expected_handler="structured_arithmetic",
        expected_source="structured_arithmetic",
        expected_lang="en",
        expected_generate_stream_parity=False,
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group B: Missing Stream Features
# ---------------------------------------------------------------------------

P0_GROUP_B: list[TestCase] = [
    TestCase(
        id="B01",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="yes_no_continuation",
        description="Yes/no continuation: exists in generate, missing in stream",
        turns=[
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
            _t("yes", handler="structured_lookup", source="structured_lookup", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B02",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="yes_no_continuation",
        description="Language switch + repeat: generate re-runs query, stream switches lang only",
        turns=[
            _t(
                "CSE fee kya hai?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
            _t("hindi me", handler="structured_lookup", source="structured_lookup", lang="hi"),
            _t("repeat", handler="repeat_replay", source="repeat_replay", lang="hi"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B03",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="greeting",
        description="Greeting detection: generate has it, stream does not",
        turns=[
            _t(
                "hello",
                handler="greeting_deterministic",
                source="greeting_deterministic",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B04",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="greeting",
        description="Greeting 'good morning': generate returns structured greeting, stream falls to LLM",
        turns=[
            _t(
                "good morning",
                handler="greeting_deterministic",
                source="greeting_deterministic",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B05",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="greeting",
        description="Bengali greeting: generate returns structured greeting, stream falls to LLM",
        turns=[
            _t(
                "নমস্কার",
                handler="greeting_deterministic",
                source="greeting_deterministic",
                lang="bn",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B06",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="multi_intent",
        description="Multi-intent split: generate splits CSE fee + hostel, stream does not",
        turns=[
            _t(
                "What is the fee for CSE and hostel facilities?",
                handler="multi_intent",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B07",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="multi_intent",
        description="Multi-intent: admission process and scholarship",
        turns=[
            _t(
                "tell me about admission process and scholarship",
                handler="multi_intent",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B08",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="cache",
        description="Cache: generate has cache (only on first turn), stream has no cache at all",
        turns=[
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B09",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="prompt_query_difference",
        description="Prompt query: generate passes raw query, stream passes normalized query to LLM",
        turns=[
            _t("tell me about cse department", handler="groq_rag", source="groq_rag", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B10",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="tts_preparation",
        description="TTS preparation: generate calls _prepare_for_tts, stream does not",
        turns=[
            _t(
                "What is the placement percentage of CSE?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
        requires_voice=True,
    ),
    TestCase(
        id="B11",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="tts_preparation",
        description="TTS prep for phone number: generate expands digits, stream does not",
        turns=[
            _t(
                "What is the contact number?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
        requires_voice=True,
    ),
    TestCase(
        id="B12",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="truncation",
        description="Truncation: generate uses sentence-boundary, stream uses char-count mid-word cut",
        turns=[
            _t(
                "Tell me about placements at BCREC",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="B13",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="error_response",
        description="Error response: generate has phone number, stream has generic apology",
        turns=[
            _t(
                "Trigger 500 error",
                handler="error",
                source="error",
                lang="en",
                injection={"mock_error": "GroqAPIError: 500 Internal Server Error"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="B14",
        priority="P0",
        group="B",
        risk_ids=["R02"],
        category="safepoint_difference",
        description="SAFEPOINT: generate uses _sp_safe_pre, stream uses _sp_handoff — different functions",
        turns=[
            _t("What is the fee?", handler="safepoint", source="safepoint", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group C: OOD False Positives
# ---------------------------------------------------------------------------

P0_GROUP_C: list[TestCase] = [
    TestCase(
        id="C01",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_tech",
        description="Python course query: 2 hits in coding via corrected threshold analysis → blocked (false positive)",
        turns=[
            _t(
                "Does BCREC offer Python programming courses?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
        expected_handler="groq_rag",
        expected_source="groq_rag",
    ),
    TestCase(
        id="C02",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_tech",
        description="Languages taught: single OOD keyword, passes correctly",
        turns=[
            _t(
                "What programming languages are taught in CSE?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C03",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_tech",
        description="Python script: 1 OOD keyword hit → false negative (should block, passes)",
        turns=[
            _t(
                "How to write a Python script for data analysis?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C04",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_sports",
        description="Cricket team: college-relevant sports query, correctly allowed",
        turns=[
            _t("Does BCREC have a cricket team?", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C05",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_sports",
        description="IPL match query: 2 hits in sports = blocked via total_hits >= 2 (corrected analysis)",
        turns=[
            _t(
                "Who won the IPL match yesterday?", handler="groq_rag", source="groq_rag", lang="en"
            ),
        ],
    ),
    TestCase(
        id="C06",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_sports",
        description="T20 cricket: 4 hits >= 3 → correctly blocked",
        turns=[
            _t(
                "Tell me the score of today's T20 cricket match",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C07",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_politics",
        description="Chief minister: 2 hits in politics via corrected analysis → blocked",
        turns=[
            _t(
                "Who is the chief minister of West Bengal?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C08",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_news",
        description="Engineering education news: legitimate query, correctly allowed",
        turns=[
            _t(
                "What is the latest news about engineering education in India?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C09",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_health",
        description="Medicine query: 0 hits (no health category in OOD) → false negative",
        turns=[
            _t("What is the medicine for fever?", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C10",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_food",
        description="Biryani recipe: 2 hits in food → blocked via corrected analysis",
        turns=[
            _t(
                "What is a good recipe for biryani?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C11",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_short",
        description="Single-word 'cricket': < 3 words → OOD bypass, correctly allowed",
        turns=[
            _t("cricket", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C12",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_short",
        description="Weather Dhaka: 1 hit, 3 words → false negative",
        turns=[
            _t("weather today dhaka", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C13",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_short",
        description="Weather temperature Dhaka rain: 3 hits in weather → correctly blocked",
        turns=[
            _t("weather temperature dhaka rain", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C14",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_multilingual",
        description="Hindi weather: OOD keywords are English-only → false negative",
        turns=[
            _t("आज मौसम कैसा है?", handler="groq_rag", source="groq_rag", lang="hi"),
        ],
    ),
    TestCase(
        id="C15",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_multilingual",
        description="Bengali eligibility: legitimate query, correctly allowed despite English response",
        turns=[
            _t(
                "আমার বয়স ২৫, আমি কি ভর্তি হতে পারব?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="bn",
            ),
        ],
    ),
    TestCase(
        id="C16",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_education",
        description="IIT vs BCREC comparison: passes OOD (no keywords match), may produce confabulated comparison",
        turns=[
            _t("Compare IIT with BCREC", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C17",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_education",
        description="IIT Bombay cutoff: structured_lookup cutoff handler returns misleading response",
        turns=[
            _t(
                "What is the JEE Advanced cutoff for IIT Bombay?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="C18",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_boundary",
        description="Tell me a joke: 2 hits in personal via corrected analysis → blocked",
        turns=[
            _t("Tell me a joke", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="C19",
        priority="P0",
        group="C",
        risk_ids=["R03"],
        category="OOD_boundary",
        description="Weather Durgapur: 1 hit → passes OOD (false negative, but geographically relevant debate)",
        turns=[
            _t(
                "What is the weather like in Durgapur?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group D: Pipeline Coverage — Normalization + Validation
# ---------------------------------------------------------------------------

P0_GROUP_D: list[TestCase] = [
    TestCase(
        id="D01",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="normalization_stream",
        description="Double normalization in stream: normalize_query + _normalize_query",
        turns=[
            _t(
                "what is iml fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
                response_contains=["91,900"],
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="D02",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="normalization_stream",
        description="STT variant 'cse aml': normalization gap",
        turns=[
            _t("cse aml fee", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="D03",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="validation_rejection",
        description="Voice stutter 'um what is the fee': passes correctly",
        turns=[
            _t(
                "um what is the fee",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="D04",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="validation_ambiguous",
        description="Single-word 'fees' → ambiguous word clarification",
        turns=[
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="D05",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="validation_ambiguous_skip",
        description="Follow-up 'fees' after CSE fee: should use history to skip ambig (but doesn't)",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="D06",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="validation_skip_for_repeat",
        description="'repeat' is exempt from ambiguous word check",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("repeat", handler="repeat_replay", source="repeat_replay", lang="en"),
        ],
    ),
    TestCase(
        id="D07",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="noise_detection",
        description="Stutter 'yes yes yes yes' → filler acknowledgment (false positive)",
        turns=[
            _t(
                "yes yes yes yes",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="D08",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="noise_detection_order",
        description="Single-char noise 'a b c d e f' → noise detection fires correctly",
        turns=[
            _t(
                "a b c d e f",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="D09",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="validation_short_query",
        description="Single Hindi word 'क्या' → too short → clarification",
        turns=[
            _t(
                "क्या",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="hi",
            ),
        ],
    ),
    TestCase(
        id="D10",
        priority="P0",
        group="D",
        risk_ids=["R02"],
        category="normalization_mixed_script",
        description="Mixed Devanagari+English query → lang forced to Hindi, English response",
        turns=[
            _t(
                "CSE फीस कितना है?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
        ],
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group E: Language + Conversation State
# ---------------------------------------------------------------------------

P0_GROUP_E: list[TestCase] = [
    TestCase(
        id="E01",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_switch_stream",
        description="Language switch 'in bengali': generate re-runs query, stream switches lang only",
        turns=[
            _t(
                "CSE fee kya hai?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
            _t("in bengali", handler="structured_lookup", source="structured_lookup", lang="bn"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="E02",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_switch_stream",
        description="Language switch then repeat: generate replays in new lang, stream replays switch ack",
        turns=[
            _t(
                "What is the fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("hindi me", handler="structured_lookup", source="structured_lookup", lang="hi"),
            _t("repeat", handler="repeat_replay", source="repeat_replay", lang="hi"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="E03",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="conversation_state_stale",
        description="RAG-only turn does not update ConversationState → follow-up works via text-merge",
        turns=[
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("Tell me about placements in CSE", handler="groq_rag", source="groq_rag", lang="en"),
            _t("What about seats?", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="E04",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="conversation_state_stale",
        description="Structured HOD follow-up 'What about ECE?' → state-based expansion works",
        turns=[
            _t(
                "Who is the HOD of CSE?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
            _t(
                "What about ECE?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="E05",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="conversation_state_stale",
        description="Structured dept info → HOD follow-up: expansion doesn't use state for complete intents",
        turns=[
            _t(
                "Tell me about CSE department",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
            _t(
                "Who is the HOD?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="E06",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_inheritance_short",
        description="Short Hindi follow-up 'fees' inherits Hindi from previous turn → Hindi clarification",
        turns=[
            _t(
                "सीएसई फीस कितना है",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="hi",
            ),
        ],
    ),
    TestCase(
        id="E07",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_inheritance_short_roman",
        description="Roman Hindi follow-up 'kya hai' inherits English (short query rule) → language mismatch",
        turns=[
            _t(
                "What is the fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("kya hai", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="E08",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_inheritance_short_roman2",
        description="3-word Hindi-mixed 'fees kya hai' inherits English (≤3 word rule) → language mismatch",
        turns=[
            _t(
                "What is the fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("fees kya hai", handler="structured_lookup", source="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="E09",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_kw_threshold",
        description="5-word Roman Hindi → ≥2 markers → switches to Hindi correctly",
        turns=[
            _t(
                "What is the fee for CSE?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t(
                "mujhe hostel ke baare mein batao",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
        ],
    ),
    TestCase(
        id="E10",
        priority="P0",
        group="E",
        risk_ids=["R02"],
        category="lang_kw_threshold_explicit",
        description="Bengali explicit switch then 'fees' → inherits Bengali, Hindi clarification",
        turns=[
            _t("বাংলায় বলো", handler="structured_lookup", source="structured_lookup", lang="bn"),
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="bn",
            ),
        ],
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group F: Structured Lookup + Multi-Intent
# ---------------------------------------------------------------------------

P0_GROUP_F: list[TestCase] = [
    TestCase(
        id="F01",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="multi_intent_3plus",
        description="'fee and hostel and placement': 1-word left side prevents split → only fee returned",
        turns=[
            _t(
                "fee and hostel and placement",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=True,
    ),
    TestCase(
        id="F02",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="multi_intent_comma",
        description="Comma-separated 'hostel, fees, placement': single words fail ≥2 word check",
        turns=[
            _t(
                "hostel, fees, placement",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F03",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="multi_intent_2word",
        description="'CSE fee and hostel facilities': ≥2 words each → splits correctly in generate only",
        turns=[
            _t(
                "CSE fee and hostel facilities",
                handler="multi_intent",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="F04",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="multi_intent_generate_only",
        description="'fees for CSE and hostel for boys': splits correctly in generate only",
        turns=[
            _t(
                "fees for CSE and hostel for boys",
                handler="multi_intent",
                source="structured_lookup",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="F05",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_priority",
        description="'admission fee for CSE': admission_general fires before fee handler → wrong handler",
        turns=[
            _t(
                "admission fee for CSE",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F06",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_priority",
        description="'hostel fee for boys': hostel fires before fee handler → returns hostel info, not fee",
        turns=[
            _t(
                "hostel fee for boys",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F07",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_priority",
        description="'safety in hostel': safety handler fires correctly before hostel",
        turns=[
            _t(
                "safety in hostel",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F08",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_faculty",
        description="'professor contact': contact handler fires before faculty due to priority",
        turns=[
            _t(
                "professor contact",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F09",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_fallback",
        description="'Data Science placements': dept_code not recognized → falls to RAG",
        turns=[
            _t(
                "Which companies visit for placements in Data Science?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="F10",
        priority="P0",
        group="F",
        risk_ids=["R02"],
        category="structured_lookup_empty",
        description="CSD fee: FEE_GROUP_MAP should have CSD entry",
        turns=[
            _t(
                "What is the fee for CSD?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group G: RAG + LLM + Post-Processing
# ---------------------------------------------------------------------------

P0_GROUP_G: list[TestCase] = [
    TestCase(
        id="G01",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_stream",
        description="Hallucinated placement package: generate blocks, stream logs only",
        turns=[
            _t(
                "What is the average placement package for CSE?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"llm_response": "The average package is 25 LPA"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="G02",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_stream_phone",
        description="Hallucinated phone: generate blocks, stream logs only",
        turns=[
            _t(
                "What is the college phone number?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"llm_response": "Call 1800-123-4567"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="G03",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_guard_stream_vs_gen",
        description="Bengali hallucination: generate blocks, stream logs only",
        turns=[
            _t(
                "CSE fee koto?",
                handler="groq_rag",
                source="groq_rag",
                lang="bn",
                injection={"llm_response": "CSE total fee 5 lakh"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="G04",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_guard_placement_exempt",
        description="Placement query without numbers → exempt from hallucination guard",
        turns=[
            _t(
                "What is the placement rate for CSE?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="G05",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_guard_placement_numbers",
        description="Placement query with 2024 → not exempt, normal validation applies",
        turns=[
            _t(
                "What is the placement rate for CSE 2024?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="G06",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_guard_empty_context",
        description="Library timing on Sunday: empty context → low confidence guard fires",
        turns=[
            _t(
                "What is the library timing on Sunday?",
                handler="low_confidence_retrieval",
                source="low_confidence_retrieval",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="G07",
        priority="P0",
        group="G",
        risk_ids=["R01"],
        category="hallucination_guard_context_mismatch",
        description="Partial context with numbers from wrong dept → validation passes despite wrong answer",
        turns=[
            _t(
                "What is the fee for CSE?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"override_context": "ECE fee is 5,00,000"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="G08",
        priority="P0",
        group="G",
        risk_ids=["R02"],
        category="truncation_stream",
        description="450-char response: generate truncates at sentence boundary, stream mid-word",
        turns=[
            _t(
                "Tell me about hostel facilities at BCREC",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="G09",
        priority="P0",
        group="G",
        risk_ids=["R02"],
        category="out_of_kb_stream",
        description="Out-of-KB 'NAAC grade': generate blocks with phone, stream logs only",
        turns=[
            _t(
                "What is the college's NAAC grade?",
                handler="low_confidence_retrieval",
                source="low_confidence_retrieval",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group H: Long Multi-Turn + Voice-Specific
# ---------------------------------------------------------------------------

P0_GROUP_H: list[TestCase] = [
    TestCase(
        id="H01",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="long_voice_conversation",
        description="7-turn conversation: 3/7 turns differ between generate and stream",
        turns=[
            _t(
                "hello",
                handler="greeting_deterministic",
                source="greeting_deterministic",
                lang="en",
            ),
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t("hostel", handler="structured_lookup", source="structured_lookup", lang="en"),
            _t("in bengali", handler="structured_lookup", source="structured_lookup", lang="bn"),
            _t("repeat", handler="repeat_replay", source="repeat_replay", lang="bn"),
            _t(
                "fees",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="bn",
            ),
            _t("yes", handler="structured_lookup", source="structured_lookup", lang="bn"),
        ],
        expected_generate_stream_parity=False,
        requires_voice=True,
    ),
    TestCase(
        id="H02",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="long_multi_turn_state",
        description="Multi-turn state staleness across domain switches",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t(
                "what about ECE",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
            _t(
                "tell me about hostel",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
            _t("placement", handler="groq_rag", source="groq_rag", lang="en"),
            _t("and seats", handler="groq_rag", source="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="H03",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="voice_interruption",
        description="Incomplete fragment followed by correction: validation catches fragment",
        turns=[
            _t(
                "what is the",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
            _t(
                "what is the CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="H04",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="voice_correction",
        description="Correction 'no, tell me about CSE': expand does not handle corrections → merges with previous",
        turns=[
            _t("tell me about AIML", handler="groq_rag", source="groq_rag", lang="en"),
            _t("no, tell me about CSE", handler="groq_rag", source="groq_rag", lang="en"),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="H05",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="voice_filler_recovery",
        description="Filler 'ah' filtered, then normal fee query works",
        turns=[
            _t(
                "ah",
                handler="transcript_clarification",
                source="transcript_clarification",
                lang="en",
            ),
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="H06",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="voice_network_recovery",
        description="Disconnect-reconnect: session may or may not have saved partial turn",
        turns=[
            _t(
                "what is the CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="H07",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="multilingual_multi_turn",
        description="Hindi → hostel → english → repeat: language-ignorant handlers + no switch re-run in stream",
        turns=[
            _t(
                "CSE fee kya hai?",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
            _t(
                "hostel ke baare mein batao",
                handler="structured_lookup",
                source="structured_lookup",
                lang="hi",
            ),
            _t("in english", handler="structured_lookup", source="structured_lookup", lang="en"),
            _t("repeat", handler="repeat_replay", source="repeat_replay", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="H08",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="session_isolation",
        description="Concurrent sessions: session isolation works via session_id keys",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="H09",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="session_clear_mid_conversation",
        description="clear_session then re-ask: cache checked on fresh session",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="H10",
        priority="P0",
        group="H",
        risk_ids=["R02", "R01"],
        category="livekit_crash_recovery",
        description="Crash → new session: history lost, re-ask works as fresh",
        turns=[
            _t(
                "CSE fee",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
        requires_voice=True,
    ),
]

# ---------------------------------------------------------------------------
# P0 — Group I: Failure Injection
# ---------------------------------------------------------------------------

P0_GROUP_I: list[TestCase] = [
    TestCase(
        id="I01",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_timeout",
        description="LLM timeout with SAFEPOINT: arithmetic returns before LLM → no timeout",
        turns=[
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I02",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_timeout_rag",
        description="LLM timeout for placement query: structured handler returns before LLM",
        turns=[
            _t(
                "Tell me about CSE department placements",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I03",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_timeout_non_safepoint",
        description="Non-SAFEPOINT, empty retrieval: low-confidence guard fires before LLM",
        turns=[
            _t(
                "What is the college NAAC accreditation?",
                handler="low_confidence_retrieval",
                source="low_confidence_retrieval",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I04",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_timeout_genuine",
        description="Non-SAFEPOINT, confidence=0.5, LLM hangs → no timeout → hangs forever",
        turns=[
            _t(
                "Can you tell me more about the extracurricular activities?",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"mock_timeout": True},
            ),
        ],
        requires_llm_mock=True,
    ),
    TestCase(
        id="I05",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_429_all_models",
        description="429 for all models: structured query avoids LLM entirely",
        turns=[
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I06",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="llm_429_rag_query",
        description="429 for RAG query: retry chain x3 models x3 retries → eventual success or error",
        turns=[
            _t(
                "Tell me about college clubs",
                handler="groq_rag",
                source="groq_rag",
                lang="en",
                injection={"mock_429": True},
            ),
        ],
        requires_llm_mock=True,
    ),
    TestCase(
        id="I07",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="chromadb_unavailable",
        description="ChromaDB unavailable: structured lookup avoids RAG entirely",
        turns=[
            _t(
                "What is the CSE fee?",
                handler="structured_arithmetic",
                source="structured_arithmetic",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I08",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="chromadb_unavailable_rag",
        description="ChromaDB unavailable: establishment query intercepted by structured handler",
        turns=[
            _t(
                "Tell me about college history",
                handler="structured_lookup",
                source="structured_lookup",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I09",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="chromadb_unavailable_genuine_rag",
        description="ChromaDB unavailable for novel query: exception → empty context → low-confidence guard",
        turns=[
            _t(
                "What is the faculty-to-student ratio in the college?",
                handler="low_confidence_retrieval",
                source="low_confidence_retrieval",
                lang="en",
            ),
        ],
    ),
    TestCase(
        id="I10",
        priority="P0",
        group="I",
        risk_ids=["R01", "R02"],
        category="sarvam_stt_failure",
        description="Empty STT transcript → validation returns clarification",
        turns=[
            _t(
                "", handler="transcript_clarification", source="transcript_clarification", lang="en"
            ),
        ],
        requires_voice=True,
    ),
]

# ---------------------------------------------------------------------------
# P1 test cases (condensed — key cases from P1 catalog)
# ---------------------------------------------------------------------------

P1_CASES: list[TestCase] = [
    # ConversationState Staleness
    TestCase(
        id="P1-CS-001",
        priority="P1",
        group="CS",
        risk_ids=["R-CS", "R-WS"],
        category="conversation_state_stale",
        description="RAG-only turn does not update state; next fee query works from stale state",
        turns=[
            _t(
                "What is the total fee for CSE department?",
                handler="structured_arithmetic",
                lang="en",
            ),
            _t("How is the teaching quality?", handler="groq_rag", lang="en"),
            _t("also tell me about the fees", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-CS-002",
        priority="P1",
        group="CS",
        risk_ids=["R-CS", "R-FU"],
        category="conversation_state_stale",
        description="Cutoff follow-up lacks department from previous state",
        turns=[
            _t("What is the cutoff rank for CSE?", handler="structured_lookup", lang="en"),
            _t(
                "How many companies visited for placement last year?",
                handler="structured_lookup",
                lang="en",
            ),
            _t("what about the cutoff?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-CS-003",
        priority="P1",
        group="CS",
        risk_ids=["R-CS"],
        category="conversation_state_stale",
        description="Hostel → fee follow-up: general fee returned instead of hostel-specific fee",
        turns=[
            _t("Is hostel available at BCREC?", handler="structured_lookup", lang="en"),
            _t("what is the fee", handler="structured_lookup", lang="en"),
        ],
    ),
    # Multi-Turn Memory
    TestCase(
        id="P1-MM-001",
        priority="P1",
        group="MM",
        risk_ids=["R-FU"],
        category="multi_turn_memory",
        description="Department → 'what about fees?': fee handler doesn't carry department context",
        turns=[
            _t("Tell me about CSE department", handler="structured_lookup", lang="en"),
            _t("what about fees?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-MM-002",
        priority="P1",
        group="MM",
        risk_ids=["R-FU"],
        category="multi_turn_memory",
        description="HOD of CSE → 'how about ECE?': new_domain_blocked prevents expansion",
        turns=[
            _t("Who is the HOD of CSE?", handler="structured_lookup", lang="en"),
            _t("how about ECE?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-MM-003",
        priority="P1",
        group="MM",
        risk_ids=["R-FU"],
        category="multi_turn_memory",
        description="Fee → 'what about seats?': structured_fee_followup appends 'fee' incorrectly",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("and for ECE?", handler="structured_arithmetic", lang="en"),
            _t("what about seats?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-MM-005",
        priority="P1",
        group="MM",
        risk_ids=["R-FU"],
        category="multi_turn_memory",
        description="Fee → 'tell me about placement': placement handler lacks dept context",
        turns=[
            _t("What is the total fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("and for ECE?", handler="structured_arithmetic", lang="en"),
            _t("now tell me about placement", handler="groq_rag", lang="en"),
        ],
    ),
    # Cross-Domain Switching
    TestCase(
        id="P1-CD-002",
        priority="P1",
        group="CD",
        risk_ids=["R-CP"],
        category="cross_domain",
        description="Contact handler priority: 'contact number of admission office' hits contact not admission_office",
        turns=[
            _t("Who is the principal of BCREC?", handler="structured_lookup", lang="en"),
            _t(
                "what is the contact number of admission office?",
                handler="structured_lookup",
                lang="en",
            ),
        ],
    ),
    # Pronoun Resolution
    TestCase(
        id="P1-PR-002",
        priority="P1",
        group="PR",
        risk_ids=["R-FU"],
        category="pronoun_resolution",
        description="'what is the fee for it' after hostel: 'it' not resolved, general fee returned",
        turns=[
            _t("Tell me about hostel facilities", handler="structured_lookup", lang="en"),
            _t("what is the fee for it?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-PR-003",
        priority="P1",
        group="PR",
        risk_ids=["R-FU"],
        category="pronoun_resolution",
        description="'what is his email' after HOD query: new_domain_blocked + missing email handler",
        turns=[
            _t("Who is the HOD of ECE?", handler="structured_lookup", lang="en"),
            _t("what is his email?", handler="groq_rag", lang="en"),
        ],
    ),
    # Stream vs Generate Parity
    TestCase(
        id="P1-PG-001",
        priority="P1",
        group="PG",
        risk_ids=["R-EG", "R-MI"],
        category="stream_generate_parity",
        description="Multi-intent 'fee and hostel': generate splits, stream falls to RAG",
        turns=[
            _t(
                "What is the fee for CSE and also tell me about hostel?",
                handler="multi_intent",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-003",
        priority="P1",
        group="PG",
        risk_ids=["R-EG", "R-GR"],
        category="stream_generate_parity",
        description="Greeting 'Hello': generate returns structured greeting, stream goes to LLM",
        turns=[
            _t("Hello", handler="greeting_deterministic", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-004",
        priority="P1",
        group="PG",
        risk_ids=["R-EG", "R-HG"],
        category="stream_generate_parity",
        description="Hallucination guard: generate blocks, stream logs only",
        turns=[
            _t(
                "The fee for CSE is six lakh four thousand seven hundred rupees",
                handler="groq_rag",
                lang="en",
                injection={"llm_response": "Yes, that's correct"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="P1-PG-005",
        priority="P1",
        group="PG",
        risk_ids=["R-EG", "R-KB"],
        category="stream_generate_parity",
        description="Out-of-KB: generate adds phone, stream does not",
        turns=[
            _t("I don't think you have information about this", handler="groq_rag", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-006",
        priority="P1",
        group="PG",
        risk_ids=["R-EG"],
        category="stream_generate_parity",
        description="Bengali fee query: generate has টাকা normalization + TTS prep, stream does not",
        turns=[
            _t("সি এস ই এর ফি কত?", handler="structured_lookup", lang="bn"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-007",
        priority="P1",
        group="PG",
        risk_ids=["R-EG"],
        category="stream_generate_parity",
        description="Cache: generate caches, stream has no cache",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-008",
        priority="P1",
        group="PG",
        risk_ids=["R-EG"],
        category="stream_generate_parity",
        description="Language switch: generate re-runs previous question, stream does not",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("Switch to Hindi", handler="structured_lookup", lang="hi"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PG-009",
        priority="P1",
        group="PG",
        risk_ids=["R-EG"],
        category="stream_generate_parity",
        description="Yes/no continuation: generate re-routes, stream treats 'yes' as filler",
        turns=[
            _t("hostel", handler="transcript_clarification", lang="en"),
            _t("yes", handler="structured_lookup", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    # Prompt Query Differences
    TestCase(
        id="P1-PQ-001",
        priority="P1",
        group="PQ",
        risk_ids=["R-PQ"],
        category="prompt_query",
        description="Double normalization in stream: normalize_query + _normalize_query",
        turns=[
            _t("Tell me about cs e aml department", handler="groq_rag", lang="en"),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-PQ-002",
        priority="P1",
        group="PQ",
        risk_ids=["R-PQ"],
        category="prompt_query",
        description="Language switch query text: generate re-routes to previous, stream sends 'banglay bolo' as-is",
        turns=[
            _t("What is CSE fee?", handler="structured_arithmetic", lang="en"),
            _t("Banglay bolo", handler="structured_lookup", lang="bn"),
        ],
        expected_generate_stream_parity=False,
    ),
    # LLM Timeout/Retry
    TestCase(
        id="P1-LT-001",
        priority="P1",
        group="LT",
        risk_ids=["R-LT"],
        category="llm_timeout",
        description="429 rate limit: generate error has phone, stream generic apology",
        turns=[
            _t("What is the fee?", handler="error", lang="en", injection={"mock_429": True}),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="P1-LT-002",
        priority="P1",
        group="LT",
        risk_ids=["R-LT"],
        category="llm_timeout",
        description="SAFEPOINT timeout: generate returns filler in 6s, stream hangs",
        turns=[
            _t("What is the fee?", handler="groq_rag", lang="en", injection={"mock_timeout": True}),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="P1-LT-003",
        priority="P1",
        group="LT",
        risk_ids=["R-LT"],
        category="llm_timeout",
        description="500 error: generate has phone, stream generic apology",
        turns=[
            _t(
                "What is the fee?",
                handler="error",
                lang="en",
                injection={"mock_error": "GroqAPIError: 500 Internal Server Error"},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    TestCase(
        id="P1-LT-004",
        priority="P1",
        group="LT",
        risk_ids=["R-LT"],
        category="llm_timeout",
        description="Circuit breaker open: 10-30s delay before error, no fast-fail",
        turns=[
            _t(
                "What is the fee?",
                handler="error",
                lang="en",
                injection={"mock_circuit_open": True},
            ),
        ],
        expected_generate_stream_parity=False,
        requires_llm_mock=True,
    ),
    # RAG Retrieval Degradation
    TestCase(
        id="P1-RD-001",
        priority="P1",
        group="RD",
        risk_ids=["R-RD"],
        category="rag_degradation",
        description="Corrupted canonical_kb: structured_lookup falls through to RAG",
        turns=[
            _t("What is the placement rate for CSE?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-RD-004",
        priority="P1",
        group="RD",
        risk_ids=["R-RD"],
        category="rag_degradation",
        description="Follow-up 'what about it' expands to 'what about it fee' → poor RAG query",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("what about it?", handler="groq_rag", lang="en"),
        ],
    ),
    # Ranking Failures
    TestCase(
        id="P1-RF-001",
        priority="P1",
        group="RF",
        risk_ids=["R-RK"],
        category="ranking",
        description="Bengali query vs English: different rankings due to language penalty",
        turns=[
            _t("সি এস ই ডিপার্টমেন্টের ফি কত?", handler="structured_lookup", lang="bn"),
        ],
    ),
    TestCase(
        id="P1-RF-002",
        priority="P1",
        group="RF",
        risk_ids=["R-RK"],
        category="ranking",
        description="'fee and placement' single words → split fails, only fee returned",
        turns=[
            _t("fee and placement", handler="structured_lookup", lang="en"),
        ],
    ),
    # Comparison Reasoning
    TestCase(
        id="P1-CR-001",
        priority="P1",
        group="CR",
        risk_ids=["R-RD"],
        category="comparison",
        description="'Which has better placement CSE or ECE?': no comparison handler, returns single dept data",
        turns=[
            _t("Which has better placement, CSE or ECE?", handler="groq_rag", lang="en"),
        ],
    ),
    TestCase(
        id="P1-CR-002",
        priority="P1",
        group="CR",
        risk_ids=["R-RD"],
        category="comparison",
        description="'Is CSE better than ECE?': no comparison support, RAG fallback",
        turns=[
            _t("Is CSE better than ECE?", handler="groq_rag", lang="en"),
        ],
    ),
    # Aggregation Reasoning
    TestCase(
        id="P1-AR-001",
        priority="P1",
        group="AR",
        risk_ids=["R-RD"],
        category="aggregation",
        description="Total seats: generate has _calculate_seat_total, stream does not",
        turns=[
            _t(
                "What is the total number of seats in all B.Tech departments combined?",
                handler="structured_arithmetic",
                lang="en",
            ),
        ],
        expected_generate_stream_parity=False,
    ),
    TestCase(
        id="P1-AR-002",
        priority="P1",
        group="AR",
        risk_ids=["R-RD"],
        category="aggregation",
        description="Average placement package: uses canonical KB overall data",
        turns=[
            _t(
                "What is the average placement package of all departments?",
                handler="structured_lookup",
                lang="en",
            ),
        ],
    ),
    # Long Conversations
    TestCase(
        id="P1-LC-001",
        priority="P1",
        group="LC",
        risk_ids=["R-CW"],
        category="long_conversation",
        description="7-turn mixed conversation: structured queries independently resolvable",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("and for ECE?", handler="structured_arithmetic", lang="en"),
            _t("what about hostel?", handler="structured_lookup", lang="en"),
            _t("who is the HOD of CSE?", handler="structured_lookup", lang="en"),
            _t("tell me about placements", handler="groq_rag", lang="en"),
            _t("what is the cutoff for CSE?", handler="structured_lookup", lang="en"),
            _t("what about scholarships?", handler="structured_lookup", lang="en"),
        ],
    ),
    TestCase(
        id="P1-LC-002",
        priority="P1",
        group="LC",
        risk_ids=["R-CS", "R-WS"],
        category="long_conversation",
        description="Multiple RAG-only turns don't update state → fee query from stale state",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
            _t("How is the campus infrastructure?", handler="groq_rag", lang="en"),
            _t("what about fees again?", handler="structured_lookup", lang="en"),
        ],
    ),
    # Session Recovery
    TestCase(
        id="P1-SR-001",
        priority="P1",
        group="SR",
        risk_ids=["R-SR"],
        category="session_recovery",
        description="Session timeout → fresh session: follow-up fails without history",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
        ],
    ),
    # Voice-Specific
    TestCase(
        id="P1-VF-001",
        priority="P1",
        group="VF",
        risk_ids=["R-VT"],
        category="voice_flow",
        description="Voice 'hello': no greeting in stream → LLM-generated greeting",
        turns=[
            _t("hello", handler="greeting_deterministic", lang="en"),
        ],
        expected_generate_stream_parity=False,
        requires_voice=True,
    ),
    TestCase(
        id="P1-VF-004",
        priority="P1",
        group="VF",
        risk_ids=["R-VT"],
        category="voice_flow",
        description="Room disconnect during stream: race condition with session cleanup",
        turns=[
            _t("What is the CSE fee?", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
    # Sarvam STT/TTS
    TestCase(
        id="P1-ST-002",
        priority="P1",
        group="ST",
        risk_ids=["R-VT"],
        category="stt_acronyms",
        description="STT 'c s e' not normalized to 'CSE': structured_lookup may fail",
        turns=[
            _t("what is c s e fee", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="P1-ST-004",
        priority="P1",
        group="ST",
        risk_ids=["R-VT"],
        category="tts_failure",
        description="TTS failure: no fallback → silence",
        turns=[
            _t("What is the fee for CSE?", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="P1-ST-005",
        priority="P1",
        group="ST",
        risk_ids=["R-VT"],
        category="tts_failure",
        description="TTS WAV parsing: non-standard header produces garbage audio",
        turns=[
            _t("What is the fee?", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
    # Partial Transcripts
    TestCase(
        id="P1-PT-003",
        priority="P1",
        group="PT",
        risk_ids=["R-ST"],
        category="partial_transcript",
        description="'um' hesitation: not in FILLER_ONLY_PATTERNS → triggers clarification",
        turns=[
            _t("um", handler="transcript_clarification", lang="en"),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="P1-PT-004",
        priority="P1",
        group="PT",
        risk_ids=["R-ST"],
        category="partial_transcript",
        description="'fee um': hesitation not stripped before structured lookup",
        turns=[
            _t("fee um", handler="structured_lookup", lang="en"),
        ],
        requires_voice=True,
    ),
    # Interruptions
    TestCase(
        id="P1-IN-001",
        priority="P1",
        group="IN",
        risk_ids=["R-VT"],
        category="interruption",
        description="Stream cancelled mid-execution: state corruption race condition",
        turns=[
            _t("What is the CSE fee?", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
    # Barge-in
    TestCase(
        id="P1-BG-001",
        priority="P1",
        group="BG",
        risk_ids=["R-VT"],
        category="barge_in",
        description="'stop': treated as partial transcript, triggers clarification",
        turns=[
            _t("stop", handler="transcript_clarification", lang="en"),
        ],
        requires_voice=True,
    ),
    TestCase(
        id="P1-BG-003",
        priority="P1",
        group="BG",
        risk_ids=["R-VT"],
        category="barge_in",
        description="'yes' after clarification: stream treats as filler, generate re-routes",
        turns=[
            _t("hostel", handler="transcript_clarification", lang="en"),
            _t("yes", handler="structured_lookup", lang="en"),
        ],
        expected_generate_stream_parity=False,
        requires_voice=True,
    ),
    # Duplicate STT Events
    TestCase(
        id="P1-DS-002",
        priority="P1",
        group="DS",
        risk_ids=["R-VT"],
        category="duplicate_stt",
        description="Concurrent STT events: race condition on session state",
        turns=[
            _t("What is the fee?", handler="structured_arithmetic", lang="en"),
        ],
        requires_voice=True,
    ),
]


# ---------------------------------------------------------------------------
# Aggregated lists
# ---------------------------------------------------------------------------

P0_CASES: list[TestCase] = (
    P0_GROUP_A
    + P0_GROUP_B
    + P0_GROUP_C
    + P0_GROUP_D
    + P0_GROUP_E
    + P0_GROUP_F
    + P0_GROUP_G
    + P0_GROUP_H
    + P0_GROUP_I
)

ALL_CASES: list[TestCase] = P0_CASES + P1_CASES

# Summary statistics
SUMMARY = {
    "P0": len(P0_CASES),
    "P1": len(P1_CASES),
    "total": len(ALL_CASES),
    "require_llm_mock": sum(1 for c in ALL_CASES if c.requires_llm_mock),
    "require_voice": sum(1 for c in ALL_CASES if c.requires_voice),
    "parity_fail_expected": sum(1 for c in ALL_CASES if not c.expected_generate_stream_parity),
}
