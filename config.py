"""Central configuration — all values come from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


# ── Anthropic ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
CLAUDE_MODEL: str = "claude-sonnet-4-6"

# ── Connection scheduler ───────────────────────────────────────────────────────
CONNECTION_HOUR: int = int(os.getenv("CONNECTION_HOUR", "8"))
CONNECTION_MINUTE: int = int(os.getenv("CONNECTION_MINUTE", "0"))
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Jerusalem")

# ── Email report ───────────────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
REPORT_EMAIL: str = os.getenv("REPORT_EMAIL", "")

