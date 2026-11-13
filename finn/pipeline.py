import json
from datetime import datetime, timezone

from finn.alerts import save_announcement, save_prices
from finn.db import Database
from finn.providers import ProviderError, Providers


def run_refresh(db: Database, providers: Providers, run_id: str, tickers: list[str], days: int):
    started = datetime.now(timezone.utc).isoformat()
    report = {"id": run_id, "status": "running", "tickers": tickers, "sources": [], "days": days}
    db.execute("UPDATE refresh_runs SET payload=? WHERE id=?", (json.dumps(report), run_id))
    try:
        portfolio = {r["ticker"]: json.loads(r["payload"]) for r in db.all("SELECT * FROM portfolio")}
        for ticker in tickers:
            exchange = portfolio.get(ticker, {}).get("exchange", "NSE")
            for source in ("prices", "announcements"):
                try:
                    if source == "prices":
                        data = providers.prices(ticker, exchange)
                        save_prices(db, data)
                        count = len(data.prices)
                    else:
                        if exchange != "NSE":
                            raise ProviderError(
                                "Automatic BSE filing ingestion is not implemented; use filing import"
                            )
                        data = providers.announcements(ticker, days)
                        for item in data:
                            save_announcement(db, item)
                        count = len(data)
                    report["sources"].append(
                        {"ticker": ticker, "source": source, "status": "ok", "count": count}
                    )
                except ProviderError as exc:
                    report["sources"].append(
                        {"ticker": ticker, "source": source, "status": "error", "message": str(exc)}
                    )
                db.execute("UPDATE refresh_runs SET payload=? WHERE id=?", (json.dumps(report), run_id))
        errors = sum(s["status"] == "error" for s in report["sources"])
        report["status"] = (
            "completed" if not errors else "partial" if errors < len(report["sources"]) else "failed"
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
