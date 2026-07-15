"""LLM client wrapper using litellm for multi-provider support.

Supports DeepSeek, Qwen (DashScope), Anthropic Claude, and any
other provider supported by litellm, with automatic fallback.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import litellm
from loguru import logger


@dataclass
class ToolCall:
    """Represents a tool/function call from the LLM."""

    id: str
    name: str
    arguments: dict

    @classmethod
    def from_litellm(cls, tool_call) -> "ToolCall":
        """Parse from litellm response format."""
        return cls(
            id=tool_call.id if hasattr(tool_call, "id") else tool_call.get("id", ""),
            name=tool_call.function.name
            if hasattr(tool_call, "function")
            else tool_call["function"]["name"],
            arguments=json.loads(
                tool_call.function.arguments
                if hasattr(tool_call, "function")
                else tool_call["function"]["arguments"]
            ),
        )


@dataclass
class LlmResponse:
    """Structured response from the LLM."""

    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    finish_reason: str = "stop"


class LLMClient:
    """Async LLM client with retry, fallback, and tool support.

    Uses litellm for unified access to multiple LLM providers.
    Supports function calling across DeepSeek, Qwen, Anthropic, OpenAI, etc.
    """

    def __init__(
        self,
        primary_model: str = "deepseek/deepseek-chat",
        fallback_model: str = "qwen/qwen-turbo",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        timeout: int = 30,
        tool_choice: str = "auto",
    ):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.tool_choice = tool_choice

        # Configure litellm
        litellm.drop_params = True  # Drop unsupported params per provider
        litellm.set_verbose = False

        # Set API keys from environment
        self._configure_api_keys()

    def _configure_api_keys(self):
        """Ensure API keys are available for configured providers."""
        # DashScope (千问)
        if "dashscope" in self.primary_model.lower() and not os.environ.get("DASHSCOPE_API_KEY"):
            logger.warning("DASHSCOPE_API_KEY not set in environment")
        # DeepSeek
        if "deepseek" in (self.primary_model + self.fallback_model).lower() and not os.environ.get("DEEPSEEK_API_KEY"):
            logger.warning("DEEPSEEK_API_KEY not set in environment")

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LlmResponse:
        """Send a chat completion request with retry and fallback.

        Args:
            messages: List of message dicts (role, content)
            tools: Optional list of OpenAI-format tool definitions
            tool_choice: How to choose tools ("auto", "required", "none", or specific)
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            LlmResponse with content and/or tool calls

        Raises:
            Exception: If all models (primary + fallback) fail
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        # Try primary model first
        try:
            return await self._call_model(
                self.primary_model,
                messages,
                tools,
                tool_choice or self.tool_choice,
                temp,
                tokens,
            )
        except Exception as e:
            logger.warning(f"Primary model {self.primary_model} failed: {e}")
            if self.fallback_model and self.fallback_model != self.primary_model:
                logger.info(f"Falling back to {self.fallback_model}")
                try:
                    return await self._call_model(
                        self.fallback_model,
                        messages,
                        tools,
                        tool_choice or self.tool_choice,
                        temp,
                        tokens,
                    )
                except Exception as fallback_e:
                    logger.error(f"Fallback model also failed: {fallback_e}")
                    raise fallback_e
            raise e

    async def _call_model(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list[dict]],
        tool_choice: str,
        temperature: float,
        max_tokens: int,
    ) -> LlmResponse:
        """Make the actual litellm API call."""
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": self.timeout,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        # litellm.acompletion is async
        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        message = choice.message

        # Build response
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall.from_litellm(tc))

        return LlmResponse(
            content=message.content if hasattr(message, "content") else None,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or "stop",
        )

    async def simple_chat(self, messages: list[dict], **kwargs) -> str:
        """Simple chat without tool calling. Returns just the text content."""
        response = await self.chat(messages, tools=None, **kwargs)
        return response.content or ""

    def token_count(self, messages: list[dict]) -> int:
        """Estimate token count for a list of messages."""
        try:
            # Rough estimate: ~4 chars per token for Chinese, ~4 for English
            total_chars = sum(
                len(str(m.get("content", ""))) + len(str(m.get("role", ""))) for m in messages
            )
            return total_chars // 2
        except Exception:
            return 0
