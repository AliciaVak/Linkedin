"""
Reporting skill — connection stats, CSV export, email.

Tools:
  get_connection_status   → today's count, daily limit, remaining
  export_and_email_report → CSV export + email
"""
import logging
from datetime import date

from config import REPORT_EMAIL
from db.connections_db import ConnectionsDB
from integrations.email_sender import send_csv_report
from skills.base import BaseSkill

logger = logging.getLogger(__name__)


class ReportingSkill(BaseSkill):
    def __init__(self):
        self._db = ConnectionsDB()

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "get_connection_status",
                "description": "Returns today's connection count, the daily limit, and how many more can be sent today.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "export_and_email_report",
                "description": "Export today's connections to a CSV file and email it.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]

    async def handle(self, tool_name: str, inputs: dict):
        if tool_name == "get_connection_status":
            return self._get_connection_status()
        if tool_name == "export_and_email_report":
            return self._export_and_email()
        raise ValueError(f"Unknown tool: {tool_name}")

    def _get_connection_status(self) -> dict:
        import json
        from pathlib import Path
        today = str(date.today())
        criteria_file = Path(__file__).parent.parent / "criteria.json"
        try:
            with open(criteria_file) as f:
                daily_limit = json.load(f).get("daily_limit", 10)
        except Exception:
            daily_limit = 10

        today_list = self._db.get_by_date(today)
        return {
            "today": len(today_list),
            "daily_limit": daily_limit,
            "remaining": max(0, daily_limit - len(today_list)),
            "connections": [{"name": c["name"], "job": c["job_description"]} for c in today_list],
        }

    def _export_and_email(self) -> str:
        today = str(date.today())
        total = len(self._db.get_by_date(today))
        if total == 0:
            return "No connections today to export."
        csv_path = self._db.export_csv(target_date=today)
        if REPORT_EMAIL:
            send_csv_report(csv_path=csv_path, report_date=today, count=total, recipient=REPORT_EMAIL)
            return f"Exported {total} connections and emailed report to {REPORT_EMAIL}."
        return f"Exported {total} connections to {csv_path}. REPORT_EMAIL not set, skipping email."
