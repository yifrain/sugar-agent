"""Mock WeChat bridge for local development and testing.

Simulates a WeChat conversation in the terminal or via REST API.
All sent messages are stored in memory and can be retrieved.
"""

import asyncio
from collections import deque
from datetime import datetime
from typing import Optional

from sugar_agent.wechat.base import BridgeStatus, IncomingMessage, WeChatBridge


class MockWeChatBridge(WeChatBridge):
    """Mock bridge that stores messages in memory and prints to console.

    Supports:
    - Manual message injection via REST /api/v1/simulate/message
    - Sending messages to the console
    - Polling for injected messages
    """

    def __init__(self, target_user_id: str = "test_user_001", target_user_name: str = "宝宝"):
        self.target_user_id = target_user_id
        self.target_user_name = target_user_name
        self._sent_messages: deque[dict] = deque(maxlen=1000)
        self._incoming_queue: deque[IncomingMessage] = deque()
        self._message_counter = 0
        self._listeners: list = []  # Callbacks for new messages

    async def send_text(self, to_user: str, text: str) -> bool:
        """Store the sent message and print to console."""
        msg = {
            "to_user": to_user,
            "content": text,
            "timestamp": datetime.now().isoformat(),
        }
        self._sent_messages.append(msg)

        # Pretty print to console
        print(f"\n{'='*50}")
        print(f"🤖 Agent -> {to_user}:")
        print(f"   {text}")
        print(f"{'='*50}\n")

        return True

    async def send_image(self, to_user: str, image_bytes: bytes) -> bool:
        """Log image send."""
        print(f"\n🤖 Agent -> {to_user}: [Image: {len(image_bytes)} bytes]\n")
        return True

    async def poll_messages(self, since_id: Optional[str] = None) -> list[IncomingMessage]:
        """Return queued injected messages."""
        messages = []
        while self._incoming_queue:
            messages.append(self._incoming_queue.popleft())
        return messages

    async def get_bridge_status(self) -> BridgeStatus:
        """Always returns healthy."""
        return BridgeStatus(
            connected=True,
            wechat_logged_in=True,
        )

    def inject_message(self, content: str, from_name: Optional[str] = None) -> IncomingMessage:
        """Inject a simulated user message for testing.

        This can be called via the admin API's simulate endpoint.

        Args:
            content: The message content to simulate
            from_name: Optional override for sender name

        Returns:
            The injected IncomingMessage
        """
        self._message_counter += 1
        msg = IncomingMessage(
            from_user=self.target_user_id,
            from_name=from_name or self.target_user_name,
            content=content,
            message_type="text",
            message_id=f"mock_{self._message_counter}_{datetime.now().timestamp()}",
            timestamp=datetime.now(),
        )
        self._incoming_queue.append(msg)

        print(f"\n💬 {msg.from_name} -> Agent:")
        print(f"   {content}")

        return msg

    def get_sent_messages(self, limit: int = 50) -> list[dict]:
        """Get recently sent messages for testing/verification."""
        messages = list(self._sent_messages)
        return messages[-limit:]

    def clear(self):
        """Clear all stored messages."""
        self._sent_messages.clear()
        self._incoming_queue.clear()
