import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app
from finn.models import Announcement, Price, PriceImport
from finn.providers import ProviderError


@pytest.fixture
def phase_client(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / "phase.sqlite", cache_path=tmp_path / "cache",
                                       glm_api_key="", api_token="", _env_file=None))) as client:
        yield client


def test_all_three_push_cards_and_reconnect_end_to_end(phase_client):
    client = phase_client
    seeded = client.post("/api/demo/phases")
    assert seeded.status_code == 200, seeded.text
    scenario = seeded.json()
    digest = client.get("/digest", params={"mode": "demo", "from": scenario["digest_since"]}).json()
    assert digest["routine_count"] == 1
    assert len(client.get("/api/network").json()["contacts"]) == 40
    scores = [item["attention_score"]["value"] for item in digest["items"]]
    assert scores == sorted(scores, reverse=True)
    management = next(i for i in digest["items"] if i.get("category") == "management_change")
    assert management["enrichment"]["management"]["paths"][0]["person_ids"] == [
        "investor-local", "workflow-connector", "workflow-cfo",
    ]
    results = next(i for i in digest["items"] if i["id"] == scenario["results_event_id"])["enrichment"]["results"]
    assert results["comparisons"]["qoq"]["revenue"]["percent"] == 20
    assert results["comparisons"]["yoy"]["pat"]["percent"] == 50
    assert results["cross_check"]["metrics"]["revenue"]["status"] == "mismatch"
    assert results["cross_check"]["metrics"]["ebitda"]["status"] == "not_available"
    assert results["cross_check"]["reference"]["mode"] == "demo"
    capex = next(i for i in digest["items"] if i["id"] == scenario["material_event_id"])
    assert any(c["person_id"] == "network-supplier" for c in capex["enrichment"]["contacts"])
    assert any(n["person_id"] == "network-reconnect" for n in client.get("/api/network/reconnect?mode=demo").json()["nudges"])
    assert client.get("/api/digest").json()["items"] == []
    assert not client.app.state.db.all("SELECT * FROM llm_calls")  # Viewing the digest never calls a model.
    prior = len(client.app.state.db.all("SELECT * FROM financials"))
    client.post("/api/demo/phases")
    assert len(client.app.state.db.all("SELECT * FROM financials")) == prior
    assert len(client.get("/api/network").json()["contacts"]) == 40


def test_missing_figures_and_preference_changes(phase_client):
    client = phase_client
    scenario = client.post("/api/demo/phases").json()
    digest = client.get("/api/digest", params={"mode": "demo", "since": scenario["digest_since"]}).json()
    missing = next(i for i in digest["items"] if i["ticker"] == "TCS")
    assert missing["enrichment"]["results"] is None and missing["enrichment"]["gaps"]
    client.put("/settings/alerts", json={"category_weights": {"capex": 5}})
    ranked = client.get("/api/digest?mode=demo").json()["items"]
    assert ranked[0]["category"] == "capex"
    assert client.put("/api/alerts/settings", json={"category_weights": {"capex": -1}}).status_code == 422


def test_filing_extraction_exact_quotes_and_model_cache(phase_client, monkeypatch):
    client = phase_client
    scenario = client.post("/api/demo/phases").json()
    event_id = scenario["results_event_id"]
    client.app.state.providers.settings.glm_api_key = __import__("pydantic").SecretStr("test-key")
    original, calls = httpx.Client, []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        source = json.loads(payload["messages"][1]["content"])["pages"][0]["lines"][-1]["citation_id"]
        facts = {"category": "results", "summary": "Synthetic revenue was INR 1200 crore.",
                 "summary_citation_ids": [source], "person_name": None, "person_title": None, "person_citation_ids": [],
                 "financial_periods": [{"period_end": scenario["period_end"], "basis": "consolidated", "unit": "crore",
                                        "revenue": 1200, "revenue_citation_ids": [source],
                                        "ebitda": None, "ebitda_citation_ids": [],
                                        "pbt": None, "pbt_citation_ids": [], "pat": None, "pat_citation_ids": []}],
                 "gaps": ["Only explicitly extracted metrics are included."]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(facts)}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    response = client.post(f"/api/announcements/{event_id}/enrich")
    assert response.status_code == 200, response.text
    assert response.json()["summary_method"] == "source_cited_financials"
    assert response.json()["results"]["period"]["source_type"] == "filing"
    assert client.post(f"/api/announcements/{event_id}/enrich").status_code == 200
    assert len(calls) == 1
    model_data = calls[0]["messages"][1]["content"]
    assert "workflow-connector" not in model_data and "Neha" not in model_data
    usage = client.get("/api/usage").json()
    assert sum(r["prompt_tokens"] for r in usage["models"]) == 10


