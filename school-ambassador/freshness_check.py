"""Freshness Checker — warns if KB files haven't been updated recently.

Can be run standalone::

    uv run python freshness_check.py

Or called from ``pipeline.py`` at startup.
"""

from __future__ import annotations

import os
import sys
import time

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



def _load_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("rag", {})
    except FileNotFoundError:
        return {}


def check_freshness(max_age_days: int = 90) -> list[str]:
    """Return a list of KB files older than *max_age_days*.

    Each entry is a string like ``"kb/school/timings.md (142 days old)"``.
    """
    cfg = _load_config()
    kb_dir = cfg.get("kb_dir", "kb")
    stale: list[str] = []

    if not os.path.isdir(kb_dir):
        return stale

    for root, _dirs, files in os.walk(kb_dir):
        for fname in sorted(files):
            if not fname.endswith((".md", ".txt")):
                continue
            filepath = os.path.join(root, fname)
            rel_path = os.path.relpath(filepath, ".").replace("\\", "/")
            mtime = os.path.getmtime(filepath)
            age_days = (time.time() - mtime) / 86400
            if age_days > max_age_days:
                stale.append(f"{rel_path} ({int(age_days)} days old)")

    return stale


if __name__ == "__main__":
    stale = check_freshness()
    if stale:
        print("⚠️  The following KB files haven't been modified in 90+ days:")
        for s in stale:
            print(f"   • {s}")
        print("   Consider reviewing them to confirm the information is still current.\n")
    else:
        print("✅  All KB files are fresh (modified within the last 90 days).\n")

