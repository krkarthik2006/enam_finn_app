"""Portfolio identity, US sources and news separation; all external responses are fixtures."""
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = create_app(Settings(database_path=tmp_path/'db.sqlite', cache_path=tmp_path/'sources',
                              glm_api_key='', api_token='', _env_file=None))
    calls, state = [], {'news_down': False}
    now = datetime.now(timezone.utc)

    def handle(request):
        calls.append(str(request.url))
        path = request.url.path
        if 'company/search' in path:
            return httpx.Response(200, json=[])
        if path.endswith('company_tickers_exchange.json'):
            return httpx.Response(200, json={'fields': ['cik', 'name', 'ticker', 'exchange'],
                'data': [[1045810, 'NVIDIA CORP', 'NVDA', 'Nasdaq'], [320193, 'Apple Inc.', 'AAPL', 'Nasdaq']]})
        if '/submissions/' in path:
            return httpx.Response(200, json={'filings': {'recent': {
                'form': ['8-K', '10-K'], 'filingDate': [now.date().isoformat(), '2026-02-25'],
                'acceptanceDateTime': [(now-timedelta(hours=1)).isoformat(), '2026-02-25T12:00:00Z'],
                'accessionNumber': ['0001045810-26-000099', '0001045810-26-000021'],
                'primaryDocument': ['current.htm', 'annual.htm'], 'reportDate': [now.date().isoformat(), '2026-01-25']}}})
        if '/Archives/' in path:
            return httpx.Response(200, text='<html><body>TEST FIXTURE ONLY. Our business supplies computing products. Customer concentration is a reported risk. These are original annual report business disclosures for the test.</body></html>')
        if '/finance/chart/' in path:
            timestamps = [int((now-timedelta(days=i)).timestamp()) for i in range(24, 0, -1)]
            return httpx.Response(200, json={'chart': {'result': [{'timestamp': timestamps,
                'indicators': {'quote': [{'close': [100]*23+[110], 'volume': [100]*24}]}}]}})
        if path == '/rss/headline':
            return httpx.Response(301, headers={'location': 'https://feeds.finance.yahoo.com/rss/2.0/headline'})
        if path == '/rss/2.0/headline':
            if state['news_down']:
                return httpx.Response(503)
            stamp = format_datetime(now-timedelta(minutes=30))
            return httpx.Response(200, text=f'<rss><channel><item><title>NVIDIA EXTERNAL_NEWS_MARKER headline</title><link>https://finance.yahoo.com/news/company-story.html</link><pubDate>{stamp}</pubDate><source>Yahoo Finance</source></item></channel></rss>')
        return httpx.Response(404)

    original = httpx.Client
    monkeypatch.setattr(app.state.providers, 'client', lambda: original(transport=httpx.MockTransport(handle)))
    with TestClient(app) as client:
        yield client, calls, state


def test_portfolio_resolves_names_and_refresh_repairs_legacy_us_entry(workspace):
    client, calls, _ = workspace
    resolved = client.post('/api/portfolio/resolve', json={'query': 'NVIDIA'})
    assert resolved.status_code == 200, resolved.text
    company = resolved.json()
    assert company['ticker'] == 'US-NVDA' and company['exchange'] == 'US'
    assert company['name'] == 'NVIDIA CORP'
    assert client.post('/api/portfolio/resolve', json={'query': 'NOSUCHCOMPANY'}).status_code == 422
    client.put('/api/portfolio', json={'companies': [{'ticker': 'NVIDIA', 'name': 'NVIDIA'}]})
    queued = client.post('/api/refresh', json={'tickers': ['NVIDIA'], 'news': True, 'fundamentals': True, 'enrich': True})
    assert queued.status_code == 202, queued.text
    report = client.get('/api/refresh/'+queued.json()['id']).json()
    assert report['status'] == 'completed', report
    assert client.get('/api/portfolio').json()['companies'][0]['ticker'] == 'US-NVDA'
    assert any('/finance/chart/NVDA?' in url for url in calls)
    assert not any('NVDA.NS' in url or '/company/US-NVDA/' in url for url in calls)
    assert {s['source'] for s in report['sources']} == {'prices', 'announcements', 'news'}
    digest = client.get('/api/digest', params={'include_routine': True}).json()
    news = next(item for item in digest['items'] if item['type'] == 'news')
    assert news['ticker'] == 'US-NVDA' and news['source']['publisher'] == 'Yahoo Finance'
    assert any(item['source'].get('form') == '8-K' for item in digest['items']+digest['routine'])
    assert client.post('/api/announcements/'+news['id']+'/enrich').status_code == 422
    assert not client.app.state.db.all('SELECT * FROM financials')
    response = client.post('/api/research/US-NVDA/brief', json={'question': 'AI?', 'use_model': False})
    assert response.status_code == 200
    result = json.loads(response.text.splitlines()[-1])['data']
    assert result['ticker'] == 'NVDA' and result['coverage']['annual_reports'] == 1
    assert 'EXTERNAL_NEWS_MARKER' not in json.dumps(result['sources'])
    assert all('/Archives/' in source['url'] for source in result['sources'])


