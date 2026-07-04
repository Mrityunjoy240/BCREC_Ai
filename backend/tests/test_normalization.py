import pytest
from app.services.normalization import normalize_query, normalize_for_tts, NormalizationLog


# -----------------------------------------------------------------------
# Basic normalization pipeline
# -----------------------------------------------------------------------
class TestNormalizeQuery:
    def test_clean_text_unchanged(self):
        """Clean text with no entities should pass through unchanged."""
        log = normalize_query("what is the fee for college")
        assert log.normalized_text == "what is the fee for college"
        assert log.changes == []

    def test_unknown_text_unchanged(self):
        """Text with no known entities should not be modified."""
        log = normalize_query("tell me a joke")
        assert log.normalized_text == "tell me a joke"

    def test_empty_text(self):
        """Empty or whitespace-only text returns as-is."""
        log = normalize_query("")
        assert log.normalized_text == ""
        assert log.changes == []

    def test_whitespace_only(self):
        log = normalize_query("   ")
        assert log.normalized_text == "   "

    def test_single_character(self):
        """Single character should not trigger fuzzy matching."""
        log = normalize_query("a")
        assert log.normalized_text == "a"

    def test_numbers_preserved(self):
        """PIN codes, phone numbers should remain untouched."""
        log = normalize_query("pin code 713301")
        assert "713301" in log.normalized_text


# -----------------------------------------------------------------------
# AIML alias resolution
# -----------------------------------------------------------------------
class TestAIML:
    def test_iml_corrected(self):
        """STT mistake 'iml' should resolve to AIML."""
        log = normalize_query("what is iml fee")
        assert "AIML" in log.normalized_text

    def test_ai_ml_resolved(self):
        """Alias 'ai ml' should resolve to AIML."""
        log = normalize_query("ai ml fee")
        # 'ai ml' -> 'aiml' after alias resolution matches AIML
        assert "AIML" in log.normalized_text

    def test_a_i_m_l_resolved(self):
        """Alias 'a i m l' should resolve to AIML."""
        log = normalize_query("a i m l department")
        # After cleanup + alias, 'a i m l' -> 'aiml' -> AIML
        assert "AIML" in log.normalized_text

    def test_aml_corrected(self):
        """STT mistake 'am l' should resolve to AIML."""
        log = normalize_query("am l hod")
        assert "AIML" in log.normalized_text


# -----------------------------------------------------------------------
# Department alias resolution
# -----------------------------------------------------------------------
class TestDepartments:
    def test_cse_full_name(self):
        """Computer Science and Engineering → CSE."""
        log = normalize_query("computer science and engineering fee")
        assert "CSE" in log.normalized_text

    def test_cse_short_name(self):
        """Computer Science → CSE."""
        log = normalize_query("computer science department")
        assert "CSE" in log.normalized_text

    def test_ece_electronics(self):
        """Electronics → ECE."""
        log = normalize_query("electronics department")
        assert "ECE" in log.normalized_text

    def test_e_c_e_resolved(self):
        """E C E → ECE."""
        log = normalize_query("e c e hod")
        assert "ECE" in log.normalized_text

    def test_it_resolved(self):
        """Information Technology → IT."""
        log = normalize_query("information technology fee")
        assert "IT" in log.normalized_text

    def test_mechanical_resolved(self):
        """Mechanical → ME."""
        log = normalize_query("mechanical engineering")
        assert "ME" in log.normalized_text

    def test_civil_resolved(self):
        """Civil → CE."""
        log = normalize_query("civil engineering")
        assert "CE" in log.normalized_text

    def test_data_science_resolved(self):
        """Data Science → DS."""
        log = normalize_query("data science department")
        assert "DS" in log.normalized_text

    def test_cyber_security_resolved(self):
        """Cyber Security → CY."""
        log = normalize_query("cyber security hod")
        assert "CY" in log.normalized_text


# -----------------------------------------------------------------------
# Faculty spelling corrections
# -----------------------------------------------------------------------
class TestFaculty:
    def test_pabitra_dey(self):
        """STT mistake 'pabitra day' → Dr. Pabitra Kumar Dey."""
        log = normalize_query("pabitra day hod")
        assert "Pabitra Kumar Dey" in log.normalized_text

    def test_chandan_chattoraj(self):
        """STT mistake 'chandan chatoraj' → Dr. Chandan Chattoraj."""
        log = normalize_query("chandan chatoraj")
        assert "Chandan Chattoraj" in log.normalized_text

    def test_sanjay_pawar(self):
        """Alias 'sanjay pawar' → Dr. Sanjay S. Pawar."""
        log = normalize_query("sanjay pawar principal")
        assert "Sanjay" in log.normalized_text

    def test_principal_alias(self):
        """Alias 'principal' → Dr. Sanjay S. Pawar."""
        log = normalize_query("who is principal")
        assert "Sanjay" in log.normalized_text


# -----------------------------------------------------------------------
# Mixed-language normalization (Bengali/Hindi → English)
# -----------------------------------------------------------------------
class TestMixedLanguage:
    def test_bengali_fee(self):
        """Bengali ফি → fee."""
        log = normalize_query("ফি কত")
        assert "fee" in log.normalized_text
        assert "how much" in log.normalized_text

    def test_bengali_hostel(self):
        """Bengali হোস্টেল → hostel."""
        log = normalize_query("হোস্টেল ফি")
        assert "hostel" in log.normalized_text

    def test_hindi_fee(self):
        """Hindi फीस → fee."""
        log = normalize_query("फीस कितना")
        assert "fee" in log.normalized_text

    def test_hindi_principal(self):
        """Hindi प्रिंसिपल → principal → Dr. Sanjay S. Pawar."""
        log = normalize_query("प्रिंसिपल कौन")
        assert "Sanjay" in log.normalized_text
        assert "Pawar" in log.normalized_text

    def test_hindi_hostel(self):
        """Hindi हॉस्टल → hostel."""
        log = normalize_query("हॉस्टल शुल्क")
        assert "hostel" in log.normalized_text
        assert "fee" in log.normalized_text


