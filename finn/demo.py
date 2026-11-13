from datetime import date, datetime, timedelta, timezone

from finn.alerts import save_announcement, save_prices
from finn.db import Database
from finn.documents import save_document
from finn.models import Announcement, Company, Contact, Document, Price, PriceImport, Role

COMPANIES = [
    ("RELIANCE", "Reliance Industries", "Energy & retail"),
    ("TCS", "Tata Consultancy Services", "IT services"),
    ("INFY", "Infosys", "IT services"),
    ("HDFCBANK", "HDFC Bank", "Banking"),
    ("ICICIBANK", "ICICI Bank", "Banking"),
    ("SBIN", "State Bank of India", "Banking"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom"),
    ("ITC", "ITC", "Consumer goods"),
    ("HINDUNILVR", "Hindustan Unilever", "Consumer goods"),
    ("TITAN", "Titan", "Consumer discretionary"),
    ("MARUTI", "Maruti Suzuki", "Automobiles"),
    ("M&M", "Mahindra & Mahindra", "Automobiles"),
    ("LT", "Larsen & Toubro", "Engineering"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Pharmaceuticals"),
    ("DRREDDY", "Dr Reddy's Laboratories", "Pharmaceuticals"),
    ("TATASTEEL", "Tata Steel", "Metals"),
    ("PIDILITIND", "Pidilite Industries", "Specialty chemicals"),
    ("SRF", "SRF", "Specialty chemicals"),
]


def seed(db: Database):
    now = datetime.now(timezone.utc)
    existing = db.one("SELECT ticker FROM portfolio LIMIT 1")
    if not existing:
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO portfolio VALUES (?,?)",
                [
                    (ticker, Company(ticker=ticker, name=name, sector=sector).model_dump_json())
                    for ticker, name, sector in COMPANIES
                ],
            )
    people = [
        (
            "demo-meera",
            Contact(
                name="Meera Shah",
                roles=[
                    Role(
                        company="TCS", ticker="TCS", title="Delivery director", start_year=2017, end_year=2023
                    )
                ],
                expertise=["IT services", "enterprise technology", "operating margins"],
                education=["IIT Delhi"],
                knows=["demo-arjun"],
                notes="Fictional demo contact; no real relationship implied.",
            ),
        ),
        (
            "demo-arjun",
            Contact(
                name="Arjun Rao",
                roles=[Role(company="TCS", ticker="TCS", title="Finance leader", start_year=2020)],
                expertise=["cash conversion", "IT services"],
                education=["IIM Ahmedabad"],
            ),
        ),
        (
            "demo-kavya",
            Contact(
                name="Kavya Menon",
                roles=[
                    Role(
                        company="Infosys",
                        ticker="INFY",
                        title="Strategy manager",
                        start_year=2018,
                        end_year=2024,
                    )
                ],
                expertise=["IT services", "AI adoption"],
                education=["IIT Delhi"],
            ),
        ),
        (
            "demo-rohan",
            Contact(
                name="Rohan Sethi",
                roles=[
                    Role(company="SRF", ticker="SRF", title="Plant manager", start_year=2016, end_year=2022)
                ],
                expertise=["specialty chemicals", "capacity expansion", "capex"],
            ),
        ),
        (
            "demo-nisha",
            Contact(
                name="Nisha Iyer",
                roles=[
                    Role(
                        company="HDFC Bank",
                        ticker="HDFCBANK",
                        title="Credit analyst",
                        start_year=2019,
                        end_year=2024,
                    )
                ],
                expertise=["banking", "rural lending", "credit quality"],
            ),
        ),
        (
            "demo-dev",
            Contact(
                name="Dev Kapoor",
                roles=[
                    Role(
                        company="Titan",
                        ticker="TITAN",
                        title="Regional manager",
                        start_year=2015,
                        end_year=2021,
                    )
                ],
                expertise=["retail", "consumer demand", "jewellery"],
            ),
        ),
    ]
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO contacts VALUES (?,?)", [(i, c.model_dump_json()) for i, c in people]
        )
    for index, (ticker, _, _) in enumerate(COMPANIES):
        bars = []
        day = now.date() - timedelta(days=45)
        while day < now.date():
            if day.weekday() < 5:
                bars.append(
                    Price(day=day, close=100 + index * 15 + len(bars) * 0.2, volume=100000 + index * 1000)
                )
            day += timedelta(days=1)
        if ticker == "TCS":
            bars[-1] = Price(day=bars[-1].day, close=bars[-2].close * 1.07, volume=350000)
        save_prices(db, PriceImport(ticker=ticker, prices=bars, mode="demo"))
    for ticker, title, body, category in [
        (
            "TCS",
            "SYNTHETIC: Quarterly financial results",
            "Fictional exercise: revenue 1,180 crore; EBITDA 260 crore; "
            "PBT 230 crore; PAT 170 crore. Not actual company results.",
            "results",
        ),
        (
            "SRF",
            "SYNTHETIC: Board approves new plant",
            "Fictional capacity expansion for demonstrating network context.",
            "capex",
        ),
        (
            "INFY",
            "SYNTHETIC: Appointment of finance director",
            "Fictional management change. No real appointment is asserted.",
            "management_change",
        ),
        ("TITAN", "SYNTHETIC: Compliance certificate", "Routine fictional filing.", "unclassified"),
    ]:
        save_announcement(
            db,
            Announcement(
                ticker=ticker,
                title=title,
                body=body,
                category=category,
                published_at=now.replace(hour=0, minute=0, second=0, microsecond=0),
                mode="demo",
            ),
        )
    for ticker in ("TCS", "INFY", "TITAN", "CDSL", "COFORGE", "DIXON"):
        save_document(
            db,
            Document(
                ticker=ticker,
                kind="annual_report",
                mode="demo",
                title=f"SYNTHETIC {ticker} annual report",
                published_on=date(2026, 6, 1),
                text=f"SYNTHETIC DEMO SOURCE. These are fictional figures, not {ticker}'s actual financials. "
                "All figures in INR crore, consolidated, for this exercise only. The business sells services in India and overseas. "
                "FY2025 revenue was 4,000, EBITDA 800, PBT 700 and PAT 520. FY2026 revenue was 4,400, EBITDA 924, "
                "PBT 800 and PAT 600. Cash from operations was 550 in FY2025 and 660 in FY2026. FY2026 capex was 180. "
                "Debt at year end was 300 and equity was 2,000. Management described a shift toward higher-value services.",
            ),
        )
        for quarter, revenue, margin, guided_margin in [
            (1, 1000, 20, 21),
            (2, 1050, 20, 22),
            (3, 1120, 21, 23),
            (4, 1180, 22, 24),
        ]:
            save_document(
                db,
                Document(
                    ticker=ticker,
                    kind="transcript",
                    mode="demo",
                    title=f"SYNTHETIC {ticker} FY2026 Q{quarter} transcript",
                    published_on=date(2025 + (quarter == 4), {1: 7, 2: 10, 3: 12, 4: 3}[quarter], 20),
                    text=f"SYNTHETIC DEMO TRANSCRIPT. Not real company data. {ticker}, FY2026 Q{quarter}. "
                    f"Consolidated revenue for this quarter was INR {revenue} crore. EBITDA margin delivered was {margin}%. "
                    f"Management explicitly guided for EBITDA margin of {guided_margin}% in the following quarter. "
                    "The CFO said customer approvals delayed two projects. An analyst asked whether the prior margin target "
                    "was achieved; management said hiring and implementation costs remained higher than planned. "
                    "No numerical revenue growth guidance was provided.",
                ),
            )
    return {
        "status": "seeded",
        "mode": "demo",
        "portfolio_created": not bool(existing),
        "research_tickers": ["TCS", "INFY", "TITAN", "CDSL", "COFORGE", "DIXON"],
        "notice": "All demo prices, filings, financial documents and contacts are synthetic. Company names are real.",
    }
