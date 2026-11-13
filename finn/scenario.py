"""Small, repeatable fictional scenario for inspecting Push -> Pull -> people."""

from datetime import date, datetime, timedelta, timezone

from finn.alerts import save_announcement, save_prices
from finn.db import Database
from finn.documents import save_document
from finn.models import Announcement, Company, Contact, Document, Price, PriceImport, Role

TICKER = "MOCKIT"
TARGET = "workflow-cfo"
QUESTION = (
    "Compare Q2 delivered EBITDA margin with the guidance given in Q1. "
    "What explains the shortfall in IT services operating margins?"
)


def seed_workflow(db: Database):
    now = datetime.now(timezone.utc)
    suffix = "" if db.owner_id == "local" else ":" + db.owner_id
    target_id = TARGET + suffix
    company = Company(ticker=TICKER, name="Mock IT Services (fictional)", sector="IT services")
    db.execute("INSERT OR IGNORE INTO portfolio VALUES (?,?)", (TICKER, company.model_dump_json()))
    people = {
        TARGET: Contact(
            name="Riya Sen (fictional)",
            direct_contact=False,
            roles=[Role(company=company.name, ticker=TICKER, title="Incoming CFO", start_year=2026)],
            notes="Subject of the synthetic appointment; not an introduction contact.",
        ),
        "workflow-expert": Contact(
            name="Ananya Das (fictional)",
            expertise=["IT services", "operating margins"],
            notes="Independent industry expert. No employment or connection to the CFO is recorded.",
        ),
        "workflow-insider": Contact(
            name="Vikram Shah (fictional)",
            roles=[Role(company=company.name, ticker=TICKER, title="Delivery director", start_year=2022)],
            notes="Current company employee. Employment overlap does not prove acquaintance.",
        ),
        "workflow-connector": Contact(
            name="Neha Rao (fictional)", knows=[TARGET],
            notes="Explicitly recorded connection to Riya; no company employment or expertise is recorded.",
        ),
        "workflow-unrelated": Contact(
            name="Kabir Mehta (fictional)", expertise=["agriculture", "irrigation"],
            notes="Negative control: unrelated to this company, question and person.",
        ),
    }
    people = {identifier + suffix: contact.model_copy(update={
        "knows": [other + suffix for other in contact.knows],
    }) for identifier, contact in people.items()}
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO contacts(id,payload,owner_id) VALUES (?,?,?)",
            [(identifier, contact.model_dump_json(), db.owner_id) for identifier, contact in people.items()],
        )
    for kind, title, published, text in [
        ("annual_report", "SYNTHETIC MOCKIT FY2025 annual report", date(2025, 6, 1),
         "Mock IT Services is fictional. It sells IT services. FY2025 consolidated revenue was INR "
         "4,000 crore and EBITDA was INR 800 crore. These are synthetic exercise figures."),
        ("transcript", "SYNTHETIC MOCKIT FY2026 Q1 transcript", date(2025, 7, 20),
         "Synthetic exercise, fictional company. FY2026 Q1: management guided for Q2 EBITDA margin "
         "of 22%. This is forward guidance, not delivered Q2 performance. IT services operating "
         "margins were expected to improve as new projects ramped up."),
        ("transcript", "SYNTHETIC MOCKIT FY2026 Q2 transcript", date(2025, 10, 20),
         "Synthetic exercise, fictional company. FY2026 Q2 consolidated revenue was INR 1,100 crore. "
         "Delivered EBITDA margin was 20%, versus prior Q1 guidance for Q2 of 22%. Management "
         "attributed the operating margins shortfall to delayed customer approvals and higher hiring "
         "costs in IT services. No numerical guidance was supplied for Q3."),
    ]:
        save_document(db, Document(
            ticker=TICKER, kind=kind, title=title, published_on=published, text=text, mode="demo",
        ))
    event = save_announcement(db, Announcement(
        ticker=TICKER, title="SYNTHETIC: Appointment of CFO; IT services operating margins review",
        body="Fictional Riya Sen appointed CFO following a margin shortfall. All data is synthetic.",
        published_at=now - timedelta(minutes=1), subject_person_id=target_id, mode="demo",
    ))
    # Stable event identity keeps repeated seeding from accumulating daily filing copies.
    db.execute(
        "DELETE FROM announcements WHERE ticker=? AND mode='demo' "
        "AND json_extract(payload,'$.title')=? AND id<>?",
        (TICKER, event["title"], event["id"]),
    )
    bars = []
    day = now.date() - timedelta(days=40)
    while day < now.date():
        if day.weekday() < 5:
            bars.append(Price(day=day, close=100, volume=1000))
        day += timedelta(days=1)
    bars[-1] = Price(day=bars[-1].day, close=107, volume=3000)
    save_prices(db, PriceImport(ticker=TICKER, prices=bars, mode="demo"))
    return {
        "mode": "demo", "ticker": TICKER, "subject_person_id": target_id,
        "announcement_id": event["id"],
        "research_request": {
            "ticker": TICKER, "question": QUESTION, "mode": "demo",
            "person_id": target_id, "include_trace": True,
        },
        "expected_contacts": {
            "industry_expert": "workflow-expert" + suffix, "company_insider": "workflow-insider" + suffix,
            "recorded_connection": "workflow-connector" + suffix,
        },
        "expected_evidence": {"q2_guided_margin_percent": 22, "q2_actual_margin_percent": 20},
        "notice": "Company, people, relationships and financial figures are fictional. No messages are sent.",
    }
