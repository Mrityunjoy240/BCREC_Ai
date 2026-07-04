"""Regression tests: verify async Groq client preserves all behavior."""

import pytest


class TestAsyncClientBehavior:
    """Verify the async client change preserves existing guarantees."""

    def test_async_client_is_available(self):
        from app.config import settings

        assert settings.async_groq_client is not None, (
            "async_groq_client must be initialized. "
            "Check config.py — both groq_client and async_groq_client "
            "are set together in __init__."
        )

    def test_async_client_is_not_sync_client(self):
        from app.config import settings

        assert settings.async_groq_client is not settings.groq_client

    def test_groq_service_uses_async_client(self):
        """The guard in generate_response must check async_client, not client."""
        import inspect
        from app.services.llm.groq_service import GroqService

        source = inspect.getsource(GroqService.generate_response)
        assert "self.async_client" in source, (
            "generate_response must reference async_client (not client)"
        )
        assert "await self.async_client" in source, (
            "generate_response must await the async_client call"
        )

    def test_stream_response_unchanged(self):
        """stream_response already used async_client — verify it wasn't changed."""
        import inspect
        from app.services.llm.groq_service import GroqService

        source = inspect.getsource(GroqService.stream_response)
        assert "self.async_client" in source
        assert "await self.async_client" in source

    def test_fallback_models_preserved(self):
        """The model fallback chain must be unchanged."""
        import inspect
        from app.services.llm.groq_service import GroqService, FALLBACK_MODELS

        assert "llama-3.1-8b-instant" in FALLBACK_MODELS
        assert "groq/compound-mini" in FALLBACK_MODELS


class TestGenerateResponseApiContract:
    """Verify the return dict shape is unchanged."""

    @pytest.mark.asyncio
    async def test_return_contract(self, mocker):
        from app.services.llm.groq_service import GroqService

        svc = GroqService()

        # Mock the async client to avoid real API calls
        mock_completion = mocker.MagicMock()
        mock_choice = mocker.MagicMock()
        mock_choice.message.content = "Mocked answer about B.Tech fees."
        mock_completion.choices = [mock_choice]
        mock_usage = mocker.MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 20
        mock_completion.usage = mock_usage

        svc.async_client = mocker.AsyncMock()
        svc.async_client.chat.completions.create = mocker.AsyncMock(return_value=mock_completion)
        # Also mock dependencies
        svc.gemini_client = None
        svc._rate_limiter.acquire = mocker.AsyncMock(return_value=0)
        svc._rate_limiter.record_success = mocker.AsyncMock()
        svc._cache = None
        svc._sessions = {}
        svc.intent_classifier.classify = mocker.MagicMock(
            return_value=type("Intent", (), {"value": "college_info"})()
        )

        mocker.patch.object(svc, "_build_messages", return_value=[])
        mocker.patch.object(svc, "_retrieve_context", return_value="")
        mocker.patch.object(svc, "_get_session_history", return_value=[])
        mocker.patch.object(svc, "_validate_answer", return_value=(True, ""))
        mocker.patch.object(svc, "_is_greeting", return_value=False)
        mocker.patch.object(svc, "_prepare_for_tts", side_effect=lambda x, y: x)
        mocker.patch.object(svc, "_extract_for_context", return_value=([], [], []))
        mocker.patch.object(svc, "_safe_fallback", return_value="fallback")
        mocker.patch.object(svc, "conv_manager")
        svc.conv_manager.get_context = mocker.AsyncMock()

        result = await svc.generate_response("What is the B.Tech fee?")

        assert "answer" in result
        assert "source" in result
        assert "model" in result
        assert "latency_ms" in result
        assert "hallucination_validated" in result
        assert "tokens" in result
        assert "cache_hit" in result
        assert result["answer"] == "Mocked answer about B.Tech fees."
        assert result["source"] == "groq_rag"
