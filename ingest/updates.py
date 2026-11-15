"""Public portfolio updates. News is stored as headlines, never as research evidence."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from finn.models import Announcement
from finn.providers import ProviderError


def rss(response):
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ValueError('Invalid news feed') from exc
    if root.find('channel') is None:
        raise ValueError('No news channel in source')
    return root


def news(providers, ticker, exchange, days):
    symbol = ticker.removeprefix('US-') + ({'NSE': '.NS', 'BSE': '.BO'}.get(exchange, ''))
    try:
        with providers.client() as client:
            response = providers.cache.fetch(client, 'https://feeds.finance.yahoo.com/rss/2.0/headline',
                params={'s': symbol, 'region': 'US', 'lang': 'en-US'}, max_age_seconds=300, validate=rss)
        now = datetime.now(timezone.utc)
        result = []
        for item in ET.fromstring(response.content).findall('./channel/item')[:40]:
            title, link, stamp = item.findtext('title'), item.findtext('link'), item.findtext('pubDate')
            if not title or not link or not stamp or urlparse(link).scheme != 'https':
                continue
            try:
                published = parsedate_to_datetime(stamp)
            except (ValueError, TypeError):
                continue
            if published.tzinfo is None or not now-timedelta(days=days) <= published <= now:
                continue
            result.append(Announcement(ticker=ticker, title=title, url=link, published_at=published, category='news',
                source={**response.extensions.get('finn_source', {}), 'kind': 'news',
                        'publisher': item.findtext('source') or urlparse(link).hostname}))
        return result
    except (httpx.HTTPError, ET.ParseError, ValueError, TypeError) as exc:
        raise ProviderError('News is unavailable; no saved headlines could be loaded.') from exc


def us_filings(providers, company, days):
    try:
        with providers.client() as client:
            response = providers.cache.fetch(client, f"https://data.sec.gov/submissions/CIK{company['cik']:010d}.json",
                headers={'User-Agent': 'FINNResearch/0.1'}, max_age_seconds=900,
                validate=lambda r: r.json()['filings']['recent']['form'])
        recent = response.json()['filings']['recent']
        now = datetime.now(timezone.utc)
        result = []
        labels = {'10-K': 'Annual report', '20-F': 'Annual report', '40-F': 'Annual report',
                  '10-Q': 'Quarterly report', '8-K': 'Current report', '6-K': 'Company report'}
        for i, form in enumerate(recent['form']):
            if form not in labels:
                continue
            dates = recent.get('acceptanceDateTime', [])
            published = datetime.fromisoformat(dates[i].replace('Z', '+00:00')) if i < len(dates) else datetime.fromisoformat(recent['filingDate'][i]).replace(tzinfo=timezone.utc)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if not now-timedelta(days=days) <= published <= now:
                continue
            accession, filename = recent['accessionNumber'][i], recent['primaryDocument'][i]
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.-]+\.(?:htm|html|pdf)', filename, re.I):
                continue
            result.append(Announcement(ticker=company['id'], title=f"{labels[form]} · {form}",
                url=f"https://www.sec.gov/Archives/edgar/data/{company['cik']}/{accession.replace('-', '')}/{filename}",
                published_at=published, category='results' if form in {'10-K', '20-F', '40-F', '10-Q'} else 'press_release',
                source={**response.extensions.get('finn_source', {}), 'kind': 'filing', 'publisher': 'SEC EDGAR', 'form': form}))
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise ProviderError('US company filings are unavailable and no saved filing list could be loaded.') from exc
