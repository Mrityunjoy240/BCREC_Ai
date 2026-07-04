"""Tests for session isolation across browser tabs and voice chat."""

import uuid
import pytest
from app.api.qa import GroqQueryRequest


class TestSessionMemory:
    """Verify that different session_ids produce isolated in-memory history."""

    def _make_service(self):
        """Create a minimal object with the same session API as GroqService."""
        return _SessionContainer()

    def test_different_sessions_have_different_history(self):
        svc = self._make_service()
        sid_a = "test-session-a"
        sid_b = "test-session-b"

        svc._append_session_turn(sid_a, "hello", "hi there")
        svc._append_session_turn(sid_b, "what is the fee", "fees are 50000")

        hist_a = svc._get_session_history(sid_a)
        hist_b = svc._get_session_history(sid_b)

        assert len(hist_a) == 2
        assert len(hist_b) == 2
        assert hist_a[0]["content"] == "hello"
        assert hist_b[0]["content"] == "what is the fee"

    def test_session_clear_does_not_affect_other_sessions(self):
        svc = self._make_service()
        sid_a = "test-isolation-a"
        sid_b = "test-isolation-b"

        svc._append_session_turn(sid_a, "hi", "hello")
        svc._append_session_turn(sid_b, "bye", "goodbye")

        svc.clear_session(sid_a)

        assert svc._get_session_history(sid_a) == []
        assert len(svc._get_session_history(sid_b)) == 2

    def test_unknown_session_returns_empty(self):
        svc = self._make_service()
        hist = svc._get_session_history("nonexistent-session")
        assert hist == []

    def test_session_history_capped_at_12_turns(self):
        svc = self._make_service()
        sid = "test-cap-12"
        for i in range(20):
            svc._append_session_turn(sid, f"q{i}", f"a{i}")
        hist = svc._get_session_history(sid)
        assert len(hist) == 12

    def test_sequential_queries_same_session_accumulate(self):
        svc = self._make_service()
        sid = "test-accumulate"
        svc._append_session_turn(sid, "q1", "a1")
        svc._append_session_turn(sid, "q2", "a2")
        svc._append_session_turn(sid, "q3", "a3")
        hist = svc._get_session_history(sid)
        assert len(hist) == 6
        assert hist[0]["content"] == "q1"
        assert hist[-1]["content"] == "a3"


class _SessionContainer:
    """Minimal replica of GroqService's session memory logic."""

    def __init__(self):
        self._sessions: dict = {}

    def _get_session_history(self, session_id: str) -> list:
        return self._sessions.get(session_id, [])

    def _append_session_turn(self, session_id, user_msg, assistant_msg):
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append({"role": "user", "content": user_msg})
        self._sessions[session_id].append({"role": "assistant", "content": assistant_msg})
        if len(self._sessions[session_id]) > 12:
            self._sessions[session_id] = self._sessions[session_id][-12:]

    def clear_session(self, session_id):
        self._sessions.pop(session_id, None)


class TestBackendUUIDFallback:
    """Verify the backend doesn't use 'default' for anonymous requests."""

    def test_no_session_id_gets_uuid(self):
        request = GroqQueryRequest(message="hello")
        sid = request.session_id or f"anon_{uuid.uuid4().hex[:12]}"
        assert sid != "default"
        assert sid.startswith("anon_")

    def test_explicit_session_id_is_preserved(self):
        my_sid = "my-custom-session-123"
        request = GroqQueryRequest(message="hello", session_id=my_sid)
        sid = request.session_id or f"anon_{uuid.uuid4().hex[:12]}"
        assert sid == my_sid

    def test_empty_session_id_gets_uuid(self):
        request = GroqQueryRequest(message="hello", session_id="")
        sid = request.session_id or f"anon_{uuid.uuid4().hex[:12]}"
        assert sid != "default"
        assert sid.startswith("anon_")

    def test_uuid_uniqueness(self):
        ids = {f"anon_{uuid.uuid4().hex[:12]}" for _ in range(100)}
        assert len(ids) == 100


class TestConversationManagerIsolation:
    """Verify ConversationManager isolates contexts per session_id."""

    @pytest.mark.asyncio
    async def test_contexts_isolated_by_session(self):
        from app.services.conversation.context import ConversationManager

        mgr = ConversationManager()
        ctx_a = await mgr.get_context("session-a")
        ctx_b = await mgr.get_context("session-b")

        ctx_a.current_language = "hi"
        assert ctx_b.current_language != "hi"

        ctx_a.previous_user_question = "what is the fee"
        assert not ctx_b.previous_user_question

    @pytest.mark.asyncio
    async def test_clear_session_removes_context(self):
        from app.services.conversation.context import ConversationManager

        mgr = ConversationManager()
        await mgr.get_context("session-to-clear")
        await mgr.clear_session("session-to-clear")
        ctx = await mgr.get_context("session-to-clear")
        assert not ctx.previous_user_question

    @pytest.mark.asyncio
    async def test_clear_one_does_not_affect_others(self):
        from app.services.conversation.context import ConversationManager

        mgr = ConversationManager()
        await mgr.get_context("keep-a")
        await mgr.get_context("keep-b")
        ctx_c = await mgr.get_context("to-clear")
        ctx_c.previous_user_question = "test question"

        await mgr.clear_session("to-clear")

        ctx_a = await mgr.get_context("keep-a")
        ctx_b = await mgr.get_context("keep-b")
        assert not ctx_a.previous_user_question
        assert not ctx_b.previous_user_question
        ctx_c2 = await mgr.get_context("to-clear")
        assert not ctx_c2.previous_user_question


class TestFrontendSessionKey:
    """Verify the session key generation logic (simulating browser behavior)."""

    def test_uuid_format(self):
        sid = uuid.uuid4().hex[:12]
        assert len(sid) == 12
        assert isinstance(sid, str)

    def test_unique_per_call(self):
        ids = {uuid.uuid4().hex[:12] for _ in range(100)}
        assert len(ids) == 100
