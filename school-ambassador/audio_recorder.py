"""Audio Recorder — microphone capture with Voice Activity Detection.

Provides a synchronous ``record_question()`` function that captures
audio from the default microphone, trims silence using the configured
VAD engine, and returns the raw PCM bytes.
"""

from __future__ import annotations

import json
import os
import sys
import time
import struct
import wave
import tempfile
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



def _load_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def _load_hardware_profile() -> dict:
    try:
        with open("hardware_profile.json", "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_input_device() -> tuple[Optional[int], str]:
    """Return the input device to use. Defaults to system default."""
    cfg = _load_config().get("audio", {})
    configured = cfg.get("input_device")

    devices = sd.query_devices()
    if configured is not None:
        try:
            dev_idx = int(configured)
            return dev_idx, devices[dev_idx]["name"]
        except (ValueError, IndexError):
            pass

    # Use the system default input device (e.g. earphones when plugged in)
    def_in = sd.default.device[0]
    dev_name = devices[def_in]["name"] if (def_in is not None and def_in >= 0) else "System Default"
    return (def_in if (def_in is not None and def_in >= 0) else None), dev_name


def record_audio(
    duration: float = 5.0,
    sample_rate: int = 16000,
) -> Optional[Tuple[bytes, str]]:
    """Record audio from the microphone and normalize gain for whisper.

    Returns
    -------
    (audio_bytes, temp_wav_path) | None
    """
    dev_idx, dev_name = _get_input_device()
    print(f"  🎙  Recording from [{dev_name}] for {duration:.1f}s… (speak now)")

    try:
        audio = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=dev_idx,
            blocking=True,
        )
    except Exception as exc:
        print(f"  ❌  Microphone capture error: {exc}")
        return None

    if audio is None or len(audio) == 0:
        return None

    # Flatten
    audio = audio.flatten()
    max_amp = int(np.abs(audio).max())

    # Dynamic gain normalization for quiet earphone mics:
    # If the microphone signal is quiet, boost it safely so Whisper hears it clearly!
    if max_amp > 0:
        gain = min(28000.0 / float(max_amp), 30.0)  # up to 30x digital boost
        boosted = np.clip(audio.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
        audio = boosted
        print(f"  🔊  Audio processed (peak raw: {max_amp}, digital gain: {gain:.1f}x)")
    else:
        print("  ⚠️  Microphone captured complete zero signal.")

    audio_bytes = audio.tobytes()

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)

    return audio_bytes, tmp.name

