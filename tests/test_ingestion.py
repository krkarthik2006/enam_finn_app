import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from engine.financials import (
    compare_records,
    cross_check,
    growth,
    parse_screener,
    parse_statement_pages,
    save_financial,
)
from finn.config import Settings
from finn.db import Database
from finn.documents import save_document
from finn.models import Document, FinancialRecord
from finn.providers import Providers
from ingest.cache import SourceCache


def record(period, revenue=100, **extra):
    return FinancialRecord(ticker="TEST", period_end=period, basis="consolidated",
                           metrics={"revenue": revenue, "ebitda": 20, "pbt": 15, "pat": 10},
                           source_type="filing", **extra)


def test_source_retry_and_snapshot_preserves_age(tmp_path):
    cache = SourceCache(tmp_path)
    calls = []
    failing = False

    def handle(request):
        calls.append(request)
        return httpx.Response(503) if failing else httpx.Response(200, json={"value": 42})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        first = cache.fetch(client, "https://public.example/data")
        failing = True
        fallback = cache.fetch(client, "https://public.example/data")
    assert len(calls) == 3
    assert fallback.json() == first.json()
    assert fallback.extensions["finn_source"]["origin"] == "cache"
    assert fallback.extensions["finn_source"]["stale"]
    assert fallback.extensions["finn_source"]["fetched_at"] == first.extensions["finn_source"]["fetched_at"]


def test_malformed_response_does_not_replace_good_snapshot(tmp_path):
    cache = SourceCache(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"value": 42}))) as client:
        cache.fetch(client, "https://public.example/data", validate=lambda r: r.json()["value"])
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={}))) as client:
        response = cache.fetch(client, "https://public.example/data", validate=lambda r: r.json()["value"])
    assert response.json() == {"value": 42}
    assert response.extensions["finn_source"]["origin"] == "cache"


@pytest.mark.parametrize("ticker", ["TCS", "INFY"])
def test_packaged_real_source_snapshots_work_offline(tmp_path, ticker):
    providers = Providers(Settings(cache_path=tmp_path, offline_sources=True, _env_file=None))
    financials = providers.fundamentals(ticker)
    assert len(financials["records"]) >= 8
    assert financials["source"]["origin"] == "cache"
    assert financials["source"]["fetched_at"]
    assert financials["bse_code"] is not None
    assert all(r.metrics.get("ebitda") is None for r in financials["records"])
    assert any(r.metrics.get("revenue") for r in financials["records"])


def test_growth_exact_periods_and_basis():
    current = record(date(2026, 9, 30), 150)
    history = [record(date(2026, 6, 30), 100), record(date(2025, 9, 30), 120)]
    result = compare_records(current, history)
    assert result["qoq"]["revenue"]["percent"] == 50
    assert result["yoy"]["revenue"]["percent"] == 25
    other_basis = history[0].model_copy(update={"basis": "standalone"})
    assert compare_records(current, [other_basis])["qoq"]["revenue"]["status"] == "missing_value"
    assert compare_records(current, [record(date(2026, 3, 31), 50)])["qoq"]["revenue"]["percent"] is None
    assert growth(10, 0)["status"] == "nonpositive_base"
    assert growth(10, -5)["status"] == "nonpositive_base"
    annual = current.model_copy(update={"frequency": "annual"})
    assert compare_records(annual, [])["qoq"]["revenue"]["status"] == "not_applicable_to_annual"


def test_cross_check_threshold_and_incompatible_units():
    filing = record(date(2026, 9, 30), 102)
    reference = record(date(2026, 9, 30), 100).model_copy(update={"source_type": "screener"})
    assert cross_check(filing, reference)["metrics"]["revenue"]["status"] == "match"
    assert cross_check(filing.model_copy(update={"metrics": {"revenue": 103}}), reference)["metrics"]["revenue"]["status"] == "mismatch"
    assert cross_check(filing, reference.model_copy(update={"unit": "lakh"}))["status"].startswith("incompatible")
    assert cross_check(filing, reference.model_copy(update={"metrics": {"revenue": None}}))["metrics"]["revenue"]["status"] == "not_available"


