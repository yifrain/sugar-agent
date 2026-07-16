"""定时任务调度器。

每个任务都是自描述的——包含名称、说明、cron 表达式、
以及"如果现在触发会发送什么"的预览能力。

持久化：通过 admin UI 修改的任务配置会保存到 data/scheduler.json，
重启服务后自动加载，不会丢失。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from sugar_agent.config import ScheduleConfig, DATA_DIR

# 持久化文件路径
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler.json"

# 任务注册表：每个任务包含自描述信息和 handler
TASK_REGISTRY = {}


def _register_task(task_id, info, handler):
    """注册一个定时任务。"""
    TASK_REGISTRY[task_id] = {**info, "id": task_id, "handler": handler}


class TaskScheduler:
    """管理所有定时任务，追踪执行历史。"""

    def __init__(self, config: ScheduleConfig, agent=None, bridge=None, weather_service=None):
        self.config = config
        self.agent = agent
        self.bridge = bridge
        self.weather_service = weather_service
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self._history: list[dict] = []

        # 注册所有内置任务
        self._register_builtin_tasks()

        # 从持久化文件恢复配置（覆盖 YAML 默认值）
        self._load_persisted_config()

    def _register_builtin_tasks(self):
        """注册四个内置任务。"""
        _register_task(
            "weather_reminder",
            {
                "name": "早晨问候 + 天气",
                "description": "每天早上像男朋友一样说早安，自然地提醒今天的天气：下雨带伞、降温添衣、晴天也有好心情",
                "icon": "☀️",
                "example_message": "早呀☀️ 今天北京大晴天，25度，心情也要亮起来！记得吃早饭～",
            },
            self._weather_reminder,
        )
        _register_task(
            "afternoon_checkin",
            {
                "name": "下午问候",
                "description": "下午关心她今天过得怎么样，忙不忙，心情好不好。自然的聊天，不提血糖",
                "icon": "💛",
                "example_message": "下午啦～今天忙吗？累了就休息会儿，别太拼哦",
            },
            self._afternoon_checkin,
        )
        _register_task(
            "evening_summary",
            {
                "name": "晚安问候",
                "description": "晚上温柔地提醒她早点休息，祝她做个好梦",
                "icon": "🌙",
                "example_message": "今天辛苦了，早点睡哦。晚安，做个好梦🌙",
            },
            self._evening_summary,
        )
        _register_task(
            "weekly_health",
            {
                "name": "周末问候",
                "description": "每周日早上祝她周末愉快，让她放松享受休息日",
                "icon": "🌸",
                "example_message": "周末快乐呀！今天好好放松，做点自己喜欢的事～🌸",
            },
            self._weekly_health,
        )

    def start(self):
        """注册并启动所有定时任务。"""
        tasks_config = self.config.tasks

        job_configs = {
            "weather_reminder": tasks_config.weather_reminder,
            "afternoon_checkin": tasks_config.afternoon_checkin,
            "evening_summary": tasks_config.evening_summary,
            "weekly_health": tasks_config.weekly_health,
        }

        for task_id, t in job_configs.items():
            if task_id not in TASK_REGISTRY:
                continue
            info = TASK_REGISTRY[task_id]

            if t.enabled:
                if t.cron_day is not None:
                    trigger = CronTrigger(day_of_week=t.cron_day, hour=t.cron_hour, minute=t.cron_minute)
                else:
                    trigger = CronTrigger(hour=t.cron_hour, minute=t.cron_minute)

                self.scheduler.add_job(
                    info["handler"],
                    trigger=trigger,
                    id=task_id,
                    name=info["name"],
                    replace_existing=True,
                )
                logger.info(f"  {info['icon']} {info['name']}: {t.cron_hour:02d}:{t.cron_minute:02d}")

        # 暂停的任务也注册（放在 paused 状态）
        for task_id, t in job_configs.items():
            if not t.enabled and task_id in TASK_REGISTRY:
                info = TASK_REGISTRY[task_id]
                trigger = CronTrigger(hour=t.cron_hour or 0, minute=t.cron_minute or 0)
                self.scheduler.add_job(
                    info["handler"],
                    trigger=trigger,
                    id=task_id,
                    name=info["name"],
                    replace_existing=True,
                )
                self.scheduler.pause_job(task_id)
                logger.info(f"  ⏸ {info['name']}: 已暂停")

        self.scheduler.start()
        logger.info(f"调度器启动: {len(self.scheduler.get_jobs())} 个任务")

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("调度器已停止")

    def get_tasks(self) -> list[dict]:
        """获取所有任务的状态（给管理后台用）。"""
        tasks = []
        for task_id, info in TASK_REGISTRY.items():
            job = self.scheduler.get_job(task_id)
            t_config = self._get_task_config(task_id)

            # 从历史记录中找最近一次执行
            recent = [h for h in self._history if h.get("task_id") == task_id]
            last_run = recent[-1] if recent else None

            tasks.append({
                "id": task_id,
                "name": info["name"],
                "icon": info["icon"],
                "description": info["description"],
                "example_message": info.get("example_message", ""),
                "enabled": t_config.enabled if t_config else True,
                "cron_hour": t_config.cron_hour if t_config else 7,
                "cron_minute": t_config.cron_minute if t_config else 0,
                "cron_day": t_config.cron_day if t_config else None,
                "schedule_text": self._cron_to_text(t_config),
                "next_run": str(job.next_run_time) if job and job.next_run_time else None,
                "is_paused": job.next_run_time is None and t_config and t_config.enabled if job else False,
                "last_run": last_run,
                "run_count": len(recent),
            })
        return tasks

    async def trigger_task(self, task_id: str) -> dict:
        """手动触发一个任务，只生成预览不回实际发送消息。返回生成的文本。"""
        if task_id not in TASK_REGISTRY:
            return {"status": "error", "message": f"未知任务: {task_id}"}

        info = TASK_REGISTRY[task_id]
        handler = info["handler"]

        try:
            # 传入 preview=True 表示只生成不发送
            message = await handler(preview=True)
            created_at = datetime.now(timezone.utc).isoformat()

            self._history.append({
                "task_id": task_id,
                "task_name": info["name"],
                "message": message[:200] if message else "(无内容)",
                "created_at": created_at,
                "status": "success",
            })

            return {
                "status": "ok",
                "task_id": task_id,
                "task_name": info["name"],
                "message": message,
                "created_at": created_at,
            }
        except Exception as e:
            logger.error(f"触发任务 {task_id} 失败: {e}")
            return {"status": "error", "message": str(e)}

    # ===== 持久化：admin UI 改的时间重启不丢失 =====

    def _load_persisted_config(self):
        """从 data/scheduler.json 恢复配置。"""
        if not SCHEDULER_STATE_FILE.exists():
            return
        try:
            with open(SCHEDULER_STATE_FILE, "r") as f:
                saved = json.load(f)
            for task_id, overrides in saved.get("tasks", {}).items():
                t_config = self._get_task_config(task_id)
                if t_config:
                    if "enabled" in overrides:
                        t_config.enabled = overrides["enabled"]
                    if "cron_hour" in overrides:
                        t_config.cron_hour = overrides["cron_hour"]
                    if "cron_minute" in overrides:
                        t_config.cron_minute = overrides["cron_minute"]
            logger.info(f"已从 {SCHEDULER_STATE_FILE.name} 恢复调度配置")
        except Exception as e:
            logger.warning(f"恢复调度配置失败: {e}")

    def _save_persisted_config(self):
        """保存当前配置到 data/scheduler.json。"""
        try:
            tasks = {}
            for task_id in TASK_REGISTRY:
                t = self._get_task_config(task_id)
                if t:
                    tasks[task_id] = {
                        "enabled": t.enabled,
                        "cron_hour": t.cron_hour,
                        "cron_minute": t.cron_minute,
                    }
            with open(SCHEDULER_STATE_FILE, "w") as f:
                json.dump({"tasks": tasks}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存调度配置失败: {e}")

    async def update_task(self, task_id: str, **kwargs) -> dict:
        """更新任务配置（启停、修改时间）。"""
        job = self.scheduler.get_job(task_id)
        if not job:
            return {"status": "error", "message": f"任务不存在: {task_id}"}

        # 更新 config 中的值
        t_config = self._get_task_config(task_id)
        if t_config is None:
            return {"status": "error", "message": f"任务无配置项: {task_id}"}

        if "enabled" in kwargs:
            t_config.enabled = kwargs["enabled"]
            if kwargs["enabled"]:
                self.scheduler.resume_job(task_id)
            else:
                self.scheduler.pause_job(task_id)

        if "cron_hour" in kwargs:
            t_config.cron_hour = kwargs["cron_hour"]
        if "cron_minute" in kwargs:
            t_config.cron_minute = kwargs["cron_minute"]

        # 重新调度
        if "cron_hour" in kwargs or "cron_minute" in kwargs:
            self.scheduler.reschedule_job(
                task_id,
                trigger=CronTrigger(
                    hour=t_config.cron_hour,
                    minute=t_config.cron_minute,
                    day_of_week=t_config.cron_day if hasattr(t_config, 'cron_day') else None,
                ),
            )

        # 持久化到文件
        self._save_persisted_config()

        return {"status": "ok", "task_id": task_id}

    def get_history(self, task_id: Optional[str] = None, limit: int = 20) -> list[dict]:
        """获取执行历史。"""
        history = self._history
        if task_id:
            history = [h for h in history if h.get("task_id") == task_id]
        return history[-limit:]

    def _get_task_config(self, task_id):
        """获取任务对应的配置对象。"""
        tc = self.config.tasks
        mapping = {
            "weather_reminder": tc.weather_reminder,
            "afternoon_checkin": tc.afternoon_checkin,
            "evening_summary": tc.evening_summary,
            "weekly_health": tc.weekly_health,
        }
        return mapping.get(task_id)

    @staticmethod
    def _cron_to_text(t_config) -> str:
        """把 cron 配置转成人类可读的描述。"""
        if t_config is None:
            return "未配置"
        hour = t_config.cron_hour
        minute = t_config.cron_minute
        day = t_config.cron_day
        time_str = f"{hour:02d}:{minute:02d}"
        if day is not None:
            days = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
            return f"每{days[day] if day < 7 else ''} {time_str}"
        return f"每天 {time_str}"

    # === 任务 handler（preview=True 只生成不发送）===

    def _get_target_users(self) -> list[str]:
        """获取推送目标：优先用 agent 记录的真实用户，否则用配置的占位符。"""
        if self.agent and self.agent._known_users:
            return list(self.agent._known_users)
        if self.agent:
            return [self.agent.config.wechat_bridge.target_user_id]
        return []

    async def _send_to_all(self, message: str):
        """给所有已知用户发消息。"""
        for user_id in self._get_target_users():
            if self.bridge:
                await self.bridge.send_text(user_id, message)

    async def _weather_reminder(self, preview: bool = False):
        if not self.agent:
            return None
        weather_data = {}
        if self.weather_service:
            try:
                forecast = await self.weather_service.get_today_forecast()
                if forecast:
                    weather_data = {
                        "condition": forecast.condition,
                        "temp_high": forecast.temperature_high,
                        "temp_low": forecast.temperature_low,
                        "rain": forecast.rain_probability,
                    }
            except Exception:
                pass
        message = await self.agent.generate_proactive("weather", weather_data)
        if message and not preview:
            await self._send_to_all(message)
        return message

    async def _afternoon_checkin(self, preview: bool = False):
        if not self.agent:
            return None
        message = await self.agent.generate_proactive("checkin", {})
        if message and not preview:
            await self._send_to_all(message)
        return message

    async def _evening_summary(self, preview: bool = False):
        if not self.agent:
            return None
        message = await self.agent.generate_proactive("summary", {})
        if message and not preview:
            await self._send_to_all(message)
        return message

    async def _weekly_health(self, preview: bool = False):
        if not self.agent:
            return None
        message = await self.agent.generate_proactive("health", {})
        if message and not preview:
            await self._send_to_all(message)
        return message
