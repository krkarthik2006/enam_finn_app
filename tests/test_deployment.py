import pytest

from deploy.start_api import prepare
from finn.config import Settings


def configuration(tmp_path, **changes):
    return Settings(database_path=tmp_path / "persistent/finn.sqlite", cache_path=tmp_path / "persistent/cache",
                    glm_api_key="", api_token="x" * 40, _env_file=None, **changes)


def test_hosting_refuses_missing_auth_or_ephemeral_storage(tmp_path):
    settings = configuration(tmp_path)
    with pytest.raises(ValueError, match="persistent volume"):
        prepare(settings, None)
    with pytest.raises(ValueError, match="Database must"):
        prepare(settings, str(tmp_path / "elsewhere"))
    with pytest.raises(ValueError, match="API token"):
        prepare(settings.model_copy(update={"api_token": Settings(api_token="", _env_file=None).api_token}), str(tmp_path))
    with pytest.raises(ValueError, match="Source cache must"):
        prepare(settings.model_copy(update={"cache_path": tmp_path / "ephemeral-cache"}), str(tmp_path / "persistent"))


def test_hosted_review_seed_is_repeatable_and_preserves_settings(tmp_path):
    settings = configuration(tmp_path)
    volume = str(tmp_path / "persistent")
    db = prepare(settings, volume)
    assert db.one("SELECT COUNT(*) n FROM contacts")["n"] == 40
    db.set_setting("alerts", {"price_change_percent": 7})
    docs = db.one("SELECT COUNT(*) n FROM documents")["n"]
    prepared = prepare(settings, volume)
    assert prepared.one("SELECT COUNT(*) n FROM documents")["n"] == docs
    assert prepared.setting("alerts", {})["price_change_percent"] == 7


def test_public_bootstrap_has_real_sources_without_contacts_or_credentials(tmp_path):
    import gzip
    import json
    from pathlib import Path

    from deploy.bootstrap import bootstrap
    from finn.db import Database
    bundle = json.loads(gzip.decompress(Path('deploy/public_sources.json.gz').read_bytes()))
    assert 'contacts' not in bundle['tables'] and 'settings' not in bundle['tables'] and 'llm_cache' not in bundle['tables']
    assert all(d['mode'] == 'live' and d['url'].startswith('https://') for d in bundle['tables']['documents'])
    db = Database(tmp_path / 'public.sqlite')
    db.initialize()
    bootstrap(db)
    assert db.one("SELECT COUNT(*) n FROM announcements WHERE mode='live'")['n'] > 0
    assert db.one("SELECT COUNT(*) n FROM doc_pages")['n'] > 0
    assert db.one("SELECT COUNT(*) n FROM contacts")['n'] == 0
    count = db.one("SELECT COUNT(*) n FROM chunks")['n']
    bootstrap(db)
    assert db.one("SELECT COUNT(*) n FROM chunks")['n'] == count
