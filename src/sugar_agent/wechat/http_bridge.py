"""HTTP-based WeChat bridge adapter.

Communicates with an external bridge process via HTTP API.
The bridge process runs on a machine logged into WeChat.
"""

import asyncio
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from sugar_agent.wechat.base import BridgeStatus, IncomingMessage, WeChatBridge


class HttpBridgeConfig:
    """Configuration for the HTTP bridge."""

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 10, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries


class HttpWeChatBridge(WeChatBridge):
    """WeChat bridge that communicates with an external process via HTTP.

    The external bridge must implement these endpoints:
    - POST /api/send      - Send a message
    - POST /api/send_image - Send an image
    - GET  /api/messages   - Poll for new messages
    - GET  /api/health     - Health check
    """

    def __init__(self, config: HttpBridgeConfig):
        self.config = config
        self._last_message_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client."""
        if self._client is None:
            headers = {
                "Content-Type": "application/json",
            }
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    async def send_text(self, to_user: str, text: str) -> bool:
        """Send a text message via the bridge."""
        for attempt in range(self.config.max_retries):
            try:
                client = await self._get_client()
                response = await client.post(
                    "/api/send",
                    json={
                        "to_user": to_user,
                        "content": text,
                    },
                )
                response.raise_for_status()
                data = response.json()
                logger.debug(f"Message sent to {to_user}, id={data.get('message_id')}")
                return True

            except httpx.HTTPStatusError as e:
                logger.error(f"Bridge HTTP error (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2**attempt)
            except httpx.RequestError as e:
                logger.error(f"Bridge connection error (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2**attempt)

        logger.error(f"Failed to send message after {self.config.max_retries} attempts")
        return False

    async def send_image(self, to_user: str, image_bytes: bytes) -> bool:
        """Send an image via the bridge."""
        import base64

        try:
            client = await self._get_client()
            response = await client.post(
                "/api/send_image",
                json={
                    "to_user": to_user,
                    "image": base64.b64encode(image_bytes).decode("utf-8"),
                },
            )
            response.raise_for_status()
            return True

        except Exception as e:
            logger.error(f"Failed to send image: {e}")
            return False

    async def poll_messages(self, since_id: Optional[str] = None) -> list[IncomingMessage]:
        """Poll for new messages from the bridge."""
        try:
            client = await self._get_client()
            params = {"limit": 10}
            if since_id:
                params["since_id"] = since_id
            elif self._last_message_id:
                params["since_id"] = self._last_message_id

            response = await client.get("/api/messages", params=params)
            response.raise_for_status()
            data = response.json()

            messages = []
            for raw in data.get("messages", []):
                msg = IncomingMessage(
                    from_user=raw.get("from_user", ""),
                    from_name=raw.get("from_name", ""),
                    content=raw.get("content", ""),
                    message_type=raw.get("message_type", "text"),
                    message_id=raw.get("message_id"),
                    raw_payload=raw,
                )
                messages.append(msg)

                # Track the last message ID
                if msg.message_id:
                    self._last_message_id = msg.message_id

            return messages

        except Exception as e:
            logger.error(f"Failed to poll messages: {e}")
            return []

    async def get_bridge_status(self) -> BridgeStatus:
        """Check bridge health."""
        try:
            client = await self._get_client()
            response = await client.get("/api/health")
            response.raise_for_status()
            data = response.json()

            return BridgeStatus(
                connected=True,
                wechat_logged_in=data.get("wechat_logged_in", False),
                messages_queued=data.get("messages_queued", 0),
            )

        except Exception as e:
            return BridgeStatus(
                connected=False,
                last_error=str(e),
            )

    async def stop(self):
        """Clean up the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
