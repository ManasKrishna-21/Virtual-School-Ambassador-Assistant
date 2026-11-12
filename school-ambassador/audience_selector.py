"""Audience Selector — simple audience-type chooser with timeout.

In **NOVA-integrated mode** (``robot.enabled=true`` in config.yaml),
reads the audience from the NOVA frontend HUD via the REST endpoint.

In **dev/terminal mode**, prompts in the terminal with a keyboard
timeout.
"""

from __future__ import annotations

import sys
import time
import threading
from typing import Optional

import httpx
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



VALID_AUDIENCES = {"parent", "student", "teacher", "visitor"}
DEFAULT_AUDIENCE = "visitor"


def _load_robot_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return cfg.get("robot", {})
    except FileNotFoundError:
        return {}


def _try_nova_audience(timeout: float = 5.0) -> Optional[str]:
    """Poll the NOVA backend for an audience selection.

    The NOVA frontend shows an overlay after a ``greet`` action; the
    user taps Parent / Student / Teacher / Visitor, which POSTs to
    ``/api/robots/{id}/audience``.  The pipeline reads and consumes it
    here via GET.
    """
    robot_cfg = _load_robot_config()
    if not robot_cfg.get("enabled", False):
        return None

    base_url = robot_cfg.get("api_base_url", "http://127.0.0.1:8000").rstrip("/")
    robot_id = robot_cfg.get("robot_id", "nova")
    token = robot_cfg.get("token", "")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/api/robots/{robot_id}/audience"

    deadline = time.time() + timeout
    poll_interval = 0.5  # seconds

    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    aud = data.get("audience")
                    if aud and aud in VALID_AUDIENCES:
                        return aud
        except Exception:
            pass
        time.sleep(poll_interval)

    return None  # Timeout — no selection from HUD


def _terminal_audience(timeout: float = 5.0) -> str:
    """Prompt for audience in the terminal with a timeout."""
    result: Optional[str] = None

    def _input_worker():
        nonlocal result
        try:
            choice = input(
                "  👤  Who are you? [P]arent / [S]tudent / [T]eacher / [V]isitor: "
            ).strip().lower()
            mapping = {
                "p": "parent", "parent": "parent",
                "s": "student", "student": "student",
                "t": "teacher", "teacher": "teacher",
                "v": "visitor", "visitor": "visitor",
            }
            result = mapping.get(choice)
        except (EOFError, KeyboardInterrupt):
            pass

    thread = threading.Thread(target=_input_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if result and result in VALID_AUDIENCES:
        return result
    return DEFAULT_AUDIENCE


def get_audience(timeout: float = 5.0) -> str:
    """Get the audience type — tries NOVA HUD first, falls back to terminal.

    Parameters
    ----------
    timeout : float
        Seconds to wait before defaulting to ``'visitor'``.

    Returns
    -------
    str
        One of ``'parent'``, ``'student'``, ``'teacher'``, ``'visitor'``.
    """
    # Try NOVA frontend HUD first
    aud = _try_nova_audience(timeout=timeout)
    if aud:
        print(f"  ✅  Audience (from NOVA HUD): {aud}")
        return aud

    # Fall back to terminal
    aud = _terminal_audience(timeout=timeout)
    print(f"  ✅  Audience: {aud}")
    return aud

