"""Repeatable local ingestion: python -m ingest.all --tickers TCS INFY --fundamentals."""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from finn.config import Settings
from finn.db import Database
from finn.documents import extract_pdf, save_document
from finn.models import Document, normalize_ticker
from finn.pipeline import run_refresh
from finn.providers import Providers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--days", type=int, choices=range(1, 91), default=7)
    parser.add_argument("--fundamentals", action="store_true")
    parser.add_argument("--enrich", action="store_true", help="Use model tokens for material filing extraction and classification rule misses")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--document-manifest", type=Path, help="JSON list of selected documents with authentic publication dates")
    args = parser.parse_args()
    settings = Settings(**({"offline_sources": True} if args.offline else {}))
    db = Database(settings.database_path)
    db.initialize()
    providers = Providers(settings)
    identifier = str(uuid.uuid4())
    db.execute("INSERT INTO refresh_runs VALUES (?,?,NULL,?)", (
        identifier, datetime.now(timezone.utc).isoformat(), json.dumps({"status": "queued"}),
    ))
    run_refresh(db, providers, identifier, [normalize_ticker(t) for t in args.tickers], args.days, args.fundamentals, args.enrich)
    if args.document_manifest:
        for payload in json.loads(args.document_manifest.read_text()):
            doc = Document(**payload)
            pages = extract_pdf(providers.download(doc.url)) if not doc.text else None
            save_document(db, doc, pages)
    report = json.loads(db.one("SELECT payload FROM refresh_runs WHERE id=?", (identifier,))["payload"])
    print(json.dumps(report, indent=2))
    return int(report["status"] in ("failed", "partial"))


if __name__ == "__main__":
    raise SystemExit(main())
