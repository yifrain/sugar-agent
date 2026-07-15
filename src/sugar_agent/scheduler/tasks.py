"""定时任务调度器。

每个任务都是自描述的——包含名称、说明、cron 表达式、
以及"如果现在触发会发送什么"的预览能力。
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from sugar_agent.config import ScheduleConfig

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
        self._history: list[dict] = []  # 内存中的执行记录

        # 注册所有内置任务
        self._register_builtin_tasks()

    def _register_builtin_tasks(self):
        """注册四个内置任务。"""
        _register_task(
            "weather_reminder",
            {
                "name": "早晨天气提醒",
                "description": "每天早上给女朋友发送天气预报，下雨提醒带伞，降温提醒添衣，高温提醒防晒",
                "icon": "🌤️",
                "example_message": "宝宝早安！☀️ 今天北京晴，25°C~36°C，记得防晒多喝水～新的一天加油💪",
            },
            self._weather_reminder,
        )
        _register_task(
            "afternoon_checkin",
            {
                "name": "下午暖心问候",
                "description": "下午3点左右主动问候，关心她今天的状态和血糖情况",
                "icon": "💛",
                "example_message": "下午啦～今天感觉怎么样？血糖还稳定吗？记得测一下哦😊",
            },
            self._afternoon_checkin,
        )
        _register_task(
            "evening_summary",
            {
                "name": "晚间贴心小结",
                "description": "晚上回顾一天的血糖数据，送上温暖的晚安问候",
                "icon": "🌙",
                "example_message": "今天血糖整体不错，达标率80%！辛苦啦，早点休息，晚安宝贝🌙",
            },
            self._evening_summary,
        )
        _register_task(
            "weekly_health",
            {
                "name": "每周健康周报",
                "description": "每周日早上发送周血糖趋势总结，用数据给鼓励",
                "icon": "📊",
                "example_message": "这周血糖总结：平均6.2，达标率75%，比上周有进步！继续保持哦💪",
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
        if message and not preview and self.bridge:
            target = self.agent.config.wechat_bridge.target_user_id
            await self.bridge.send_text(target, message)
        return message

    async def _afternoon_checkin(self, preview: bool = False):
        if not self.agent:
            return None
        message = await self.agent.generate_proactive("checkin", {})
        if message and not preview and self.bridge:
            target = self.agent.config.wechat_bridge.target_user_id
            await self.bridge.send_text(target, message)
        return message

    async def _evening_summary(self, preview: bool = False):
        if not self.agent:
            return None
        message = await self.agent.generate_proactive("summary", {})
        if message and not preview and self.bridge:
            target = self.agent.config.wechat_bridge.target_user_id
            await self.bridge.send_text(target, message)
        return message

    async def _weekly_health(self, preview: bool = False):
        if not self.agent:
            return None
        bg_context = {}
        if self.agent:
            readings = await self.agent._get_recent_bg_readings(days=7)
            if readings:
                report = self.agent.bg_analyzer.analyze_trend(readings, days=7)
                bg_context = report.model_dump()
        message = await self.agent.generate_proactive("health", bg_context)
        if message and not preview and self.bridge:
            target = self.agent.config.wechat_bridge.target_user_id
            await self.bridge.send_text(target, message)
        return message
