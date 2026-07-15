"""Core Agent orchestrator for Sugar Agent.

Coordinates the full message processing pipeline:
receive → parse → context building → LLM call → tool execution → response.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from sugar_agent.config import Config, PROMPTS_DIR
from sugar_agent.llm.client import LLMClient, LlmResponse, ToolCall
from sugar_agent.llm.tools import LLM_TOOLS
from sugar_agent.llm.context import ConversationContext
from sugar_agent.health.parser import BloodGlucoseParser
from sugar_agent.health.analyzer import BloodGlucoseAnalyzer
from sugar_agent.health.models import BloodGlucoseReading


class Agent:
    """Main agent orchestrator.

    Handles incoming messages, coordinates tool execution,
    manages conversation context, and generates responses.
    """

    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        bridge,  # WeChatBridge
        memory_store,  # MemoryStore
        weather_service,  # WeatherService
        db_session_factory,  # async session factory
    ):
        self.config = config
        self.llm = llm_client
        self.bridge = bridge
        self.memory = memory_store
        self.weather = weather_service
        self.db_factory = db_session_factory

        # Health components
        self.bg_parser = BloodGlucoseParser(default_unit=config.health.bg_unit)
        self.bg_analyzer = BloodGlucoseAnalyzer(
            low_threshold=config.health.low_threshold,
            high_threshold=config.health.high_threshold,
            urgent_low=config.health.urgent_low,
            urgent_high=config.health.urgent_high,
        )

        # Conversation context tracker
        self.context = ConversationContext()

        # Load system prompt
        self.system_prompt = self._load_system_prompt()

        # Track usage
        self.daily_tokens = 0
        self.messages_processed = 0

    def _load_system_prompt(self) -> str:
        """Load and template the system prompt."""
        prompt_path = PROMPTS_DIR / "system.md"
        if not prompt_path.exists():
            logger.warning(f"System prompt not found at {prompt_path}, using default")
            return "你是Sugar Agent，一个关心用户健康的AI助手。"

        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()

        # Template variables
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        return template.format(
            target_name=self.config.wechat_bridge.target_user_name,
            agent_name="小糖",
            current_time=now,
            weather_summary="待获取",
            bg_trend="暂无数据",
            memories="暂无",
            key_knowledge="",
            memories_detail="",
            bg_detail="",
        )

    async def process_incoming_message(self, payload) -> str:
        """Process an incoming message from a user.

        Full pipeline:
        1. Parse blood glucose from message
        2. Store message in DB
        3. If BG detected, auto-store it
        4. Build context with memories + BG history + weather
        5. Run LLM with tool execution loop
        6. Store assistant response in DB
        7. Return response text
        """
        from_user = payload.from_user if hasattr(payload, "from_user") else payload.get("from_user")
        from_name = payload.from_name if hasattr(payload, "from_name") else payload.get("from_name", "")
        content = payload.content if hasattr(payload, "content") else payload.get("content", "")

        self.messages_processed += 1
        logger.info(f"Agent processing message #{self.messages_processed} from {from_name}")

        # Step 1: Parse blood glucose
        bg_reading = self.bg_parser.parse(content)
        if bg_reading:
            logger.info(f"Detected BG: {bg_reading.value_mmol} mmol/L")
            # Auto-record to DB
            await self._store_bg_reading(bg_reading)

        # Step 2: Add user message to context
        self.context.add_message("user", content)
        await self._store_message(from_user, from_name, "user", content)

        # Step 3: Build enriched context
        memories_context = await self._get_memories_context()
        bg_context = await self._get_bg_context()
        weather_context = await self._get_weather_context()

        # Step 4: Build message list for LLM
        messages = self.context.build_messages(
            system_prompt=self.system_prompt,
            memories_context=memories_context,
            bg_context=bg_context,
            weather_context=weather_context,
        )

        # Step 5: Run LLM with tool loop
        try:
            response_text = await self._run_llm_with_tools(messages)

            # Step 6: Store assistant response
            self.context.add_message("assistant", response_text)
            await self._store_message(from_user, from_name, "assistant", response_text)

            return response_text

        except Exception as e:
            logger.exception(f"LLM processing failed: {e}")
            error_response = "抱歉，我暂时有点迷糊，等下再聊好吗？🥺"
            self.context.add_message("assistant", error_response)
            return error_response

    async def generate_proactive(self, task_type: str, context_data: dict) -> Optional[str]:
        """Generate a proactive (agent-initiated) message.

        Args:
            task_type: Type of proactive message (weather, checkin, summary, health)
            context_data: Relevant data for the message

        Returns:
            Generated text or None
        """
        task_prompts = {
            "weather": f"现在是早晨，请根据以下天气信息给{self.config.wechat_bridge.target_user_name}发送一条温馨的早安和天气提醒：\n{json.dumps(context_data, ensure_ascii=False)}",
            "checkin": f"下午了，请温柔地问候一下{self.config.wechat_bridge.target_user_name}，关心她今天的状态和血糖情况。",
            "summary": f"晚上了，请根据今天的对话和血糖数据，给{self.config.wechat_bridge.target_user_name}发一条温暖的晚间问候。",
            "health": f"这是一周的血糖数据总结，请用关心和鼓励的语气告诉{self.config.wechat_bridge.target_user_name}：\n{json.dumps(context_data, ensure_ascii=False)}",
        }

        prompt = task_prompts.get(task_type, "")
        if not prompt:
            return None

        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}]

        try:
            response = await self.llm.simple_chat(messages, temperature=0.8)
            return response
        except Exception as e:
            logger.error(f"Failed to generate proactive message: {e}")
            return None

    async def _run_llm_with_tools(self, messages: list[dict]) -> str:
        """Run the LLM with tool execution loop.

        The LLM can call tools, and we execute them and feed results back.
        Maximum 5 iterations to prevent infinite loops.
        """
        tools = LLM_TOOLS
        max_iterations = 5

        for iteration in range(max_iterations):
            response = await self.llm.chat(messages, tools=tools)

            if response.tool_calls:
                logger.info(f"LLM called {len(response.tool_calls)} tool(s)")
                for tool_call in response.tool_calls:
                    # Add assistant's tool call to messages
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.name,
                                        "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    )

                    # Execute the tool
                    result = await self._execute_tool(tool_call)

                    # Add tool result to messages
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

                # Continue loop - LLM sees tool results and may respond or call more tools
            else:
                # No tool calls - this is the final response
                if response.usage:
                    self.daily_tokens += response.usage.get("total_tokens", 0)
                return response.content or "嗯嗯，我在听~"

        # Max iterations reached
        logger.warning(f"Max tool iterations ({max_iterations}) reached")
        return "好的，让我消化一下这些信息...有什么我可以帮你的吗？"

    async def _execute_tool(self, tool_call: ToolCall) -> Any:
        """Execute a tool call from the LLM and return the result."""
        name = tool_call.name
        args = tool_call.arguments

        logger.debug(f"Executing tool: {name}({args})")

        try:
            match name:
                case "record_blood_glucose":
                    return await self._tool_record_bg(args)
                case "get_blood_glucose_trend":
                    return await self._tool_get_bg_trend(args)
                case "add_memory":
                    return await self._tool_add_memory(args)
                case "query_memory":
                    return await self._tool_query_memory(args)
                case "get_weather":
                    return await self._tool_get_weather(args)
                case "set_reminder":
                    return await self._tool_set_reminder(args)
                case "get_time":
                    return {"now": datetime.now(timezone.utc).isoformat(), "local": datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")}
                case _:
                    return {"error": f"Unknown tool: {name}"}

        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}

    async def _tool_record_bg(self, args: dict) -> dict:
        """Record a blood glucose reading."""
        value = args["value"]
        unit = args.get("unit", "mmol/L")

        from sugar_agent.health.models import convert_to_mmol

        value_mmol = convert_to_mmol(value, unit)
        reading = BloodGlucoseReading(
            value=value,
            unit=unit,
            value_mmol=value_mmol,
            context=args.get("context"),
            notes=args.get("notes"),
        )

        await self._store_bg_reading(reading)

        # Check for alerts
        alert = self.bg_analyzer.check_alert(reading)
        alert_msg = ""
        if alert:
            alert_msg = self.bg_analyzer.get_alert_message(reading) or ""

        return {
            "recorded": True,
            "value_mmol": value_mmol,
            "context": reading.context,
            "alert_level": alert,
            "alert_message": alert_msg,
            "message": f"已记录血糖 {value_mmol} mmol/L" + (f" ({alert_msg})" if alert_msg else ""),
        }

    async def _tool_get_bg_trend(self, args: dict) -> dict:
        """Get blood glucose trend data."""
        days = args.get("days", 7)
        readings = await self._get_recent_bg_readings(days)
        report = self.bg_analyzer.analyze_trend(readings, days)
        return report.model_dump()

    async def _tool_add_memory(self, args: dict) -> dict:
        """Add a memory."""
        content = args["content"]
        category = args.get("category", "fact")
        importance = args.get("importance", 3)

        memory_id = await self.memory.add(content, category, importance)
        return {"added": True, "id": memory_id, "content": content, "category": category}

    async def _tool_query_memory(self, args: dict) -> dict:
        """Query memories."""
        query = args["query"]
        category = args.get("category")
        results = await self.memory.query(query, category)
        return {"query": query, "results": results, "count": len(results)}

    async def _tool_get_weather(self, args: dict) -> dict:
        """Get weather forecast."""
        days = args.get("days", 1)
        if self.weather:
            forecast = await self.weather.get_forecast(days)
            return forecast if isinstance(forecast, dict) else {"data": str(forecast)}
        return {"error": "Weather service not available"}

    async def _tool_set_reminder(self, args: dict) -> dict:
        """Set a reminder (placeholder - will be implemented with scheduler)."""
        return {
            "set": True,
            "time": args.get("time_description", ""),
            "message": args.get("message", ""),
            "note": "提醒已设置，但目前版本中提醒功能需要通过管理后台配置",
        }

    # === Database helpers ===

    async def _store_message(self, user_id: str, user_name: str, role: str, content: str):
        """Store a message in the database."""
        try:
            from sugar_agent.db.models import Message

            async with self.db_factory() as session:
                msg = Message(
                    from_user=user_id,
                    from_name=user_name,
                    role=role,
                    content=content,
                    is_proactive=False,
                )
                session.add(msg)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to store message: {e}")

    async def _store_bg_reading(self, reading: BloodGlucoseReading):
        """Store a blood glucose reading in the database."""
        try:
            from datetime import datetime, timezone
            from sugar_agent.db.models import BloodGlucose

            async with self.db_factory() as session:
                bg = BloodGlucose(
                    recorded_at=reading.recorded_at or datetime.now(timezone.utc),
                    value_mmol=reading.value_mmol,
                    context=reading.context,
                    notes=reading.notes,
                )
                session.add(bg)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to store BG reading: {e}")

    async def _get_recent_bg_readings(self, days: int = 7) -> list[BloodGlucoseReading]:
        """Get recent blood glucose readings from the database."""
        try:
            from datetime import datetime, timedelta, timezone
            from sqlalchemy import select, desc
            from sugar_agent.db.models import BloodGlucose

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            async with self.db_factory() as session:
                result = await session.execute(
                    select(BloodGlucose)
                    .where(BloodGlucose.recorded_at >= cutoff)
                    .order_by(desc(BloodGlucose.recorded_at))
                    .limit(100)
                )
                rows = result.scalars().all()

                return [
                    BloodGlucoseReading(
                        id=row.id,
                        value=row.value_mmol,
                        unit="mmol/L",
                        value_mmol=row.value_mmol,
                        context=row.context,
                        notes=row.notes,
                        recorded_at=row.recorded_at,
                        created_at=row.created_at,
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to get BG readings: {e}")
            return []

    async def _get_memories_context(self) -> str:
        """Get relevant memories for context injection."""
        if not self.memory:
            return ""
        try:
            memories = await self.memory.get_recent(limit=self.config.memory.max_context_memories)
            if not memories:
                return ""
            return "\n".join(f"- [{m.get('category', '')}] {m.get('content', '')}" for m in memories)
        except Exception:
            return ""

    async def _get_bg_context(self) -> str:
        """Get blood glucose context for injection."""
        readings = await self._get_recent_bg_readings(days=3)
        if not readings:
            return "暂无近期血糖数据"

        lines = ["最近3天血糖记录："]
        for r in readings[:10]:
            time_str = r.recorded_at.strftime("%m/%d %H:%M") if r.recorded_at else "未知时间"
            ctx = r.context or ""
            lines.append(f"- {time_str}: {r.value_mmol} mmol/L {ctx}")
        return "\n".join(lines)

    async def _get_weather_context(self) -> str:
        """Get current weather for context."""
        if self.weather:
            try:
                forecast = await self.weather.get_forecast(days=1)
                if isinstance(forecast, dict):
                    return json.dumps(forecast, ensure_ascii=False)
            except Exception:
                pass
        return ""
