"""Explicit financial periods and units; never substitute operating profit for EBITDA."""

import calendar
import hashlib
import json
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from finn.models import FinancialRecord

METRICS = ("revenue", "ebitda", "pbt", "pat")


def save_financial(db, record):
    payload = record.model_dump(mode="json")
    key = hashlib.sha256(json.dumps([
        record.ticker, payload["period_end"], record.frequency, record.basis,
        record.currency, record.unit, record.source_type, record.mode,
    ]).encode()).hexdigest()[:24]
    db.execute("INSERT OR REPLACE INTO financials VALUES (?,?,?,?,?,?,?)", (
        key, record.ticker, payload["period_end"], record.frequency,
        record.source_type, record.mode, json.dumps(payload),
    ))
    return {"id": key, **payload}


def parse_screener(html, ticker, url):
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    basis = "consolidated" if "Consolidated Figures" in text else (
        "standalone" if "Standalone Figures" in text else None
    )
    if basis is None or "Crores" not in text:
        raise ValueError("Cannot establish Screener accounting basis and units")
    records = []
    mapping = {"sales": "revenue", "revenue": "revenue", "net profit": "pat",
               "profit before tax": "pbt", "ebitda": "ebitda", "operating profit": "operating_profit"}
    for section_id, frequency in (("quarters", "quarterly"), ("profit-loss", "annual")):
        section = soup.select_one(f"#{section_id}")
        if not section:
            continue
        headers = section.select("thead th")
        periods = []
        for position, header in enumerate(headers):
            try:
                parsed = datetime.strptime(header.get_text(" ", strip=True), "%b %Y")
                periods.append((position, date(parsed.year, parsed.month, calendar.monthrange(parsed.year, parsed.month)[1])))
            except ValueError:
                continue  # TTM is not a financial year.
        rows = {}
        for row in section.select("tbody tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(" ", strip=True).replace("+", "").strip().casefold()
            if label in mapping:
                rows[mapping[label]] = cells
        for column, period in periods:
            metrics = {}
            for metric in (*METRICS, "operating_profit"):
                cells = rows.get(metric, [])
                raw = cells[column].get_text(strip=True).replace(",", "") if column < len(cells) else ""
                try:
                    metrics[metric] = float(raw)
                except ValueError:
                    metrics[metric] = None
            if any(value is not None for value in metrics.values()):
                records.append(FinancialRecord(
                    ticker=ticker, period_end=period, frequency=frequency, basis=basis,
                    metrics=metrics, source_type="screener", source_url=url,
                ))
    if not records:
        raise ValueError("No parseable Screener financial periods")
    return records


def previous_period(period, months):
    total = period.year * 12 + period.month - 1 - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, calendar.monthrange(year, month)[1])


def growth(current, previous):
    if current is None or previous is None:
        return {"percent": None, "status": "missing_value"}
    if previous <= 0:
        return {"percent": None, "status": "nonpositive_base"}
    return {"percent": round((current / previous - 1) * 100, 4), "status": "calculated"}


def compare_records(current, history):
    comparable = [r for r in history if all(
        getattr(r, k) == getattr(current, k) for k in ("ticker", "frequency", "basis", "currency", "unit", "mode")
    )]
    result = {}
    for label, months in (("qoq", 3), ("yoy", 12)):
        if label == "qoq" and current.frequency == "annual":
            result[label] = {metric: {"percent": None, "status": "not_applicable_to_annual"} for metric in METRICS}
            continue
        prior = next((r for r in comparable if r.period_end == previous_period(current.period_end, months)), None)
        result[label] = {metric: {**growth(current.metrics.get(metric), prior.metrics.get(metric) if prior else None),
                                  "previous": prior.metrics.get(metric) if prior else None,
                                  "period": prior.period_end.isoformat() if prior else None}
                         for metric in METRICS}
    return result


