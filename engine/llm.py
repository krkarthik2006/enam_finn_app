"""Single OpenAI-compatible model boundary: validated cache, bounded retries and usage."""

import hashlib
import json
import time
from pathlib import Path

import httpx

from finn.providers import ProviderError

PROMPTS = Path(__file__).parent / "prompts"


class LLM:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def complete(self, payload, version, validate):
        key = hashlib.sha256(json.dumps({
            "endpoint": self.settings.glm_base_url, "version": version, "payload": payload,
        }, sort_keys=True).encode()).hexdigest()
        cached = self.db.one("SELECT payload FROM llm_cache WHERE key=?", (key,))
        if cached:
            raw = json.loads(cached["payload"])
            validate(raw)
            self.log(payload["model"], version, "cached", {}, 0)
            return raw
        if not self.settings.glm_api_key.get_secret_value():
            raise ProviderError("Model key is not configured")
        started = time.monotonic()
        try:
            with httpx.Client(timeout=90) as client:
                for attempt in range(2):
                    try:
                        response = client.post(
                            self.settings.glm_base_url.rstrip("/") + "/chat/completions",
                            headers={"Authorization": "Bearer " + self.settings.glm_api_key.get_secret_value()},
                            json=payload,
                        )
                        response.raise_for_status()
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                            exc.response.status_code == 429 or exc.response.status_code >= 500
                        )
                        if attempt or not retryable:
                            raise
                        time.sleep(0.25)
            raw = response.json()
            validate(raw)  # Invalid citations/schema must never enter the cache.
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            self.log(payload["model"], version, "failed", {}, time.monotonic() - started)
            raise ProviderError("Model request failed or returned invalid structured evidence") from exc
        self.db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?)", (key, json.dumps(raw)))
        self.log(payload["model"], version, "completed", raw.get("usage", {}), time.monotonic() - started)
        return raw

    def log(self, model, task, status, usage, seconds):
        self.db.execute(
            "INSERT INTO llm_calls(model,task,status,prompt_tokens,completion_tokens,seconds) VALUES (?,?,?,?,?,?)",
            (model, task, status, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), seconds),
        )
