"""Hardware Benchmark — profiles the school computer and writes hardware_profile.json.

Usage::

    uv run python benchmark.py

Times a representative STT transcription, TTS synthesis, and LLM
generation, then classifies the machine into Tier A / B / C and writes
the result to ``hardware_profile.json``.

Tier definitions
----------------
  Tier A (fast)   → Whisper ``small``, richest Piper voice, Silero VAD
  Tier B (medium) → Whisper ``base``,  standard voice,     Silero VAD (if budget allows, else webrtcvad)
  Tier C (slow)   → Whisper ``tiny``,  lightest voice,     webrtcvad
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
import struct
from typing import Dict

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


def _generate_sine_wav(path: str, duration: float = 2.0, sample_rate: int = 16000) -> None:
    """Write a short sine-wave WAV for STT timing (not meaningful speech)."""
    import math
    n_samples = int(duration * sample_rate)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            sample = int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wf.writeframes(struct.pack("<h", sample))


def benchmark_stt(sample_wav: str) -> float:
    """Time a faster-whisper transcription on the base model. Returns ms."""
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    start = time.perf_counter()
    segments, _info = model.transcribe(sample_wav, language="en", beam_size=1)
    # Consume the generator
    for _ in segments:
        pass
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed


def benchmark_tts() -> float:
    """Time a TTS synthesis with Kokoro-82M (af_bella @ 24 kHz). Returns ms."""
    sample_text = "Hello, welcome to our school. How can I help you today?"
    try:
        from tts_client import TTSClient

        tts = TTSClient()
        start = time.perf_counter()
        _samples, _sr = tts.synthesize(sample_text)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"    [Kokoro-82M (af_bella @ {_sr}Hz): {elapsed:.0f} ms]")
        return elapsed
    except Exception as exc:
        print(f"  ⚠  Kokoro synthesis error: {exc}")
        return -1.0


def benchmark_llm() -> float:
    """Time a short Ollama generation. Returns ms."""
    import httpx

    cfg = _load_config().get("llm", {})
    base_url = cfg.get("base_url", "http://127.0.0.1:11434")
    model = cfg.get("model", "qwen2.5:0.5b")

    payload = {
        "model": model,
        "prompt": "What time do school gates open? Answer in one sentence.",
        "stream": False,
        "options": {"temperature": 0.25, "num_predict": 40},
    }

    try:
        start = time.perf_counter()
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{base_url}/api/generate", json=payload)
            resp.raise_for_status()
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed
    except Exception as exc:
        print(f"  ⚠  LLM benchmark failed ({exc}) — is Ollama running?")
        return -1.0


def classify_tier(stt_ms: float, tts_ms: float, llm_ms: float) -> str:
    """Classify hardware into Tier A / B / C based on benchmark results."""
    cfg = _load_config().get("latency_targets_ms", {})
    stt_budget = cfg.get("stt", 800)
    tts_budget = cfg.get("tts", 800)
    llm_budget = cfg.get("llm", 1200)

    # Count how many stages are within budget
    within = 0
    total = 0

    if stt_ms > 0:
        total += 1
        if stt_ms <= stt_budget:
            within += 1

    if tts_ms > 0:
        total += 1
        if tts_ms <= tts_budget:
            within += 1

    if llm_ms > 0:
        total += 1
        if llm_ms <= llm_budget:
            within += 1

    if total == 0:
        return "B"  # Fallback when benchmarks couldn't run

    ratio = within / total
    if ratio >= 0.9:
        return "A"
    elif ratio >= 0.5:
        return "B"
    else:
        return "C"


def main() -> None:
    print("═══════════════════════════════════════════════════════")
    print("  AI School Ambassador — Hardware Benchmark")
    print("═══════════════════════════════════════════════════════\n")

    sample_wav = "_benchmark_sample.wav"

    # ── Generate sample audio ───────────────────────────────────
    print("🔊  Generating sample audio…")
    _generate_sine_wav(sample_wav)

    # ── STT Benchmark ───────────────────────────────────────────
    print("🎤  Benchmarking STT (faster-whisper, base model, int8)…")
    try:
        stt_ms = benchmark_stt(sample_wav)
        print(f"    ⏱  STT: {stt_ms:.0f} ms")
    except Exception as exc:
        print(f"    ❌  STT benchmark failed: {exc}")
        stt_ms = -1.0

    # ── TTS Benchmark ───────────────────────────────────────────
    print("🔈  Benchmarking TTS (Kokoro af_bella 24kHz)…")
    tts_ms = benchmark_tts()
    if tts_ms > 0:
        print(f"    ⏱  TTS: {tts_ms:.0f} ms")

    # ── LLM Benchmark ───────────────────────────────────────────
    print("🧠  Benchmarking LLM (Ollama)…")
    llm_ms = benchmark_llm()
    if llm_ms > 0:
        print(f"    ⏱  LLM: {llm_ms:.0f} ms")

    # ── Classify ────────────────────────────────────────────────
    tier = classify_tier(stt_ms, tts_ms, llm_ms)
    tier_names = {"A": "Fast", "B": "Medium", "C": "Slow"}

    # ── Determine component choices per tier ────────────────────
    tier_config = {
        "A": {"whisper_model": "small", "tts_engine": "kokoro", "voice": "af_bella", "sample_rate": 24000, "vad": "silero"},
        "B": {"whisper_model": "base",  "tts_engine": "kokoro", "voice": "af_bella", "sample_rate": 24000, "vad": "silero"},
        "C": {"whisper_model": "tiny",  "tts_engine": "kokoro", "voice": "af_bella", "sample_rate": 24000, "vad": "webrtcvad"},
    }

    # For tier B, downgrade VAD if TTS was already slow
    profile_components = tier_config[tier].copy()
    if tier == "B" and tts_ms > 0 and tts_ms > 600:
        profile_components["vad"] = "webrtcvad"

    profile = {
        "tier": tier,
        "tier_name": tier_names[tier],
        "benchmarks": {
            "stt_ms": round(stt_ms, 1) if stt_ms > 0 else None,
            "tts_ms": round(tts_ms, 1) if tts_ms > 0 else None,
            "llm_ms": round(llm_ms, 1) if llm_ms > 0 else None,
        },
        "components": profile_components,
        "benchmarked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    with open("hardware_profile.json", "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)

    # ── Cleanup ─────────────────────────────────────────────────
    try:
        os.unlink(sample_wav)
    except OSError:
        pass

    # ── Report ──────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"🏆  Hardware Tier: {tier} ({tier_names[tier]})")
    print(f"    Whisper model:  {profile_components['whisper_model']}")
    print(f"    Voice quality:  {profile_components['voice_quality']}")
    print(f"    VAD engine:     {profile_components['vad']}")
    print(f"\n✅  Profile written to: hardware_profile.json")


if __name__ == "__main__":
    main()

