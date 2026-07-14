"""Scheduled tasks for Sugar Agent.

Uses APScheduler for cron-based task scheduling.
Tasks include: weather reminders, check-ins, health summaries.
"""

import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from sugar_agent.config import ScheduleConfig


class TaskScheduler:
    """Manages scheduled proactive tasks for the agent."""

    def __init__(self, config: ScheduleConfig, agent=None, bridge=None, weather_service=None):
        self.config = config
        self.agent = agent
        self.bridge = bridge
        self.weather_service = weather_service
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self._running = False

    def start(self):
        """Register and start all scheduled tasks."""
        tasks_config = self.config.tasks

        # Morning weather reminder
        if tasks_config.weather_reminder.enabled:
            t = tasks_config.weather_reminder
            self.scheduler.add_job(
                self._weather_reminder,
                trigger=CronTrigger(hour=t.cron_hour, minute=t.cron_minute),
                id="weather_reminder",
                name="早晨天气提醒",
                replace_existing=True,
            )
            logger.info(f"Registered weather_reminder at {t.cron_hour:02d}:{t.cron_minute:02d}")

        # Afternoon check-in
        if tasks_config.afternoon_checkin.enabled:
            t = tasks_config.afternoon_checkin
            self.scheduler.add_job(
                self._afternoon_checkin,
                trigger=CronTrigger(hour=t.cron_hour, minute=t.cron_minute),
                id="afternoon_checkin",
                name="下午问候",
                replace_existing=True,
            )
            logger.info(f"Registered afternoon_checkin at {t.cron_hour:02d}:{t.cron_minute:02d}")

        # Evening summary
        if tasks_config.evening_summary.enabled:
            t = tasks_config.evening_summary
            self.scheduler.add_job(
                self._evening_summary,
                trigger=CronTrigger(hour=t.cron_hour, minute=t.cron_minute),
                id="evening_summary",
                name="晚间小结",
                replace_existing=True,
            )
            logger.info(f"Registered evening_summary at {t.cron_hour:02d}:{t.cron_minute:02d}")

        # Weekly health digest
        if tasks_config.weekly_health.enabled:
            t = tasks_config.weekly_health
            self.scheduler.add_job(
                self._weekly_health,
                trigger=CronTrigger(
                    day_of_week=t.cron_day if t.cron_day is not None else 0,
                    hour=t.cron_hour,
                    minute=t.cron_minute,
                ),
                id="weekly_health",
                name="每周健康摘要",
                replace_existing=True,
            )
            logger.info(f"Registered weekly_health on day={t.cron_day} at {t.cron_hour:02d}:{t.cron_minute:02d}")

        self.scheduler.start()
        self._running = True
        logger.info(f"Scheduler started with {len(self.scheduler.get_jobs())} tasks")

    def stop(self):
        """Stop all scheduled tasks."""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Scheduler stopped")

    def get_jobs(self) -> list[dict]:
        """Get all registered jobs with their status."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return jobs

    async def trigger_task(self, task_id: str) -> dict:
        """Manually trigger a scheduled task.

        Args:
            task_id: ID of the task to trigger

        Returns:
            Result dict with status
        """
        task_map = {
            "weather_reminder": self._weather_reminder,
            "afternoon_checkin": self._afternoon_checkin,
            "evening_summary": self._evening_summary,
            "weekly_health": self._weekly_health,
        }

        handler = task_map.get(task_id)
        if not handler:
            return {"status": "error", "message": f"Unknown task: {task_id}"}

        try:
            await handler()
            return {"status": "ok", "task": task_id, "triggered_at": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"Failed to trigger task {task_id}: {e}")
            return {"status": "error", "message": str(e)}

    async def update_task(self, task_id: str, enabled: Optional[bool] = None,
                          cron_hour: Optional[int] = None,
                          cron_minute: Optional[int] = None) -> dict:
        """Update a scheduled task configuration.

        Args:
            task_id: Task to update
            enabled: Enable or disable the task
            cron_hour: New hour for cron trigger
            cron_minute: New minute for cron trigger

        Returns:
            Result dict
        """
        job = self.scheduler.get_job(task_id)
        if not job:
            return {"status": "error", "message": f"Task not found: {task_id}"}

        if enabled is False:
            self.scheduler.pause_job(task_id)
            return {"status": "ok", "message": f"Task {task_id} paused"}
        elif enabled is True:
            self.scheduler.resume_job(task_id)

        if cron_hour is not None or cron_minute is not None:
            current_trigger = job.trigger
            hour = cron_hour if cron_hour is not None else current_trigger.fields[1] if hasattr(current_trigger, 'fields') else 0
            minute = cron_minute if cron_minute is not None else 0
            self.scheduler.reschedule_job(
                task_id,
                trigger=CronTrigger(hour=hour, minute=minute),
            )

        return {"status": "ok", "message": f"Task {task_id} updated"}

    # === Task Handlers ===

    async def _weather_reminder(self):
        """Send morning weather reminder."""
        logger.info("Running weather reminder task")
        if not self.agent or not self.bridge:
            logger.warning("Agent or bridge not available for weather reminder")
            return

        try:
            # Get weather data
            weather_data = {}
            if self.weather_service:
                forecast = await self.weather_service.get_today_forecast()
                if forecast:
                    weather_data = {
                        "condition": forecast.condition,
                        "temp_high": forecast.temperature_high,
                        "temp_low": forecast.temperature_low,
                        "rain_probability": forecast.rain_probability,
                        "humidity": forecast.humidity,
                    }

            # Generate message
            message = await self.agent.generate_proactive("weather", weather_data)
            if message:
                config = self.agent.config
                target_user = config.wechat_bridge.target_user_id
                await self.bridge.send_text(target_user, message)
                await self._log_proactive("weather_reminder", message, "sent")
            else:
                logger.warning("No weather message generated")

        except Exception as e:
            logger.error(f"Weather reminder failed: {e}")
            await self._log_proactive("weather_reminder", "", "failed", str(e))

    async def _afternoon_checkin(self):
        """Send afternoon check-in message."""
        logger.info("Running afternoon checkin task")
        if not self.agent or not self.bridge:
            return

        try:
            message = await self.agent.generate_proactive("checkin", {})
            if message:
                config = self.agent.config
                await self.bridge.send_text(config.wechat_bridge.target_user_id, message)
                await self._log_proactive("afternoon_checkin", message, "sent")
        except Exception as e:
            logger.error(f"Afternoon checkin failed: {e}")

    async def _evening_summary(self):
        """Send evening summary message."""
        logger.info("Running evening summary task")
        if not self.agent or not self.bridge:
            return

        try:
            message = await self.agent.generate_proactive("summary", {})
            if message:
                config = self.agent.config
                await self.bridge.send_text(config.wechat_bridge.target_user_id, message)
                await self._log_proactive("evening_summary", message, "sent")
        except Exception as e:
            logger.error(f"Evening summary failed: {e}")

    async def _weekly_health(self):
        """Send weekly health digest."""
        logger.info("Running weekly health task")
        if not self.agent or not self.bridge:
            return

        try:
            # Get weekly BG data
            bg_context = {}
            if self.agent:
                readings = await self.agent._get_recent_bg_readings(days=7)
                if readings:
                    analyzer = self.agent.bg_analyzer
                    report = analyzer.analyze_trend(readings, days=7)
                    bg_context = report.model_dump()

            message = await self.agent.generate_proactive("health", bg_context)
            if message:
                config = self.agent.config
                await self.bridge.send_text(config.wechat_bridge.target_user_id, message)
                await self._log_proactive("weekly_health", message, "sent")
        except Exception as e:
            logger.error(f"Weekly health failed: {e}")

    async def _log_proactive(self, task_name: str, content: str, status: str, error: str = ""):
        """Log a proactive message to the database."""
        try:
            from sugar_agent.db.models import ProactiveLog
            # This needs a db session - will be wired in main.py
            logger.info(f"Proactive [{task_name}]: {status}")
        except Exception as e:
            logger.debug(f"Failed to log proactive: {e}")
