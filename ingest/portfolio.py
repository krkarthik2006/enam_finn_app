"""Choose an event-backed portfolio from the official Nifty 100 universe."""

import argparse
import csv
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from finn.alerts import classify
from finn.config import Settings
from finn.models import normalize_ticker
from finn.providers import ProviderError, Providers


def select_portfolio(universe, announcements, limit=18):
    by_symbol = {row["Symbol"]: row for row in universe}
    grouped = {}
    for event in announcements:
        if event.ticker in by_symbol:
            category = classify(event.title, event.body)
            if category in ("management_change", "results", "M&A", "capex", "litigation"):
                grouped.setdefault(event.ticker, []).append({
                    "category": category, "title": event.title, "url": event.url,
                    "published_at": event.published_at.isoformat(),
                })
    weights = {"management_change": 10, "results": 3, "M&A": 7, "capex": 6, "litigation": 5}
    chosen, sectors = [], Counter()
    remaining = set(grouped)
    while remaining and len(chosen) < limit:
        ticker = max(sorted(remaining), key=lambda t: (
            sum(weights[e["category"]] for e in grouped[t]) / (1 + sectors[by_symbol[t]["Industry"]]), t,
        ))
        row = by_symbol[ticker]
        chosen.append({"ticker": ticker, "name": row["Company Name"], "sector": row["Industry"],
                       "exchange": "NSE", "reason": "Real material filings in the scanned window", "events": grouped[ticker]})
        sectors[row["Industry"]] += 1
        remaining.remove(ticker)
    categories = Counter(e["category"] for c in chosen for e in c["events"])
    coverage = {
        "portfolio_size": 15 <= len(chosen) <= 20,
        "management_change": categories["management_change"] >= 1,
        "five_results": categories["results"] >= 5,
        "material_event": any(categories[c] for c in ("M&A", "capex", "litigation")),
    }
    research, research_sectors = [], set()
    selected = {c["ticker"] for c in chosen}
    for row in universe:
        if row["Symbol"] not in selected and row["Industry"] not in research_sectors:
            research.append(row["Symbol"])
            research_sectors.add(row["Industry"])
        if len(research) == 4:
            break
    return {"companies": chosen, "coverage": coverage, "categories": dict(categories),
            "research_tickers": research,
            "status": "covered" if all(coverage.values()) else "insufficient_event_coverage"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, choices=range(1, 91), default=90)
    parser.add_argument("--output", type=Path, default=Path("data/mock/portfolio.json"))
    args = parser.parse_args()
    providers = Providers(Settings())
    try:
        with providers.client() as client:
            response = providers.cache.fetch(client, "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv")
        universe = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
        if not universe or "Symbol" not in universe[0]:
            raise ProviderError("Official Nifty 100 universe unavailable")
        for row in universe:
            row["Symbol"] = normalize_ticker(row["Symbol"])
        # The all-market endpoint can reject large date windows. Per-symbol calls are
        # slower but expose coverage explicitly instead of silently selecting from a subset.
        announcements, failures = [], []
        for index, row in enumerate(universe):
            try:
                announcements.extend(providers.announcements(row["Symbol"], args.days))
            except ProviderError as exc:
                failures.append({"ticker": row["Symbol"], "message": str(exc)})
            if (index + 1) % 10 == 0:
                print(f"Scanned {index + 1}/{len(universe)} symbols; {len(failures)} source failures", file=sys.stderr, flush=True)
        result = select_portfolio(universe, announcements)
        result.update({"scanned_universe": len(universe), "days": args.days,
                       "scanned_at": datetime.now(timezone.utc).isoformat(),
                       "sources": providers.cache.observations, "mode": "live"})
        result["scan_failures"] = failures
        result["notice"] = "Portfolio picks are backed by public filings; network people and relationships are separate synthetic fixtures."
        if failures:
            result["status"] = "partial_scan"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "companies"}, indent=2))
        return int(result["status"] != "covered")
    except (ProviderError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "source_failure", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
