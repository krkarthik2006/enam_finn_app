from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app
from finn.providers import ProviderError, Providers


@pytest.fixture
def reader(tmp_path):
    with TestClient(create_app(Settings(database_path=tmp_path / 'reader.sqlite', cache_path=tmp_path / 'cache',
                                       glm_api_key='', api_token='', _env_file=None))) as client:
        yield client


def filing(reader, url):
    result = reader.post('/api/announcements', json={'ticker': 'TVSMOTOR', 'title': 'Resignation',
                         'published_at': datetime.now(timezone.utc).isoformat(), 'url': url})
    assert result.status_code == 200
    return '/api/announcements/' + result.json()['id'] + '/document'


def test_reader_serves_original_pdf_without_analysis(reader, monkeypatch):
    calls = []
    def download(url, prefer_cache=False):
        calls.append(prefer_cache)
        return b'%PDF-original'
    monkeypatch.setattr(reader.app.state.providers, 'download', download)
    result = reader.get(filing(reader, 'https://nsearchives.nseindia.com/corporate/filing.pdf'))
    assert result.status_code == 200
    assert result.content == b'%PDF-original'
    assert result.headers['content-type'] == 'application/pdf'
    assert calls == [True]
    assert not reader.app.state.db.all('SELECT * FROM llm_calls')


def test_unavailable_filing_has_readable_retry_and_original_source(reader, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ProviderError('Exchange blocked')
    monkeypatch.setattr(reader.app.state.providers, 'download', unavailable)
    url = 'https://nsearchives.nseindia.com/corporate/filing.pdf?a=1&b=2'
    result = reader.get(filing(reader, url))
    assert result.status_code == 503
    assert result.headers['content-type'].startswith('text/html')
    assert 'Open original filing' in result.text and 'Try again' in result.text
    assert 'href="https://nsearchives.nseindia.com/corporate/filing.pdf?a=1&amp;b=2"' in result.text
    assert '"detail"' not in result.text


def test_zip_attachment_opens_official_download_instead_of_pdf_parser(reader, monkeypatch):
    def no_pdf_download(*args, **kwargs):
        pytest.fail('ZIP must not be parsed as PDF')
    monkeypatch.setattr(reader.app.state.providers, 'download', no_pdf_download)
    url = 'https://nsearchives.nseindia.com/corporate/TVSMOTOR_ROID_104748_KMP_Doc.zip'
    result = reader.get(filing(reader, url), follow_redirects=False)
    assert result.status_code == 307
    assert result.headers['location'] == url


def test_reader_does_not_redirect_to_untrusted_host(reader):
    result = reader.get(filing(reader, 'https://evil.example/filing.zip'), follow_redirects=False)
    assert result.status_code == 422
    assert 'location' not in result.headers


def test_download_remains_readable_when_disk_cache_write_fails(tmp_path, monkeypatch):
    provider = Providers(Settings(cache_path=tmp_path, _env_file=None))
    monkeypatch.setattr(provider, '_download', lambda url: b'%PDF-original')
    original = Path.write_bytes
    def full_disk(path, data):
        if path.suffix == '.tmp':
            raise OSError('No space left on device')
        return original(path, data)
    monkeypatch.setattr(Path, 'write_bytes', full_disk)
    assert provider.download('https://nsearchives.nseindia.com/corporate/filing.pdf') == b'%PDF-original'
    assert provider.cache.observations[-1]['cache_failure'] == 'OSError'
