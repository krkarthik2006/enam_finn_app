"""Company discovery, primary-source ingestion, and repeat requests work without a fixed stock list."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.documents import save_document
from finn.main import create_app
from finn.models import Document


@pytest.fixture
def research_app(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / 'research.sqlite', cache_path=tmp_path / 'sources',
                        glm_api_key='', api_token='', _env_file=None)
    app = create_app(settings)
    requests = []
    state = {'new_report': False, 'unavailable': False}
    issuers = [(1045810, 'NVIDIA CORP', 'NVDA', 'Nasdaq'), (320193, 'Apple Inc.', 'AAPL', 'Nasdaq')]

    def handle(request):
        requests.append(str(request.url))
        if 'screener.in/api/company/search' in str(request.url):
            query = request.url.params['q'].upper()
            matches = [{'name': 'Infosys Ltd', 'url': '/company/INFY/consolidated/'}] if query == 'INFOSYS' else []
            return httpx.Response(200, json=matches)
        if request.url.path == '/files/company_tickers_exchange.json':
            return httpx.Response(200, json={'fields': ['cik', 'name', 'ticker', 'exchange'], 'data': issuers})
        if '/submissions/' in request.url.path:
            if state['unavailable']:
                return httpx.Response(503)
            ticker = 'NVDA' if '1045810' in request.url.path else 'AAPL'
            suffix = 'updated' if state['new_report'] else 'original'
            return httpx.Response(200, json={'filings': {'recent': {
                'form': ['10-Q', '10-K'], 'accessionNumber': ['0001045810-26-000099', '0001045810-26-000021'],
                'primaryDocument': ['quarter.htm', f'{ticker.lower()}-{suffix}.htm'],
                'reportDate': ['2026-09-30', '2026-01-25'],
                'filingDate': ['2026-10-25', '2026-03-01' if state['new_report'] else '2026-02-25'],
            }}})
        if '/Archives/edgar/data/' in request.url.path:
            return httpx.Response(200, text='''<html><body><ix:header>HIDDEN_FACT_DO_NOT_USE</ix:header>
            <h1>Annual report — TEST FIXTURE ONLY</h1><p>Our business supplies computing products.
            Annual revenue was USD 100 million. Customer concentration is a reported risk.
            No quarterly margin guidance was provided.</p></body></html>''')
        return httpx.Response(404)

    original = httpx.Client
    monkeypatch.setattr(app.state.providers, 'client', lambda: original(transport=httpx.MockTransport(handle)))
    with TestClient(app) as client:
        yield client, requests, state


def ask(client, query, **changes):
    response = client.post(f'/api/research/{query}/brief', json={
        'question': 'Describe the business, revenue and risks.', 'use_model': False, **changes})
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def test_company_name_ingests_official_filing_and_repeat_uses_database(research_app):
    client, requests, _ = research_app
    first = ask(client, 'NVIDIA')[-1]['data']
    assert first['ticker'] == 'NVDA' and first['company_name'] == 'NVIDIA CORP'
    assert first['market'] == 'US' and first['coverage']['annual_reports'] == 1
    assert first['sources'] and all('/Archives/edgar/data/1045810/' in s['url'] for s in first['sources'])
    assert all(s['page'] is None and s['published_on'] == '2026-02-25' for s in first['sources'])
    assert all('HIDDEN_FACT' not in s['text'] for s in first['sources'])
    assert first['financials'] == []  # US dollars must never be presented as INR tables.
    initial_requests = list(requests)
    second = ask(client, 'Nvidia Corporation')[-1]['data']
    assert requests == initial_requests
    assert second['sources'] == first['sources']
    third = ask(client, 'NVDA')[-1]['data']
    assert third['sources'] == first['sources']
    assert requests == initial_requests
    db = client.app.state.db
    assert db.one("SELECT COUNT(*) n FROM documents WHERE ticker='US-NVDA'")['n'] == 1
    assert db.one("SELECT COUNT(*) n FROM chunks")['n'] > 0


def test_other_us_company_and_unknown_name_are_not_hardwired(research_app):
    client, _, _ = research_app
    result = ask(client, 'Apple Inc.')[-1]['data']
    assert result['ticker'] == 'AAPL' and result['coverage']['annual_reports'] == 1
    assert all('/Archives/edgar/data/320193/' in s['url'] for s in result['sources'])
    events = ask(client, 'Unknown Company XYZ')
    assert events[-1]['type'] == 'error'
    assert not client.app.state.db.all("SELECT id FROM documents WHERE ticker LIKE '%UNKNOWN%'")


def test_us_and_nse_sources_with_same_symbol_never_mix(research_app):
    client, _, _ = research_app
    db = client.app.state.db
    save_document(db, Document(ticker='NVDA', kind='annual_report', title='Unrelated NSE fixture',
                               text='TEST FIXTURE: an unrelated Indian company has revenue of INR 999 crore and a different business.'))
    result = ask(client, 'US:NVDA')[-1]['data']
    assert result['company_id'] == 'US-NVDA'
    assert all('999 crore' not in s['text'] for s in result['sources'])
    indian = ask(client, 'NVDA', prepare_sources=False)[-1]['data']
    assert indian['market'] == 'NSE' and indian['company_id'] == 'NVDA'
    assert any('999 crore' in s['text'] for s in indian['sources'])


def test_source_refresh_adds_new_filing_and_failure_retains_saved_sources(research_app):
    client, requests, state = research_app
    first = ask(client, 'NVIDIA')[-1]['data']
    db = client.app.state.db
    checked = db.setting('corpus:US-NVDA', {})
    checked['checked_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.set_setting('corpus:US-NVDA', checked)
    state['new_report'] = True
    refreshed = ask(client, 'NVIDIA')[-1]['data']
    assert refreshed['sources'][0]['document_id'] != first['sources'][0]['document_id']
    assert db.one("SELECT COUNT(*) n FROM documents WHERE ticker='US-NVDA'")['n'] == 2
    checked = db.setting('corpus:US-NVDA', {})
    checked['checked_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.set_setting('corpus:US-NVDA', checked)
    state['unavailable'] = True
    fallback = ask(client, 'NVIDIA')[-1]['data']
    assert fallback['sources'] == refreshed['sources']
    assert not any('screener.in/company/US-' in url for url in requests)


def test_nse_company_name_uses_existing_source_pipeline(research_app, monkeypatch):
    client, requests, _ = research_app
    provider = client.app.state.providers
    monkeypatch.setattr(provider, 'fundamentals', lambda symbol: {'records': []})
    monkeypatch.setattr(provider, 'discover', lambda symbol: {'documents': [], 'company_website': None})
    save_document(client.app.state.db, Document(ticker='INFY', kind='annual_report', title='Infosys report',
                                               text='TEST FIXTURE ONLY: original company report evidence, with revenue and business risks.'))
    result = ask(client, 'Infosys')[-1]['data']
    assert result['ticker'] == 'INFY' and result['market'] == 'NSE'
    assert not any('sec.gov' in url for url in requests)


def test_company_and_documents_survive_a_new_application_instance(research_app, monkeypatch):
    client, _, _ = research_app
    original = ask(client, 'NVIDIA')[-1]['data']
    restarted = create_app(client.app.state.providers.settings)
    def no_network():
        raise AssertionError('Saved company research must not fetch sources again')
    monkeypatch.setattr(restarted.state.providers, 'client', no_network)
    with TestClient(restarted) as second:
        saved = ask(second, 'NVDA')[-1]['data']
    assert saved['sources'] == original['sources']
    assert saved['company_id'] == 'US-NVDA'


@pytest.mark.parametrize('stale_alias', [False, True])
def test_unverified_portfolio_entry_does_not_override_company_identity(research_app, stale_alias):
    client, requests, _ = research_app
    db = client.app.state.db
    assert client.put('/api/portfolio', json={'companies': [{'ticker': 'NVIDIA', 'name': 'NVIDIA'}]}).status_code == 200
    if stale_alias:
        company = {'id': 'NVIDIA', 'ticker': 'NVIDIA', 'name': 'NVIDIA', 'market': 'NSE'}
        db.execute('INSERT OR REPLACE INTO companies VALUES (?,?)', ('NVIDIA', json.dumps(company)))
        db.set_setting('research_company:auto:NVIDIA', company)
    result = ask(client, 'NVIDIA')[-1]['data']
    assert result['company_id'] == 'US-NVDA' and result['ticker'] == 'NVDA'
    assert result['coverage']['annual_reports'] == 1
    count = len(requests)
    repeat = ask(client, 'NVIDIA')[-1]['data']
    assert repeat['sources'] == result['sources'] and len(requests) == count
    assert client.get('/api/portfolio').json()['companies'][0]['ticker'] == 'NVIDIA'
