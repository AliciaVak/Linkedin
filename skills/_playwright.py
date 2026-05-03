"""
Playwright mechanics for LinkedIn automation.

Low-level browser operations: scraping, finding buttons, sending connection requests.
No business logic — called by LinkedInConnectSkill.
"""
import asyncio
import logging
import random
import re
import urllib.parse
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class LinkedInBrowser:

    # ── Title matching ──────────────────────────────────────────────────────────

    def _title_matches(self, scraped_title: str, target_titles: list[str]) -> bool:
        """Substring match first, then word-level so 'VP Sales' matches 'VP of Sales'."""
        scraped_lower = scraped_title.lower()
        for t in target_titles:
            t_lower = t.lower()
            if t_lower in scraped_lower:
                return True
            if all(w in scraped_lower for w in t_lower.split()):
                return True
        return False

    # ── Navigation helpers ──────────────────────────────────────────────────────

    def _company_slug(self, company: str, known_slugs: dict = None) -> str:
        """Return the LinkedIn slug for a company, using known_slugs map if available."""
        if known_slugs and company in known_slugs:
            return known_slugs[company]
        slug = company.lower().strip()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        return slug

    async def _wait_for_results(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("load", timeout=10_000)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(2.5, 3.5))

    async def _scroll_to_load(self, page: Page) -> None:
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            await asyncio.sleep(1.0)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    # ── Scraping ────────────────────────────────────────────────────────────────

    async def _scrape_page(self, page: Page) -> list[dict]:
        """Scrape person cards from the current LinkedIn people-search results page."""
        await self._wait_for_results(page)
        logger.debug(f"Scraping URL: {page.url} | Title: {await page.title()}")

        for attempt in range(3):
            try:
                people: list[dict] = await page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();

            function cleanUrl(href) {
                try {
                    const u = new URL(href);
                    const match = u.pathname.match(/\\/in\\/[^/]+/);
                    return match ? 'https://www.linkedin.com' + match[0] : null;
                } catch { return null; }
            }

            const mainSelectors = [
                'main', '[role="main"]',
                '.scaffold-layout__main',
                '.org-people-profile-card__card-spacing',
                '#main-content',
            ];
            let root = document.body;
            for (const sel of mainSelectors) {
                const el = document.querySelector(sel);
                if (el) { root = el; break; }
            }

            const allLis = Array.from(root.querySelectorAll('li'));
            const cardLis = allLis.filter(li => {
                if (!li.querySelector('a[href*="/in/"]')) return false;
                return li.innerText.trim().length > 20;
            });

            function isValidName(name) {
                if (!name || name.length < 3) return false;
                const bad = ['works here', 'view profile', 'connect', 'message', 'follow'];
                const lower = name.toLowerCase();
                if (bad.some(b => lower.includes(b))) return false;
                if (/^[•\\d]/.test(name)) return false;
                return true;
            }

            for (const li of cardLis) {
                const profileLink = li.querySelector('a[href*="/in/"]');
                if (!profileLink) continue;

                const profileUrl = cleanUrl(profileLink.href);
                if (!profileUrl || seen.has(profileUrl)) continue;
                seen.add(profileUrl);

                let name = '';
                const nameSelectors = [
                    '[data-anonymize="person-name"]',
                    '.org-people-profile-card__profile-title',
                    '.entity-result__title-text',
                    '.artdeco-entity-lockup__title',
                ];
                for (const sel of nameSelectors) {
                    const el = li.querySelector(sel);
                    if (el) {
                        const t = el.innerText.trim().split('\\n')[0].trim();
                        if (isValidName(t)) { name = t; break; }
                    }
                }
                if (!name) {
                    const ariaSpans = profileLink.querySelectorAll('span[aria-hidden="true"]');
                    for (const span of ariaSpans) {
                        const t = span.innerText.trim().split('\\n')[0].trim();
                        if (isValidName(t)) { name = t; break; }
                    }
                }
                if (!name) {
                    const raw = profileLink.innerText.trim().split('\\n')[0].trim();
                    if (isValidName(raw)) name = raw;
                }
                if (!name) continue;

                let title = '';
                const titleSelectors = [
                    '[data-anonymize="job-title"]',
                    '.org-people-profile-card__profile-position',
                    '.entity-result__primary-subtitle',
                    '.artdeco-entity-lockup__subtitle',
                    '.entity-result__summary',
                ];
                for (const sel of titleSelectors) {
                    const el = li.querySelector(sel);
                    if (el) {
                        title = el.innerText.trim().split('\\n')[0].trim();
                        if (title) break;
                    }
                }
                if (!title) {
                    const lines = li.innerText.split('\\n')
                        .map(l => l.trim())
                        .filter(l => l && !l.startsWith('•') && l !== name && l.length > 2);
                    title = lines[0] || '';
                }

                results.push({ name, title, profile_url: profileUrl });
            }

            return results;
        }
        """)
                break
            except Exception as exc:
                if attempt < 2:
                    logger.debug(f"evaluate failed (attempt {attempt+1}), retrying: {exc}")
                    await asyncio.sleep(2.0)
                else:
                    logger.warning(f"evaluate failed after 3 attempts: {exc}")
                    people = []

        logger.info(f"Scraped {len(people)} profiles from current page.")
        return people

    # ── Connect button ──────────────────────────────────────────────────────────

    async def _find_connect_button(self, page: Page, name: str, profile_url: str = None) -> Optional[object]:
        """Find the Connect button for a person. Tries card-scoped search first."""
        if profile_url:
            slug = profile_url.rstrip("/").split("/")[-1]
            card = await page.query_selector(f"li:has(a[href*='/in/{slug}'])")
            if card:
                for sel in [
                    "button[aria-label*='Invite']",
                    "button[aria-label*='Connect']",
                    "button:has-text('Connect')",
                ]:
                    btn = await card.query_selector(sel)
                    if btn:
                        label = (await btn.get_attribute("aria-label") or "").lower()
                        text = (await btn.inner_text()).strip().lower()
                        if "connect" in label or "invite" in label or text == "connect":
                            return btn
                more_btn = await card.query_selector("button[aria-label*='More actions']")
                if more_btn:
                    await more_btn.click()
                    await asyncio.sleep(0.8)
                    dropdown = await page.query_selector(
                        "div[role='menu'] button:has-text('Connect'), "
                        "div[role='menu'] span:has-text('Connect')"
                    )
                    if dropdown:
                        return dropdown
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.3)

        name_css = name.replace("'", "\\'")
        for selector in [
            f"button[aria-label*='Invite {name_css}']",
            f"button[aria-label*='{name_css}']",
        ]:
            btn = await page.query_selector(selector)
            if btn:
                label = (await btn.get_attribute("aria-label") or "").lower()
                if "connect" in label or "invite" in label:
                    return btn

        buttons = await page.query_selector_all("button")
        for btn in buttons:
            label = (await btn.get_attribute("aria-label") or "").lower()
            text = (await btn.inner_text()).strip().lower()
            if ("connect" in label or "connect" in text) and name.split()[0].lower() in label:
                return btn

        more_btns = await page.query_selector_all(f"button[aria-label*='More actions for {name_css}']")
        for more_btn in more_btns:
            await more_btn.click()
            await asyncio.sleep(0.8)
            dropdown = await page.query_selector(
                "div[role='menu'] button:has-text('Connect'), "
                "div[role='menu'] span:has-text('Connect')"
            )
            if dropdown:
                return dropdown
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)

        return None

    async def _send_connect_request(self, page: Page, connect_btn) -> bool:
        """Click Connect and handle follow-up dialogs. Returns True on success."""
        try:
            await connect_btn.click()
            await asyncio.sleep(random.uniform(1.0, 2.0))

            for selector in [
                "button[aria-label='Send without a note']",
                "button:has-text('Send without a note')",
                "button:has-text('Send now')",
            ]:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                    return True

            other_label = await page.query_selector("label[for='other'], label:has-text('Other')")
            if other_label:
                await other_label.click()
                await asyncio.sleep(0.5)
                send_btn = await page.query_selector("button[aria-label='Connect'], button:has-text('Connect')")
                if send_btn:
                    await send_btn.click()
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                    return True

            await asyncio.sleep(1.0)
            return True

        except Exception as exc:
            logger.error(f"Error sending connection request: {exc}")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    # ── Bulk search + connect ───────────────────────────────────────────────────

    async def search_and_connect(
        self,
        page: Page,
        company: str,
        title: str,
        job_titles: list[str],
        daily_limit: int,
        added: list[dict],
        already_added_urls: set[str],
        known_slugs: dict = None,
    ) -> None:
        """Navigate to company people page, scrape, filter, and connect."""
        slug = self._company_slug(company, known_slugs)
        url = (
            f"https://www.linkedin.com/company/{slug}/people/?"
            + urllib.parse.urlencode({"keywords": title})
        )
        logger.info(f"Company people page: {company} / '{title}'")
        try:
            await page.goto(url, timeout=20_000)
        except Exception:
            pass
        await self._wait_for_results(page)
        await self._scroll_to_load(page)
        people = await self._scrape_page(page)

        if not people:
            logger.info(f"  Company page empty, trying keyword search...")
            kw_url = (
                "https://www.linkedin.com/search/results/people/?"
                + urllib.parse.urlencode({"keywords": f"{title} {company}", "origin": "GLOBAL_SEARCH_HEADER"})
            )
            try:
                await page.goto(kw_url, timeout=20_000)
            except Exception:
                pass
            await self._wait_for_results(page)
            await self._scroll_to_load(page)
            people = await self._scrape_page(page)

        if not people:
            logger.info(f"  No results for '{title}' at '{company}'.")
            return

        for person in people:
            if len(added) >= daily_limit:
                return
            if person["profile_url"] in already_added_urls:
                continue
            if not self._title_matches(person["title"], job_titles):
                logger.info(f"  Skipping {person['name']} — title '{person['title']}' doesn't match.")
                continue

            logger.info(f"  Connecting: {person['name']} — {person['title']}")
            connect_btn = await self._find_connect_button(page, person["name"], person["profile_url"])
            if not connect_btn:
                logger.info(f"  No Connect button for {person['name']} — skipping.")
                continue

            success = await self._send_connect_request(page, connect_btn)
            if success:
                added.append({"name": person["name"], "job": person["title"], "url": person["profile_url"]})
                already_added_urls.add(person["profile_url"])
                logger.info(f"  Connected #{len(added)}: {person['name']}")
                await asyncio.sleep(random.uniform(3.0, 6.0))
