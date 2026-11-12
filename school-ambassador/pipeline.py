"""AI School Ambassador — Main Pipeline.

Usage::

    uv run python pipeline.py

This is the single-process synchronous loop that ties every stage
together.  No ``async`` / ``await`` anywhere.

Loop:
  1. Wait for trigger  (TriggerSource)
  2. Record audio + VAD trim
  3. Transcribe with faster-whisper  (STTClient)
  4. Check guardrails on the question
  5. Select audience
  6. Retrieve context from Chroma  (Retriever)
  7. Generate grounded answer  (LLMClient)
  8. Check guardrails on the answer
  9. Synthesize speech  (TTSClient)
 10. Play audio + show caption  (AudioSink + CaptionDisplay)
 11. Log the turn  (QueryLogger)
 12. Return to step 1

Every stage is wrapped in try/except so a single bad turn degrades
gracefully instead of crashing the kiosk.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Always run from the directory containing pipeline.py
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")



# ─── Load full config ───────────────────────────────────────────
def _load_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        print("❌  config.yaml not found. Cannot start the pipeline.")
        sys.exit(1)


def _is_offline() -> bool:
    """Check whether the manual offline flag is set."""
    return os.path.isfile("offline.flag")


# ─── Startup checks ────────────────────────────────────────────
def startup_checks() -> None:
    """Validate that essential prerequisites are in place before entering
    the main loop."""

    config = _load_config()

    # 1. Offline flag
    if _is_offline():
        print("⏸  offline.flag detected — kiosk is paused.")
        print("   Remove the file and restart to resume.")
        sys.exit(0)

    # 2. Chroma index
    rag_cfg = config.get("rag", {})
    chroma_dir = rag_cfg.get("chroma_dir", "chroma_db")
    if not os.path.isdir(chroma_dir):
        print(
            f"❌  Chroma index directory '{chroma_dir}' not found.\n"
            "   Run  uv run python ingest.py  to build the knowledge-base index first."
        )
        sys.exit(1)

    # 3. KB freshness warning
    try:
        from freshness_check import check_freshness

        stale = check_freshness()
        if stale:
            print("⚠️  Stale KB files (not modified in 90+ days):")
            for s in stale:
                print(f"   • {s}")
            print()
    except ImportError:
        pass

    print("✅  Startup checks passed.\n")


# ─── Main loop ──────────────────────────────────────────────────
def main() -> None:
    print("═══════════════════════════════════════════════════════")
    print("  AI School Ambassador — Pipeline")
    print("═══════════════════════════════════════════════════════\n")

    startup_checks()

    config = _load_config()
    guardrail_cfg = config.get("guardrails", {})
    fallback_msg = guardrail_cfg.get(
        "fallback_message",
        "I don't have that information -- please check with the school office.",
    )
    error_msg = guardrail_cfg.get(
        "error_message",
        "Sorry, something went wrong -- please ask a staff member or try again.",
    )

    # ── Lazy-init components (so import errors are caught cleanly) ──
    print("📦  Loading components…")

    from hardware_io import DevTriggerSource, DevAudioSink, DevCaptionDisplay, RobotController
    from stt_client import STTClient
    from tts_client import TTSClient
    from llm_client import LLMClient
    from retriever import Retriever
    from guardrails import Guardrails
    from logger import QueryLogger
    from audio_recorder import record_audio
    from audience_selector import get_audience

    trigger = DevTriggerSource()
    audio_sink = DevAudioSink()
    display = DevCaptionDisplay()
    robot = RobotController()
    stt = STTClient()
    tts = TTSClient()
    llm = LLMClient()
    retriever = Retriever()
    guard = Guardrails()
    query_logger = QueryLogger()

    # Verify index is non-empty
    if not retriever.check_index_exists():
        print(
            "❌  Chroma collection 'school_kb' is empty.\n"
            "   Run  uv run python ingest.py  to index your knowledge base."
        )
        sys.exit(1)

    print(f"🧠  LLM: {llm.model_name}")
    if stt.engine == "parakeet":
        print(f"🎤  STT: NVIDIA Parakeet TDT ({stt.model_size}, CC-BY-4.0)")
    else:
        print(f"🎤  STT: faster-whisper ({stt.model_size})")
    print(f"🔊  TTS: Kokoro-82M female voice ({tts.voice} @ {tts.sample_rate} Hz)")
    print(f"\n{'═'*55}")
    print("  Ready — waiting for interaction…")
    print(f"{'═'*55}\n")

    # ── Main pipeline loop ──────────────────────────────────────
    while True:
        try:
            # Check offline flag each iteration
            if _is_offline():
                print("\n⏸  offline.flag detected — pausing kiosk.")
                print("   Remove the file and restart pipeline.py to resume.")
                break

            # ── Step 1: Wait for trigger ────────────────────────
            if not trigger.wait_for_trigger():
                print("\n👋  Goodbye!")
                break

            turn_start = time.perf_counter()

            # ── Step 2: Robot greets ────────────────────────────
            robot.trigger("greet")

            # ── Step 3: Capture Question (Audio or Typed) ──────
            if getattr(trigger, "last_typed_text", None):
                question = trigger.last_typed_text
                robot.trigger("think")
            else:
                try:
                    result = record_audio()
                    if result is None:
                        # No speech → return to idle
                        robot.trigger("idle")
                        continue
                    audio_bytes, wav_path = result
                    if audio_bytes == b"" and isinstance(wav_path, str):
                        # User typed the question directly in the fallback prompt
                        question = wav_path
                        robot.trigger("think")
                    else:
                        # ── Step 4: Transcribe ──────────────────────────────
                        robot.trigger("think")
                        try:
                            question = stt.transcribe(wav_path)
                        except Exception as exc:
                            print(f"  ❌  STT error: {exc}")
                            _speak_error(error_msg, tts, audio_sink, display, robot)
                            _cleanup_wav(wav_path)
                            continue

                        _cleanup_wav(wav_path)

                        if not question:
                            print("  ⏸  Whisper heard no words in the audio.")
                            try:
                                typed = input("  ⌨️   Type your question instead (or Enter to skip): ").strip()
                                if typed:
                                    question = typed
                                else:
                                    robot.trigger("idle")
                                    continue
                            except (EOFError, KeyboardInterrupt):
                                robot.trigger("idle")
                                continue
                except Exception as exc:
                    print(f"  ❌  Recording error: {exc}")
                    robot.trigger("idle")
                    continue

            print("\n" + "─" * 55)
            print(f"🗣  Question: {question}")
            print("─" * 55)

            # ── Step 5: Guardrail check on question ─────────────
            try:
                q_safe, q_reason = guard.check_question(question)
            except Exception:
                q_safe, q_reason = True, ""

            if not q_safe:
                print(f"  🛡  Question flagged: {q_reason}")
                _speak_decline(guard.decline_message, tts, audio_sink, display, robot)
                query_logger.log(
                    question=question,
                    answer=guard.decline_message,
                    flagged=True,
                )
                continue

            # ── Step 6: Audience selection ───────────────────────
            try:
                audience = get_audience(timeout=5.0)
            except Exception:
                audience = "visitor"

            # ── Step 7: Retrieve context ────────────────────────
            try:
                chunks = retriever.query(question, audience)
                sources = retriever.last_sources
            except Exception as exc:
                print(f"  ❌  Retrieval error: {exc}")
                _speak_error(error_msg, tts, audio_sink, display, robot)
                continue

            if chunks is None:
                # Nothing relevant found — speak fallback, skip LLM
                print("  📭  No relevant context found — using fallback.")
                _speak_fallback(fallback_msg, tts, audio_sink, display, robot)
                query_logger.log(
                    question=question,
                    answer=fallback_msg,
                    audience=audience,
                    sources=[],
                )
                continue

            # ── Step 8: Generate answer ─────────────────────────
            try:
                answer = llm.generate(question, chunks, audience)
            except Exception as exc:
                print(f"  ❌  LLM error: {exc}")
                _speak_error(error_msg, tts, audio_sink, display, robot)
                continue

            print(f"  💬  Answer: {answer}")

            # ── Step 9: Guardrail check on answer ───────────────
            try:
                a_safe, a_reason = guard.check_answer(answer)
            except Exception:
                a_safe, a_reason = True, ""

            if not a_safe:
                print(f"  🛡  Answer flagged: {a_reason}")
                answer = guard.decline_message

            # ── Step 10: Synthesize & play ──────────────────────
            try:
                audio_out, sr = tts.synthesize(answer)
                display.show(answer, question=question)
                audio_sink.play(audio_out, sr)
            except Exception as exc:
                print(f"  ❌  TTS/playback error: {exc}")
                # Still show the text answer at minimum
                display.show(answer, question=question)

            # ── Step 11: Log ────────────────────────────────────
            elapsed_ms = (time.perf_counter() - turn_start) * 1000
            try:
                query_logger.log(
                    question=question,
                    answer=answer,
                    audience=audience,
                    sources=sources,
                    latency_ms=elapsed_ms,
                    flagged=not a_safe,
                )
            except Exception:
                pass

            print(f"  ⏱  Turn latency: {elapsed_ms:.0f} ms")

        except KeyboardInterrupt:
            print("\n\n👋  Pipeline stopped by user.")
            break
        except Exception as exc:
            # Outer catch-all: log crash and restart the loop
            print(f"\n💥  Unhandled error: {exc}")
            print("    Restarting loop in 2 seconds…\n")
            time.sleep(2)
            continue


# ─── Helpers ────────────────────────────────────────────────────
def _speak_error(msg, tts, audio_sink, display, robot):
    """Speak the error apology message."""
    robot.trigger("shrug")
    display.show(msg)
    try:
        audio, sr = tts.synthesize(msg)
        audio_sink.play(audio, sr)
    except Exception:
        pass


def _speak_fallback(msg, tts, audio_sink, display, robot):
    """Speak the 'nothing found' fallback message."""
    robot.trigger("nod")
    display.show(msg)
    try:
        audio, sr = tts.synthesize(msg)
        audio_sink.play(audio, sr)
    except Exception:
        pass


def _speak_decline(msg, tts, audio_sink, display, robot):
    """Speak the guardrail decline message."""
    robot.trigger("shrug")
    display.show(msg)
    try:
        audio, sr = tts.synthesize(msg)
        audio_sink.play(audio, sr)
    except Exception:
        pass


def _cleanup_wav(path: str) -> None:
    """Remove a temporary WAV file."""
    try:
        os.unlink(path)
    except (OSError, TypeError):
        pass


# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    main()

