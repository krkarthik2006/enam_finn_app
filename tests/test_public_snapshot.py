"""Public offline data must retain the same grounding as connected research."""
import json
from pathlib import Path

import pytest

from deploy.bootstrap import bootstrap
from finn.config import Settings
from finn.db import Database
from finn.mock_network import seed_network
from scripts.build_review_snapshot import build_snapshot, validate_snapshot


def test_snapshot_uses_public_sources_and_synthetic_contacts_only(tmp_path):
    settings = Settings(database_path=tmp_path / 'public.sqlite', glm_api_key='', api_token='', _env_file=None)
    db = Database(settings.database_path)
    db.initialize()
    bootstrap(db)
    seed_network(db)
    snapshot = build_snapshot(db, settings)
    validate_snapshot(snapshot)
    assert {'TCS', 'INFY'} <= {c['ticker'] for c in snapshot['portfolio']}
    assert all(c['provenance'] == 'synthetic' for c in snapshot['contacts'])
    assert snapshot['briefs']['INFY']['coverage']['transcripts'] > 0
    assert snapshot['briefs']['INFY']['coverage']['annual_reports'] > 0
    assert db.one("SELECT COUNT(*) n FROM documents WHERE mode='demo'")['n'] == 0
    assert db.one("SELECT COUNT(*) n FROM financials WHERE mode='demo'")['n'] == 0


@pytest.mark.parametrize('location', ['brief', 'source', 'financial', 'filing'])
def test_snapshot_rejects_synthetic_financial_content(tmp_path, location):
    settings = Settings(database_path=tmp_path / 'public.sqlite', glm_api_key='', api_token='', _env_file=None)
    db = Database(settings.database_path)
    db.initialize()
    bootstrap(db)
    seed_network(db)
    snapshot = build_snapshot(db, settings)
    if location == 'brief':
        snapshot['briefs']['INFY']['mode'] = 'demo'
    elif location == 'source':
        snapshot['briefs']['INFY']['sources'][0]['mode'] = 'demo'
    elif location == 'financial':
        snapshot['briefs']['INFY']['financials'][0]['mode'] = 'demo'
    else:
        snapshot['digest']['items'] = [{'mode': 'demo'}]
    with pytest.raises(ValueError, match='primary-source'):
        validate_snapshot(snapshot)


def test_shipped_snapshot_has_no_fictional_financial_sources():
    snapshot = json.loads(Path('web/public/snapshot.json').read_text())
    validate_snapshot(snapshot)
    assert snapshot['briefs']['TCS']['sources']
    assert not Path('web/public/demo.json').exists()


def test_cached_excerpts_match_bundled_original_pages_and_tables():
    import gzip
    bundle = json.loads(gzip.decompress(Path('deploy/public_sources.json.gz').read_bytes()))['tables']
    pages = {(p['document_id'], p['page']): p['text'] for p in bundle['doc_pages']}
    financials = {r['id']: json.loads(r['payload']) for r in bundle['financials']}
    snapshot = json.loads(Path('web/public/snapshot.json').read_text())
    for brief in snapshot['briefs'].values():
        for source in brief['sources']:
            if source['kind'] == 'financial_table':
                assert source['financial_record'] == financials[source['document_id']]
            else:
                assert ' '.join(source['text'].split()) in ' '.join(pages[(source['document_id'], source['page'])].split())
