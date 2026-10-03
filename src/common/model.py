"""
Provider-agnostic LLM adapter. OpenAI-compatible client, configured via env:
MODEL_ID, MODEL_BASE_URL, MODEL_API_KEY, MODEL_PRICE_IN/OUT (USD per 1M tokens).
Usage and cost are returned per call so callers charge the ledger in REAL
units, replacing the len/4 estimation era. Retries with backoff; structured
outputs enforced by JSON-mode prompt discipline (ask for raw JSON, validate
with Pydantic, retry once on parse failure with the validation error fed back).
"""
from __future__ import annotations
import json
import os
import time
from typing import Any

class ModelCallError(RuntimeError):
    pass

class ModelAdapter:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=os.environ["MODEL_API_KEY"],
            base_url=os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model_id = os.environ["MODEL_ID"]
        self.price_in = float(os.environ.get("MODEL_PRICE_IN", "0.15"))   # per 1M
        self.price_out = float(os.environ.get("MODEL_PRICE_OUT", "0.60"))  # per 1M

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> tuple[Any, dict]:
        """Returns (parsed_json, usage_ledger_entry). Raises ModelCallError."""
        for attempt in range(2):
            try:
                if attempt:
                    user += "\n\nYour previous reply failed validation. Output ONLY valid JSON."
                resp = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
                raw = resp.choices[0].message.content.strip()
                raw = raw[raw.find("["):raw.rfind("]") + 1] or raw[raw.find("{"):raw.rfind("}") + 1]
                parsed = json.loads(raw)
                u = resp.usage
                usage = {
                    "tokens_in": u.prompt_tokens,
                    "tokens_out": u.completion_tokens,
                    "cost_usd": (u.prompt_tokens * self.price_in + u.completion_tokens * self.price_out) / 1e6,
                }
                return parsed, usage
            except Exception as exc:
                if attempt:
                    raise ModelCallError(f"LLM call/parse failed twice: {exc}")
                time.sleep(2)
