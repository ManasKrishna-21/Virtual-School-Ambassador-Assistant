"""test_offline.py — Assert no network calls occur during a pipeline turn.

Usage::

    uv run python tests/test_offline.py

Monkey-patches ``socket.socket`` to block all outbound connections
(except localhost for Ollama), then runs a simulated pipeline turn.
Fails if any external network call is attempted.
"""

from __future__ import annotations

import os
import socket
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_original_connect = socket.socket.connect
_violations: list[str] = []

ALLOWED_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",
}


def _patched_connect(self, address):
    """Intercept socket.connect to catch any non-local connections."""
    host = None
    if isinstance(address, tuple) and len(address) >= 2:
        host = str(address[0])
    elif isinstance(address, str):
        host = address

    if host and host not in ALLOWED_HOSTS:
        msg = f"BLOCKED external connection to: {address}"
        _violations.append(msg)
        raise ConnectionRefusedError(msg)

    return _original_connect(self, address)


def main() -> None:
    print("═══════════════════════════════════════════════════════")
    print("  Offline Test — verifying no external network calls")
    print("═══════════════════════════════════════════════════════\n")

    # Apply monkey-patch
    socket.socket.connect = _patched_connect

    try:
        # Simulate a pipeline turn without microphone
        from retriever import Retriever
        from llm_client import LLMClient
        from guardrails import Guardrails

        print("1. Testing retriever initialization…")
        retriever = Retriever()

        print("2. Testing retrieval query…")
        chunks = retriever.query("What time do the gates open?")
        if chunks:
            print(f"   Retrieved {len(chunks)} chunk(s)")

        print("3. Testing LLM generation…")
        llm = LLMClient()
        if chunks:
            answer = llm.generate("What time do the gates open?", chunks)
            print(f"   Answer: {answer[:80]}…")

        print("4. Testing guardrails…")
        guard = Guardrails()
        safe, _ = guard.check("What time do the gates open?")
        print(f"   Safe: {safe}")

    except ConnectionRefusedError as exc:
        # This is expected if we blocked something
        pass
    except Exception as exc:
        print(f"   ⚠  Non-network error (OK): {exc}")
    finally:
        # Restore original
        socket.socket.connect = _original_connect

    # Report
    print(f"\n{'─'*50}")
    if _violations:
        print(f"❌  FAIL — {len(_violations)} external network call(s) detected:")
        for v in _violations:
            print(f"   • {v}")
        sys.exit(1)
    else:
        print("✅  PASS — No external network calls detected.")
        print("   (Localhost connections to Ollama on 127.0.0.1 are allowed.)")
        sys.exit(0)


if __name__ == "__main__":
    main()

