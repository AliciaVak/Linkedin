"""
Connect skill — send LinkedIn connection requests.

Tools:
  load_criteria           → job titles, companies, daily limit from criteria.json
  connect_with_person     → connect with one specific person (after search_people)
  connect_with_people     → bulk search + connect for automated pipeline
  get_exhausted_companies → companies already fully processed
  mark_company_exhausted  → flag a company as done
"""
import json
import logging
from pathlib import Path

from db.connections_db import ConnectionsDB
from skills._playwright import LinkedInBrowser
from skills.base import BaseSkill
from skills.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

CRITERIA_FILE = Path(__file__).parent.parent / "criteria.json"


class ConnectSkill(BaseSkill):
    def __init__(self, browser: BrowserManager):
        self._browser = browser
        self._ops = LinkedInBrowser()
        self._db = ConnectionsDB()

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "load_criteria",
                "description": "Load job titles, target companies, daily limit, and known LinkedIn slugs from criteria.json.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "connect_with_person",
                "description": (
                    "Send a connection request to one specific person by their profile URL. "
                    "Use this after search_people to connect with people you decided are a match."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Person's full name"},
                        "profile_url": {"type": "string", "description": "LinkedIn profile URL"},
                        "job": {"type": "string", "description": "Their job title"},
                    },
                    "required": ["name", "profile_url", "job"],
                },
            },
            {
                "name": "connect_with_people",
                "description": (
                    "Bulk operation: navigate to a company's LinkedIn people page filtered by title, "
                    "find matching people using built-in title matching, and send connection requests. "
                    "Use this for the automated daily pipeline."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string", "description": "Company name"},
                        "title": {"type": "string", "description": "Job title to search for"},
                        "limit": {"type": "integer", "description": "Max connections to make"},
                    },
                    "required": ["company", "title", "limit"],
                },
            },
            {
                "name": "get_exhausted_companies",
                "description": "Return the list of companies already fully processed (no more people to connect with).",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "mark_company_exhausted",
                "description": "Mark a company as fully processed so it is skipped in future runs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                    },
                    "required": ["company"],
                },
            },
        ]

    async def handle(self, tool_name: str, inputs: dict):
        if tool_name == "load_criteria":
            return self._load_criteria()
        if tool_name == "connect_with_person":
            return await self._connect_with_person(**inputs)
        if tool_name == "connect_with_people":
            return await self._connect_with_people(**inputs)
        if tool_name == "get_exhausted_companies":
            return list(self._db.get_exhausted_companies())
        if tool_name == "mark_company_exhausted":
            self._db.mark_company_exhausted(inputs["company"])
            return f"Marked '{inputs['company']}' as exhausted."
        raise ValueError(f"Unknown tool: {tool_name}")

    def _load_criteria(self) -> dict:
        with open(CRITERIA_FILE) as f:
            data = json.load(f)
        return {
            "job_titles": data.get("job_titles", []),
            "companies": data.get("companies", []),
            "daily_limit": data.get("daily_limit", 10),
            "company_slugs": data.get("company_slugs", {}),
        }

    async def _connect_with_person(self, name: str, profile_url: str, job: str) -> dict:
        await self._browser.ensure_connected()
        page = self._browser.page

        # Navigate to the company people page where the card should be visible
        # (we rely on the current page having this person's card from the prior search)
        connect_btn = await self._ops._find_connect_button(page, name, profile_url)
        if not connect_btn:
            return {"success": False, "reason": "No Connect button found — already connected or pending on this LinkedIn account."}

        success = await self._ops._send_connect_request(page, connect_btn)
        if success:
            self._db.save_connection(
                name=name,
                job_description=job,
                profile_url=profile_url,
                criteria_used="manual via chat",
            )
            return {"success": True, "name": name, "job": job}
        return {"success": False, "reason": "Failed to send connection request."}

    async def _connect_with_people(self, company: str, title: str, limit: int) -> dict:
        await self._browser.ensure_connected()
        page = self._browser.page
        criteria = self._load_criteria()
        already_urls = self._db.get_all_profile_urls()

        added: list[dict] = []
        await self._ops.search_and_connect(
            page=page,
            company=company,
            title=title,
            job_titles=criteria["job_titles"],
            daily_limit=limit,
            added=added,
            already_added_urls=already_urls,
            known_slugs=criteria["company_slugs"],
        )

        for person in added:
            self._db.save_connection(
                name=person["name"],
                job_description=person.get("job", ""),
                profile_url=person["url"],
                criteria_used=f"title={title} company={company}",
            )

        return {"connected": added, "count": len(added)}
