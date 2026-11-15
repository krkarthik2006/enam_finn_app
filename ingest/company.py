"""Resolve company names and ingest original US annual filings; no generated company facts."""
import json
import re
from datetime import date
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from finn.documents import extract_pdf, save_document
from finn.models import Document, normalize_ticker
from finn.providers import ProviderError, json_list


def name_key(value):
    words = re.findall(r'[A-Z0-9]+', str(value or '').upper())
    while len(words) > 1 and words[-1] in {'CORPORATION', 'CORP', 'INCORPORATED', 'INC', 'LTD', 'LIMITED', 'PLC', 'CO', 'COMPANY'}:
        words.pop()
    return ''.join(words)


def catalog(response):
    data = response.json()
    if not {'cik', 'name', 'ticker', 'exchange'} <= set(data['fields']):
        raise ValueError('Company catalog is incomplete')
    return [dict(zip(data['fields'], row, strict=True)) for row in data['data']]


def match_company(rows, query, prefix=False):
    key = name_key(query)
    matches = [r for r in rows if name_key(r['ticker']) == key]
    matches = matches or [r for r in rows if name_key(r['name']) == key]
    if not matches and prefix and len(key) >= 3:
        matches = [r for r in rows if name_key(r['name']).startswith(key)]
    identities = {str(r.get('cik') or r['ticker']) for r in matches}
    return matches[0] if len(identities) == 1 else None


def resolve_company(db, providers, query, fetch=True):
    market, name = 'auto', query.strip()
    if ':' in name:
        prefix, name = name.split(':', 1)
        market = {'US': 'US', 'NASDAQ': 'US', 'NYSE': 'US', 'NSE': 'NSE'}.get(prefix.upper())
        if not market:
            raise ProviderError('Enter a company name or ticker.')
    alias = f'research_company:{market}:{name_key(name)}'
    saved = db.setting(alias, None)
    # Known Indian companies take precedence over an unqualified US ticker alias.
    if market != 'US':
        known = []
        for row in db.all('SELECT ticker,payload FROM portfolio UNION ALL SELECT ticker,payload FROM companies'):
            item = json.loads(row['payload'])
            if item.get('market') == 'US':
                continue
            known.append({'ticker': row['ticker'], 'name': item.get('name', row['ticker'])})
        selected = match_company(known, name)
        if selected:
            return remember_company(db, {**selected, 'id': selected['ticker'], 'market': 'NSE'}, market, name)
        try:
            ticker = normalize_ticker(name)
            if db.one("SELECT id FROM documents WHERE ticker=? AND mode='live'", (ticker,)):
                return remember_company(db, {'id': ticker, 'ticker': ticker, 'name': ticker, 'market': 'NSE'}, market, name)
        except ValueError:
            pass
    if saved:
        return saved
    if not fetch:
        ticker = normalize_ticker(name)
        return {'id': ticker, 'ticker': ticker, 'name': ticker, 'market': 'NSE'}
    if market != 'US':
        try:
            with providers.client() as client:
                response = providers.cache.fetch(client, 'https://www.screener.in/api/company/search/',
                    params={'q': name, 'v': '3', 'fts': '1'}, validate=json_list, max_age_seconds=86400)
            candidates = []
            for item in response.json():
                match = re.match(r'^/company/([A-Z0-9&_-]+)/', item.get('url', ''), re.I)
                if match and match[1].upper() != 'ID':
                    candidates.append({'ticker': match[1].upper(), 'name': item['name']})
            selected = match_company(candidates, name)
            if selected:
                return remember_company(db, {**selected, 'id': selected['ticker'], 'market': 'NSE'}, market, name)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
    if market != 'NSE':
        try:
            with providers.client() as client:
                response = providers.cache.fetch(client, 'https://www.sec.gov/files/company_tickers_exchange.json',
                    headers={'User-Agent': 'FINNResearch/0.1'}, validate=catalog, max_age_seconds=86400)
            selected = match_company(catalog(response), name, prefix=True)
            if selected:
                ticker = normalize_ticker(selected['ticker'])
                return remember_company(db, {'id': 'US-' + ticker, 'ticker': ticker, 'name': selected['name'],
                                               'market': 'US', 'cik': int(selected['cik'])}, market, name)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
    raise ProviderError('Company not found. Try its full name or exchange ticker.')


def remember_company(db, company, market, query):
    existing = db.one('SELECT payload FROM companies WHERE ticker=?', (company['id'],))
    payload = {**(json.loads(existing['payload']) if existing else {}), **company}
    db.execute('INSERT OR REPLACE INTO companies VALUES (?,?)', (company['id'], json.dumps(payload)))
    for label in {query, company['name']}:
        db.set_setting(f'research_company:{market}:{name_key(label)}', company)
    db.set_setting(f"research_company:{company['market']}:{name_key(company['ticker'])}", company)
    if company['market'] == 'US':
        db.set_setting(f"research_company:auto:{name_key(company['ticker'])}", company)
    return company


def prepare_us_corpus(db, providers, company):
    ticker = company['id']
    indexed = db.all("SELECT id,kind,url,title FROM documents WHERE ticker=? AND mode='live'", (ticker,))
    report = {'documents': indexed, 'gaps': [], 'financial_periods': 0}
    try:
        with providers.client() as client:
            response = providers.cache.fetch(client, f"https://data.sec.gov/submissions/CIK{company['cik']:010d}.json",
                headers={'User-Agent': 'FINNResearch/0.1'}, validate=lambda r: r.json()['filings']['recent']['form'])
            recent = response.json()['filings']['recent']
            index = next((i for i, form in enumerate(recent['form']) if form in {'10-K', '20-F', '40-F'}), None)
            if index is None:
                report['gaps'].append('No annual report is available from the company filings.')
                return report
            accession = recent['accessionNumber'][index]
            filename = recent['primaryDocument'][index]
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.-]+\.(?:htm|html|pdf)', filename, re.I):
                raise ValueError('Invalid original filing path')
            url = f"https://www.sec.gov/Archives/edgar/data/{company['cik']}/{accession.replace('-', '')}/{quote(filename)}"
            if not any(d['url'] == url for d in indexed):
                document = providers.cache.fetch(client, url, headers={'User-Agent': 'FINNResearch/0.1'},
                    validate=lambda r: extract_filing(r.content))
                pages = extract_filing(document.content)
                period = recent.get('reportDate', [''] * len(recent['form']))[index]
                title = f"{company['name']} annual report · {period}"
                published = date.fromisoformat(recent['filingDate'][index])
                save_document(db, Document(ticker=ticker, kind='annual_report', title=title, url=url,
                                            published_on=published, mode='live'), pages)
            if response.extensions.get('finn_source', {}).get('stale'):
                report['gaps'].append('Using the last saved annual filing; newer filings could not be checked.')
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ProviderError):
        report['gaps'].append('The latest annual report could not be retrieved. Available saved reports are retained.')
    report['documents'] = db.all("SELECT id,kind,url,title FROM documents WHERE ticker=? AND mode='live'", (ticker,))
    report['gaps'].append('Earnings-call transcripts are not available in these annual filings.')
    return report


def extract_filing(content):
    if content.startswith(b'%PDF-'):
        return extract_pdf(content)
    soup = BeautifulSoup(content, 'html.parser')
    for tag in soup.find_all(['script', 'style', 'noscript', 'ix:header', 'ix:hidden']):
        tag.decompose()
    text = soup.get_text('\n', strip=True)
    if len(text) < 100 or len(text) > 2_000_000:
        raise ValueError('No usable annual report text')
    return [(None, text)]  # HTML has no original PDF page numbers; do not invent them.
