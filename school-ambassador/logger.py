"""Query Logger — append-only JSONL log with configurable retention.

Records every Q&A turn so school staff can review what the ambassador
has actually said.  Entries older than the configured retention period
(default 30 days) are purged on startup.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import yaml


def _load_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("logging", {})
    except FileNotFoundError:
        return {}


class QueryLogger:
    """Simple JSONL query logger with automatic rotation."""

    def __init__(self) -> None:
        cfg = _load_config()
        self._log_dir = cfg.get("log_dir", "logs")
        self._retention_days = int(cfg.get("retention_days", 30))
        os.makedirs(self._log_dir, exist_ok=True)
        # Purge old entries on init
        self._purge_old_logs()

    def _log_path(self) -> str:
        """One log file per calendar day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self._log_dir, f"queries_{today}.jsonl")

    def log(
        self,
        question: str,
        answer: str,
        audience: str = "visitor",
        sources: Optional[List[dict]] = None,
        latency_ms: Optional[float] = None,
        flagged: bool = False,
    ) -> None:
        """Append a single Q&A entry to today's log file."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "audience": audience,
            "question": question,
            "answer": answer,
            "sources": sources or [],
            "latency_ms": round(latency_ms, 1) if latency_ms else None,
            "flagged": flagged,
        }
        path = self._log_path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _purge_old_logs(self) -> None:
        """Delete log files older than the retention window."""
        if self._retention_days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        for fname in os.listdir(self._log_dir):
            if not fname.startswith("queries_") or not fname.endswith(".jsonl"):
                continue
            # Extract date from filename: queries_YYYY-MM-DD.jsonl
            date_str = fname.replace("queries_", "").replace(".jsonl", "")
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    os.remove(os.path.join(self._log_dir, fname))
                except OSError:
                    pass

    def get_recent_entries(self, n: int = 20) -> List[dict]:
        """Return the last *n* log entries across all files (most recent first)."""
        entries: List[dict] = []
        files = sorted(
            [
                f
                for f in os.listdir(self._log_dir)
                if f.startswith("queries_") and f.endswith(".jsonl")
            ],
            reverse=True,
        )
        for fname in files:
            path = os.path.join(self._log_dir, fname)
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            if len(entries) >= n:
                break
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return entries[:n]

