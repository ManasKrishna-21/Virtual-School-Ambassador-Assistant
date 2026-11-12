"""Local LLM client for grounded Q&A generation.

Talks to a locally-served model via Ollama's HTTP API (default
``http://127.0.0.1:11434``).  The system prompt bakes in the school
name, company name, audience, and two worked few-shot examples so the
small model stays on-format.

Everything is synchronous — no ``async`` / ``await``.
"""

from __future__ import annotations

import json
from typing import List, Optional

import httpx
import yaml


def _load_config() -> dict:
    """Load the full config.yaml."""
    try:
        with open("config.yaml", "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


# ─── System prompt template ─────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = """\
You are the voice of {school_name}, speaking through a kiosk to parents, students, teachers, and visitors. \
Answer only using the information given below under "Context." \
If the Context does not contain the answer, reply with exactly: "I don't have that information -- please check with the school office." and say nothing else. \
Never invent facts, names, dates, or numbers. \
Keep every answer to 1-3 short sentences in a warm, simple, spoken style -- you are heard, not read, so never use lists, bullet points, or markdown formatting. \
You may describe {school_name}'s partnership with {company_name} only when the Context below actually includes partnership information for this question. \
Do not answer questions unrelated to the school. \
If asked something personal, medical, legal, or about another specific child's or staff member's private details, decline and point to the school office.

Audience: {audience} -- adjust tone accordingly: simpler words and extra warmth for a student, concise and procedural for a parent or teacher.

Example 1
Context: School gates open at 7:30 AM and close at 8:00 AM. Students arriving after 8:00 AM must sign in at the front office.
Question: What time do the gates open?
Answer: The gates open at seven thirty in the morning and close at eight. If you arrive after eight, just sign in at the front office.

Example 2
Context: (nothing relevant retrieved)
Question: What's the school's wifi password?
Answer: I don't have that information -- please check with the school office.

Context:
{retrieved_chunks}

Question: {question}

Answer:\
"""


class LLMClient:
    """Synchronous Ollama-backed LLM client with grounded prompt assembly."""

    def __init__(self) -> None:
        cfg = _load_config()
        llm_cfg = cfg.get("llm", {})
        self._base_url = llm_cfg.get("base_url", "http://127.0.0.1:11434")
        self._model = llm_cfg.get("model", "qwen2.5:0.5b")
        self._temperature = float(llm_cfg.get("temperature", 0.25))
        self._max_tokens = int(llm_cfg.get("max_tokens", 80))
        self._school_name = cfg.get("school_name", "Our School")
        self._company_name = cfg.get("company_name", "Weguide")

        guardrail_cfg = cfg.get("guardrails", {})
        self._fallback = guardrail_cfg.get(
            "fallback_message",
            "I don't have that information -- please check with the school office.",
        )

    @property
    def model_name(self) -> str:
        return self._model

    def build_prompt(
        self,
        question: str,
        chunks: Optional[List[str]],
        audience: str = "visitor",
    ) -> str:
        """Assemble the full system prompt with context and question."""
        if chunks:
            context_block = "\n\n".join(
                f"[{i+1}] {chunk}" for i, chunk in enumerate(chunks)
            )
        else:
            context_block = "(nothing relevant retrieved)"

        return _SYSTEM_PROMPT_TEMPLATE.format(
            school_name=self._school_name,
            company_name=self._company_name,
            audience=audience,
            retrieved_chunks=context_block,
            question=question,
        )

    def generate(
        self,
        question: str,
        chunks: Optional[List[str]],
        audience: str = "visitor",
    ) -> str:
        """Generate a grounded answer using Ollama's ``/api/generate`` endpoint.

        Returns the answer string, or the fallback line on failure.
        """
        prompt = self.build_prompt(question, chunks, audience)

        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self._base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("response", "").strip()
                if not answer:
                    return self._fallback
                return answer
        except Exception:
            return self._fallback

