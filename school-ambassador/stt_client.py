"""Speech-to-Text client with NVIDIA Parakeet TDT 0.6B v3 as primary engine
and faster-whisper as the fallback engine.

Primary Model:
  NVIDIA Parakeet TDT 0.6B v3 (FastConformer-TDT, CC-BY-4.0)
  High-accuracy, multilingual, low-latency transducer model running locally
  via sherpa-onnx CPU runtime.

Fallback Model:
  faster-whisper (CTranslate2 backend, int8 quantized).
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path
from typing import Optional, Union

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

BASE_DIR = Path(__file__).resolve().parent

_TIER_WHISPER_MAP = {
    "A": "small",
    "B": "base",
    "C": "tiny",
}


def _load_stt_config() -> dict:
    """Return the ``stt:`` section of config.yaml."""
    try:
        config_path = BASE_DIR / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("stt", {})
    except FileNotFoundError:
        return {}


def _load_hardware_tier() -> str:
    """Return the hardware tier letter from hardware_profile.json, or 'B'."""
    try:
        profile_path = BASE_DIR / "hardware_profile.json"
        with open(profile_path, "r", encoding="utf-8") as fh:
            profile = json.load(fh)
        return profile.get("tier", "B")
    except (FileNotFoundError, json.JSONDecodeError):
        return "B"


class STTClient:
    """Synchronous STT client supporting NVIDIA Parakeet TDT 0.6B v3 & Whisper."""

    def __init__(self) -> None:
        cfg = _load_stt_config()
        self._engine_preference = cfg.get("engine", "parakeet").lower()
        self._parakeet_recognizer = None
        self._whisper_model = None
        self._active_engine = "whisper"

        # Try initializing NVIDIA Parakeet TDT 0.6B v3
        if self._engine_preference == "parakeet":
            parakeet_cfg = cfg.get("parakeet", {})
            model_dir = BASE_DIR / parakeet_cfg.get("model_dir", "models/parakeet-tdt-0.6b-v3")
            tokens_path = model_dir / parakeet_cfg.get("tokens", "tokens.txt")
            encoder_path = model_dir / parakeet_cfg.get("encoder", "encoder.int8.onnx")
            decoder_path = model_dir / parakeet_cfg.get("decoder", "decoder.int8.onnx")
            joiner_path = model_dir / parakeet_cfg.get("joiner", "joiner.int8.onnx")

            # Check if files exist and sherpa-onnx is available
            if tokens_path.is_file() and encoder_path.is_file():
                try:
                    import sherpa_onnx

                    num_threads = int(parakeet_cfg.get("num_threads", 4))
                    self._parakeet_recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                        tokens=str(tokens_path),
                        encoder=str(encoder_path),
                        decoder=str(decoder_path),
                        joiner=str(joiner_path),
                        model_type="nemo_transducer",
                        num_threads=num_threads,
                        sample_rate=16000,
                        feature_dim=128,
                        decoding_method="greedy_search",
                    )
                    self._active_engine = "parakeet"
                    print("🎤  STT: NVIDIA Parakeet TDT 0.6B v3 (FastConformer-TDT, CC-BY-4.0)")
                except Exception as exc:
                    print(f"⚠️   Could not initialize sherpa-onnx Parakeet ({exc}). Falling back to faster-whisper.")
            else:
                print("ℹ️   NVIDIA Parakeet TDT 0.6B v3 model files not found in models/parakeet-tdt-0.6b-v3/.")
                print("    Falling back to faster-whisper (CTranslate2).")

        # Fallback to faster-whisper if Parakeet is not active
        if self._parakeet_recognizer is None:
            whisper_cfg = cfg.get("whisper", {})
            tier = _load_hardware_tier()
            model_size = _TIER_WHISPER_MAP.get(tier, "base")

            from faster_whisper import WhisperModel

            device = whisper_cfg.get("device", "cpu")
            compute_type = whisper_cfg.get("compute_type", "int8")
            self._language = whisper_cfg.get("language", "en")

            self._whisper_model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            self._model_size = model_size
            self._active_engine = "whisper"
            print(f"🎤  STT: faster-whisper ({model_size}, int8)")

    @property
    def engine(self) -> str:
        """Name of the active STT engine ('parakeet' or 'whisper')."""
        return self._active_engine

    @property
    def model_size(self) -> str:
        if self._active_engine == "parakeet":
            return "0.6B v3"
        return getattr(self, "_model_size", "base")

    def _load_audio_as_float32(self, audio_source: Union[str, bytes, np.ndarray]) -> Optional[np.ndarray]:
        """Convert path, bytes, or ndarray into normalized float32 mono array."""
        if isinstance(audio_source, str):
            if not os.path.isfile(audio_source):
                return None
            try:
                with wave.open(audio_source, "rb") as wf:
                    data = wf.readframes(wf.getnframes())
                return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            except Exception:
                return None
        elif isinstance(audio_source, (bytes, bytearray)):
            return np.frombuffer(audio_source, dtype=np.int16).astype(np.float32) / 32768.0
        elif isinstance(audio_source, np.ndarray):
            if audio_source.dtype == np.int16:
                return audio_source.astype(np.float32) / 32768.0
            return audio_source.astype(np.float32)
        return None

    def transcribe(self, audio_source: Union[str, bytes, np.ndarray]) -> Optional[str]:
        """Transcribe audio (path to WAV, raw PCM bytes, or float32 ndarray)
        and return the transcribed text, or ``None`` if no speech was found."""
        audio_np = self._load_audio_as_float32(audio_source)
        if audio_np is None or len(audio_np) == 0:
            return None

        # 1. Parakeet TDT 0.6B v3 inference
        if self._active_engine == "parakeet" and self._parakeet_recognizer is not None:
            try:
                stream = self._parakeet_recognizer.create_stream()
                stream.accept_waveform(16000, audio_np)
                self._parakeet_recognizer.decode_stream(stream)
                text = stream.result.text.strip()
                return text if text else None
            except Exception as exc:
                print(f"⚠️   Parakeet transcription failed ({exc}). Trying Whisper fallback.")

        # 2. faster-whisper fallback
        if self._whisper_model is not None:
            segments, _ = self._whisper_model.transcribe(
                audio_np,
                language=getattr(self, "_language", "en"),
                beam_size=3,
                best_of=2,
                vad_filter=True,
            )
            text_parts = [s.text.strip() for s in segments]
            full_text = " ".join(text_parts).strip()
            return full_text if full_text else None

        return None

    def transcribe_bytes(self, audio_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe raw 16-bit PCM audio bytes directly."""
        return self.transcribe(audio_bytes)
