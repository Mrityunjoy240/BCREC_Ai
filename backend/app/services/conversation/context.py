import asyncio
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 4


class ConversationContext:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.current_language: str = "en"
        self.last_intent: str = ""
        self.recent_entities: List[str] = []
        self.recent_topics: List[str] = []
        self.recent_numeric_values: List[Dict[str, str]] = []
        self.previous_user_question: str = ""
        self.previous_bot_answer: str = ""
        self.previous_user_question_raw: str = ""
        self._lock: asyncio.Lock = asyncio.Lock()

    async def update(
        self,
        user_query: str,
        bot_answer: str,
        intent: str,
        lang: str,
        entities: Optional[List[str]] = None,
        numeric_values: Optional[List[Dict[str, str]]] = None,
        topics: Optional[List[str]] = None,
    ):
        async with self._lock:
            self.previous_user_question_raw = user_query
            self.previous_user_question = user_query
            self.previous_bot_answer = bot_answer
            self.last_intent = intent
            self.current_language = lang
            if entities:
                self.recent_entities = (entities + self.recent_entities)[:10]
            if numeric_values:
                for nv in numeric_values:
                    if nv not in self.recent_numeric_values:
                        self.recent_numeric_values.insert(0, nv)
                self.recent_numeric_values = self.recent_numeric_values[:6]
            if topics:
                self.recent_topics = (topics + self.recent_topics)[:6]

    async def get_followup_context(self) -> str:
        async with self._lock:
            parts = []
            if self.recent_numeric_values:
                for nv in self.recent_numeric_values[:2]:
                    label = nv.get("label", "amount")
                    ctx = nv.get("context", "")
                    val = nv.get("value", "")
                    parts.append(f"{label} {val} ({ctx})")
            if self.previous_user_question:
                parts.append(f"previous question: {self.previous_user_question}")
            if self.recent_topics:
                parts.append(f"topic: {', '.join(self.recent_topics[:2])}")
            return " | ".join(parts)

    async def clear(self):
        async with self._lock:
            self.last_intent = ""
            self.recent_entities.clear()
            self.recent_topics.clear()
            self.recent_numeric_values.clear()
            self.previous_user_question = ""
            self.previous_bot_answer = ""
            self.previous_user_question_raw = ""


class ConversationManager:
    def __init__(self):
        self._contexts: Dict[str, ConversationContext] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get_context(self, session_id: str) -> ConversationContext:
        async with self._lock:
            if session_id not in self._contexts:
                self._contexts[session_id] = ConversationContext(session_id=session_id)
            return self._contexts[session_id]

    async def clear_session(self, session_id: str):
        async with self._lock:
            self._contexts.pop(session_id, None)

    async def clear_all(self):
        async with self._lock:
            self._contexts.clear()
