import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app
from finn.providers import ProviderError


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            database_path=tmp_path / "test.sqlite",
            glm_api_key="",
            api_token="",
            refresh_interval_seconds=0,
            _env_file=None,
        )
    )
    with TestClient(app) as client:
        yield client


def portfolio(client):
    response = client.put("/api/portfolio", json={"companies": [{"ticker": "TCS.NS", "name": "TCS"}]})
    assert response.status_code == 200


def document(client, text=None, **overrides):
    payload = {
        "ticker": "TCS",
        "kind": "annual_report",
        "title": "Company annual report",
        "text": text
        or "Consolidated revenue increased to INR 1,000 crore in FY2026. Cash from operations was INR 120 crore.",
        "published_on": "2026-06-01",
        **overrides,
    }
    response = client.post("/api/documents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_demo_full_workflow_and_live_separation(client):
    assert client.post("/api/demo/seed").status_code == 200
    assert len(client.get("/api/portfolio").json()["companies"]) == 18
    digest = client.get("/api/digest", params={"mode": "demo", "include_routine": True}).json()
    assert any(i["ticker"] == "TCS" and i["network"] for i in digest["items"])
    assert digest["routine_count"] == 1
    assert client.get("/api/digest").json()["items"] == []
    research = client.post("/api/research", json={"ticker": "TCS", "mode": "demo"}).json()
    assert research["status"] == "evidence_only"
    assert research["sources"] and research["network"]
    assert all(s["mode"] == "demo" for s in research["sources"])
    assert client.post("/api/research", json={"ticker": "TCS"}).json()["status"] == "needs_sources"
    before = len(client.get("/api/documents?mode=demo").json()["documents"])
    client.post("/api/demo/seed")
    assert len(client.get("/api/documents?mode=demo").json()["documents"]) == before


def test_arbitrary_ticker_retrieval_and_replacement(client):
    item = document(
        client,
        ticker="ANOTHER",
        text="Revenue was INR 100 crore. Unique oldword evidence from the original company document.",
    )
    result = client.post(
        "/api/research", json={"ticker": "ANOTHER", "question": "What is the revenue?"}
    ).json()
    assert result["sources"][0]["document_id"] == item["id"]
    document(
        client,
        ticker="ANOTHER",
        text="Revenue was INR 200 crore. Updatedword evidence replaces the previous original company document.",
    )
    result = client.post(
        "/api/research", json={"ticker": "ANOTHER", "question": "What is the revenue?"}
    ).json()
    assert "200" in result["sources"][0]["text"]
    assert "oldword" not in result["sources"][0]["text"]
    assert len(client.app.state.db.all("SELECT * FROM chunk_search")) == 1
    assert client.delete("/api/documents/" + item["id"]).status_code == 200
    assert not client.app.state.db.all("SELECT * FROM chunk_search")


def test_alert_window_and_prior_volume_baseline(client):
    portfolio(client)
    client.put(
        "/api/alerts/settings",
        json={"volume_lookback_days": 2, "price_change_percent": 5, "volume_multiple": 2},
    )
    client.post(
        "/api/prices",
        json={
            "ticker": "TCS",
            "prices": [
                {"day": "2026-11-09", "close": 100, "volume": 100},
                {"day": "2026-11-10", "close": 100, "volume": 100},
                {"day": "2026-11-11", "close": 107, "volume": 300},
            ],
        },
    )
    params = {"since": "2026-11-11T00:00:00Z", "until": "2026-11-11T23:59:00Z"}
    result = client.get("/api/digest", params=params).json()
    alert = result["items"][0]
    assert alert["volume_multiple"] == 3
    assert alert["price_change_percent"] == 7
    assert alert["volume_baseline_complete"]
    assert (
        len(client.get("/api/digest", params={**params, "since": "2026-11-11T13:00:00Z"}).json()["items"])
        == 0
    )


def test_short_baseline_does_not_trigger_volume_alert(client):
    portfolio(client)
    client.post(
        "/api/prices",
        json={
            "ticker": "TCS",
            "prices": [
                {"day": "2026-11-10", "close": 100, "volume": 100},
                {"day": "2026-11-11", "close": 100, "volume": 1000},
            ],
        },
    )
    result = client.get(
        "/api/digest", params={"since": "2026-11-11T00:00:00Z", "until": "2026-11-12T00:00:00Z"}
    ).json()
    assert result["items"] == []


def test_announcement_timezone_deduplication_and_routine(client):
    portfolio(client)
    payload = {
        "ticker": "TCS",
        "title": "Appointment of chief financial officer",
        "published_at": "2026-11-12T12:00:00+05:30",
    }
    first = client.post("/api/announcements", json=payload).json()
    second = client.post(
        "/api/announcements", json={**payload, "published_at": "2026-11-12T06:30:00Z"}
    ).json()
    assert first["id"] == second["id"]
    assert first["category"] == "management_change"
    result = client.get(
        "/api/digest", params={"since": "2026-11-12T06:00:00Z", "until": "2026-11-12T07:00:00Z"}
    ).json()
    assert len(result["items"]) == 1


def test_digest_fractional_second_boundary(client):
    portfolio(client)
    client.post(
        "/api/announcements",
        json={"ticker": "TCS", "title": "Financial results", "published_at": "2026-11-12T06:30:00Z"},
    )
    result = client.get(
        "/api/digest", params={"since": "2026-11-12T06:29:59.900Z", "until": "2026-11-12T06:30:00.500Z"}
    ).json()
    assert len(result["items"]) == 1


def test_network_explicit_edges_vs_overlap_and_delete(client):
    client.post("/api/demo/seed")
    result = client.get("/api/network/recommendations?person_id=demo-arjun").json()["matches"]
    meera = next(c for c in result if c["contact_id"] == "demo-meera")
    assert meera["relationship"] == "explicit_connection"
    assert any("unverified" in r for r in meera["reasons"])
    client.delete("/api/network/demo-arjun")
    assert (
        "demo-arjun"
        not in next(c for c in client.get("/api/network").json()["contacts"] if c["id"] == "demo-meera")[
            "knows"
        ]
    )
    assert client.get("/api/network/recommendations?person_id=missing").status_code == 404


def test_bearer_authentication(tmp_path):
    app = create_app(
        Settings(database_path=tmp_path / "private.sqlite", api_token="test-secret", _env_file=None)
    )
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/api/network").status_code == 401
        assert c.post("/api/demo/seed").status_code == 401
        assert c.get("/api/network", headers={"Authorization": "Bearer test-secret"}).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "../etc/passwd"},
        {"ticker": "TCS", "question": "x"},
        {"ticker": "TCS", "unexpected": True},
    ],
)
def test_bad_research_input(client, payload):
    assert client.post("/api/research", json=payload).status_code == 422


