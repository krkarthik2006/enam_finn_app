import json

import httpx
import pytest

from engine.llm import LLM
from finn.config import Settings
from finn.db import Database
from finn.providers import ProviderError


def gateway(tmp_path, monkeypatch, handle):
    db = Database(tmp_path / "llm.sqlite")
    db.initialize()
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    return LLM(db, Settings(glm_api_key="test-key", _env_file=None)), db


def test_shared_model_cache_versions_and_usage(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"value": 42, "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    llm, db = gateway(tmp_path, monkeypatch, handle)
    payload = {"model": "test", "messages": [{"role": "user", "content": "test"}]}

    def validate(raw):
        assert raw["value"] == 42

    llm.complete(payload, "v1", validate)
    llm.complete(payload, "v1", validate)
    llm.complete(payload, "v2", validate)
    assert len(calls) == 2
    rows = db.all("SELECT * FROM llm_calls ORDER BY id")
    assert [r["status"] for r in rows] == ["completed", "cached", "completed"]
    assert sum(r["prompt_tokens"] for r in rows) == 20
    assert "test-key" not in json.dumps(rows)


@pytest.mark.parametrize("status,expected_calls", [(503, 2), (429, 2), (401, 1)])
def test_bounded_retries_and_no_error_cache(tmp_path, monkeypatch, status, expected_calls):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private provider response"})

    llm, db = gateway(tmp_path, monkeypatch, handle)
    with pytest.raises(ProviderError, match="Model request failed"):
        llm.complete({"model": "test"}, "v1", lambda raw: None)
    assert len(calls) == expected_calls
    assert not db.all("SELECT * FROM llm_cache")


def test_invalid_model_output_not_cached(tmp_path, monkeypatch):
    llm, db = gateway(tmp_path, monkeypatch, lambda req: httpx.Response(200, json={"invented": True}))

    def validate(raw):
        raise ValueError("invalid citation")

    with pytest.raises(ProviderError):
        llm.complete({"model": "test"}, "v1", validate)
    assert not db.all("SELECT * FROM llm_cache")
