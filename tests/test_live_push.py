import json
import os

import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.getenv("FINN_RUN_LIVE_TESTS") != "1",
                                                reason="Explicit live-model opt-in required")]


def test_live_filing_extraction_to_results_card(tmp_path):
    settings = Settings(database_path=tmp_path / "live-push.sqlite", cache_path=tmp_path / "cache", api_token="")
    assert settings.glm_api_key.get_secret_value(), "Live model key required"
    observations = []
    try:
        with TestClient(create_app(settings)) as client:
            response = client.post("/api/demo/phases")
            assert response.status_code == 200, response.text
            scenario = response.json()
            identifier = scenario["results_event_id"]
            response = client.post(f"/api/announcements/{identifier}/enrich")
            observations.append({"status": response.status_code, "response": response.json()})
            assert response.status_code == 200, response.text
            card = response.json()
            assert card["summary_method"] == "source_cited_financials"
            assert card["model_facts"]["financial_periods"]
            periods = card["model_facts"]["financial_periods"]
            assert any(p["period_end"] == scenario["period_end"] for p in periods)
            metrics = card["results"]["period"]["metrics"]
            assert metrics == {"revenue": 1200, "ebitda": 240, "pbt": 200, "pat": 150}
            assert card["results"]["comparisons"]["qoq"]["revenue"]["percent"] == 20
            assert card["results"]["cross_check"]["metrics"]["revenue"]["status"] == "mismatch"
            response = client.post(f"/api/announcements/{identifier}/enrich")
            assert response.status_code == 200
            calls = client.app.state.db.all("SELECT * FROM llm_calls WHERE status='completed'")
            assert len(calls) == 1
            before = len(client.app.state.db.all("SELECT * FROM llm_calls"))
            digest = client.get("/api/digest", params={"mode": "demo", "since": scenario["digest_since"]}).json()
            assert next(i for i in digest["items"] if i["id"] == identifier)["summary_method"] == "source_cited_financials"
            assert len(client.app.state.db.all("SELECT * FROM llm_calls")) == before
    finally:
        (tmp_path / "observations.json").write_text(json.dumps(observations, indent=2))
