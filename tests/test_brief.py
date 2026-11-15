import json

from fastapi.testclient import TestClient

from finn.brief import build_brief
from finn.config import Settings
from finn.db import Database
from finn.documents import save_document
from finn.main import create_app
from finn.models import Document
from finn.review import seed_review


def test_brief_math_citations_and_mode_isolation(tmp_path):
    settings = Settings(database_path=tmp_path / "brief.sqlite", glm_api_key="", _env_file=None)
    db = Database(settings.database_path)
    db.initialize()
    seed_review(db)
    brief = build_brief(db, settings, "MOCKIT", "business financial guidance delivered risks", "demo", False)
    assert brief["coverage"]["transcripts"] >= 4
    latest = next(r for r in brief["guidance"] if r["period"] == "FY2027 Q2")
    assert latest["actual"] == 20 and latest["delta"] == -2
    ids = {s["citation_id"] for s in brief["sources"]}
    assert set(latest["citation_ids"]) <= ids
    assert all(s["mode"] == "demo" for s in brief["sources"])
    assert brief["network"]
    assert build_brief(db, settings, "MOCKIT", "business financial guidance", "live", False)["status"] == "needs_sources"


def test_stream_and_exact_original_page(tmp_path):
    settings = Settings(database_path=tmp_path / "brief.sqlite", glm_api_key="", api_token="", _env_file=None)
    with TestClient(create_app(settings)) as client:
        doc = save_document(client.app.state.db, Document(ticker="UNSEEN", kind="annual_report", title="Unseen FY2026 report"),
                            [(7, "Original page seven. Consolidated revenue was INR 500 crore, with material customer concentration risks.")])
        response = client.post("/api/research/UNSEEN/brief", json={"question": "What risks are reported?", "prepare_sources": False, "use_model": False})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["type"] == "progress" and events[-1]["type"] == "result"
        assert events[-1]["data"]["sources"][0]["page"] == 7
        assert events[-1]["data"]["sources"][0]["published_on"] is None
        page = client.get(f"/api/documents/{doc['id']}/pages/7").json()
        assert page["text"].startswith("Original page seven.")
        assert client.get(f"/api/documents/{doc['id']}/pages/8").status_code == 404
        assert client.post("/api/research/invalid!/brief", json={}).status_code == 422


def test_reingest_keeps_unknown_publication_date(tmp_path):
    db = Database(tmp_path / "docs.sqlite")
    db.initialize()
    doc = Document(ticker="NEW", kind="transcript", title="Q2 FY27", published_on=None,
                   text="The original document does not disclose a precise publication date. We must not invent it.")
    save_document(db, doc)
    save_document(db, doc)
    assert len(db.all("SELECT * FROM documents")) == 1
    assert db.one("SELECT published_on FROM documents")["published_on"] == ""


def test_corpus_limits_and_company_host_scope(tmp_path, monkeypatch):
    from finn.corpus import prepare_corpus
    from finn.providers import Providers
    settings = Settings(database_path=tmp_path / "corpus.sqlite", glm_api_key="", _env_file=None)
    db = Database(settings.database_path)
    db.initialize()
    provider = Providers(settings)
    monkeypatch.setattr(provider, "fundamentals", lambda ticker: {"records": []})
    monkeypatch.setattr(provider, "discover", lambda ticker: {"company_website": "https://www.company.example", "documents": [
        {"kind": "annual_report", "title": "Annual report 2026", "url": "https://ir.company.example/annual.pdf"},
        *[{"kind": "transcript", "title": f"Q{i} FY2027", "url": f"https://ir.company.example/q{i}.pdf"} for i in range(1, 5)],
        {"kind": "transcript", "title": "Older", "url": "https://unrelated.example/other.pdf"}]})
    downloads = []
    monkeypatch.setattr(Providers, "download", lambda self, url: downloads.append(url) or b"pdf")
    monkeypatch.setattr("finn.corpus.extract_pdf", lambda content: [(1, "Original report text with enough detail to be indexed. All source publication dates are unknown.")])
    result = prepare_corpus(db, provider, "UNSEEN")
    assert len(result["documents"]) == 5 and len(downloads) == 5
    assert all("ir.company.example" in url for url in downloads)
    assert all(not r["published_on"] for r in db.all("SELECT published_on FROM documents"))
    prepare_corpus(db, provider, "UNSEEN")
    assert len(downloads) == 5
    monkeypatch.setattr(provider, "discover", lambda ticker: {"company_website": "https://company.example", "documents": [
        {"kind": "transcript", "title": "Host spoof", "url": "https://company.example.evil.example/x.pdf"}]})
    refused = prepare_corpus(db, provider, "OTHER")
    assert not refused["documents"] and any("requires configuration" in g for g in refused["gaps"])


def test_broad_questions_retrieve_financials_and_risks_beyond_cover_pages(tmp_path):
    from finn.documents import retrieve
    db = Database(tmp_path / 'long-report.sqlite')
    db.initialize()
    save_document(db, Document(ticker='NEW', kind='annual_report', title='Annual report'), [
        *[(page, 'Cover sheet. Company address and registration information. ' * 70) for page in range(1, 10)],
        (10, 'Our business supplies computing products and services to customers. ' * 40),
        (11, 'Annual revenue was USD 100 million and net income was USD 20 million. ' * 40),
        (12, 'Our main reported risk is customer concentration and competition. ' * 40)])
    excerpts = retrieve(db, 'NEW', 'what is happening', 'live')
    assert {10, 11, 12} <= {s['page'] for s in excerpts}
    assert len({s['citation_id'] for s in excerpts}) == len(excerpts)


def test_empty_punctuation_is_not_a_research_finding(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / 'brief.sqlite', glm_api_key='unit-test', _env_file=None)
    db = Database(settings.database_path)
    db.initialize()
    save_document(db, Document(ticker='TEST', kind='annual_report', title='Test report',
                               text='TEST FIXTURE ONLY: The company provides subscription software. No financial forecast is supplied.'))
    def complete(self, payload, version, validate):
        source = json.loads(payload['messages'][1]['content'])['sources'][0]['citation_id']
        raw = {'choices': [{'message': {'content': json.dumps({'findings': [
            {'section': 'business', 'text': ':', 'citation_ids': [source]},
            {'section': 'business', 'text': 'The company provides subscription software.', 'citation_ids': [source]},
            {'section': 'business', 'text': 'The company provides subscription software.', 'citation_ids': [source]}], 'gaps': []})}}]}
        validate(raw)
        return raw
    monkeypatch.setattr('finn.brief.LLM.complete', complete)
    brief = build_brief(db, settings, 'TEST', 'Describe the business')
    assert [f['text'] for s in brief['sections'] for f in s['findings']] == ['The company provides subscription software.']


def test_newly_indexed_annual_report_wins_when_publication_dates_are_unknown(tmp_path):
    db = Database(tmp_path / 'source-refresh.sqlite')
    db.initialize()
    settings = Settings(database_path=db.path, glm_api_key='', _env_file=None)
    save_document(db, Document(ticker='NEW', kind='annual_report', title='Older report',
                               url='https://issuer.example/older.pdf', text='TEST FIXTURE: Older business report with superseded evidence and financial information.'))
    latest = save_document(db, Document(ticker='NEW', kind='annual_report', title='New report',
                                       url='https://issuer.example/new.pdf', text='TEST FIXTURE: Newly indexed business report with current revenue and operating risk evidence.'))
    brief = build_brief(db, settings, 'NEW', 'Describe the business', use_model=False)
    assert {s['document_id'] for s in brief['sources']} == {latest['id']}
    assert all(s['published_on'] is None for s in brief['sources'])
