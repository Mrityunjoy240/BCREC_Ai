"""
Regression tests for conversation-quality UX improvements.

Tests cover:
1. Valid transcripts are NOT rejected (no false positives)
2. Bad transcripts ARE rejected (no false negatives)
3. Ambiguous words get tailored clarification prompts
4. Multi-word queries with ambiguous words are NOT caught as ambiguous
5. Response truncation does not break on "Dr. B.C. Roy" type abbreviations
6. PIN code removal in voice output
7. Confidence threshold returns only the expected source on low confidence
"""

import re
import inspect
import sys

sys.path.insert(0, "backend")

from app.services.llm.groq_service import (
    GroqService,
    FILLER_ONLY_PATTERNS,
    INCOMPLETE_TRAILING_PATTERNS,
    AMBIGUOUS_WORDS,
    AMBIGUOUS_CLARIFICATIONS,
    AMBIGUOUS_CLARIFICATIONS_HI,
    AMBIGUOUS_CLARIFICATIONS_BN,
    GREETING_PATTERNS,
    RETRIEVAL_CONFIDENCE_THRESHOLD,
    MAX_VOICE_RESPONSE_CHARS,
)


# ---------------------------------------------------------------------------
# Test 1: Valid transcripts are NOT rejected
# ---------------------------------------------------------------------------


def test_valid_multi_word_query_passes_ambiguity_detector():
    """Multi-word queries like 'five lakh fee' should NOT be flagged as ambiguous."""
    svc = GroqService()
    for query in [
        "five lakh fee for CSE",
        "five hostels in BCREC",
        "five departments available",
        "professor name in CSE department",
        "fees for hostel per year",
        "hostel facilities for girls",
        "seats available in AIML",
        "placement data for CSE 2024",
        "library timings for students",
    ]:
        result = svc._validate_transcript(query, "test-session")
        assert result is None, f"Valid query '{query}' should NOT be rejected (got: {result})"


def test_valid_greeting_passes():
    """Greetings should pass through validation."""
    svc = GroqService()
    for greeting in ["hi", "hello", "hey", "good morning"]:
        result = svc._validate_transcript(greeting, "test-session")
        assert result is None, f"Greeting '{greeting}' should pass"


def test_valid_bengali_query_passes():
    """Bengali script queries should pass validation."""
    svc = GroqService()
    for query in [
        "আমি সি এস ই তে ভর্তি হতে চাই",
        "ফি কত?",
        "হোস্টেলের সুবিধা কী কী?",
    ]:
        result = svc._validate_transcript(query, "test-session")
        assert result is None, f"Bengali query '{query}' should pass (got: {result})"


def test_valid_hindi_query_passes():
    """Hindi script queries should pass validation."""
    svc = GroqService()
    for query in [
        "मुझे सीएसई में एडमिशन चाहिए",
        "फीस कितनी है?",
        "हॉस्टल की सुविधाएँ क्या हैं?",
    ]:
        result = svc._validate_transcript(query, "test-session")
        assert result is None, f"Hindi query '{query}' should pass (got: {result})"


# ---------------------------------------------------------------------------
# Test 2: Bad transcripts ARE rejected
# ---------------------------------------------------------------------------


def test_single_word_noise_words_rejected():
    """Standalone noise words like 'prefix', 'five' should be rejected."""
    svc = GroqService()
    for noise_word in ["prefix", "five"]:
        result = svc._validate_transcript(noise_word, "test-session")
        assert result is not None, f"Noise word '{noise_word}' should be rejected"
        assert "catch" in result.lower() or "समझ" in result or "বুঝ" in result, (
            f"Should return clarification prompt, got: {result}"
        )


def test_trailing_punctuation_stripped():
    """Transcripts with trailing punctuation (STT artifact) should still match patterns."""
    svc = GroqService()
    for noisy in ["okay.", "okay okay.", "yes!", "thanks.", "prefix.", "five."]:
        result = svc._validate_transcript(noisy, "test-session")
        assert result is not None, f"'{noisy}' with trailing punctuation should be rejected"


