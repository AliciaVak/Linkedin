"""
SQLite database for tracking LinkedIn connections added by the agent.

Stores name, job description, profile URL, date added, and criteria used.
The profile URL is a unique key — prevents double-connecting on reruns.
"""
import csv
import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "connections.db"


class ConnectionsDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    name             TEXT    NOT NULL,
                    job_description  TEXT,
                    profile_url      TEXT    UNIQUE NOT NULL,
                    added_date       TEXT    NOT NULL,
                    criteria_used    TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exhausted_companies (
                    company TEXT PRIMARY KEY,
                    checked_date TEXT NOT NULL
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def is_duplicate(self, profile_url: str) -> bool:
        """Return True if this profile URL is already in the DB."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM connections WHERE profile_url = ?", (profile_url,)
            ).fetchone()
        return row is not None

    def save_connection(
        self,
        name: str,
        job_description: str,
        profile_url: str,
        criteria_used: str = "",
        added_date: Optional[str] = None,
    ) -> bool:
        """
        Insert a connection record.
        Returns True on success, False if the URL already exists (duplicate).
        """
        if added_date is None:
            added_date = str(date.today())
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO connections
                       (name, job_description, profile_url, added_date, criteria_used)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, job_description, profile_url, added_date, criteria_used),
                )
            logger.info(f"Saved connection: {name} ({profile_url})")
            return True
        except sqlite3.IntegrityError:
            logger.debug(f"Duplicate skipped: {profile_url}")
            return False

    def get_all_profile_urls(self) -> set[str]:
        """Return all profile URLs ever saved — used to avoid re-connecting across days."""
        with self._conn() as conn:
            rows = conn.execute("SELECT profile_url FROM connections").fetchall()
        return {r[0] for r in rows}

    def mark_company_exhausted(self, company: str) -> None:
        """Mark a company as fully processed — no more matching people to connect with."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO exhausted_companies (company, checked_date) VALUES (?, ?)",
                (company, str(date.today()))
            )
        logger.debug(f"Marked exhausted: {company}")

    def get_exhausted_companies(self) -> set[str]:
        """Return set of companies already fully processed."""
        with self._conn() as conn:
            rows = conn.execute("SELECT company FROM exhausted_companies").fetchall()
        return {r[0] for r in rows}

    def get_by_date(self, target_date: Optional[str] = None) -> list[dict]:
        """Return all connections added on target_date (default: today)."""
        if target_date is None:
            target_date = str(date.today())
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT name, job_description, profile_url, added_date, criteria_used
                   FROM connections WHERE added_date = ?
                   ORDER BY id""",
                (target_date,),
            ).fetchall()
        return [
            {
                "name": r[0],
                "job_description": r[1],
                "profile_url": r[2],
                "added_date": r[3],
                "criteria_used": r[4],
            }
            for r in rows
        ]

    def export_csv(self, target_date: Optional[str] = None, export_dir: Path = None) -> Path:
        """
        Write a CSV file for target_date and return its path.
        File name: connections_YYYY-MM-DD.csv
        """
        if target_date is None:
            target_date = str(date.today())
        if export_dir is None:
            export_dir = Path(__file__).parent.parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        csv_path = export_dir / f"connections_{target_date}.csv"
        rows = self.get_by_date(target_date)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["name", "job_description", "profile_url", "added_date"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in writer.fieldnames})

        logger.info(f"Exported {len(rows)} connections to {csv_path}")
        return csv_path
