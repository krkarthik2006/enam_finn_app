"""Discover a bounded primary-source corpus, preserving unknown publication dates."""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from engine.financials import save_financial
from finn.documents import extract_pdf, save_document
from finn.models import Document
from finn.providers import ProviderError, Providers
from ingest.company import prepare_us_corpus


def prepare_corpus(db, providers, ticker, company=None):
    indexed = db.all("SELECT id,kind,url,title FROM documents WHERE ticker=? AND mode='live'", (ticker,))
    saved = db.setting('corpus:' + ticker, {})
    checked = saved.get('checked_at')
    if indexed and checked and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(checked)).total_seconds() < 21600:
        return {**saved, 'documents': indexed}
    if company and company['market'] == 'US':
        report = prepare_us_corpus(db, providers, company)
        if report['documents']:
            db.set_setting('corpus:' + ticker, {**report, 'checked_at': datetime.now(timezone.utc).isoformat()})
        return report
    report = {"documents": [], "gaps": [], "financial_periods": 0}
    try:
        data = providers.fundamentals(ticker)
        for record in data["records"]:
            save_financial(db, record)
        report["financial_periods"] = len(data["records"])
    except ProviderError as exc:
        report["gaps"].append(str(exc))
    try:
        discovery = providers.discover(ticker)
    except ProviderError as exc:
        report["gaps"].append(str(exc))
        report["documents"] = indexed
        return report
    official = (urlparse(discovery.get("company_website") or "").hostname or "").removeprefix("www.")
    selected, counts, seen = [], {"annual_report": 0, "transcript": 0}, set()
    for link in discovery["documents"]:
        kind = link["kind"]
        if link["url"] in seen or counts[kind] >= (1 if kind == "annual_report" else 4):
            continue
        selected.append(link)
        seen.add(link["url"])
        counts[kind] += 1
    for link in selected:
        if any(d["url"] == link["url"] for d in indexed):
            continue
        host = urlparse(link["url"]).hostname or ""
        allowed = host in providers.settings.document_hosts
        # The company website is supplied by Screener's company-links section. Only
        # that exact official domain/subdomains may extend this one download's allowlist.
        if official and (host == official or host.endswith("." + official)) and "." in official:
            allowed = True
        if not allowed:
            report["gaps"].append(f"Official document host requires configuration: {host}")
            continue
        scoped = Providers(providers.settings.model_copy(update={"document_hosts": [*providers.settings.document_hosts, host]}))
        try:
            content = scoped.download(link["url"])
            pages = extract_pdf(content)
            title = re.sub(r"\s+", " ", link["title"])[:300]
            result = save_document(db, Document(ticker=ticker, kind=link["kind"], title=title,
                                               url=link["url"], published_on=None, mode="live"), pages)
            report["documents"].append(result)
        except (ProviderError, ValueError) as exc:
            report["gaps"].append(f"{link['kind']}: {exc}")
    report["documents"] = db.all("SELECT id,kind,url,title FROM documents WHERE ticker=? AND mode='live'", (ticker,))
    if any(not r["published_on"] for r in db.all("SELECT published_on FROM documents WHERE ticker=? AND mode='live'", (ticker,))):
        report["gaps"].append("Some source publication dates are not supplied; no precise publication date has been invented.")
    if report['documents']:
        db.set_setting('corpus:' + ticker, {**report, 'checked_at': datetime.now(timezone.utc).isoformat()})
    return report