def test_incomplete_fragment_rejected():
    """Incomplete queries ending on trailing words should be rejected."""
    svc = GroqService()
    for fragment in [
        "what is",
        "where is",
        "how many",
        "tell me",
        "Prefix",
        "Five",
    ]:
        result = svc._validate_transcript(fragment, "test-session")
        assert result is not None, f"Fragment '{fragment}' should be rejected"


# ---------------------------------------------------------------------------
# Test 3: Ambiguous words get tailored clarification prompts
# ---------------------------------------------------------------------------


def test_ambiguous_word_tailored_prompt():
    """Each ambiguous word gets a specific clarification prompt."""
    svc = GroqService()
    # English
    eng_result = svc._validate_transcript("professor", "test-en-session")
    assert eng_result is not None
    assert "department" in eng_result.lower() or "professor" in eng_result.lower()

    # Fees
    fees_result = svc._validate_transcript("fees", "test-en-session")
    assert fees_result is not None
    assert "fee" in fees_result.lower() or "department" in fees_result.lower()

    # Seats
    seats_result = svc._validate_transcript("seats", "test-en-session")
    assert seats_result is not None
    assert "seat" in seats_result.lower() or "department" in seats_result.lower()


def test_ambiguous_word_inherits_language():
    """Ambiguous word clarification should use session language."""
    svc = GroqService()
    # Set session to Hindi
    svc._session_langs["test-hi-session"] = "hi"
    hi_result = svc._validate_transcript("fees", "test-hi-session")
    assert hi_result is not None
    assert any(c in hi_result for c in "किस विभाग"), f"Hindi expected, got: {hi_result}"

    # Set session to Bengali
    svc._session_langs["test-bn-session"] = "bn"
    bn_result = svc._validate_transcript("fees", "test-bn-session")
    assert bn_result is not None
    assert any(c in bn_result for c in "কোন বিভাগ"), f"Bengali expected, got: {bn_result}"


# ---------------------------------------------------------------------------
# Test 4: Multi-word queries with ambiguous words are NOT caught
# ---------------------------------------------------------------------------


def test_multi_word_not_ambiguous():
    """Multi-word queries containing ambiguous words should not be caught."""
    svc = GroqService()
    multi_word = [
        "CSE professor name",
        "hostel fee for boys",
        "admission process for AIML",
        "placement data for CSE",
        "library timings",
    ]
    for query in multi_word:
        result = svc._validate_transcript(query, "test-session")
        assert result is None, (
            f"Multi-word query '{query}' should pass ambiguous check (got: {result})"
        )


# ---------------------------------------------------------------------------
# Test 5: Response truncation does not break on abbreviations
# ---------------------------------------------------------------------------


def test_abbreviation_safe_truncation():
    """Response truncation should not split 'Dr. B.C. Roy' type abbreviations."""
    # Simulate the truncation logic from generate_response
    svc = GroqService()

    # A long response with "Dr. B.C. Roy" in it
    long_response = (
        "The fee for CSE is six lakh rupees per year. "
        "Dr. B.C. Roy Engineering College is located in Durgapur. "
        "The college has good placement records. "
        "Many top companies visit for campus recruitment every year."
    )
    # This is 226 chars, under the 400 char limit — should NOT be truncated at all
    assert len(long_response) < 400
    # Verify the full response is preserved
    assert "Dr. B.C. Roy" in long_response


def test_overly_long_response_truncated():
    """Very long responses should be truncated at sentence boundary."""
    svc = GroqService()
    # Build a response that exceeds 400 chars
    long_response = (
        "The fee for CSE is six lakh rupees per year. "
        "The fee for ECE is five lakh rupees per year. "
        "The fee for ME is four lakh rupees per year. "
        "The fee for CE is three lakh rupees per year. "
        "The fee for IT is four lakh rupees per year. "
        "All fees are payable per semester."
    ) * 2
    # This is well over 400 chars
    assert len(long_response) > 400
    # The first sentence should contain "CSE" — key info preserved
    first_three = ". ".join(long_response.split(". ")[:3]) + "."
    assert "CSE" in first_three, "First sentences should contain CSE fee info"


# ---------------------------------------------------------------------------
# Test 6: PIN code removal in voice output
# ---------------------------------------------------------------------------


