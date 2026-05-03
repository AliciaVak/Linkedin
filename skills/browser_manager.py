"""
BrowserManager — shared Chrome connection.

Owns the CDP browser session and exposes a single page.
Injected into any skill that needs browser access (SearchSkill, ConnectSkill).
Managed by main.py — cleanup() is called once at session end, not per-run.
"""
import logging

from playwright.async_api import async_playwright, Page

logger = logging.getLogger(__name__)

CDP_URL = "http://localhost:9222"


class BrowserManager:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not connected. Call ensure_connected() first.")
        return self._page

    async def ensure_connected(self) -> None:
        """Connect to Chrome if not already connected."""
        if self._page is not None:
            return
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            raise RuntimeError(
                "Could not connect to Chrome. Launch it with:\n"
                "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
                "--remote-debugging-port=9222\n"
                "Then log into LinkedIn and try again."
            )
        contexts = self._browser.contexts
        if contexts and contexts[0].pages:
            self._page = contexts[0].pages[0]
        else:
            ctx = contexts[0] if contexts else await self._browser.new_context()
            self._page = await ctx.new_page()
        logger.info(f"Browser connected. Current page: {self._page.url}")

    async def cleanup(self) -> None:
        """Close the browser. Safe to call multiple times."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser disconnected.")
