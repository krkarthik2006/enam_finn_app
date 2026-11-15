"""Verify portfolio names against company catalogs before fetching market-specific sources."""
import json

from finn.models import Company
from ingest.company import resolve_company


def lookup(db, providers, query):
    identity = resolve_company(db, providers, query)
    return Company(ticker=identity['id'], name=identity['name'], exchange='US' if identity['market'] == 'US' else 'NSE')


def canonicalize(db, providers, tickers):
    changes, resolved = [], []
    for ticker in tickers:
        row = db.one('SELECT payload FROM portfolio WHERE ticker=?', (ticker,))
        old = json.loads(row['payload']) if row else None
        company = lookup(db, providers, ticker)
        if old:
            company.sector = old.get('sector', '')
            if old.get('exchange') == 'BSE':
                company.exchange = 'BSE'
            company.bse_code = old.get('bse_code') if company.exchange != 'US' else None
            changes.append((ticker, company))
        resolved.append(company.ticker)
    with db.connect() as conn:
        for old, company in changes:
            if old != company.ticker:
                conn.execute('DELETE FROM portfolio WHERE ticker=?', (old,))
            conn.execute('INSERT OR REPLACE INTO portfolio VALUES (?,?)', (company.ticker, company.model_dump_json()))
    return list(dict.fromkeys(resolved))
