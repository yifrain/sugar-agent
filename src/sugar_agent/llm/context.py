"""Conversation context management for the LLM.

Handles:
- Sliding window of recent conversation history
- Context summarization when the window gets too long
- Injection of system prompt, memories, and blood sugar data
"""

import json
import time
from typing import Optional

from loguru import logger

# Maximum tokens before we start summarizing
MAX_CONTEXT_TOKENS = 4000
# Number of most recent turns to always keep verbatim
KEEP_RECENT_TURNS = 10
# Rough token estimation ratio
CHARS_PER_TOKEN = 2


class ConversationContext:
    """Manages conversation history with sliding window and summarization."""

    def __init__(self, max_tokens: int = MAX_CONTEXT_TOKENS):
        self.max_tokens = max_tokens
        self._history: list[dict] = []
        self._summary: Optional[str] = None

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self._history.append({"role": role, "content": content})
        self._maybe_summarize()

    def add_tool_call(self, call_id: str, name: str, arguments: dict, result: dict):
        """Add a tool call and its result to the history."""
        self._history.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                    }
                ],
            }
        )
        self._history.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    def build_messages(self, system_prompt: str) -> list[dict]:
        """组装发给 LLM 的消息列表。

        [0] system: 人格提示词
        [1] system: 旧对话摘要（如果上下文过长）
        [2..n] 最近的对话轮次
        """
        messages = [{"role": "system", "content": system_prompt}]

        # Add summary if we have one
        if self._summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"[之前的对话摘要]\n{self._summary}\n---",
                }
            )

        # Add recent history
        messages.extend(self._history)

        return messages

    def _maybe_summarize(self):
        """Check if we need to summarize older messages to save context."""
        estimated_tokens = self._estimate_tokens()
        if estimated_tokens <= self.max_tokens:
            return

        logger.info(
            f"Context size {estimated_tokens} > {self.max_tokens} max, summarizing..."
        )

        # Keep the most recent turns, summarize the rest
        if len(self._history) > KEEP_RECENT_TURNS:
            older = self._history[:-KEEP_RECENT_TURNS]
            recent = self._history[-KEEP_RECENT_TURNS:]

            # Build a simple summary
            older_text = "\n".join(
                f"[{m['role']}]: {m.get('content', '[tool call]')[:200]}"
                for m in older
            )
            self._summary = (
                f"以下对话历史摘要（共{len(older)}条消息）:\n{older_text[:500]}"
                + ("..." if len(older_text) > 500 else "")
            )

            self._history = recent

    def _estimate_tokens(self) -> int:
        """Rough token estimation based on character count."""
        total_chars = sum(
            len(str(m.get("content", ""))) + len(str(m.get("role", "")))
            for m in self._history
        )
        return total_chars // CHARS_PER_TOKEN

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent history for display."""
        return self._history[-limit:]

    def clear(self):
        """Clear all history."""
        self._history.clear()
        self._summary = None
