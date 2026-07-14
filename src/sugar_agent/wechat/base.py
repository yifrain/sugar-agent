"""Abstract base interface for WeChat bridge adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class IncomingMessage:
    """Normalized incoming message from any WeChat bridge."""

    from_user: str
    from_name: str = ""
    content: str = ""
    message_type: str = "text"  # text, image, voice
    message_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    raw_payload: dict = field(default_factory=dict)


@dataclass
class BridgeStatus:
    """Status information from the bridge."""

    connected: bool = False
    wechat_logged_in: bool = False
    last_error: Optional[str] = None
    messages_queued: int = 0


class WeChatBridge(ABC):
    """Abstract interface for WeChat bridge adapters.

    All bridge implementations must implement these methods.
    This decouples the agent logic from any specific WeChat bridge.
    """

    @abstractmethod
    async def send_text(self, to_user: str, text: str) -> bool:
        """Send a text message to a WeChat user.

        Args:
            to_user: Target user's WeChat ID
            text: Message content to send

        Returns:
            True if sent successfully, False otherwise
        """
        ...

    @abstractmethod
    async def send_image(self, to_user: str, image_bytes: bytes) -> bool:
        """Send an image to a WeChat user.

        Args:
            to_user: Target user's WeChat ID
            image_bytes: Raw image bytes

        Returns:
            True if sent successfully, False otherwise
        """
        ...

    @abstractmethod
    async def poll_messages(self, since_id: Optional[str] = None) -> list[IncomingMessage]:
        """Poll for new messages from the bridge.

        Used when the bridge doesn't support webhook push.
        Called periodically by the scheduler.

        Args:
            since_id: Only return messages after this ID (for incremental polling)

        Returns:
            List of new messages since last poll
        """
        ...

    @abstractmethod
    async def get_bridge_status(self) -> BridgeStatus:
        """Check if the bridge is connected and healthy.

        Returns:
            BridgeStatus with connection state
        """
        ...

    async def handle_webhook(self, payload: dict) -> Optional[IncomingMessage]:
        """Parse a webhook payload into an IncomingMessage.

        Override this for bridge-specific payload formats.

        Args:
            payload: Raw webhook JSON payload

        Returns:
            IncomingMessage if valid, None if should be ignored
        """
        try:
            return IncomingMessage(
                from_user=payload.get("from_user", ""),
                from_name=payload.get("from_name", ""),
                content=payload.get("content", ""),
                message_type=payload.get("message_type", "text"),
                message_id=payload.get("message_id"),
                raw_payload=payload,
            )
        except Exception:
            return None

    async def start(self):
        """Optional startup hook for bridge initialization."""
        pass

    async def stop(self):
        """Optional shutdown hook for cleanup."""
        pass
