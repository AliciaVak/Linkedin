"""
Search skill — find people on LinkedIn without connecting.

Tools:
  search_people → scrape a company people page, return all profiles with live
                  connection status. No title filtering — Claude decides who matches.
"""
import logging
import urllib.parse

from db.connections_db import ConnectionsDB
from skills._playwright import LinkedInBrowser
from skills.base import BaseSkill
from skills.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class SearchSkill(BaseSkill):
    def __init__(self, browser: BrowserManager):
        self._browser = browser
        self._ops = LinkedInBrowser()
        self._db = ConnectionsDB()

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "search_people",
                "description": (
                    "Search a company's LinkedIn people page and return ALL scraped profiles "
                    "WITHOUT filtering or connecting. Each result includes name, title, "
                    "profile_url, and connection_status (live from LinkedIn: "
                    "available / connected / pending / unknown). "
                    "YOU decide who matches based on their title. "
                    "Use whatever keyword the user specifies. If the user is vague "
                    "(e.g. 'search sales'), prefer a specific title from the target roles "
                    "list for better results. If the user is explicit, use that exactly."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string", "description": "Company name"},
                        "title": {
                            "type": "string",
                            "description": "Search keyword (e.g. 'VP Sales', 'CRO')",
                        },
                    },
                    "required": ["company", "title"],
                },
            },
        ]

    async def handle(self, tool_name: str, inputs: dict):
        if tool_name == "search_people":
            return await self._search_people(**inputs)
        raise ValueError(f"Unknown tool: {tool_name}")

    async def _search_people(self, company: str, title: str) -> dict:
        await self._browser.ensure_connected()
        page = self._browser.page

        # Load known slugs from criteria
        import json
        from pathlib import Path
        criteria_file = Path(__file__).parent.parent / "criteria.json"
        try:
            with open(criteria_file) as f:
                data = json.load(f)
            known_slugs = data.get("company_slugs", {})
        except Exception:
            known_slugs = {}

        already_urls = self._db.get_all_profile_urls()
        slug = self._ops._company_slug(company, known_slugs)
        url = (
            f"https://www.linkedin.com/company/{slug}/people/?"
            + urllib.parse.urlencode({"keywords": title})
        )
        await page.goto(url, timeout=20_000)
        await self._ops._wait_for_results(page)
        await self._ops._scroll_to_load(page)
        people = await self._ops._scrape_page(page)

        # Read live connection status from LinkedIn's UI
        card_statuses: dict = await page.evaluate("""
        () => {
            const statuses = {};
            const lis = Array.from(document.querySelectorAll('li'));
            for (const li of lis) {
                const profileLink = li.querySelector('a[href*="/in/"]');
                if (!profileLink) continue;
                try {
                    const u = new URL(profileLink.href);
                    const match = u.pathname.match(/\\/in\\/([^/]+)/);
                    if (!match) continue;
                    const slug = match[1];
                    const buttons = Array.from(li.querySelectorAll('button'));
                    let status = 'unknown';
                    for (const btn of buttons) {
                        const label = (btn.getAttribute('aria-label') || btn.innerText || '').toLowerCase();
                        if (label.includes('message')) { status = 'connected'; break; }
                        if (label.includes('pending') || label.includes('withdraw')) { status = 'pending'; break; }
                        if (label.includes('connect') || label.includes('invite')) { status = 'available'; break; }
                        if (label.includes('follow')) { status = 'available'; break; }
                    }
                    statuses[slug] = status;
                } catch {}
            }
            return statuses;
        }
        """)

        results = []
        for p in people:
            slug = p["profile_url"].rstrip("/").split("/")[-1]
            results.append({
                "name": p["name"],
                "title": p["title"],
                "profile_url": p["profile_url"],
                "connection_status": card_statuses.get(slug, "unknown"),
            })

        return {
            "company": company,
            "search_keyword": title,
            "total_scraped": len(people),
            "note": "No title filtering — you decide who matches. connection_status is live from LinkedIn.",
            "results": results,
        }
