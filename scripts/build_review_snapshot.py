"""Build the offline snapshot only from public primary sources and synthetic contacts."""
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from deploy.bootstrap import COLUMNS, bootstrap
from finn.brief import build_brief
from finn.config import Settings
from finn.corpus import prepare_corpus
from finn.db import Database
from finn.main import create_app
from finn.mock_network import seed_network
from finn.providers import ProviderError, Providers

QUESTION = "Explain the business, financial trajectory, management guidance delivery, positives and risks."


def validate_snapshot(snapshot):
    financial_content = [snapshot['digest'], *snapshot['digest']['items'], *snapshot['digest']['routine']]
    for brief in snapshot['briefs'].values():
        financial_content.extend([brief, *brief['sources'], *brief['financials']])
        for source in brief['sources']:
            if not source['url'].startswith('https://'):
                raise ValueError('Offline research requires a primary-source URL')
    if any(item.get('mode') != 'live' for item in financial_content):
        raise ValueError('Offline financial content must be primary-source data')
    if any(p['provenance'] != 'synthetic' for p in snapshot['contacts']):
        raise ValueError('Never export private contacts to the public snapshot')


def build_snapshot(db, settings):
    now = datetime.now(timezone.utc)
    companies = {row['ticker']: json.loads(row['payload']) for row in db.all('SELECT * FROM companies')}
    tickers = sorted(set(companies) | {row['ticker'] for row in db.all("SELECT DISTINCT ticker FROM documents WHERE mode='live'")})
    portfolio = [{'ticker': ticker, 'name': companies.get(ticker, {}).get('name', ticker), 'sector': '',
                  'bse_code': companies.get(ticker, {}).get('bse_code')} for ticker in tickers]
    with TestClient(create_app(settings)) as client:
        token = settings.api_token.get_secret_value()
        if token:
            client.headers['Authorization'] = 'Bearer ' + token
        contacts = client.get('/api/network').json()['contacts']
        # Set only the public builder's isolated portfolio, never an investor's database.
        client.put('/api/portfolio', json={'companies': portfolio}).raise_for_status()
        snapshot = {'generated_at': now.isoformat(), 'portfolio': portfolio, 'contacts': contacts,
                    'digest': client.get('/api/digest', params={'mode': 'live', 'since': (now - timedelta(days=90)).isoformat(), 'include_routine': True}).json(),
                    'investor': client.get('/api/network/investor').json(),
                    'settings': client.get('/api/alerts/settings').json(),
                    'nudges': client.get('/api/network/reconnect?mode=live').json()['nudges'],
                    'paths': {p['id']: client.get('/api/network/paths', params={'person_id': p['id']}).json()['paths'] for p in contacts},
                    'briefs': {}}
        for ticker in tickers:
            try:
                brief = build_brief(db, settings, ticker, QUESTION, 'live')
            except ProviderError:
                brief = build_brief(db, settings, ticker, QUESTION, 'live', use_model=False)
            if brief['sources']:
                snapshot['briefs'][ticker] = brief
    validate_snapshot(snapshot)
    return snapshot


def main():
    # This dedicated DB preserves model/source caches across builds. It never reads
    # data/review.sqlite or the hosted investor database.
    settings = Settings(database_path=Path('data/public_snapshot.sqlite'))
    db = Database(settings.database_path, settings.owner_id)
    db.initialize()
    bootstrap(db)
    seed_network(db)
    for row in db.all('SELECT ticker FROM companies'):
        if not db.one("SELECT id FROM documents WHERE ticker=? AND mode='live'", (row['ticker'],)):
            print('Preparing original reports:', row['ticker'], flush=True)
            report = prepare_corpus(db, Providers(settings), row['ticker'])
            print(len(report['documents']), 'documents;', len(report['gaps']), 'source gaps', flush=True)
    snapshot = build_snapshot(db, settings)
    encoded = json.dumps(snapshot, indent=2)
    for secret in (settings.glm_api_key.get_secret_value(), settings.api_token.get_secret_value()):
        if secret:
            assert secret not in encoded
    Path('web/public/snapshot.json').write_text(encoded + '\n')
    bundle = {'version': 2, 'tables': {}}
    for table, columns in COLUMNS.items():
        where = " WHERE mode='live'" if 'mode' in columns.split(',') else ''
        bundle['tables'][table] = db.all(f'SELECT {columns} FROM {table}' + where)
    Path('deploy/public_sources.json.gz').write_bytes(gzip.compress(json.dumps(bundle).encode(), mtime=0))
    print('Saved primary-source briefs:', ', '.join(snapshot['briefs']), flush=True)


if __name__ == '__main__':
    main()
