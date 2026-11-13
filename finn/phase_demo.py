"""Reviewable synthetic management/results/event cards with all planted network stories."""

from datetime import datetime, timedelta, timezone

from engine.financials import previous_period, save_financial
from finn.alerts import save_announcement
from finn.enrichment import refresh_cards
from finn.mock_network import seed_network
from finn.models import Announcement, Company, FinancialRecord
from finn.scenario import seed_workflow


def seed_phases(db):
    network = seed_network(db)
    workflow = seed_workflow(db)
    now = datetime.now(timezone.utc)
    # The most recently completed calendar quarter, independent of demo ticker/year.
    quarter_start_month = ((now.month - 1) // 3) * 3 + 1
    period = previous_period(now.date().replace(month=quarter_start_month, day=1), 1)
    previous = previous_period(period, 3)
    prior_year = previous_period(period, 12)
    for company in (Company(ticker="SRF", name="SRF", sector="specialty chemicals"),
                    Company(ticker="TCS", name="TCS", sector="IT services")):
        db.execute("INSERT OR IGNORE INTO portfolio VALUES (?,?)", (company.ticker, company.model_dump_json()))
    for end, values in [(period, (1200, 240, 200, 150)), (previous, (1000, 200, 160, 120)),
                        (prior_year, (900, 150, 140, 100))]:
        save_financial(db, FinancialRecord(
            ticker="MOCKIT", period_end=end, basis="consolidated", mode="demo", source_type="synthetic",
            metrics=dict(zip(("revenue", "ebitda", "pbt", "pat"), values, strict=True)),
            source_url="https://demo.invalid/MOCKIT/results", pages={m: None for m in ("revenue", "ebitda", "pbt", "pat")},
        ))
    save_financial(db, FinancialRecord(
        ticker="MOCKIT", period_end=period, basis="consolidated", mode="demo", source_type="screener",
        metrics={"revenue": 1100, "ebitda": None, "pbt": 200, "pat": 148},
        source_url="https://demo.invalid/MOCKIT/synthetic-reference",
    ))
    events = []
    for title, body, ticker, category in [
        ("SYNTHETIC: Quarterly financial results", f"Fictional quarterly results for period ended {period.isoformat()}. "
         "Consolidated figures, INR crore: Revenue 1200; EBITDA 240; PBT 200; PAT 150. "
         "These are reported results in this synthetic exercise, not forecasts or real financial data.", "MOCKIT", "results"),
        ("SYNTHETIC: Board approves capacity expansion", "Fictional new plant; the investor knows a synthetic supplier contact.", "SRF", "capex"),
        ("SYNTHETIC: Quarterly financial results", "Fictional results event to demonstrate a reconnect nudge; no actual financial figures supplied.", "TCS", "results"),
        ("SYNTHETIC: Compliance certificate", "Fictional routine filing.", "MOCKIT", "unclassified"),
    ]:
        event = save_announcement(db, Announcement(
            ticker=ticker, title=title, body=body, category=category, mode="demo",
            published_at=now.replace(hour=0, minute=1, second=0, microsecond=0),
            financial_period_end=period if ticker == "MOCKIT" and category == "results" else None,
        ))
        events.append(event)
    refresh_cards(db)
    return {"mode": "demo", "network": network, "workflow": workflow,
            "results_event_id": events[0]["id"], "material_event_id": events[1]["id"],
            "period_end": period.isoformat(), "digest_since": (now-timedelta(days=3)).isoformat(),
            "notice": "All demo financials, reference figures, people and relationships are synthetic. "
                      "The revenue reference deliberately differs by >2% to demonstrate a mismatch flag."}
