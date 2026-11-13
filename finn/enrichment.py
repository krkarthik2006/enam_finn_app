"""Ingest-time orchestration; digest reads precomputed cards without model calls."""

import hashlib
import json
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.network import investor, load_people
from engine.financials import parse_statement_pages, save_financial
from engine.llm import LLM, PROMPTS
from engine.network import resolve_person
from engine.push import enrich
from finn.documents import extract_pdf, save_document
from finn.models import Category, Document, FinancialRecord
from finn.providers import ProviderError


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation_ids: list[str] = Field(min_length=1, max_length=8)


class Figure(Quote):
    value: float = Field(allow_inf_nan=False)


class Person(Quote):
    name: str
    title: str


class Figures(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revenue: Figure | None
    ebitda: Figure | None
    pbt: Figure | None
    pat: Figure | None


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_end: date
    basis: Literal["consolidated", "standalone"]
    unit: Literal["crore", "lakh", "million"]
    figures: Figures

    def items(self):
        return [(metric, getattr(self.figures, metric)) for metric in ("revenue", "ebitda", "pbt", "pat")
                if getattr(self.figures, metric) is not None]


class FilingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    summary: str
    summary_quotes: list[Quote] = Field(min_length=1)
    incoming_person: Person | None
    financial_periods: list[Period]
    gaps: list[str]


class FlatPeriod(BaseModel):
    """Shallow provider schema; internal facts retain richer quoted-value objects."""
    model_config = ConfigDict(extra="forbid")
    period_end: date
    basis: Literal["consolidated", "standalone"]
    unit: Literal["crore", "lakh", "million"]
    revenue: float | None
    revenue_citation_ids: list[str]
    ebitda: float | None
    ebitda_citation_ids: list[str]
    pbt: float | None
    pbt_citation_ids: list[str]
    pat: float | None
    pat_citation_ids: list[str]


class FlatFilingFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    summary: str
    summary_citation_ids: list[str] = Field(min_length=1)
    person_name: str | None
    person_title: str | None
    person_citation_ids: list[str]
    financial_periods: list[FlatPeriod]
    gaps: list[str]


def event_hash(event):
    return hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()


def save_card(db, event, facts=None):
    old = db.one("SELECT payload FROM enrichments WHERE event_id=? AND owner_id=?", (event["id"], db.owner_id))
    cached = json.loads(old["payload"]) if old else {}
    if facts is None and cached.get("event_hash") == event_hash(event):
        facts = cached.get("model_facts")
    people = load_people(db)
    effective = dict(event)
    resolution = []
    if facts and facts.get("incoming_person") and not effective.get("subject_person_id"):
        profile = {"name": facts["incoming_person"]["name"], "roles": [{
            "company": event["ticker"], "ticker": event["ticker"], "start_year": int(event["published_at"][:4]),
        }]}
        resolution = resolve_person(profile, people)
        confident = [m for m in resolution if m["confidence"] >= 0.7]
        if len(confident) == 1:
            effective["subject_person_id"] = confident[0]["person_id"]
    financials = [FinancialRecord(**json.loads(r["payload"])) for r in db.all(
        "SELECT payload FROM financials WHERE ticker=? AND mode=? ORDER BY period_end DESC", (event["ticker"], event["mode"]),
    )]
    company = db.one("SELECT payload FROM portfolio WHERE ticker=?", (event["ticker"],))
    sector = json.loads(company["payload"]).get("sector", "") if company else ""
    settings = db.setting("alerts", {})
    result = enrich(effective, people, investor(db), financials, sector, settings.get("category_weights"))
    result.update({"event_hash": event_hash(event), "model_facts": facts, "person_resolution": resolution})
    if facts:
        if event["category"] != "results" or not result.get("results"):
            result.update({"summary": facts["summary"], "summary_method": "model_with_exact_source_quotes"})
        result["gaps"].extend(facts.get("gaps", []))
        if "extraction_coverage" in cached:
            result["extraction_coverage"] = cached["extraction_coverage"]
        if "source_quotes" in cached:
            result["source_quotes"] = cached["source_quotes"]
    db.execute("INSERT OR REPLACE INTO enrichments VALUES (?,?,?)", (event["id"], db.owner_id, json.dumps(result)))
    return result


def refresh_cards(db):
    for row in db.all("SELECT payload FROM announcements"):
        save_card(db, json.loads(row["payload"]))


def extract_filing(db, event, providers):
    if event.get("url"):
        content = providers.download(event["url"])
        pages = extract_pdf(content)
        save_document(db, Document(
            ticker=event["ticker"], kind="quarterly_results", title=event["title"], url=event["url"],
            published_on=date.fromisoformat(event["published_at"][:10]), mode=event["mode"],
        ), pages)
    else:
        pages = [(None, event["title"] + "\n" + event.get("body", ""))]
    parsed = parse_statement_pages(pages, event["ticker"], event.get("url", ""), event["mode"]) if event["category"] == "results" else []
    if parsed:
        for record in parsed:
            if record.period_end <= date.fromisoformat(event["published_at"][:10]):
                save_financial(db, record)
        event["financial_period_end"] = max(r.period_end for r in parsed).isoformat()
        db.execute("UPDATE announcements SET payload=? WHERE id=?", (json.dumps(event), event["id"]))
        result = save_card(db, event, {})
        result["extraction_method"] = "explicit_three_quarter_statement"
        result["summary_method"] = "structured_financial_table"
        current = (result.get("results") or {}).get("period")
        if current:
            result["summary"] = f"Quarter ended {current['period_end']} ({current['basis']}, INR {current['unit']}): " + "; ".join(
                f"{m.upper()} {v:g}" for m, v in current["metrics"].items() if v is not None
            )
        result["extraction_coverage"] = {"total_pages": len(pages), "page_numbers": sorted({p for r in parsed for p in r.pages.values() if p is not None}),
                                         "selection": "recognised_statement_tables", "unrecognised_tables_not_extracted": True}
        db.execute("INSERT OR REPLACE INTO enrichments VALUES (?,?,?)", (event["id"], db.owner_id, json.dumps(result)))
        return result
    if not providers.settings.glm_api_key.get_secret_value():
        raise ProviderError("No recognised table layout; configure a model key for source-cited extraction")
    candidates = pages
    if event["category"] == "results":
        statements = [(page, text) for page, text in pages if re.search(r"revenue from operations|\bsales\b|\brevenue\b", text, re.I)
                      and re.search(r"profit before tax|\bpbt\b", text, re.I)]
        if statements:
            candidates = statements
    # Bound model context; report truncation explicitly rather than treating a partial PDF as complete.
    selected, size = [], 0
    for page, text in candidates:
        if size + len(text) > 60000:
            break
        selected.append((page, text))
        size += len(text)
    if not selected:
        raise ProviderError("Filing pages exceed context limit; select relevant pages explicitly")
    source = {}
    page_input = []
    for page, text in selected:
        lines = []
        for index, line in enumerate(text.splitlines()):
            if line.strip():
                identifier = f"S{len(source) + 1}"
                source[identifier] = {"page": page, "text": line.strip()}
                lines.append({"citation_id": identifier, "text": line.strip()})
        page_input.append({"page": page, "lines": lines})
    schema = FlatFilingFacts.model_json_schema()
    full_text = "\n".join(text for _, text in selected)
    known_periods = set()
    for token in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", full_text):
        try:
            value = date.fromisoformat(token)
            if value.month in (3, 6, 9, 12) and value.day in (30, 31):
                known_periods.add(value.isoformat())
        except ValueError:
            pass
    for token in re.findall(r"\b[A-Z][a-z]+\s+\d{1,2},?\s+20\d{2}\b", full_text):
        try:
            value = datetime.strptime(token.replace(",", ""), "%B %d %Y").date()
            if value.month in (3, 6, 9, 12) and value.day in (30, 31):
                known_periods.add(value.isoformat())
        except ValueError:
            pass
    if event["category"] != "unclassified":
        schema["properties"]["category"]["enum"] = [event["category"]]
    if known_periods:
        schema["$defs"]["FlatPeriod"]["properties"]["period_end"]["enum"] = sorted(known_periods)
    else:
        schema["properties"]["financial_periods"]["maxItems"] = 0
    source_units = {unit for unit in ("crore", "lakh", "million") if re.search(rf"\b{unit}s?\b", full_text, re.I)}
    source_bases = {basis for basis in ("consolidated", "standalone") if re.search(rf"\b{basis}\b", full_text, re.I)}
    foreign_currency = bool(re.search(r"\b(?:USD|EUR|GBP|dollars)\b", full_text, re.I)) and not re.search(
        r"\bINR\b|₹|\brupees\b|\bRs[.\s]", full_text, re.I,
    )
    if foreign_currency:
        schema["properties"]["financial_periods"]["maxItems"] = 0
    for field, choices in (("unit", source_units), ("basis", source_bases)):
        if choices:
            schema["$defs"]["FlatPeriod"]["properties"][field]["enum"] = sorted(choices)
        else:
            schema["properties"]["financial_periods"]["maxItems"] = 0
    request = {"model": providers.settings.glm_model, "max_tokens": 6000, "stream": False, "temperature": 0,
               "response_format": {"type": "json_schema", "json_schema": {
                   "name": "filing_facts", "strict": True, "schema": schema}},
               "messages": [{"role": "system", "content": (PROMPTS / "filing.md").read_text()},
                            {"role": "user", "content": json.dumps({"ticker": event["ticker"],
                             "filing_date": event["published_at"], "pages": page_input})}]}

    def parse_facts(raw):
        flat = FlatFilingFacts.model_validate_json(raw["choices"][0]["message"]["content"])
        facts = FilingFacts(
            category=flat.category, summary=flat.summary,
            summary_quotes=[Quote(citation_ids=flat.summary_citation_ids)],
            incoming_person=Person(name=flat.person_name, title=flat.person_title or "", citation_ids=flat.person_citation_ids)
            if flat.person_name else None,
            financial_periods=[Period(period_end=p.period_end, basis=p.basis, unit=p.unit,
                                      figures=Figures(**{m: Figure(value=getattr(p, m), citation_ids=getattr(p, m + "_citation_ids"))
                                                        if getattr(p, m) is not None else None
                                                        for m in ("revenue", "ebitda", "pbt", "pat")}))
                               for p in flat.financial_periods], gaps=flat.gaps,
        )
        grouped = {}
        for period in facts.financial_periods:
            if foreign_currency:
                raise ValueError("Foreign-currency statements cannot be treated as INR")
            key = (period.period_end, period.basis, period.unit)
            if key not in grouped:
                grouped[key] = period
                continue
            for metric, figure in period.items():
                existing = getattr(grouped[key].figures, metric)
                if existing and existing.value != figure.value:
                    raise ValueError("Conflicting values for one metric/period/basis")
                if existing:
                    existing.citation_ids = list(dict.fromkeys(existing.citation_ids + figure.citation_ids))
                else:
                    setattr(grouped[key].figures, metric, figure)
        facts.financial_periods = list(grouped.values())
        return facts

    def validate(raw):
        facts = parse_facts(raw)
        quotes = [*facts.summary_quotes, *([facts.incoming_person] if facts.incoming_person else []),
                  *(f for period in facts.financial_periods for _, f in period.items())]
        for item in quotes:
            if not set(item.citation_ids) <= source.keys():
                raise ValueError("Unknown source IDs: " + ",".join(sorted(set(item.citation_ids) - source.keys())))
            quoted = " ".join(source[c]["text"] for c in item.citation_ids)
            if isinstance(item, Figure):
                numbers = [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*(?:\.\d+)?", quoted)]
                if item.value not in numbers:
                    raise ValueError("Extracted value is not in its cited quote")
            if isinstance(item, Person) and item.name.casefold() not in quoted.casefold():
                raise ValueError("Incoming person's name is not in the cited quote")
        for period in facts.financial_periods:
            if not period.items():
                raise ValueError("An empty financial period is not an extracted result")
            if period.period_end.isoformat() not in known_periods:
                raise ValueError("Financial period is not explicitly dated in the supplied source")
            if period.basis not in source_bases or period.unit not in source_units:
                raise ValueError("Financial basis or units are not explicit in the supplied source")
            labels = {"revenue": r"revenue|sales", "ebitda": r"ebitda|earnings before interest",
                      "pbt": r"profit before tax|\bpbt\b", "pat": r"profit for the period|profit after tax|net profit|\bpat\b"}
            for metric, figure in period.items():
                quoted = " ".join(source[c]["text"] for c in figure.citation_ids).lower()
                if not re.search(labels[metric], quoted):
                    raise ValueError("Metric label missing from cited source lines")
            if period.period_end > date.fromisoformat(event["published_at"][:10]):
                raise ValueError("Reported results cannot be for a future quarter")
            FinancialRecord(ticker=event["ticker"], period_end=period.period_end, basis=period.basis,
                            metrics={metric: f.value for metric, f in period.items()}, source_type="filing", unit=period.unit)

    raw = LLM(db, providers.settings).complete(request, "filing-v6", validate)
    facts = parse_facts(raw)
    for period in facts.financial_periods:
        save_financial(db, FinancialRecord(
            ticker=event["ticker"], period_end=period.period_end, basis=period.basis, unit=period.unit,
            metrics={metric: f.value for metric, f in period.items()},
            pages={metric: source[f.citation_ids[0]]["page"] for metric, f in period.items()},
            source_type="filing", source_url=event.get("url", ""), mode=event["mode"],
            source={"extraction": "model_source_lines", "quotes": {
                metric: [{**source[c], "citation_id": c} for c in f.citation_ids]
                for metric, f in period.items()
            }},
        ))
    # Rule classification wins; model classification is used only on a rule miss.
    if event["classification_method"] == "keyword_rules" and event["category"] == "unclassified":
        event.update({"category": facts.category, "classification_method": "model_filing_facts"})
    if facts.financial_periods:
        event["financial_period_end"] = max(p.period_end for p in facts.financial_periods).isoformat()
    db.execute("UPDATE announcements SET category=?,payload=? WHERE id=?", (event["category"], json.dumps(event), event["id"]))
    result = save_card(db, event, facts.model_dump(mode="json"))
    cited = {c for q in [*facts.summary_quotes, *([facts.incoming_person] if facts.incoming_person else []),
                        *(f for period in facts.financial_periods for _, f in period.items())] for c in q.citation_ids}
    result["source_quotes"] = {c: {**source[c], "url": event.get("url", "")} for c in sorted(cited)}
    result["extraction_coverage"] = {"included_pages": len(selected), "total_pages": len(pages),
                                     "truncated": len(selected) < len(pages), "page_numbers": [p for p, _ in selected],
                                     "selection": "financial_statement_pages" if candidates is not pages else "document_prefix"}
    if len(selected) < len(pages):
        result["gaps"].append("Only the included filing pages were analysed; remaining pages were omitted from model context.")
    db.execute("INSERT OR REPLACE INTO enrichments VALUES (?,?,?)", (event["id"], db.owner_id, json.dumps(result)))
    return result