def test_live_research_excludes_results_filings(phase_client):
    client = phase_client
    client.post("/api/documents", json={"ticker": "TEST", "kind": "quarterly_results", "title": "Results",
                                       "published_on": "2026-10-01", "text": "Quarterly results: revenue 100 crore. This is not an annual report or transcript."})
    result = client.post("/api/research", json={"ticker": "TEST", "use_model": False}).json()
    assert result["status"] == "needs_sources" and not result["sources"]


def test_owner_edges_are_validated(phase_client):
    client = phase_client
    assert client.post("/api/network", json={"name": "Contact", "knows": ["not-owned"]}).status_code == 422


def test_real_portfolio_manifest_has_event_coverage():
    data = json.loads((Path(__file__).parents[1] / "data/mock/portfolio.json").read_text())
    assert data["scanned_universe"] >= 100
    assert not data["scan_failures"]
    assert all(data["coverage"].values())
    assert 15 <= len(data["companies"]) <= 20
    assert all(e["url"].startswith("https://") for c in data["companies"] for e in c["events"])


@pytest.mark.parametrize("invalid", ["citation", "value", "period", "date", "unit", "basis"])
def test_filing_extraction_rejects_unsupported_output_without_caching(phase_client, monkeypatch, invalid):
    client = phase_client
    scenario = client.post("/api/demo/phases").json()
    client.app.state.providers.settings.glm_api_key = __import__("pydantic").SecretStr("test-key")
    original = httpx.Client

    def handle(request):
        payload = json.loads(request.content)
        identifier = json.loads(payload["messages"][1]["content"])["pages"][0]["lines"][-1]["citation_id"]
        period = {"period_end": scenario["period_end"], "basis": "consolidated", "unit": "crore",
                  "revenue": 999 if invalid == "value" else 1200,
                  "revenue_citation_ids": ["invented" if invalid == "citation" else identifier],
                  "ebitda": None, "ebitda_citation_ids": [], "pbt": None, "pbt_citation_ids": [], "pat": None, "pat_citation_ids": []}
        if invalid == "date":
            period["period_end"] = "2025-06-30"
        if invalid == "unit":
            period["unit"] = "million"
        if invalid == "basis":
            period["basis"] = "standalone"
        conflicting = {**period, "revenue": 240}
        facts = {"category": "results", "summary": "Reported synthetic revenue.",
                 "summary_citation_ids": [identifier], "person_name": None, "person_title": None, "person_citation_ids": [],
                 "financial_periods": [period, conflicting] if invalid == "period" else [period], "gaps": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(facts)}}]})

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    response = client.post(f"/api/announcements/{scenario['results_event_id']}/enrich")
    assert response.status_code == 502
    assert not client.app.state.db.all("SELECT * FROM llm_cache")
    assert not client.app.state.db.all("SELECT * FROM financials WHERE source_type='filing'")


def test_bad_enrichment_does_not_drop_later_filings(phase_client, monkeypatch):
    client = phase_client
    providers = client.app.state.providers
    monkeypatch.setattr(providers, "prices", lambda *args: PriceImport(ticker="TEST", prices=[
        Price(day=date(2026, 11, 12), close=100, volume=100),
    ]))
    monkeypatch.setattr(providers, "announcements", lambda *args: [
        Announcement(ticker="TEST", title=f"Financial results filing {i}", published_at=datetime.now(timezone.utc))
        for i in (1, 2)
    ])
    called = []

    def extract(db, event, source):
        called.append(event["id"])
        if len(called) == 1:
            raise ProviderError("Unsupported filing layout")
        return {}

    monkeypatch.setattr("finn.pipeline.extract_filing", extract)
    queued = client.post("/api/refresh", json={"tickers": ["TEST"], "enrich": True})
    assert queued.status_code == 202
    report = client.get("/api/refresh/" + queued.json()["id"]).json()
    assert report["status"] == "partial"
    assert len(called) == 2
    assert report["sources"][1]["count"] == 2
    assert len(report["sources"][1]["enrichment_errors"]) == 1
    assert len(client.app.state.db.all("SELECT * FROM announcements")) == 2
