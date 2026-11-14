"""Validate automatic real-source Pull, including a company outside the saved demo."""
import json
from pathlib import Path

from finn.brief import build_brief
from finn.config import Settings
from finn.corpus import prepare_corpus
from finn.db import Database
from finn.providers import Providers


def main():
    settings = Settings(database_path=Path('/private/tmp/finn-pull-live.sqlite'))
    db = Database(settings.database_path)
    db.initialize()
    report = {}
    for ticker in ('INFY', 'HCLTECH'):
        print('Preparing real corpus:', ticker, flush=True)
        corpus = prepare_corpus(db, Providers(settings), ticker)
        print(ticker, len(corpus['documents']), 'documents;', corpus['financial_periods'], 'financial observations', flush=True)
        brief = build_brief(db, settings, ticker, 'Explain the business, financial trajectory, management guidance delivery, positives and risks.')
        report[ticker] = {'corpus': corpus, 'brief': brief}
        Path('/private/tmp/finn-pull-live.json').write_text(json.dumps(report, indent=2))
        print(ticker, brief['status'], brief['coverage'], flush=True)


if __name__ == "__main__":
    main()
