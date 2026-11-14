"""Source-labelled quarterly guidance and deterministic promised-versus-delivered math."""

import calendar
import re
from datetime import date


def quarter_label(text):
    match = re.search(r"\bFY\s*(20\d{2}|\d{2})\s*[-:]?\s*Q([1-4])\b", text, re.I)
    if match:
        year, quarter = match.groups()
    else:
        match = re.search(r"\bQ([1-4])\s*[-:]?\s*FY\s*(20\d{2}|\d{2})\b", text, re.I)
        if not match:
            return None
        quarter, year = match.groups()
    return f"FY{int(year) + (2000 if len(year) == 2 else 0)} Q{quarter}"


def next_period(period):
    match = re.fullmatch(r"FY(20\d{2}) Q([1-4])", period or "")
    if match:
        year, quarter = map(int, match.groups())
        return f"FY{year + (quarter == 4)} Q{quarter % 4 + 1}"
    try:
        current = date.fromisoformat(period)
        index = current.year * 12 + current.month - 1 + 3
        year, month = divmod(index, 12)
        return date(year, month + 1, calendar.monthrange(year, month + 1)[1]).isoformat()
    except (ValueError, TypeError):
        return None


def rule_claims(source):
    if source["kind"] != "transcript":
        return []
    period = quarter_label(source["title"] + " " + source["text"])
    if not period:
        return []
    text = source["text"]
    basis = "consolidated" if "consolidated" in text.lower() else (
        "standalone" if "standalone" in text.lower() else "not_stated"
    )
    claims = []

    def claim(kind, target, low, high=None, metric="ebitda_margin", unit="percent"):
        claims.append({"kind": kind, "period": target, "metric": metric, "low": float(low),
                       "high": float(high if high is not None else low), "unit": unit, "basis": basis,
                       "citation_ids": [source["citation_id"]], "method": "explicit_source_rule"})

    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\bguid(?:ed|ance)\b", sentence, re.I):
            match = re.search(r"EBITDA margin(?: of| at| between)?\s*(\d+(?:\.\d+)?)(?:\s*(?:to|[-–])\s*(\d+(?:\.\d+)?))?\s*%", sentence, re.I)
            if match:
                target = quarter_label(sentence)
                explicit = re.search(r"for\s+Q([1-4])\b", sentence, re.I)
                if explicit:
                    year, current_q = map(int, re.findall(r"\d+", period))
                    q = int(explicit.group(1))
                    target = f"FY{year + (q < current_q)} Q{q}"
                elif re.search(r"following quarter|next quarter", sentence, re.I):
                    target = next_period(period)
                if target and target != period:
                    claim("guidance", target, *match.groups())
            continue
        actual = re.search(r"(?:EBITDA margin (?:delivered|reported|achieved)(?: was| of)?|(?:delivered|actual|reported) EBITDA margin(?: was| of)?|EBITDA margin was)\s*(\d+(?:\.\d+)?)\s*%", sentence, re.I)
        if actual:
            claim("actual", period, actual.group(1))
        revenue = re.search(r"(?:consolidated )?revenue(?: for this quarter)?(?: was| of|:)\s*(?:INR|Rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(crore|lakh|million)", sentence, re.I)
        if revenue:
            claim("actual", period, revenue.group(1).replace(",", ""), metric="revenue", unit=revenue.group(2).lower())
    return claims


def compare_guidance(claims):
    results = []
    for guide in (c for c in claims if c["kind"] == "guidance"):
        candidates = [c for c in claims if c["kind"] == "actual" and all(
            c[k] == guide[k] for k in ("period", "metric", "unit", "basis")
        )]
        values = {c["low"] for c in candidates if c["low"] == c["high"]}
        result = {"period": guide["period"], "metric": guide["metric"], "unit": guide["unit"],
                  "basis": guide["basis"], "guided_low": guide["low"], "guided_high": guide["high"],
                  "actual": None, "delta": None, "status": "missing_actual", "citation_ids": guide["citation_ids"]}
        if guide["basis"] == "not_stated":
            result["status"] = "basis_not_stated"
        elif len(values) > 1:
            result["status"] = "conflicting_actuals"
        elif len(values) == 1:
            value = values.pop()
            delta = value - guide["low"] if value < guide["low"] else (value - guide["high"] if value > guide["high"] else 0)
            result.update({"actual": value, "delta": round(delta, 4),
                           "status": "missed" if delta < 0 else "exceeded" if delta > 0 else "met",
                           "difference_unit": "percentage_points" if guide["unit"] == "percent" else guide["unit"],
                           "citation_ids": list(dict.fromkeys(guide["citation_ids"] + [i for c in candidates for i in c["citation_ids"]]))})
        if not any(all(r[k] == result[k] for k in ("period", "metric", "guided_low", "guided_high", "basis", "unit")) for r in results):
            results.append(result)
    return sorted(results, key=lambda r: (r["period"], r["metric"]))