def test_news_failure_does_not_discard_filings_or_prices(workspace):
    client, _, state = workspace
    company = client.post('/api/portfolio/resolve', json={'query': 'NVIDIA'}).json()
    assert client.put('/api/portfolio', json={'companies': [company]}).status_code == 200
    state['news_down'] = True
    queued = client.post('/api/refresh', json={'news': True})
    report = client.get('/api/refresh/'+queued.json()['id']).json()
    assert report['status'] == 'partial'
    assert next(s for s in report['sources'] if s['source'] == 'news')['status'] == 'error'
    assert client.get('/api/companies/US-NVDA/prices').json()['prices']
    assert client.app.state.db.all("SELECT * FROM announcements WHERE ticker='US-NVDA'")


def test_news_repeats_deduplicate_and_us_close_uses_its_market_timezone(workspace):
    from zoneinfo import ZoneInfo
    client, _, _ = workspace
    company = client.post('/api/portfolio/resolve', json={'query': 'NVIDIA'}).json()
    client.put('/api/portfolio', json={'companies': [company]})
    for _ in range(2):
        assert client.post('/api/refresh', json={'news': True}).status_code == 202
    db = client.app.state.db
    assert len(db.all("SELECT * FROM announcements WHERE category='news'")) == 1
    result = client.get('/api/digest').json()
    alert = next(item for item in result['items'] if item['type'] == 'market_alert')
    day = client.get('/api/companies/US-NVDA/prices').json()['prices'][0]['day']
    expected = datetime.fromisoformat(day+'T16:00:00').replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    assert datetime.fromisoformat(alert['published_at']) == expected


def test_us_alerts_do_not_use_a_close_after_the_requested_time(workspace):
    client, _, _ = workspace
    company = client.post('/api/portfolio/resolve', json={'query': 'NVIDIA'}).json()
    client.put('/api/portfolio', json={'companies': [company]})
    client.post('/api/prices', json={'ticker': 'US-NVDA', 'prices': [
        {'day': '2026-11-12', 'close': 100, 'volume': 100},
        {'day': '2026-11-13', 'close': 110, 'volume': 100},
        {'day': '2026-11-16', 'close': 120, 'volume': 100}]})
    result = client.get('/api/digest', params={'since': '2026-11-13T00:00:00Z', 'until': '2026-11-16T20:00:00Z'}).json()
    assert next(item for item in result['items'] if item['type'] == 'market_alert')['published_at'].startswith('2026-11-13T21:00:00')


@pytest.mark.parametrize('stale_alias', [False, True])
def test_us_portfolio_names_keep_us_identity_in_research(workspace, stale_alias):
    client, _, _ = workspace
    company = client.post('/api/portfolio/resolve', json={'query': 'NVIDIA'}).json()
    client.put('/api/portfolio', json={'companies': [company]})
    client.post('/api/research/US-NVDA/brief', json={'question': 'AI?', 'use_model': False})
    if stale_alias:
        bad = {'id': 'US-NVDA', 'ticker': 'US-NVDA', 'name': 'NVIDIA CORP', 'market': 'NSE'}
        client.app.state.db.set_setting('research_company:auto:NVIDIA', bad)
        client.app.state.db.execute('UPDATE companies SET payload=? WHERE ticker=?', (json.dumps(bad), 'US-NVDA'))
    response = client.post('/api/research/NVIDIA/brief', json={'question': 'AI?', 'use_model': False})
    result = json.loads(response.text.splitlines()[-1])['data']
    assert result['ticker'] == 'NVDA' and result['market'] == 'US'
    assert result['coverage']['annual_reports'] == 1
    assert all('/Archives/' in source['url'] for source in result['sources'])
