import pytest
from app.services.conversation.intent import (
    IntentClassifier,
    _is_pure_greeting,
    _word_boundary_match,
    Intent,
)
from app.services.conversation.context import ConversationContext


@pytest.fixture
def classifier():
    return IntentClassifier()


@pytest.fixture
def context():
    ctx = ConversationContext(session_id="test")
    ctx.previous_user_question = "What is the fee for B.Tech?"
    return ctx


class TestPureGreetings:
    def test_single_word_greetings(self, classifier):
        for greeting in ["hello", "hi", "hey", "hii", "hiii", "namaste"]:
            assert classifier.classify(greeting) == Intent.GREETING, (
                f"'{greeting}' should be GREETING"
            )

    def test_multi_word_greetings(self, classifier):
        for greeting in [
            "good morning",
            "good evening",
            "good afternoon",
            "good night",
            "hello there",
        ]:
            assert classifier.classify(greeting) == Intent.GREETING, (
                f"'{greeting}' should be GREETING"
            )

    def test_greeting_with_punctuation(self, classifier):
        assert classifier.classify("hello!") == Intent.GREETING
        assert classifier.classify("hi,") == Intent.GREETING
        assert classifier.classify("good morning!") == Intent.GREETING

    def test_case_insensitive(self, classifier):
        assert classifier.classify("HELLO") == Intent.GREETING
        assert classifier.classify("Good Morning") == Intent.GREETING

    def test_whitespace_handling(self, classifier):
        assert classifier.classify("  hello  ") == Intent.GREETING
        assert classifier.classify("\thello\n") == Intent.GREETING

    def test_multilingual_greetings(self, classifier):
        assert classifier.classify("नमस्ते") == Intent.GREETING
        assert classifier.classify("vanakkam") == Intent.GREETING


class TestGreetingPlusQuestion:
    def test_hello_with_question(self, classifier):
        assert classifier.classify("hello, what is the B.Tech fee?") == Intent.COLLEGE_INFO

    def test_hi_with_admission_query(self, classifier):
        assert classifier.classify("hi, I want admission in AIML") == Intent.COLLEGE_INFO

    def test_good_morning_with_hostel_query(self, classifier):
        assert (
            classifier.classify("good morning, can you tell me about hostel fees?")
            == Intent.COLLEGE_INFO
        )

    def test_hey_with_query(self, classifier):
        assert classifier.classify("hey what courses do you offer") == Intent.COLLEGE_INFO

    def test_greeting_then_substantive(self, classifier):
        assert classifier.classify("hello what is the fee structure") == Intent.COLLEGE_INFO
        assert classifier.classify("hi tell me about placements") == Intent.COLLEGE_INFO


class TestSubstringFalsePositives:
    def test_which_no_longer_triggers_greeting(self, classifier):
        assert classifier.classify("which courses are available?") != Intent.GREETING

    def test_this_no_longer_triggers_greeting(self, classifier):
        assert classifier.classify("this college has good placement") != Intent.GREETING

    def test_normal_questions_safe(self, classifier):
        for q in [
            "what is the admission process",
            "tell me about fees",
            "where is the college located",
        ]:
            assert classifier.classify(q) != Intent.GREETING, f"'{q}' should not be GREETING"


class TestOtherIntents:
    def test_thanks(self, classifier):
        assert classifier.classify("thank you") == Intent.THANKS
        assert classifier.classify("thanks") == Intent.THANKS
        assert classifier.classify("thanks a lot") == Intent.THANKS

    def test_goodbye(self, classifier):
        assert classifier.classify("goodbye") == Intent.GOODBYE
        assert classifier.classify("see you") == Intent.GOODBYE
        assert classifier.classify("take care") == Intent.GOODBYE

    def test_small_talk(self, classifier):
        assert classifier.classify("how are you") == Intent.SMALL_TALK
        assert classifier.classify("what can you do") == Intent.SMALL_TALK

    def test_confirmation(self, classifier):
        assert classifier.classify("yes") == Intent.CONFIRMATION
        assert classifier.classify("no") == Intent.CONFIRMATION

    def test_audio_check(self, classifier):
        assert classifier.classify("can you hear me") == Intent.AUDIO_CHECK
        assert classifier.classify("testing") == Intent.AUDIO_CHECK
        assert classifier.classify("hello hello") == Intent.AUDIO_CHECK

    def test_follow_up(self, classifier, context):
        assert classifier.classify("how much?", context) == Intent.FOLLOW_UP
        assert classifier.classify("tell me more", context) == Intent.FOLLOW_UP


class TestEmptyQuery:
    def test_empty_returns_greeting(self, classifier):
        assert classifier.classify("") == Intent.GREETING
        assert classifier.classify("   ") == Intent.GREETING


class TestPureGreetingHelper:
    def test_pure_greetings(self):
        assert _is_pure_greeting("hello") is True
        assert _is_pure_greeting("hi") is True
        assert _is_pure_greeting("hello there") is True
        assert _is_pure_greeting("good morning") is True

    def test_mixed_greetings(self):
        assert _is_pure_greeting("hello what is the fee") is False
        assert _is_pure_greeting("hi i want admission") is False
        assert _is_pure_greeting("good morning tell me about fees") is False

    def test_non_greetings(self):
        assert _is_pure_greeting("which courses") is False
        assert _is_pure_greeting("admission process") is False


class TestWordBoundaryMatch:
    def test_exact_match(self):
        assert _word_boundary_match("hello", "hello") is True
        assert _word_boundary_match("hi", "hi") is True

    def test_substring_no_match(self):
        assert _word_boundary_match("hi", "which") is False
        assert _word_boundary_match("hi", "this") is False
        assert _word_boundary_match("hello", "helloworld") is False

    def test_word_boundary_match(self):
        assert _word_boundary_match("hello", "hello world") is True
        assert _word_boundary_match("hi", "say hi") is True
        assert _word_boundary_match("good morning", "good morning all") is True

    def test_no_false_positive(self):
        assert _word_boundary_match("he", "she") is False
        assert _word_boundary_match("an", "thank") is False
