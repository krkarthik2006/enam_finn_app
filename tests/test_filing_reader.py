from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
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


def test_zip_attachment_serves_its_pdf_and_ignores_xml(reader, monkeypatch):
    url = 'https://nsearchives.nseindia.com/corporate/TVSMOTOR_ROID_104748_KMP_Doc.zip'
    payload = archive({'CIM.xml': b'<structured-data/>', 'TVSM_SMP_intimation.pdf': b'%PDF-original'})
    provider = reader.app.state.providers
    original = httpx.Client
    monkeypatch.setattr(provider, 'validate_document_url', lambda url: None)
    monkeypatch.setattr(provider, 'client', lambda: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=payload))))
    result = reader.get(filing(reader, url))
    assert result.status_code == 200
    assert result.headers['content-type'] == 'application/pdf'
    assert result.content == b'%PDF-original'
    # The extracted original is cached under its archive URL for offline reuse.
    provider.settings.offline_sources = True
    assert provider.download(url, prefer_cache=True) == b'%PDF-original'


def archive(files):
    out = BytesIO()
    with ZipFile(out, 'w') as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return out.getvalue()


@pytest.mark.parametrize('files', [
    {'data.xml': b'<xml/>'},
    {'first.pdf': b'%PDF-first', 'second.pdf': b'%PDF-second'},
    {'filing.pdf': b'not actually a PDF'},
])
def test_archive_without_one_valid_pdf_is_not_silently_misrepresented(tmp_path, monkeypatch, files):
    provider = Providers(Settings(cache_path=tmp_path, _env_file=None))
    original = httpx.Client
    monkeypatch.setattr(provider, 'validate_document_url', lambda url: None)
    monkeypatch.setattr(provider, 'client', lambda: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=archive(files)))))
    with pytest.raises(ValueError):
        provider.download('https://nsearchives.nseindia.com/corporate/filing.zip')
    assert not list(tmp_path.rglob('*.pdf'))


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
