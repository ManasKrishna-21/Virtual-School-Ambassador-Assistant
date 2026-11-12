"""Text-to-Speech client using Kokoro-82M (af_bella @ 24 kHz).

Architecture:
  • Kokoro-82M in-process via kokoro-onnx.
  • Voice: af_bella (female, natural, expressive neural speech).
  • Sample rate: 24,000 Hz (16-bit PCM).
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path
from typing import Tuple

import numpy as np
import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_kokoro_instance = None
BASE_DIR = Path(__file__).resolve().parent


def _resolve_path(rel_or_abs: str) -> str:
    """Resolve a path relative to the school-ambassador project directory."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    return str(BASE_DIR / p)


def _load_tts_config() -> dict:
    """Return the ``tts:`` section of config.yaml."""
    config_file = BASE_DIR / "config.yaml"
    try:
        with open(config_file, "r", encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("tts", {})
    except FileNotFoundError:
        return {}


class TTSClient:
    """Synchronous Kokoro-82M TTS client with female voice af_bella at 24 kHz."""

    def __init__(self) -> None:
        cfg = _load_tts_config()
        self._cfg = cfg
        self._engine = "kokoro"

        # Kokoro settings (Strictly af_bella @ 24 kHz)
        k_cfg = cfg.get("kokoro", {})
        self._kokoro_model = _resolve_path(k_cfg.get("model_path", "models/kokoro-v0_19.onnx"))
        self._kokoro_voices = _resolve_path(k_cfg.get("voices_path", "models/voices.json"))
        self._kokoro_voice = "af_bella"
        self._kokoro_speed = float(k_cfg.get("speed", 1.0))
        self._kokoro_lang = k_cfg.get("lang", "en-us")
        self._kokoro_sr = int(k_cfg.get("sample_rate", 24000))

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def voice(self) -> str:
        return self._kokoro_voice

    @property
    def sample_rate(self) -> int:
        return self._kokoro_sr

    def _get_kokoro(self):
        """Lazy-load the Kokoro-82M ONNX model with safe JSON/pickle support."""
        global _kokoro_instance
        if _kokoro_instance is None:
            if not os.path.isfile(self._kokoro_model):
                raise FileNotFoundError(
                    f"Kokoro model file not found at '{self._kokoro_model}'."
                )
            if not os.path.isfile(self._kokoro_voices):
                raise FileNotFoundError(
                    f"Kokoro voices file not found at '{self._kokoro_voices}'."
                )

            try:
                import kokoro_onnx
            except ImportError:
                raise ImportError(
                    "kokoro-onnx package is not installed. Run: pip install kokoro-onnx soundfile"
                )

            # Patch np.load to support json voices and allow_pickle for NumPy 2.x
            orig_load = np.load

            def _safe_load(file, *args, **kwargs):
                file_str = str(file)
                if file_str.endswith(".json"):
                    with open(file, "r", encoding="utf-8") as fp:
                        d = json.load(fp)
                    return {k: np.array(v, dtype=np.float32) for k, v in d.items()}
                kwargs["allow_pickle"] = True
                return orig_load(file, *args, **kwargs)

            np.load = _safe_load
            try:
                _kokoro_instance = kokoro_onnx.Kokoro(self._kokoro_model, self._kokoro_voices)
            finally:
                np.load = orig_load

        return _kokoro_instance

    def _synthesize_kokoro(self, text: str) -> Tuple[bytes, int]:
        """Synthesize using in-process Kokoro-82M model with af_bella voice."""
        kokoro = self._get_kokoro()

        voice = "af_bella"

        samples, sr = kokoro.create(
            text,
            voice=voice,
            speed=self._kokoro_speed,
            lang=self._kokoro_lang,
        )

        # Convert float32 array (-1.0 to 1.0) into 16-bit PCM bytes
        samples_np = np.asarray(samples, dtype=np.float32)
        samples_clipped = np.clip(samples_np * 32767.0, -32768, 32767).astype(np.int16)
        audio_bytes = samples_clipped.tobytes()
        return audio_bytes, sr

    def synthesize(self, text: str) -> Tuple[bytes, int]:
        """Convert *text* to raw 16-bit PCM audio bytes and sample rate (24 kHz)
        using Kokoro-82M (af_bella).
        """
        if not text or not text.strip():
            return b"", self.sample_rate

        return self._synthesize_kokoro(text)

    def synthesize_to_file(self, text: str, output_path: str) -> int:
        """Synthesize *text* and write a standard WAV file.

        Returns the sample rate used.
        """
        audio_bytes, sr = self.synthesize(text)
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio_bytes)
        return sr

