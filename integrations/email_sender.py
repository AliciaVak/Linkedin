"""
Send the daily connections CSV report via SMTP.

Works with any SMTP server (Gmail app password, Outlook, SendGrid SMTP, etc.).
"""
import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

logger = logging.getLogger(__name__)


def send_csv_report(
    csv_path: Path,
    report_date: str,
    count: int,
    recipient: str,
) -> None:
    """
    Email the daily connections CSV to `recipient`.

    Parameters
    ----------
    csv_path    : path to the CSV file to attach
    report_date : human-readable date string (e.g. "2026-05-01")
    count       : number of connections added today
    recipient   : destination email address
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, recipient]):
        logger.warning(
            "Email config incomplete — skipping report email. "
            "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, REPORT_EMAIL in .env"
        )
        return

    subject = f"LinkedIn Connections Report — {report_date}"
    body = (
        f"Hi,\n\n"
        f"The LinkedIn agent sent {count} connection request(s) today ({report_date}).\n\n"
        f"The full list is attached as a CSV.\n\n"
        f"— LinkedIn Agent"
    )

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    filename = os.path.basename(csv_path)
    with open(csv_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Sent connections report to {recipient} ({count} connections)")
    except Exception as exc:
        logger.error(f"Failed to send email report: {exc}", exc_info=True)
        raise
