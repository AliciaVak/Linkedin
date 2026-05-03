"""
LinkedIn Agent — entry point.

Modes:
  python main.py            # daemon: run scheduler, fires agent daily
  python main.py chat       # interactive conversation with the agent
  python main.py run        # trigger one pipeline run immediately
"""
import argparse
import asyncio
import logging
import random
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.orchestrator import Orchestrator
from config import ANTHROPIC_API_KEY, CONNECTION_HOUR, CONNECTION_MINUTE, TIMEZONE  # noqa: F401
from skills.browser_manager import BrowserManager
from skills.connect_skill import ConnectSkill
from skills.reporting_skill import ReportingSkill
from skills.scheduler_skill import SchedulerSkill
from skills.search_skill import SearchSkill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log"),
    ],
)
logger = logging.getLogger(__name__)

DAILY_GOAL = (
    "Run the daily LinkedIn connection pipeline: "
    "connect with people matching our criteria up to the daily limit, "
    "then export and email the report if any connections were made."
)


def _build_orchestrator(
    browser: BrowserManager,
    scheduler: AsyncIOScheduler = None,
    keep_history: bool = False,
) -> Orchestrator:
    skills = [
        SearchSkill(browser),
        ConnectSkill(browser),
        ReportingSkill(),
    ]

    if scheduler:
        async def _pipeline_run():
            jitter = random.randint(0, 900)
            logger.info(f"Jitter: waiting {jitter}s before pipeline.")
            await asyncio.sleep(jitter)
            run_browser = BrowserManager()
            orch = _build_orchestrator(run_browser)
            try:
                result = await orch.run(DAILY_GOAL)
                logger.info(f"Daily run complete: {result}")
            finally:
                await run_browser.cleanup()

        skills.append(SchedulerSkill(
            scheduler=scheduler,
            timezone=TIMEZONE,
            run_callback=_pipeline_run,
        ))

    return Orchestrator(skills, keep_history=keep_history)


# ── Modes ───────────────────────────────────────────────────────────────────────

async def _daemon_mode() -> None:
    """Start scheduler, fire agent daily at configured time."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    browser = BrowserManager()
    orch = _build_orchestrator(browser, scheduler=scheduler)  # noqa: F841 — keeps scheduler skill alive

    scheduler.add_job(
        _build_daily_run,
        CronTrigger(hour=CONNECTION_HOUR, minute=CONNECTION_MINUTE, timezone=TIMEZONE),
        id="daily_linkedin",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        f"Daemon started — daily run at {CONNECTION_HOUR:02d}:{CONNECTION_MINUTE:02d} {TIMEZONE}\n"
        f"  python main.py chat   — to talk to the agent\n"
        f"  python main.py run    — to trigger immediately"
    )

    stop = asyncio.Event()

    def _shutdown(sig, _frame):
        logger.info(f"Received {sig.name} — shutting down.")
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    await stop.wait()
    await browser.cleanup()
    scheduler.shutdown(wait=False)


async def _build_daily_run():
    """One isolated pipeline run with its own browser."""
    jitter = random.randint(0, 900)
    await asyncio.sleep(jitter)
    browser = BrowserManager()
    orch = _build_orchestrator(browser)
    try:
        result = await orch.run(DAILY_GOAL)
        logger.info(f"Daily run complete: {result}")
    finally:
        await browser.cleanup()


async def _chat_mode() -> None:
    """Interactive conversation — browser stays open for the whole session."""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.start()

    browser = BrowserManager()
    orchestrator = _build_orchestrator(browser, scheduler=scheduler, keep_history=True)

    print("LinkedIn Agent  (type 'quit' to exit, 'reset' to clear history)\n")
    print("Examples:")
    print("  'run the daily pipeline now'")
    print("  'how many connections did we make today?'")
    print("  'set schedule to 9am'")
    print("  'pause for 3 days'\n")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                break
            if user_input.lower() == "reset":
                orchestrator.reset_history()
                print("History cleared.\n")
                continue

            print("Agent: ", end="", flush=True)
            response = await orchestrator.run(user_input)
            print(response)
            print()
    finally:
        await browser.cleanup()
        scheduler.shutdown(wait=False)


async def _run_once() -> None:
    """Trigger one pipeline run immediately and exit."""
    browser = BrowserManager()
    orch = _build_orchestrator(browser)
    try:
        result = await orch.run(DAILY_GOAL)
        print(result)
    finally:
        await browser.cleanup()


# ── Entry point ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn Agent")
    parser.add_argument(
        "mode",
        nargs="?",
        default="daemon",
        choices=["daemon", "chat", "run"],
        help="daemon (default): run scheduler | chat: interactive | run: one-shot",
    )
    args = parser.parse_args()

    if args.mode == "chat":
        asyncio.run(_chat_mode())
    elif args.mode == "run":
        asyncio.run(_run_once())
    else:
        asyncio.run(_daemon_mode())


if __name__ == "__main__":
    main()
