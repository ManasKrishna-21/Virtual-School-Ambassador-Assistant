"""Hardware I/O Abstraction Layer.

Defines three clean interfaces so the pipeline never touches device-specific
code directly.  Each interface ships with a *dev* implementation (laptop /
terminal) and a clearly-marked stub for the real robot hardware.

NOVA Robot Integration
----------------------
The ``DevCaptionDisplay`` sends a REST ``speak`` action to the NOVA companion
backend so the 3D robot animates while the answer is shown.  Additional
choreography actions (``greet``, ``think``, ``shrug``, etc.) are exposed via
the ``RobotController`` helper.
"""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx
import sounddevice as sd
import numpy as np
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



# ─── Load config (robot section) ────────────────────────────────────
def _load_robot_config() -> dict:
    """Return the ``robot:`` section of config.yaml, or sensible defaults."""
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return cfg.get("robot", {})
    except FileNotFoundError:
        return {}


# ═══════════════════════════════════════════════════════════════════
# Interface 1 — TriggerSource
# ═══════════════════════════════════════════════════════════════════
class TriggerSource(ABC):
    """Blocks until a question session should start."""

    @abstractmethod
    def wait_for_trigger(self) -> bool:
        """Return ``True`` when a user wants to ask a question."""
        ...


class DevTriggerSource(TriggerSource):
    """Dev implementation: wait for the user to press Enter or type in the terminal."""

    def __init__(self) -> None:
        self.last_typed_text: Optional[str] = None

    def wait_for_trigger(self) -> bool:
        try:
            val = input("\n🎙  Press ENTER to speak (or type question directly): ").strip()
            self.last_typed_text = val if val else None
            return True
        except (EOFError, KeyboardInterrupt):
            return False


class StubTriggerSource(TriggerSource):
    """Stub for real hardware.

    # TODO: Replace with the robot's button / proximity-sensor API once
    #       the hardware SDK is known.
    """

    def wait_for_trigger(self) -> bool:
        raise NotImplementedError(
            "Wire this to the robot's physical trigger (button / proximity sensor)."
        )


# ═══════════════════════════════════════════════════════════════════
# Interface 2 — AudioSink
# ═══════════════════════════════════════════════════════════════════
class AudioSink(ABC):
    """Plays synthesised speech audio."""

    @abstractmethod
    def play(self, audio_bytes: bytes, sample_rate: int) -> None:
        ...


class DevAudioSink(AudioSink):
    """Dev implementation: play through the default system speaker via
    ``sounddevice``."""

    def play(self, audio_bytes: bytes, sample_rate: int) -> None:
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio_np, samplerate=sample_rate)
        sd.wait()


class StubAudioSink(AudioSink):
    """Stub for real hardware.

    # TODO: Route to the robot's speaker output if it isn't the system
    #       default audio device.
    """

    def play(self, audio_bytes: bytes, sample_rate: int) -> None:
        raise NotImplementedError(
            "Wire this to the robot's speaker output."
        )


# ═══════════════════════════════════════════════════════════════════
# Interface 3 — CaptionDisplay
# ═══════════════════════════════════════════════════════════════════
class CaptionDisplay(ABC):
    """Shows the answer text to the user."""

    @abstractmethod
    def show(self, text: str, question: Optional[str] = None) -> None:
        ...


class DevCaptionDisplay(CaptionDisplay):
    """Dev implementation: print to terminal **and** POST a ``speak`` action
    to the NOVA companion robot so the 3D model animates."""

    def __init__(self) -> None:
        robot_cfg = _load_robot_config()
        self._enabled = robot_cfg.get("enabled", False)
        self._base_url = robot_cfg.get("api_base_url", "http://127.0.0.1:8000").rstrip("/")
        self._robot_id = robot_cfg.get("robot_id", "nova")
        self._token = robot_cfg.get("token", "")

    def show(self, text: str, question: Optional[str] = None) -> None:
        print("\n" + "═" * 55)
        if question:
            print(f"🗣  Question:   {question}")
        print(f"🤖  Ambassador: {text}")
        print("═" * 55 + "\n")
        if self._enabled:
            self._send_to_nova(text, question=question)

    def _send_to_nova(self, text: str, question: Optional[str] = None) -> None:
        """Fire-and-forget ``speak`` action to NOVA REST API."""
        url = f"{self._base_url}/api/robots/{self._robot_id}/actions"
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        payload: dict = {"action": "speak", "text": text[:500]}
        if question:
            payload["params"] = {"question": question[:200]}
        try:
            with httpx.Client(timeout=3.0) as client:
                client.post(url, json=payload, headers=headers)
        except Exception:
            # Non-fatal: the terminal still showed the answer
            pass


class StubCaptionDisplay(CaptionDisplay):
    """Stub for real hardware.

    # TODO: Replace with however the existing display is actually driven
    #       (HDMI window, serial, or a proprietary API).
    """

    def show(self, text: str, question: Optional[str] = None) -> None:
        raise NotImplementedError(
            "Wire this to the display driver (HDMI, serial, or API)."
        )
        raise NotImplementedError(
            "Wire this to the display driver (HDMI, serial, or API)."
        )


# ═══════════════════════════════════════════════════════════════════
# Helper — NOVA Robot Controller (non-speech choreography)
# ═══════════════════════════════════════════════════════════════════
class RobotController:
    """Convenience wrapper to trigger NOVA animations at pipeline moments.

    Uses the same REST API as ``DevCaptionDisplay`` but for non-``speak``
    actions (``greet``, ``think``, ``shrug``, ``nod``, ``idle``…).
    """

    VALID_ACTIONS = {
        "idle", "wave", "nod", "greet", "think", "celebrate",
        "bow", "dance", "point", "shrug", "attention",
    }

    def __init__(self) -> None:
        robot_cfg = _load_robot_config()
        self._enabled = robot_cfg.get("enabled", False)
        self._base_url = robot_cfg.get("api_base_url", "http://127.0.0.1:8000").rstrip("/")
        self._robot_id = robot_cfg.get("robot_id", "nova")
        self._token = robot_cfg.get("token", "")

    def trigger(self, action: str, params: Optional[dict] = None) -> None:
        """Send a non-speak animation to NOVA.  Silently no-ops if the robot
        is disabled or unreachable."""
        if not self._enabled:
            return
        if action not in self.VALID_ACTIONS:
            return
        url = f"{self._base_url}/api/robots/{self._robot_id}/actions"
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        payload: dict = {"action": action}
        if params:
            payload["params"] = params
        try:
            with httpx.Client(timeout=3.0) as client:
                client.post(url, json=payload, headers=headers)
        except Exception:
            pass  # Non-fatal

