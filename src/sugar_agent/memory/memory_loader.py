"""Memory context loader.

Responsible for loading relevant memories into the LLM context
by ranking and selecting the most important/relevant memories.
"""

from typing import Optional

from loguru import logger


class MemoryLoader:
    """Loads and formats memories for LLM context injection."""

    def __init__(self, memory_store, max_memories: int = 10):
        self.store = memory_store
        self.max_memories = max_memories

    async def get_context_for_message(self, message: str) -> str:
        """Get relevant memory context for a given user message.

        Searches memories that relate to the message content
        and formats them for injection into the system prompt.

        Args:
            message: The user's message text

        Returns:
            Formatted memory context string
        """
        # Get pinned memories (always included)
        all_memories = await self.store.get_all()
        pinned = [m for m in all_memories if m.get("is_pinned", False)]

        # Search for relevant memories based on message content
        relevant = []
        if message:
            # Search using keywords from the message
            keywords = self._extract_keywords(message)
            for keyword in keywords[:3]:
                results = await self.store.query(keyword)
                for r in results:
                    if r not in relevant and r not in pinned:
                        relevant.append(r)

        # Combine pinned + relevant, limit to max
        selected = pinned + relevant
        selected = selected[: self.max_memories]

        if not selected:
            return ""

        return self._format_memories(selected)

    async def get_context_for_proactive(self, task_type: str) -> str:
        """Get relevant memory context for proactive messages.

        Args:
            task_type: Type of proactive task (weather, checkin, summary, health)

        Returns:
            Formatted memory context string
        """
        # For proactive messages, get pinned + high importance
        all_memories = await self.store.get_all()
        pinned = [m for m in all_memories if m.get("is_pinned", False)]
        high_importance = [
            m
            for m in all_memories
            if m.get("importance", 0) >= 4 and m not in pinned
        ]
        selected = (pinned + high_importance)[: self.max_memories]

        if not selected:
            return ""

        return self._format_memories(selected)

    def _extract_keywords(self, message: str) -> list[str]:
        """Extract potential search keywords from a message.

        Simple approach: split by common separators, filter short words.
        """
        # Remove common filler words
        filler = {"的", "了", "是", "我", "你", "他", "她", "它", "们", "这", "那", "吗", "呢", "吧", "啊", "哦", "嗯", "呀"}
        # Split by common Chinese punctuation and spaces
        import re

        words = re.split(r"[，。！？、；：\s]+", message)
        keywords = [w for w in words if len(w) >= 2 and w not in filler]
        return keywords[:5]

    def _format_memories(self, memories: list[dict]) -> str:
        """Format a list of memory dicts into a context string."""
        lines = []
        for mem in memories:
            category = mem.get("category", "fact")
            content = mem.get("content", "")
            pinned_mark = " 📌" if mem.get("is_pinned") else ""
            lines.append(f"- [{category}{pinned_mark}] {content}")

        return "\n".join(lines)