def test_unknown_documents_and_bad_windows(client):
    assert client.delete("/api/documents/missing").status_code == 404
    assert client.get("/api/digest?since=2026-11-12T00:00:00").status_code == 422
    assert client.get("/api/digest?since=2026-11-13T00:00:00Z&until=2026-11-12T00:00:00Z").status_code == 422
    assert (
        client.post(
            "/api/documents",
            json={"ticker": "TCS", "kind": "annual_report", "title": "Empty", "published_on": "2026-01-01"},
        ).status_code
        == 422
    )


def test_ssrf_rejected_before_download(client):
    for url in (
        "http://127.0.0.1/a.pdf",
        "https://evil.test/a.pdf",
        "https://www.ril.com.evil.test/a.pdf",
        "https://user:pass@www.ril.com/a.pdf",
    ):
        response = client.post(
            "/api/documents",
            json={
                "ticker": "TCS",
                "kind": "annual_report",
                "title": "Bad URL",
                "published_on": "2026-01-01",
                "url": url,
            },
        )
        assert response.status_code == 422


def test_refresh_partial_failure_visible_and_idempotent(client, monkeypatch):
    from finn.models import Price, PriceImport

    providers = client.app.state.providers
    monkeypatch.setattr(
        providers,
        "prices",
        lambda *args: PriceImport(
            ticker="TCS", prices=[Price(day=date(2026, 11, 12), close=100, volume=200)]
        ),
    )

    def blocked(*args):
        raise ProviderError("Exchange blocked automated requests")

    monkeypatch.setattr(providers, "announcements", blocked)
    for _ in range(2):
        response = client.post("/api/refresh", json={"tickers": ["TCS"]})
        assert response.status_code == 202
        report = client.get("/api/refresh/" + response.json()["id"]).json()
        assert report["status"] == "partial"
        assert report["sources"][1]["status"] == "error"
    assert len(client.get("/api/companies/TCS/prices").json()["prices"]) == 1


def mock_model(client, monkeypatch, invalid=False):
    import finn.research as module

    original = httpx.Client
    calls = []
    client.app.state.research.settings.glm_api_key = __import__("pydantic").SecretStr("not-a-real-key")

    def handle(request):
        calls.append(json.loads(request.content))
        excerpt = json.loads(calls[-1]["messages"][1]["content"])["excerpts"][0]
        body = {
            "findings": [
                {
                    "text": "Revenue was INR 1,000 crore.",
                    "citation_ids": ["invented" if invalid else excerpt["citation_id"]],
                }
            ],
            "gaps": [],
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(body)}}], "usage": {"total_tokens": 100}},
        )

    monkeypatch.setattr(
        module.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
    )
    return calls


