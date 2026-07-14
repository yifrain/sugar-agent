"""Webhook routes for receiving messages from the WeChat bridge."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter()


class WebhookPayload(BaseModel):
    """Payload sent by the external WeChat bridge."""

    from_user: str = Field(..., description="Sender's WeChat ID")
    from_name: str = Field(default="", description="Sender's display name")
    content: str = Field(..., description="Message content")
    message_type: str = Field(default="text", description="text, image, voice, etc.")
    message_id: Optional[str] = Field(default=None, description="Bridge message ID")
    timestamp: Optional[str] = Field(default=None, description="ISO 8601 timestamp")

    class Config:
        extra = "allow"


class WebhookResponse(BaseModel):
    status: str
    message: str
    response: Optional[str] = None


@router.post("/webhook/message", response_model=WebhookResponse)
async def receive_message(
    payload: WebhookPayload,
    request: Request,
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
):
    """Receive a message from the WeChat bridge.

    The bridge POSTs to this endpoint when a new message arrives.
    We validate the webhook token, then process the message asynchronously.
    """
    config = request.app.state.config

    # Validate webhook token if configured
    expected_token = config.wechat_bridge.webhook.get("secret_token", "")
    if expected_token and x_webhook_token != expected_token:
        logger.warning("Invalid webhook token received")
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    logger.info(f"📩 Received message from {payload.from_name}: {payload.content[:100]}")

    # Store the message and process via agent
    agent = request.app.state.agent
    if agent is None:
        logger.warning("Agent not initialized, storing message only")
        return WebhookResponse(status="stored", message="Agent not ready, message stored")

    # Process in background to respond quickly to the bridge
    asyncio.create_task(_process_message(payload, request))

    return WebhookResponse(status="ok", message="Processing")


async def _process_message(payload: WebhookPayload, request: Request):
    """Process a message asynchronously and send the response."""
    try:
        agent = request.app.state.agent
        bridge = request.app.state.bridge

        # Process through agent
        response_text = await agent.process_incoming_message(payload)

        # Send response back via bridge
        if bridge and response_text:
            await bridge.send_text(payload.from_user, response_text)
            logger.info(f"📤 Sent response to {payload.from_name}")

    except Exception as e:
        logger.exception(f"Error processing message: {e}")


@router.get("/webhook/health")
async def webhook_health(request: Request):
    """Simple endpoint to verify the webhook server is running."""
    return {
        "status": "ok",
        "agent_ready": request.app.state.agent is not None,
        "bridge_ready": request.app.state.bridge is not None,
    }
