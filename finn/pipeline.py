import json
from datetime import datetime, timezone

from engine.financials import save_financial
from finn.alerts import save_announcement, save_prices
from finn.db import Database
from finn.enrichment import extract_filing, refresh_cards
from finn.providers import ProviderError, Providers
from ingest.updates import news, us_filings


def run_refresh(db: Database, providers: Providers, run_id: str, tickers: list[str], days: int, fundamentals=False, enrichments=False, include_news=False):
    started = datetime.now(timezone.utc).isoformat()
    report = {"id": run_id, "status": "running", "tickers": tickers, "sources": [], "days": days}
    db.execute("UPDATE refresh_runs SET payload=? WHERE id=?", (json.dumps(report), run_id))
    try:
        portfolio = {r["ticker"]: json.loads(r["payload"]) for r in db.all("SELECT * FROM portfolio")}
        attempted_enrichments = set()
        for ticker in tickers:
            exchange = portfolio.get(ticker, {}).get("exchange", "US" if ticker.startswith("US-") else "NSE")
            bse_code = portfolio.get(ticker, {}).get("bse_code")
            company = db.one("SELECT payload FROM companies WHERE ticker=?", (ticker,))
            identity = json.loads(company["payload"]) if company else {}
            bse_code = bse_code or identity.get("bse_code")
            sources = ["prices"] + (["fundamentals"] if fundamentals and exchange != "US" else []) + ["announcements"]
            if include_news:
                sources.insert(0, "news")
            for source in sources:
                before = len(providers.cache.observations)
                enrichment_errors = []
                try:
                    if source == "prices":
                        data = providers.prices(ticker, exchange)
                        save_prices(db, data)
                        count = len(data.prices)
                    elif source == "fundamentals":
                        financials = providers.fundamentals(ticker)
                        for record in financials["records"]:
                            save_financial(db, record)
                        bse_code = financials["bse_code"] or bse_code
                        db.execute("INSERT OR REPLACE INTO companies VALUES (?,?)", (
                            ticker, json.dumps({"ticker": ticker, "bse_code": bse_code, "source": financials["source"]}),
                        ))
                        count = len(financials["records"])
                    else:
                        if source == "news":
                            data = news(providers, ticker, exchange, days)
                        elif exchange == "US":
                            data = us_filings(providers, identity, days)
                        elif exchange != "NSE" and not bse_code:
                            raise ProviderError("Provide a verified BSE code before automatic BSE filing ingestion")
                        else:
                            data = providers.announcements(ticker, days, bse_code)
                        for item in data:
                            saved = save_announcement(db, item)
                            if enrichments and exchange != "US" and source != "news" and saved["category"] in ("results", "management_change", "M&A", "capex", "litigation"):
                                attempted_enrichments.add(saved["id"])
                                try:
                                    extract_filing(db, saved, providers)
                                except (ProviderError, ValueError) as exc:
                                    enrichment_errors.append({"event_id": saved["id"], "message": str(exc)})
                        count = len(data)
                    report["sources"].append(
                        {"ticker": ticker, "source": source, "status": "partial" if enrichment_errors else "ok", "count": count,
                         "provenance": providers.cache.observations[before:], "enrichment_errors": enrichment_errors}
                    )
                except (ProviderError, ValueError) as exc:
                    report["sources"].append(
                        {"ticker": ticker, "source": source, "status": "error", "message": str(exc)}
                    )
                db.execute("UPDATE refresh_runs SET payload=? WHERE id=?", (json.dumps(report), run_id))
        # Stored filings remain actionable when exchange discovery fails or the filing
        # predates the current refresh window. Do not repeatedly extract completed cards.
        if enrichments:
            for row in db.all("SELECT id,ticker,payload FROM announcements WHERE mode='live'"):
                if row["ticker"] not in tickers or row["ticker"].startswith("US-") or row["id"] in attempted_enrichments:
                    continue
                event = json.loads(row["payload"])
                if event["category"] not in ("results", "management_change", "M&A", "capex", "litigation"):
                    continue
                stored = db.one("SELECT payload FROM enrichments WHERE event_id=? AND owner_id=?", (row["id"], db.owner_id))
                card = json.loads(stored["payload"]) if stored else {}
                if (event["category"] == "results" and card.get("results")) or card.get("source_quotes"):
                    continue
                try:
                    extract_filing(db, event, providers)
                    report["sources"].append({"ticker": row["ticker"], "source": "saved_filing_details", "event_id": row["id"], "status": "ok", "count": 1})
                except (ProviderError, ValueError) as exc:
                    report["sources"].append({"ticker": row["ticker"], "source": "saved_filing_details", "event_id": row["id"], "status": "error", "message": str(exc)})
                db.execute("UPDATE refresh_runs SET payload=? WHERE id=?", (json.dumps(report), run_id))
        errors = sum(s["status"] != "ok" for s in report["sources"])
        refresh_cards(db)
        report["status"] = (
            "completed" if not errors else "partial" if any(s.get("count", 0) > 0 for s in report["sources"]) else "failed"
        )
        report["uses_cached_sources"] = any(
            p["origin"] == "cache" for s in report["sources"] for p in s.get("provenance", [])
        )
    except Exception:
        report["status"] = "failed"
        report["error"] = "Unexpected pipeline failure; inspect local server logs."
        import logging

        logging.getLogger(__name__).exception("Refresh failed: %s", run_id)
    finally:
        report["started_at"] = started
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE refresh_runs SET payload=?,finished_at=? WHERE id=?",
            (json.dumps(report), report["finished_at"], run_id),
        )
