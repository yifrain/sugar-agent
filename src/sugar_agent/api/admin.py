"""Admin API routes for the management web UI.

Provides CRUD endpoints for:
- Dashboard stats
- Messages/conversations
- Memories
- Prompts
- Blood glucose data
- Scheduler tasks
- Settings
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from sugar_agent.config import PROMPTS_DIR

router = APIRouter(prefix="/admin", tags=["admin"])


# === Auth ===

async def verify_admin(request: Request, x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    """Simple token-based auth for admin API."""
    config = request.app.state.config
    if not config.admin.enabled:
        return True  # Admin disabled = no auth
    if not config.admin.password:
        return True  # No password set = no auth
    expected = config.admin.password
    if x_admin_token == expected:
        return True
    raise HTTPException(status_code=401, detail="Invalid admin token")


# === Pydantic Models ===

class DashboardStats(BaseModel):
    messages_today: int = 0
    bg_readings_today: int = 0
    bg_readings_week: int = 0
    total_memories: int = 0
    llm_tokens_today: int = 0
    active_tasks: int = 0
    bridge_connected: bool = False


class MemoryCreate(BaseModel):
    content: str
    category: str = "fact"
    importance: int = 3
    is_pinned: bool = False
    tags: str = ""


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[int] = None
    is_pinned: Optional[bool] = None
    tags: Optional[str] = None


class BloodGlucoseCreate(BaseModel):
    value_mmol: float
    context: Optional[str] = None
    notes: Optional[str] = None
    recorded_at: Optional[str] = None


class PromptUpdate(BaseModel):
    content: str


class SendMessagePayload(BaseModel):
    content: str


class SettingsUpdate(BaseModel):
    key: str
    value: str


# === Dashboard ===

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(request: Request, _=Depends(verify_admin)):
    """Get dashboard statistics."""
    engine = request.app.state.engine
    bridge = request.app.state.bridge

    stats = DashboardStats()

    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        async with AsyncSession(engine) as session:
            # Messages today
            result = await session.execute(
                select(func.count()).select_from(text("messages"))
                .where(text("created_at >= :start")).params(start=today_start.isoformat())
            )
            stats.messages_today = result.scalar() or 0

            # BG readings today
            result = await session.execute(
                select(func.count()).select_from(text("blood_glucose"))
                .where(text("created_at >= :start")).params(start=today_start.isoformat())
            )
            stats.bg_readings_today = result.scalar() or 0

            # BG readings this week
            result = await session.execute(
                select(func.count()).select_from(text("blood_glucose"))
                .where(text("created_at >= :start")).params(start=week_start.isoformat())
            )
            stats.bg_readings_week = result.scalar() or 0

            # Total memories
            result = await session.execute(
                select(func.count()).select_from(text("memories"))
            )
            stats.total_memories = result.scalar() or 0

    except Exception as e:
        logger.error(f"Dashboard query error: {e}")

    # Bridge status
    if bridge:
        try:
            status = await bridge.get_bridge_status()
            stats.bridge_connected = status.connected
        except Exception:
            pass

    # Active scheduler tasks
    scheduler = request.app.state.scheduler
    if scheduler:
        stats.active_tasks = len(scheduler.get_jobs())

    # LLM tokens
    agent = request.app.state.agent
    if agent:
        stats.llm_tokens_today = agent.daily_tokens

    return stats


# === Messages ===

@router.get("/messages")
async def get_messages(
    request: Request,
    date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _=Depends(verify_admin),
):
    """Get conversation messages with optional filters."""
    engine = request.app.state.engine

    try:
        async with AsyncSession(engine) as session:
            query = "SELECT id, from_user, from_name, role, content, tool_calls, is_proactive, created_at FROM messages"

            conditions = []
            params = {}

            if date:
                conditions.append("DATE(created_at) = :date")
                params["date"] = date

            if search:
                conditions.append("content LIKE :search")
                params["search"] = f"%{search}%"

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            params["limit"] = limit
            params["offset"] = offset

            result = await session.execute(text(query), params)
            rows = result.fetchall()

            messages = []
            for row in rows:
                messages.append({
                    "id": row[0],
                    "from_user": row[1],
                    "from_name": row[2],
                    "role": row[3],
                    "content": row[4],
                    "tool_calls": row[5],
                    "is_proactive": row[6],
                    "created_at": row[7].isoformat() if row[7] else None,
                })

            return {"messages": messages, "total": len(messages)}

    except Exception as e:
        logger.error(f"Messages query error: {e}")
        return {"messages": [], "total": 0, "error": str(e)}


@router.post("/messages/send")
async def send_message(payload: SendMessagePayload, request: Request, _=Depends(verify_admin)):
    """Manually send a message to the target user (for testing/management)."""
    bridge = request.app.state.bridge
    config = request.app.state.config

    if not bridge:
        raise HTTPException(status_code=503, detail="Bridge not available")

    success = await bridge.send_text(config.wechat_bridge.target_user_id, payload.content)

    # Also process through agent for context
    agent = request.app.state.agent
    if agent:
        from sugar_agent.wechat.base import IncomingMessage
        msg = IncomingMessage(
            from_user="admin",
            from_name="管理员",
            content=payload.content,
            message_type="text",
        )
        # Don't send response - just want the agent to see this
        # But we need the bridge to send

    return {"status": "sent" if success else "failed"}


class ChatPayload(BaseModel):
    content: str


@router.post("/chat")
async def chat(payload: ChatPayload, request: Request, _=Depends(verify_admin)):
    """测试聊天：发送消息给 Agent，返回回复。

    这条消息会完整经过 Agent 处理流程（血糖解析、LLM调用、工具执行），
    回复同时会通过桥接发送给目标用户。
    """
    agent = request.app.state.agent
    bridge = request.app.state.bridge
    config = request.app.state.config

    if not agent:
        raise HTTPException(status_code=503, detail="Agent not available")

    from sugar_agent.wechat.base import IncomingMessage
    msg = IncomingMessage(
        from_user="admin_test",
        from_name="测试用户",
        content=payload.content,
        message_type="text",
    )

    # Run through agent
    try:
        reply = await agent.process_incoming_message(msg)
    except Exception as e:
        from loguru import logger
        logger.exception(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    # Also send via bridge if available
    if bridge and config.wechat_bridge.target_user_id:
        try:
            await bridge.send_text(config.wechat_bridge.target_user_id, payload.content)
        except Exception:
            pass  # non-critical

    return {"reply": reply, "status": "ok"}


# === Memories ===

@router.get("/memories")
async def get_memories(
    request: Request,
    category: Optional[str] = None,
    search: Optional[str] = None,
    pinned: Optional[bool] = None,
    _=Depends(verify_admin),
):
    """Get all memories with optional filters."""
    agent = request.app.state.agent
    if not agent or not agent.memory:
        return {"memories": []}

    if search:
        memories = await agent.memory.query(search, category)
    else:
        memories = await agent.memory.get_all(category)

    if pinned is not None:
        memories = [m for m in memories if m.get("is_pinned") == pinned]

    return {"memories": memories}


@router.post("/memories")
async def create_memory(payload: MemoryCreate, request: Request, _=Depends(verify_admin)):
    """Create a new memory."""
    agent = request.app.state.agent
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory store not available")

    mem_id = await agent.memory.add(
        content=payload.content,
        category=payload.category,
        importance=payload.importance,
    )

    if payload.is_pinned:
        await agent.memory.pin(mem_id, True)

    return {"id": mem_id, "status": "created"}


@router.put("/memories/{memory_id}")
async def update_memory(memory_id: str, payload: MemoryUpdate, request: Request, _=Depends(verify_admin)):
    """Update an existing memory."""
    agent = request.app.state.agent
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory store not available")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    success = await agent.memory.update(memory_id, **updates)

    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"status": "updated"}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, request: Request, _=Depends(verify_admin)):
    """Delete a memory."""
    agent = request.app.state.agent
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory store not available")

    success = await agent.memory.delete(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"status": "deleted"}


# === Prompts ===

@router.get("/prompts")
async def get_prompts(request: Request, _=Depends(verify_admin)):
    """Get all prompt files."""
    files = {}

    for f in PROMPTS_DIR.rglob("*.md"):
        rel_path = f.relative_to(PROMPTS_DIR)
        with open(f, "r", encoding="utf-8") as fh:
            files[str(rel_path)] = fh.read()

    return {"files": files}


@router.put("/prompts/{name:path}")
async def update_prompt(name: str, payload: PromptUpdate, request: Request, _=Depends(verify_admin)):
    """Update a prompt file."""
    file_path = PROMPTS_DIR / name

    # Security: ensure the path is within prompts directory
    try:
        file_path.resolve().relative_to(PROMPTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid prompt path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Prompt file not found")

    # Backup before overwriting
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    with open(file_path, "r", encoding="utf-8") as f:
        original = f.read()
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(original)

    # Write new content
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(payload.content)

    # Reload system prompt in agent
    agent = request.app.state.agent
    if agent:
        agent.system_prompt = agent._load_system_prompt()

    return {"status": "updated", "backup": str(backup_path)}


# === Blood Glucose ===

@router.get("/blood-glucose")
async def get_blood_glucose(
    request: Request,
    days: int = 30,
    context: Optional[str] = None,
    limit: int = 100,
    _=Depends(verify_admin),
):
    """Get blood glucose readings."""
    engine = request.app.state.engine

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        async with AsyncSession(engine) as session:
            query_str = "SELECT id, value_mmol, context, notes, recorded_at, created_at FROM blood_glucose WHERE created_at >= :cutoff"
            params = {"cutoff": cutoff, "limit": limit}

            if context:
                query_str += " AND context = :context"
                params["context"] = context

            query_str += " ORDER BY recorded_at DESC LIMIT :limit"

            result = await session.execute(text(query_str), params)
            rows = result.fetchall()

            readings = []
            for row in rows:
                readings.append({
                    "id": row[0],
                    "value_mmol": row[1],
                    "context": row[2],
                    "notes": row[3],
                    "recorded_at": row[4].isoformat() if row[4] else None,
                    "created_at": row[5].isoformat() if row[5] else None,
                })

            return {"readings": readings, "total": len(readings)}

    except Exception as e:
        logger.error(f"BG query error: {e}")
        return {"readings": [], "total": 0, "error": str(e)}


@router.post("/blood-glucose")
async def create_blood_glucose(payload: BloodGlucoseCreate, request: Request, _=Depends(verify_admin)):
    """Manually add a blood glucose reading."""
    engine = request.app.state.engine

    try:
        from sugar_agent.db.models import BloodGlucose

        recorded_at = datetime.fromisoformat(payload.recorded_at) if payload.recorded_at else datetime.now(timezone.utc)

        async with AsyncSession(engine) as session:
            bg = BloodGlucose(
                recorded_at=recorded_at,
                value_mmol=payload.value_mmol,
                context=payload.context,
                notes=payload.notes,
            )
            session.add(bg)
            await session.commit()
            await session.refresh(bg)

            return {"id": bg.id, "status": "created"}

    except Exception as e:
        logger.error(f"BG create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/blood-glucose/{reading_id}")
async def delete_blood_glucose(reading_id: int, request: Request, _=Depends(verify_admin)):
    """Delete a blood glucose reading."""
    engine = request.app.state.engine

    try:
        from sugar_agent.db.models import BloodGlucose

        async with AsyncSession(engine) as session:
            result = await session.execute(
                select(BloodGlucose).where(BloodGlucose.id == reading_id)
            )
            bg = result.scalar_one_or_none()
            if not bg:
                raise HTTPException(status_code=404, detail="Reading not found")

            await session.delete(bg)
            await session.commit()

            return {"status": "deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"BG delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/blood-glucose/stats")
async def get_blood_glucose_stats(request: Request, days: int = 30, _=Depends(verify_admin)):
    """Get blood glucose statistics."""
    agent = request.app.state.agent
    if not agent:
        return {"error": "Agent not available"}

    readings = await agent._get_recent_bg_readings(days=days)
    report = agent.bg_analyzer.analyze_trend(readings, days=days)
    return report.model_dump()


# === Scheduler ===

@router.get("/scheduler")
async def get_scheduler(request: Request, _=Depends(verify_admin)):
    """Get scheduler tasks status."""
    scheduler = request.app.state.scheduler
    if not scheduler:
        return {"tasks": []}

    return {"tasks": scheduler.get_jobs()}


@router.post("/scheduler/{task_id}/trigger")
async def trigger_task(task_id: str, request: Request, _=Depends(verify_admin)):
    """Manually trigger a scheduled task."""
    scheduler = request.app.state.scheduler
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    result = await scheduler.trigger_task(task_id)
    return result


@router.put("/scheduler/{task_id}")
async def update_task(
    task_id: str,
    request: Request,
    enabled: Optional[bool] = None,
    cron_hour: Optional[int] = None,
    cron_minute: Optional[int] = None,
    _=Depends(verify_admin),
):
    """Update a scheduled task."""
    scheduler = request.app.state.scheduler
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    result = await scheduler.update_task(task_id, enabled, cron_hour, cron_minute)
    return result


# === Settings ===

@router.get("/settings")
async def get_settings(request: Request, _=Depends(verify_admin)):
    """Get current configuration (with secrets masked)."""
    config = request.app.state.config
    config_dict = config.model_dump()

    # Mask sensitive fields
    def mask_secrets(d, keys_to_mask=None):
        if keys_to_mask is None:
            keys_to_mask = {"api_key", "password", "secret_token", "api_key_deepseek", "api_key_qwen", "api_key_anthropic"}

        if isinstance(d, dict):
            for k, v in d.items():
                if k in keys_to_mask and isinstance(v, str) and v:
                    d[k] = v[:3] + "****" + v[-3:] if len(v) > 6 else "****"
                elif isinstance(v, dict):
                    mask_secrets(v, keys_to_mask)
        return d

    config_dict = mask_secrets(config_dict)
    return config_dict