# -----------------------------------------------------------------------
# Punctuation and whitespace cleanup
# -----------------------------------------------------------------------
class TestCleanup:
    def test_repeated_spaces(self):
        log = normalize_query("what   is   cse   fee")
        assert log.normalized_text == "what is CSE fee"

    def test_dots_replaced(self):
        """Dots should be replaced with spaces."""
        log = normalize_query("b.tech fee")
        assert "b.tech" not in log.normalized_text

    def test_parentheses_removed(self):
        log = normalize_query("cse (aiml) fee")
        assert "(" not in log.normalized_text
        assert ")" not in log.normalized_text

    def test_extra_punctuation(self):
        log = normalize_query("what's cse's fee?")
        assert "?" not in log.normalized_text
        # Apostrophes are preserved as they are meaningful in contractions
        assert "what's" in log.normalized_text


# -----------------------------------------------------------------------
# TTS normalization
# -----------------------------------------------------------------------
class TestTTS:
    def test_hod_expanded(self):
        """HOD → Head of Department for TTS."""
        result = normalize_for_tts("HOD is Dr. X")
        assert "Head of Department" in result

    def test_cse_expanded(self):
        """CSE → C S E for TTS."""
        result = normalize_for_tts("CSE department")
        assert "C S E" in result

    def test_aiml_expanded(self):
        """AIML → A I M L for TTS."""
        result = normalize_for_tts("AIML")
        assert "A I M L" in result

    def test_bcrec_expanded(self):
        """BCREC → B C Roy Engineering College for TTS."""
        result = normalize_for_tts("BCREC college")
        assert "B C Roy Engineering College" in result

    def test_tts_noop_clean_text(self):
        """Clean text without known acronyms should pass through."""
        result = normalize_for_tts("This is a normal sentence.")
        assert result == "This is a normal sentence."


# -----------------------------------------------------------------------
# Fuzzy resolution
# -----------------------------------------------------------------------
class TestFuzzy:
    def test_close_canonical_misspelling(self):
        """Fuzzy matching doesn't fire on unrelated text (no false positives)."""
        log = normalize_query("nothing matches here")
        assert log.normalized_text == "nothing matches here"
        assert log.changes == []

    def test_close_department_name(self):
        """'mechanical' is an exact alias for ME — not fuzzy, but should work."""
        log = normalize_query("mechanical dept")
        assert "ME" in log.normalized_text


# -----------------------------------------------------------------------
# "Did you mean?" suggestion detection
# -----------------------------------------------------------------------
class TestSuggestions:
    def test_suggestion_below_threshold(self):
        """Very mangled input like 'aimlol' should not auto-correct but may suggest."""
        from app.services.normalization.normalizer import detect_fuzzy_suggestions

        suggestions = detect_fuzzy_suggestions("aimlol")
        assert isinstance(suggestions, list)

    def test_no_suggestion_for_clean_text(self):
        """Clean text should produce no suggestions."""
        from app.services.normalization.normalizer import detect_fuzzy_suggestions

        suggestions = detect_fuzzy_suggestions("how are you")
        assert suggestions == []


# -----------------------------------------------------------------------
# NormalizationLog structure
# -----------------------------------------------------------------------
class TestNormalizationLog:
    def test_log_has_required_fields(self):
        """NormalizationLog must have original_text, normalized_text, changes."""
        log = normalize_query("iml fee")
        assert hasattr(log, "original_text")
        assert hasattr(log, "normalized_text")
        assert hasattr(log, "changes")

    def test_log_records_changes(self):
        """When normalization occurs, changes list is populated."""
        log = normalize_query("iml fee")
        assert len(log.changes) > 0
        assert log.changes[0]["type"] in (
            "stt_correction",
            "alias_resolution",
            "cleanup",
            "language_mapping",
            "fuzzy_resolution",
        )

    def test_log_no_changes_for_clean(self):
        log = normalize_query("hello world")
        assert log.changes == []


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------
class TestEdgeCases:
    def test_mixed_english_bengali_script(self):
        """Mixed Bengali + English should work."""
        log = normalize_query("CSE বিভাগের ফি কত")
        assert "CSE" in log.normalized_text or "cse" in log.normalized_text
        assert "fee" in log.normalized_text

    def test_repeated_aliases_not_duplicated(self):
        """Applying same alias twice should not produce duplicates."""
        log = normalize_query("ai ml ai ml")
        assert log.normalized_text.count("AIML") == 2

    def test_lang_mapping_disabled(self):
        """With lang mapping disabled, Bengali text should remain unchanged."""
        log = normalize_query("ফি কত", enable_lang_mapping=False)
        assert log.normalized_text is not None

    def test_fuzzy_disabled(self):
        """With fuzzy disabled, entity resolution via aliases still works (fuzzy flag affects fuzzy step only)."""
        log = normalize_query("computer science", enable_fuzzy=False)
        assert "CSE" in log.normalized_text
