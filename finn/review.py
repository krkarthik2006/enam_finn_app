"""Coherent, explicitly synthetic research corpus for visual review."""

from datetime import date

from engine.financials import save_financial
from finn.documents import save_document
from finn.models import Document, FinancialRecord
from finn.phase_demo import seed_phases

REVIEW_TICKERS = {"MOCKIT": "Mock IT Services", "TCS": "Tata Consultancy Services",
                  "INFY": "Infosys", "TITAN": "Titan", "CDSL": "CDSL"}


def seed_review(db):
    scenario = seed_phases(db)
    quarters = [("FY2026 Q3", date(2025, 12, 31), 950, 18, 20, 150, 110),
                ("FY2026 Q4", date(2026, 3, 31), 980, 19, 21, 154, 111),
                ("FY2027 Q1", date(2026, 6, 30), 1000, 20, 22, 160, 120),
                ("FY2027 Q2", date(2026, 9, 30), 1200, 20, 23, 200, 150)]
    for ticker, name in REVIEW_TICKERS.items():
        annual = (
            f"SYNTHETIC REVIEW SOURCE. {name} ({ticker}). All figures and descriptions in this exercise "
            "are fictional, not actual company financials. The illustrative business provides recurring "
            "services to enterprise customers in India and overseas. Consolidated figures in INR crore. "
            "FY2025 revenue was 3200, EBITDA 600, PBT 500 and PAT 360. FY2026 revenue was 3680, EBITDA 660.2, "
            "PBT 574 and PAT 411. FY2026 cash from operations was 580 and capital expenditure was 100. "
            "Year-end debt was 300 and equity 2000. Management described repeat customer relationships "
            "and better project delivery as strengths. Risks include delayed customer approvals, hiring "
            "costs and the concentration of revenue in a few large clients. No numerical valuation or "
            "future share-price target was provided."
        )
        save_document(db, Document(ticker=ticker, kind="annual_report", title=f"SYNTHETIC {ticker} FY2026 annual report",
                                   published_on=date(2026, 5, 31), text=annual, mode="demo"))
        save_financial(db, FinancialRecord(ticker=ticker, period_end=date(2026, 3, 31), frequency="annual",
                                          basis="consolidated", source_type="synthetic", mode="demo",
                                          metrics={"revenue": 3680, "ebitda": 660.2, "pbt": 574, "pat": 411}))
        for period, end, revenue, actual, guided, pbt, pat in quarters:
            # Synthetic publication dates are part of the fixture, not inferred real dates.
            published = date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 15)
            text = (
                f"SYNTHETIC REVIEW TRANSCRIPT. Fictional financials for {ticker}, {period}. "
                f"Period ended {end.isoformat()}. All figures are consolidated, INR crore. "
                f"Consolidated revenue for this quarter was INR {revenue} crore. "
                f"EBITDA margin delivered was {actual}%. Management explicitly guided for EBITDA margin "
                f"of {guided}% in the following quarter. PBT was INR {pbt} crore and PAT was INR {pat} crore. "
                "Management attributed margin pressure to delayed customer approvals and higher hiring costs. "
                "Repeat client relationships supported revenue resilience. An analyst asked about execution "
                "risk; management said project timing remains uncertain. No numerical revenue growth "
                "guidance or share-price target was provided."
            )
            save_document(db, Document(ticker=ticker, kind="transcript", title=f"SYNTHETIC {ticker} {period} transcript",
                                       published_on=published, text=text, mode="demo"))
            save_financial(db, FinancialRecord(ticker=ticker, period_end=end, basis="consolidated", source_type="synthetic",
                                              mode="demo", metrics={"revenue": revenue, "ebitda": round(revenue * actual / 100, 4),
                                                                    "pbt": pbt, "pat": pat}))
    from finn.enrichment import refresh_cards
    refresh_cards(db)
    return {**scenario, "research_tickers": list(REVIEW_TICKERS), "notice": "Review data is synthetic; real companies' names do not make these numbers real."}
