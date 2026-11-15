import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from finn.db import Database
from finn.enrichment import save_card
from finn.models import AlertSettings, Announcement, PriceImport
from finn.network import recommend

RULES = [
    (
        "management_change",
        ("resign", "appointment of", "chief financial", "chief executive", "cfo", "managing director"),
    ),
    ("M&A", ("acquisition", "merger", "demerger", "joint venture")),
    ("litigation", ("litigation", "penalty", "court", "regulatory order", "insolvency")),
    ("results", ("financial results", "quarterly results", "audited results", "unaudited results")),
    ("earnings_call", ("transcript", "earnings call", "concall", "conference call")),
    ("capex", ("capacity expansion", "capital expenditure", "new plant", "capex")),
    ("credit_rating", ("credit rating", "rating reaffirm", "rating downgrade")),
    ("fund_raise", ("fund raising", "rights issue", "qip", "preferential allotment", "buyback")),
    ("insider_trading", ("insider trading", "disclosure under pit")),
    ("pledging", ("pledge", "pledging", "encumbrance")),
    ("bonus_split", ("bonus issue", "stock split", "sub-division")),
    ("dividend", ("dividend",)),
    ("postal_ballot", ("postal ballot",)),
    ("agm_egm", ("annual general meeting", "extraordinary general meeting")),
    ("investor_meetings", ("investor meet", "analyst meet")),
    ("press_release", ("press release", "order win", "product launch")),
]


def classify(title, body):
    # Title first: an earnings-call transcript often mentions financial results in its body.
    for text in (title.lower(), body.lower()):
        for category, phrases in RULES:
            if any(phrase in text for phrase in phrases):
                return category
    return "unclassified"


def save_announcement(db: Database, item: Announcement):
    payload = item.model_dump(mode="json")
    payload["category"] = item.category or classify(item.title, item.body)
    identifier = hashlib.sha256(
        f"{item.mode}|{item.ticker}|{item.url}|{item.title}|{payload['published_at']}".encode()
    ).hexdigest()[:24]
    payload["id"] = identifier
    payload["classification_method"] = "provided" if item.category else "keyword_rules"
    db.execute(
        "INSERT OR REPLACE INTO announcements VALUES (?,?,?,?,?,?)",
        (
            identifier,
            item.ticker,
            payload["published_at"],
            payload["category"],
            item.mode,
            json.dumps(payload),
        ),
    )
    save_card(db, payload)
    return payload


def save_prices(db: Database, item: PriceImport):
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?)",
            [(item.ticker, p.day.isoformat(), item.mode, p.close, p.volume) for p in item.prices],
        )
    if item.source:
        db.set_setting(f"prices_source:{item.mode}:{item.ticker}", item.source)
    return {"ticker": item.ticker, "count": len(item.prices), "mode": item.mode, "source": item.source}


def digest(db: Database, since: datetime, until: datetime, mode: str, include_routine: bool):
    settings = AlertSettings(**db.setting("alerts", {}))
    companies = db.all("SELECT ticker,payload FROM portfolio")
    exchanges = {c["ticker"]: json.loads(c["payload"]).get("exchange", "NSE") for c in companies}
    tickers = {c["ticker"] for c in companies}
    rows = db.all(
        "SELECT payload FROM announcements WHERE mode=? "
        "AND julianday(published_at)>=julianday(?) AND julianday(published_at)<=julianday(?)",
        (mode, since.isoformat().replace("+00:00", "Z"), until.isoformat().replace("+00:00", "Z")),
    )
    items, routine = [], []
    for row in rows:
        item = json.loads(row["payload"])
        if item["ticker"] not in tickers:
            continue
        is_news = item.get("source", {}).get("kind") == "news" if item.get("source") else False
        material = is_news or item["category"] in settings.material_categories
        stored = db.one("SELECT payload FROM enrichments WHERE event_id=? AND owner_id=?", (item["id"], db.owner_id))
        card = json.loads(stored["payload"]) if stored else {}
        item.update(
            {
                "type": "news" if is_news else "announcement",
                "priority": "high" if material else "routine",
                "summary": card.get("summary", item["title"]),
                "summary_method": card.get("summary_method", "filing_title"),
                "enrichment": card,
                "attention_score": card.get("attention_score", {"value": 1}),
                "network": recommend(
                    db, ticker=item["ticker"], theme=item["title"] + " " + item["body"],
                    person_id=item.get("subject_person_id"),
                )[:3] if material else [],
            }
        )
        (items if material else routine).append(item)
    # EOD alerts belong to their market session, not the request time.
    for ticker in sorted(tickers):
        market_time = until.astimezone(ZoneInfo("America/New_York" if exchanges[ticker] == "US" else "Asia/Kolkata"))
        completed_day = market_time.date()
        if exchanges[ticker] == "US" and market_time.hour < 16:
            completed_day -= timedelta(days=1)
        history = db.all(
            "SELECT * FROM prices WHERE ticker=? AND mode=? AND day<=? ORDER BY day DESC LIMIT ?",
            (
                ticker,
                mode,
                completed_day.isoformat(),
                settings.volume_lookback_days + (until - since).days + 3,
            ),
        )
        for index, latest in enumerate(history[:-1]):
            previous = history[index + 1]
            timestamp = (datetime.fromisoformat(latest["day"] + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
                         if exchanges[ticker] == "US" else datetime.fromisoformat(latest["day"] + "T18:00:00+05:30")).astimezone(timezone.utc)
            if not since <= timestamp <= until:
                continue
            change = (latest["close"] / previous["close"] - 1) * 100
            baseline = history[index + 1 : index + settings.volume_lookback_days + 1]
            average = sum(p["volume"] for p in baseline) / len(baseline)
            multiple = latest["volume"] / average if average > 0 else None
            reasons = []
            if abs(change) >= settings.price_change_percent:
                reasons.append(
                    f"Daily close changed {change:+.2f}% (threshold ±{settings.price_change_percent:g}%)."
                )
            enough_history = len(baseline) == settings.volume_lookback_days
            if enough_history and multiple is not None and multiple >= settings.volume_multiple:
                reasons.append(f"Volume was {multiple:.2f}× the prior {len(baseline)} trading-day average.")
            if reasons:
                items.append(
                    {
                        "id": f"price:{mode}:{ticker}:{latest['day']}",
                        "ticker": ticker,
                        "type": "market_alert",
                        "mode": mode,
                        "source": db.setting(f"prices_source:{mode}:{ticker}", None),
                        "priority": "high",
                        "attention_score": {"value": 5, "method": "market_threshold"},
                        "published_at": timestamp.isoformat(),
                        "summary": " ".join(reasons),
                        "price_change_percent": round(change, 4),
                        "volume_multiple": round(multiple, 4) if multiple is not None else None,
                        "volume_baseline_days": len(baseline),
                        "volume_baseline_complete": enough_history,
                        "network": recommend(db, ticker=ticker)[:3],
                    }
                )
    items.sort(key=lambda i: (i["attention_score"]["value"], datetime.fromisoformat(i["published_at"])), reverse=True)
    routine.sort(key=lambda i: datetime.fromisoformat(i["published_at"]), reverse=True)
    return {
        "mode": mode,
        "since": since,
        "until": until,
        "items": items,
        "routine_count": len(routine),
        "routine": routine if include_routine else [],
        "note": "EOD price alerts use close-to-close prices; splits and other corporate actions require review.",
    }
