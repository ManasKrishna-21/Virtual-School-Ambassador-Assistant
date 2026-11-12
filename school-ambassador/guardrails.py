"""Guardrails — lightweight keyword / pattern safety filter.

Runs on both the transcribed question and the generated answer *before*
TTS.  On a flag the pipeline skips TTS of the model's text and speaks
the fixed decline line instead.

Categories checked:
  • violence & weapons
  • self-harm & suicide
  • sexual content
  • hate speech & slurs
  • requests for private individual details
  • prompt-injection / jailbreak patterns
"""

from __future__ import annotations

import re
from typing import Tuple

import yaml


def _load_config() -> dict:
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("guardrails", {})
    except FileNotFoundError:
        return {}


# ─── Pattern lists ──────────────────────────────────────────────
# These are deliberately broad trigger words.  False-positive rate
# matters less than missing a genuinely harmful response on a school
# campus kiosk used by children.

_VIOLENCE_PATTERNS = [
    r"\b(kill|murder|shoot|stab|bomb|explo[ds]|weapon|gun|knife|attack|assault)\b",
    r"\b(blow\s+up|set\s+fire|arson)\b",
]

_SELF_HARM_PATTERNS = [
    r"\b(suicide|self[- ]?harm|cut\s+my|hurt\s+myself|end\s+my\s+life|kill\s+myself)\b",
]

_SEXUAL_PATTERNS = [
    r"\b(sex|nude|naked|porn|obscene|genitals|erotic)\b",
]

_HATE_PATTERNS = [
    r"\b(racist|sexist|homophob|transphob|slur|nigger|faggot|retard)\b",
]

_PRIVATE_DATA_PATTERNS = [
    r"\b(home\s+address|phone\s+number|salary|personal\s+email|medical\s+record)\b",
    r"\b(give\s+me\s+(the|a)\s+(address|number|email|phone))\b",
    r"\b(where\s+does\s+\w+\s+live)\b",
]

_JAILBREAK_PATTERNS = [
    r"(forget|ignore|disregard|override)\s+(previous|all|your)\s+(instructions|rules|prompt)",
    r"you\s+are\s+now\s+(DAN|evil|unrestricted)",
    r"pretend\s+you\s+(are|have)\s+no\s+(rules|restrictions|limits)",
    r"(system\s+prompt|base\s+prompt)",
]

# Pre-compile all patterns
_ALL_PATTERNS = []
for group in [
    _VIOLENCE_PATTERNS,
    _SELF_HARM_PATTERNS,
    _SEXUAL_PATTERNS,
    _HATE_PATTERNS,
    _PRIVATE_DATA_PATTERNS,
    _JAILBREAK_PATTERNS,
]:
    for pattern in group:
        _ALL_PATTERNS.append(re.compile(pattern, re.IGNORECASE))


class Guardrails:
    """Synchronous safety filter."""

    def __init__(self) -> None:
        cfg = _load_config()
        self._enabled = cfg.get("enabled", True)
        self._decline_message = cfg.get(
            "decline_message",
            "I cannot assist with that request. Please contact the school office directly.",
        )

    @property
    def decline_message(self) -> str:
        return self._decline_message

    def check(self, text: str) -> Tuple[bool, str]:
        """Check *text* against all guardrail patterns.

        Returns
        -------
        (is_safe, reason)
            ``True`` if the text is safe; otherwise ``False`` with a
            short human-readable reason (logged, not spoken).
        """
        if not self._enabled:
            return True, ""

        if not text:
            return True, ""

        for pattern in _ALL_PATTERNS:
            match = pattern.search(text)
            if match:
                return False, f"Matched guardrail pattern: {match.group()}"

        return True, ""

    def check_question(self, question: str) -> Tuple[bool, str]:
        """Convenience alias for checking the transcribed question."""
        return self.check(question)

    def check_answer(self, answer: str) -> Tuple[bool, str]:
        """Convenience alias for checking the LLM-generated answer."""
        return self.check(answer)

