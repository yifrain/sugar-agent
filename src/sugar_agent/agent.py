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
        """加载 system.md 模板，填入基本变量。"""
        prompt_path = PROMPTS_DIR / "system.md"
        if not prompt_path.exists():
            return "你是Sugar Agent。"

        with open(prompt_path, "r", encoding="utf-8") as f:
            template = f.read()

        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        return template.format(
            target_name=self.config.wechat_bridge.target_user_name,
            agent_name="小糖",
            current_time=now,
        )

    async def process_incoming_message(self, payload) -> str:
        """处理一条用户消息。支持文本和图片。"""
        from_user = payload.from_user if hasattr(payload, "from_user") else payload.get("from_user")
        from_name = payload.from_name if hasattr(payload, "from_name") else payload.get("from_name", "")
        content = payload.content if hasattr(payload, "content") else payload.get("content", "")
        msg_type = getattr(payload, "message_type", "text")
        image_url = getattr(payload, "image_url", "")

        self.messages_processed += 1
        logger.info(f"Agent processing #{self.messages_processed} [{msg_type}] from {from_name}")

        # 1. 文本消息：提取血糖
        if msg_type == "text":
            bg_reading = self.bg_parser.parse(content)
            if bg_reading:
                logger.info(f"Detected BG: {bg_reading.value_mmol} mmol/L")
                await self._store_bg_reading(bg_reading)

        # 2. 消息入库 + 加入对话历史
        db_content = content if msg_type == "text" else f"[图片] {content}"
        self.context.add_message("user", db_content)
        await self._store_message(from_user, from_name, "user", db_content)

        # 3. 组装 LLM 消息（图片消息用多模态格式）
        messages = self.context.build_messages(self.system_prompt)

        if msg_type == "image" and image_url:
            # 将最后一条 user 消息替换为多模态格式
            last_msg = messages[-1]
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请描述这张图片，用你平时聊天的语气回复"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }

        # 4. LLM 调用
        try:
            response_text = await self._run_llm_with_tools(messages)

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
            "weather": (
                f"现在是早晨，请以男朋友的语气给{self.config.wechat_bridge.target_user_name}发早安问候。"
                f"根据天气信息自然地提醒她：{json.dumps(context_data, ensure_ascii=False)}。"
                f"要温暖自然，像真人早上醒来发的消息。一两句话就够了。"
            ),
            "checkin": (
                f"下午了，请自然地关心一下{self.config.wechat_bridge.target_user_name}。"
                f"问她今天过得怎么样，忙不忙，心情好不好。不要提血糖。"
            ),
            "summary": (
                f"晚上了，给{self.config.wechat_bridge.target_user_name}发条晚安消息。"
                f"温柔一点，关心她今晚早点休息，做个好梦。"
            ),
            "health": (
                f"这周结束了。请以关心的语气给{self.config.wechat_bridge.target_user_name}发一条周末问候，"
                f"祝她周末愉快，放松一下。不要提血糖数据。"
            ),
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
        """Get weather forecast for optional location.

        免费版天气 API 只支持地级市以上城市。如果查询县级市失败，
        返回提示让 LLM 自动尝试上级地级市。
        """
        days = args.get("days", 1)
        location = args.get("location", "")
        if self.weather:
            try:
                forecasts = await self.weather.get_forecast(days, location)
            except Exception as e:
                return {"error": str(e), "hint": "免费版可能不支持该城市，请尝试查询上级地级市（如邳州→徐州）"}

            if not forecasts:
                return {"error": f"无法获取'{location}'的天气数据", "hint": "请尝试查询上级地级市"}

            result = []
            for f in forecasts:
                result.append({
                    "日期": f.date,
                    "天气": f.condition,
                    "高温": f"{f.temperature_high}°C",
                    "低温": f"{f.temperature_low}°C",
                    "降雨概率": f"{f.rain_probability}%",
                    "风力": f.wind_scale if f.wind_scale else f"{f.wind_speed}km/h",
                })
            return {"location": location or self.weather.location, "forecast": result}
        return {"error": "天气服务未配置"}

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