def cross_check(filing, screener):
    if any(getattr(filing, k) != getattr(screener, k) for k in (
        "ticker", "period_end", "frequency", "basis", "currency", "unit", "mode",
    )):
        return {"status": "incompatible_period_basis_or_units", "metrics": {}}
    checks = {}
    for metric in METRICS:
        value, reference = filing.metrics.get(metric), screener.metrics.get(metric)
        if value is None or reference is None:
            checks[metric] = {"status": "not_available", "difference_percent": None}
        else:
            difference = abs(value - reference) / abs(reference) * 100 if reference else (0 if value == 0 else None)
            checks[metric] = {"status": "match" if difference is not None and difference <= 2 else "mismatch",
                              "difference_percent": round(difference, 4) if difference is not None else None}
    return {"status": "checked", "metrics": checks, "reference": {
        "source_type": screener.source_type, "source_url": screener.source_url, "mode": screener.mode,
        "notice": "Synthetic reference fixture" if screener.mode == "demo" else "Stored Screener observation",
    }}


def parse_statement_pages(pages, ticker, url, mode="live"):
    """Read a provable three-quarter statement layout, otherwise return no figures.

    Recognise dates before reading columns: current quarter, preceding quarter, same
    quarter last year. Half-year/year columns follow these and are never used here.
    This rule is independent of company names and leaves unsupported layouts to extraction.
    """
    records = []
    labels = {"revenue": r"revenue from operations", "ebitda": r"ebitda",
              "pbt": r"profit before tax", "pat": r"profit for the period|net profit for the period"}
    for page, text in pages:
        if not re.search(r"statement of financial results", text, re.I) or not re.search(r"\bcrore\b", text, re.I):
            continue
        if re.search(r"\bUSD|\bEUR|\bGBP|\bdollars\b", text, re.I) and not re.search(r"\bINR\b|₹|\brupees\b|\bRs[.\s]", text, re.I):
            continue  # Foreign-currency statements must not be relabelled INR.
        if not re.search(r"three months ended", text, re.I):
            continue
        basis = "consolidated" if re.search(r"\bconsolidated\b", text, re.I) else (
            "standalone" if re.search(r"\bstandalone\b", text, re.I) else None
        )
        if not basis:
            continue
        lines = text.splitlines()
        date_row = next((i for i, line in enumerate(lines) if len(re.findall(r"[A-Z][a-z]+ \d{1,2},", line)) >= 3), None)
        if date_row is None:
            continue
        months = re.findall(r"([A-Z][a-z]+ \d{1,2}),", lines[date_row])
        years = re.findall(r"\b20\d{2}\b", lines[date_row + 1]) if date_row + 1 < len(lines) else []
        if len(months) != len(years) or len(years) < 3:
            continue
        try:
            periods = [datetime.strptime(m + " " + y, "%B %d %Y").date() for m, y in zip(months, years, strict=True)][:3]
        except ValueError:
            continue
        if periods[1] != previous_period(periods[0], 3) or periods[2] != previous_period(periods[0], 12):
            continue
        values, quotes = {}, {}
        for metric, label in labels.items():
            for line in lines:
                match = re.match(r"\s*(?:" + label + r")\s+(.+)$", line, re.I)
                if not match:
                    continue
                tokens = re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<!\S)[-–](?!\S)", match.group(1).replace("−", "-"))
                if len(tokens) < 3:
                    continue
                parsed = []
                for token in tokens[:3]:
                    if token in ("-", "–"):
                        parsed.append(None)
                    else:
                        clean = token.replace(",", "")
                        parsed.append(-abs(float(clean[1:-1])) if clean.startswith("(") else float(clean))
                values[metric] = parsed
                quotes[metric] = {"page": page, "text": line.strip()}
                break
        if not values:
            continue
        for index, period in enumerate(periods):
            metrics = {m: values[m][index] if m in values else None for m in METRICS}
            if all(value is None for value in metrics.values()):
                continue
            records.append(FinancialRecord(
                ticker=ticker, period_end=period, basis=basis, unit="crore", mode=mode, source_type="filing",
                source_url=url, metrics=metrics,
                pages={m: page for m in values},
                source={"extraction": "explicit_three_quarter_statement", "quotes": quotes},
            ))
    return records
