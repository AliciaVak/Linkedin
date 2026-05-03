"""
Scheduler skill — lets Claude manage the APScheduler job via tools.

Tools:
  set_schedule    → configure daily run time
  pause_schedule  → suspend for N days
  cancel_schedule → remove the job
  get_schedule    → inspect current status
  run_now         → trigger immediately
"""
import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from skills.base import BaseSkill

logger = logging.getLogger(__name__)

JOB_ID = "daily_linkedin"


class SchedulerSkill(BaseSkill):
    def __init__(self, scheduler: AsyncIOScheduler, timezone: str, run_callback):
        """
        scheduler     — shared AsyncIOScheduler instance
        timezone      — e.g. "Asia/Jerusalem"
        run_callback  — async callable() that runs the pipeline
        """
        self._scheduler = scheduler
        self._timezone = timezone
        self._run_callback = run_callback

    # ── Tool definitions ────────────────────────────────────────────────────────

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "set_schedule",
                "description": "Set or update the daily LinkedIn run time.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hour": {"type": "integer", "description": "Hour (0-23)"},
                        "minute": {"type": "integer", "description": "Minute (0-59)"},
                    },
                    "required": ["hour", "minute"],
                },
            },
            {
                "name": "pause_schedule",
                "description": "Pause the daily schedule for a number of days.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Number of days to pause"},
                    },
                    "required": ["days"],
                },
            },
            {
                "name": "cancel_schedule",
                "description": "Cancel the daily schedule entirely.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_schedule",
                "description": "Get the current schedule status (active, paused, or not set).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "run_now",
                "description": "Trigger the LinkedIn connection pipeline immediately.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    # ── Dispatcher ──────────────────────────────────────────────────────────────

    async def handle(self, tool_name: str, inputs: dict):
        if tool_name == "set_schedule":
            return self._set_schedule(**inputs)
        if tool_name == "pause_schedule":
            return self._pause_schedule(**inputs)
        if tool_name == "cancel_schedule":
            return self._cancel_schedule()
        if tool_name == "get_schedule":
            return self._get_schedule()
        if tool_name == "run_now":
            await self._run_callback()
            return "Pipeline triggered successfully."
        raise ValueError(f"Unknown tool: {tool_name}")

    # ── Implementations ─────────────────────────────────────────────────────────

    def _set_schedule(self, hour: int, minute: int) -> str:
        self._scheduler.add_job(
            self._run_callback,
            CronTrigger(hour=hour, minute=minute, timezone=self._timezone),
            id=JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(f"Schedule set: {hour:02d}:{minute:02d} {self._timezone}")
        return f"Schedule set — runs daily at {hour:02d}:{minute:02d} {self._timezone}."

    def _pause_schedule(self, days: int) -> str:
        job = self._scheduler.get_job(JOB_ID)
        if not job:
            return "No active schedule to pause."
        job.pause()
        resume_date = date.today() + timedelta(days=days)
        # Schedule a one-shot job to auto-resume
        self._scheduler.add_job(
            lambda: self._scheduler.get_job(JOB_ID) and self._scheduler.get_job(JOB_ID).resume(),
            "date",
            run_date=str(resume_date),
            id="resume_schedule",
            replace_existing=True,
        )
        logger.info(f"Schedule paused for {days} days, resumes {resume_date}")
        return f"Schedule paused for {days} days. Resumes automatically on {resume_date}."

    def _cancel_schedule(self) -> str:
        job = self._scheduler.get_job(JOB_ID)
        if not job:
            return "No active schedule to cancel."
        job.remove()
        logger.info("Schedule cancelled.")
        return "Daily schedule cancelled."

    def _get_schedule(self) -> dict:
        job = self._scheduler.get_job(JOB_ID)
        if not job:
            return {"status": "not_scheduled"}
        return {
            "status": "paused" if job.next_run_time is None else "active",
            "next_run": str(job.next_run_time) if job.next_run_time else "paused",
            "trigger": str(job.trigger),
            "timezone": self._timezone,
        }
