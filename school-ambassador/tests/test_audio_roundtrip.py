"""test_audio_roundtrip.py — Smoke-test the STT and TTS stages.

Usage::

    uv run python tests/test_audio_roundtrip.py

1. Synthesizes a known sentence via TTS → WAV file.
2. Feeds that WAV back through STT.
3. Checks that the STT output contains expected words.

This confirms the audio pipeline works on this specific machine before
anyone attempts a live conversation.
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    print("═══════════════════════════════════════════════════════")
    print("  Audio Roundtrip Test — TTS → WAV → STT")
    print("═══════════════════════════════════════════════════════\n")

    test_sentence = "The school gates open at seven thirty in the morning."
    expected_words = ["school", "gates", "seven", "thirty", "morning"]

    # ── Step 1: TTS synthesis ───────────────────────────────────
    try:
        from tts_client import TTSClient

        tts = TTSClient()
        print(f"1. Synthesizing test sentence with {tts.engine.title()} TTS…")
        audio_bytes, sample_rate = tts.synthesize(test_sentence)

        if not audio_bytes:
            print("   ❌  TTS returned empty audio.")
            print("\n   ⚠  If TTS model is not installed, download kokoro-v0_19.onnx and voices.json.")
            sys.exit(1)

        print(f"   ✅  TTS ({tts.engine.title()}) produced {len(audio_bytes)} bytes at {sample_rate} Hz")

    except RuntimeError as exc:
        print(f"   ⚠  TTS not available: {exc}")
        print("\n   Skipping roundtrip — TTS model files must be in models/ for this test.")
        sys.exit(0)  # Not a failure, just a skip
    except Exception as exc:
        print(f"   ❌  TTS error: {exc}")
        sys.exit(1)

    # ── Step 2: Write to temp WAV ───────────────────────────────
    print("2. Writing audio to temporary WAV file…")
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        with wave.open(tmp_wav.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)
        print(f"   ✅  WAV written: {tmp_wav.name}")
    except Exception as exc:
        print(f"   ❌  WAV write error: {exc}")
        sys.exit(1)

    # ── Step 3: STT transcription ───────────────────────────────
    print("3. Transcribing WAV with faster-whisper…")
    try:
        from stt_client import STTClient

        stt = STTClient()
        transcription = stt.transcribe(tmp_wav.name)

        if not transcription:
            print("   ❌  STT returned empty transcription.")
            sys.exit(1)

        print(f"   📝  Transcription: \"{transcription}\"")
    except Exception as exc:
        print(f"   ❌  STT error: {exc}")
        sys.exit(1)
    finally:
        # Cleanup temp file
        try:
            os.unlink(tmp_wav.name)
        except OSError:
            pass

    # ── Step 4: Verify keywords ─────────────────────────────────
    print("4. Checking transcription against expected words…")
    transcription_lower = transcription.lower()
    matched = [w for w in expected_words if w in transcription_lower]
    missed = [w for w in expected_words if w not in transcription_lower]

    print(f"   Matched: {matched}")
    if missed:
        print(f"   Missed:  {missed}")

    # ── Result ──────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    match_ratio = len(matched) / len(expected_words)
    if match_ratio >= 0.6:
        print(f"✅  PASS — {len(matched)}/{len(expected_words)} keywords matched")
        print(f"   Input:  \"{test_sentence}\"")
        print(f"   Output: \"{transcription}\"")
        sys.exit(0)
    else:
        print(f"❌  FAIL — only {len(matched)}/{len(expected_words)} keywords matched")
        print(f"   Input:  \"{test_sentence}\"")
        print(f"   Output: \"{transcription}\"")
        print("\n   The STT model may need a different size or the TTS")
        print("   voice may not be clear enough for this machine.")
        sys.exit(1)


if __name__ == "__main__":
    main()