def test_screener_parser_does_not_call_operating_profit_ebitda():
    html = '''<p>Consolidated\n Figures in Rs. Crores</p><section id="quarters"><table>
    <thead><tr><th></th><th>Jun 2026</th><th>Sep 2026</th></tr></thead><tbody>
    <tr><td>Sales +</td><td>1,000</td><td>1,200</td></tr>
    <tr><td>Operating Profit</td><td>100</td><td>130</td></tr>
    <tr><td>Net Profit +</td><td>50</td><td>60</td></tr></tbody></table></section>'''
    records = parse_screener(html, "TEST", "https://www.screener.in/company/TEST/consolidated/")
    assert records[1].metrics["revenue"] == 1200
    assert records[1].metrics["ebitda"] is None
    assert records[1].metrics["operating_profit"] == 130


def test_document_pages_and_financial_ingestion_are_idempotent(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.initialize()
    financial = record(date(2026, 9, 30))
    save_financial(db, financial)
    save_financial(db, financial)
    assert len(db.all("SELECT * FROM financials")) == 1
    doc = Document(ticker="TEST", kind="quarterly_results", title="Results", published_on=date(2026, 10, 1))
    text = "Results in INR crore. Consolidated revenue 100, EBITDA 20, PBT 15 and PAT 10."
    result = save_document(db, doc, [(1, text), (2, "Additional notes and reporting basis details.")])
    assert len(db.all("SELECT * FROM doc_pages")) == 2
    save_document(db, doc, [(1, text.replace("100", "110"))])
    assert len(db.all("SELECT * FROM doc_pages")) == 1
    assert json.loads(db.one("SELECT payload FROM financials")["payload"])["ticker"] == "TEST"
    assert db.one("SELECT text FROM doc_pages WHERE document_id=?", (result["id"],))["text"].find("110") >= 0


def test_original_statement_fixture_bases_columns_and_citations():
    fixture = json.loads((Path(__file__).parent / "fixtures/tcs_statement_pages.json").read_text())
    records = parse_statement_pages(fixture["pages"], "TCS", fixture["source_url"])
    assert len(records) == 6
    latest = next(r for r in records if r.period_end == date(2026, 9, 30) and r.basis == "consolidated")
    assert latest.metrics == {"revenue": 73188, "ebitda": None, "pbt": 18638, "pat": 13934}
    assert latest.pages["revenue"] == 8
    assert "73,188" in latest.source["quotes"]["revenue"]["text"]
    standalone = next(r for r in records if r.period_end == date(2026, 9, 30) and r.basis == "standalone")
    assert standalone.metrics["revenue"] == 60441
    # A half-year column shares the end date but must not become quarterly revenue.
    assert latest.metrics["revenue"] != 145463
    altered = [(p, t.replace("June 30,", "March 31,")) for p, t in fixture["pages"]]
    assert parse_statement_pages(altered, "TCS", fixture["source_url"]) == []


def test_bse_contract_and_nse_fallback_provenance(tmp_path, monkeypatch):
    original = httpx.Client
    row = {"SCRIP_CD": 123456, "NEWS_DT": "2026-11-12T12:00:00", "NEWSSUB": "Appointment of CFO",
           "HEADLINE": "Board appointment", "ATTACHMENTNAME": "filing.pdf"}
    providers = Providers(Settings(cache_path=tmp_path / "cache", _env_file=None))
    monkeypatch.setattr(providers, "client", lambda: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"Table": [row], "Table1": [{"ROWCNT": 1}]}),
    )))
    items = providers.bse_announcements("TEST", "123456", 7)
    assert len(items) == 1 and items[0].ticker == "TEST"
    assert items[0].url == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/filing.pdf"
    from finn.providers import ProviderError

    def blocked(*args):
        raise ProviderError("BSE blocked")

    monkeypatch.setattr(providers, "bse_announcements", blocked)
    monkeypatch.setattr(providers, "_nse_announcements", lambda *args: items)
    assert providers.announcements("TEST", 7, "123456") == items
    assert providers.cache.observations[-1]["origin"] == "failed"


def test_fresh_source_cache_avoids_http_and_expired_cache_refreshes(tmp_path):
    from datetime import datetime, timedelta, timezone
    cache = SourceCache(tmp_path)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'count': len(calls)})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        cache.fetch(client, 'https://public.example/catalog', max_age_seconds=3600)
        saved = cache.fetch(client, 'https://public.example/catalog', max_age_seconds=3600)
        assert len(calls) == 1 and not saved.extensions['finn_source']['stale']
        path = next(tmp_path.glob('*.json'))
        snapshot = json.loads(path.read_text())
        snapshot['fetched_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        path.write_text(json.dumps(snapshot))
        refreshed = cache.fetch(client, 'https://public.example/catalog', max_age_seconds=3600)
        assert len(calls) == 2 and refreshed.json()['count'] == 2