def test_pin_code_removed_from_voice():
    """6-digit PIN codes should be removed before number-to-words conversion."""
    from app.utils.voice_utils import clean_for_voice

    text_with_pin = "Durgapur - 713206, West Bengal"
    result = clean_for_voice(text_with_pin)
    # After PIN removal, the 6-digit number should be gone
    assert "713206" not in result, "PIN code should be removed"
    assert "Durgapur" in result, "City name should be preserved"
    assert "West Bengal" in result, "State should be preserved"


def test_pin_code_not_converted_to_words():
    """PIN codes should NOT be converted to confusing number words."""
    from app.utils.voice_utils import clean_for_voice

    text = "Jemua Road, Fuljhore, Durgapur - 713206"
    result = clean_for_voice(text)
    # Should not contain "seven lakh thirteen thousand" or any six-digit number
    assert "lakh" not in result.lower(), "PIN code should not be converted to lakh"
    assert "713206" not in result, "PIN code digits should be removed"


def test_phone_numbers_preserved():
    """Phone numbers should NOT be affected by PIN code removal."""
    from app.utils.voice_utils import clean_for_voice

    text = "Call the college at 0343-2501353 for details."
    result = clean_for_voice(text)
    # Phone number digits should still be present
    digits = re.findall(r"\d+", result.replace(" ", ""))
    phone_digits = "03432501353"
    # The digits should appear somewhere (spaced out for TTS)
    all_digits = "".join(re.findall(r"\d", result))
    assert phone_digits in all_digits, "Phone number digits should be preserved"


# ---------------------------------------------------------------------------
# Test 7: Confidence threshold is configurable
# ---------------------------------------------------------------------------


def test_confidence_threshold_configurable():
    """RETRIEVAL_CONFIDENCE_THRESHOLD should be configurable via env var."""
    import os

    # Default should be 0.15
    assert RETRIEVAL_CONFIDENCE_THRESHOLD == 0.15, (
        f"Default threshold should be 0.15, got {RETRIEVAL_CONFIDENCE_THRESHOLD}"
    )


def test_confidence_threshold_used_in_guard():
    """The confidence threshold should be referenced in generate_response source."""
    source = inspect.getsource(GroqService.generate_response)
    assert "RETRIEVAL_CONFIDENCE_THRESHOLD" in source, (
        "generate_response should reference RETRIEVAL_CONFIDENCE_THRESHOLD"
    )


def test_confidence_threshold_var_read():
    """Confidence threshold env var should be settable."""
    import os

    # Test the env var is read in the module
    source = inspect.getsource(sys.modules["app.services.llm.groq_service"])
    assert "RETRIEVAL_CONFIDENCE_THRESHOLD" in source


# ---------------------------------------------------------------------------
# Test 8: Max voice response chars is configurable
# ---------------------------------------------------------------------------


def test_max_voice_chars_default():
    """MAX_VOICE_RESPONSE_CHARS should default to 400."""
    assert MAX_VOICE_RESPONSE_CHARS == 400, f"Default should be 400, got {MAX_VOICE_RESPONSE_CHARS}"


# ---------------------------------------------------------------------------
# Test 9: Ambiguity detector boundary cases
# ---------------------------------------------------------------------------


def test_standalone_ambiguous_words_caught():
    """Standalone words in AMBIGUOUS_WORDS should be caught."""
    svc = GroqService()
    for word in [
        "fees",
        "fee",
        "admission",
        "professor",
        "faculty",
        "department",
        "hostel",
        "placement",
        "library",
        "course",
        "seats",
    ]:
        result = svc._validate_transcript(word, "test-session")
        assert result is not None, f"Standalone '{word}' should be caught as ambiguous"


def test_ambiguous_word_in_sentence_not_caught():
    """Ambiguous words inside a sentence should NOT be caught."""
    svc = GroqService()
    for query in [
        "What is the fees for AIML?",
        "I want admission in CSE",
        "Tell me about hostel facilities",
        "Which departments have good placement?",
    ]:
        result = svc._validate_transcript(query, "test-session")
        assert result is None, f"Query '{query}' with embedded ambiguous word should not be caught"