def test_model_citations_cache_and_source_invalidation(client, monkeypatch):
    document(client)
    calls = mock_model(client, monkeypatch)
    payload = {"ticker": "TCS", "question": "What is revenue?"}
    first = client.post("/api/research", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "analysed"
    second = client.post("/api/research", json=payload).json()
    assert second["cached"] and len(calls) == 1
    document(
        client,
        text="Revenue was INR 2,000 crore in FY2026. Cash generated from operating activities was INR 300 crore.",
    )
    assert not client.post("/api/research", json=payload).json()["cached"]
    assert len(calls) == 2


def test_model_unknown_citation_rejected(client, monkeypatch):
    document(client)
    mock_model(client, monkeypatch, invalid=True)
    response = client.post("/api/research", json={"ticker": "TCS"})
    assert response.status_code == 502
    assert not client.app.state.db.all("SELECT * FROM research_cache")


def test_yahoo_skips_incomplete_current_day(client, monkeypatch):
    original = httpx.Client
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    response = {
        "chart": {
            "result": [
                {
                    "timestamp": [int(yesterday.timestamp()), int(today.timestamp())],
                    "indicators": {"quote": [{"close": [100, 110], "volume": [1000, 2000]}]},
                }
            ]
        }
    }
    monkeypatch.setattr(
        client.app.state.providers,
        "client",
        lambda: original(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response))),
    )
    result = client.app.state.providers.prices("TCS")
    assert len(result.prices) == 1
    assert result.prices[0].close == 100


def test_openapi_contract(client):
    schema = client.get("/openapi.json").json()
    for path in ("/api/research", "/api/digest", "/api/network/recommendations", "/api/refresh"):
        assert path in schema["paths"]


def test_mock_workflow_push_pull_and_model_boundary(client, monkeypatch):
    scenario = client.post("/api/demo/workflow").json()
    expected = set(scenario["expected_contacts"].values())
    document(client, ticker="OTHER", text=(
        "IT services operating margins EBITDA Q1 Q2 guidance 99%. "
        "UNRELATED_COMPANY_EVIDENCE must never enter MOCKIT research."
    ), mode="demo")
    calls = mock_model(client, monkeypatch)
    response = client.post("/api/research", json=scenario["research_request"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert {c["contact_id"] for c in result["network"]} == expected
    by_id = {c["contact_id"]: c for c in result["network"]}
    assert "industry_expert" in by_id["workflow-expert"]["match_types"]
    assert "company_insider" in by_id["workflow-insider"]["match_types"]
    assert by_id["workflow-connector"]["relationship"] == "explicit_connection"
    assert by_id["workflow-insider"]["relationship"] == "possible_employment_overlap"
    assert any("unverified" in r for r in by_id["workflow-insider"]["reasons"])
    assert all(any(q in s["title"] for s in result["sources"]) for q in ("Q1", "Q2"))
    assert all(s["mode"] == "demo" for s in result["sources"])
    assert "UNRELATED_COMPANY_EVIDENCE" not in json.dumps(result["sources"])
    assert result["trace"]["model_called"]
    assert result["trace"]["model_request"] == calls[0]
    model_data = json.loads(calls[0]["messages"][1]["content"])
    assert set(model_data) == {"ticker", "question", "excerpts"}
    assert model_data["excerpts"] == result["sources"]
    assert all(c["name"] not in json.dumps(calls[0]) for c in result["network"])
    digest = client.get("/api/digest?mode=demo").json()
    event = next(i for i in digest["items"] if i["id"] == scenario["announcement_id"])
    assert {c["contact_id"] for c in event["network"]} == expected
    assert client.get("/api/digest").json()["items"] == []
    assert client.post("/api/research", json={"ticker": "MOCKIT"}).json()["status"] == "needs_sources"
    # Changing the contact context and trace flag must reuse the same financial analysis.
    cached = client.post("/api/research", json={
        **scenario["research_request"], "person_id": None, "include_trace": False,
    }).json()
    assert cached["cached"] and "trace" not in cached and len(calls) == 1
    assert "workflow-connector" not in {c["contact_id"] for c in cached["network"]}
    traced_cache = client.post("/api/research", json=scenario["research_request"]).json()
    assert traced_cache["cached"] and not traced_cache["trace"]["model_called"]
    before = len(client.app.state.db.all("SELECT * FROM documents"))
    client.post("/api/demo/workflow")
    assert len(client.app.state.db.all("SELECT * FROM documents")) == before
    assert len(client.app.state.db.all("SELECT * FROM contacts")) == 5
    assert len(client.app.state.db.all("SELECT * FROM announcements")) == 1


def test_research_trace_without_model_and_unknown_person(client):
    scenario = client.post("/api/demo/workflow").json()
    result = client.post("/api/research", json=scenario["research_request"]).json()
    assert result["status"] == "evidence_only"
    assert not result["trace"]["model_called"]
    assert result["trace"]["retrieved_document_count"] >= 2
    assert client.post("/api/research", json={
        **scenario["research_request"], "person_id": "missing",
    }).status_code == 404


def test_hyde_model_configuration_defaults():
    assert Settings.model_fields["glm_base_url"].default == "https://inference.hyde.tech/v1"
    assert Settings.model_fields["glm_model"].default == "hyde/glm-5.3-flash"
