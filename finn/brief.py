"""Cited research sections and guidance math; private contacts never enter model requests."""

import json
import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engine.guidance import compare_guidance, next_period, quarter_label, rule_claims
from engine.llm import LLM, PROMPTS
from finn.documents import retrieve
from finn.network import recommend

SECTION_NAMES = {"business": "Business snapshot", "financial": "Financial trajectory",
                 "guidance": "Promised vs delivered", "bull": "What could go right", "bear": "What to watch"}


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["guidance", "actual"]
    period: str
    metric: Literal["revenue", "ebitda", "ebitda_margin", "pbt", "pat"]
    low: float = Field(allow_inf_nan=False)
    high: float = Field(allow_inf_nan=False)
    unit: Literal["percent", "crore", "lakh", "million"]
    basis: Literal["consolidated", "standalone", "not_stated"]
    citation_ids: list[str] = Field(min_length=1, max_length=4)


class Claims(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim]
    gaps: list[str]


class SectionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal["business", "financial", "guidance", "bull", "bear"]
    text: str = Field(min_length=1, max_length=2000)
    citation_ids: list[str] = Field(min_length=1, max_length=8)


class BriefAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[SectionFinding] = Field(max_length=15)
    gaps: list[str] = Field(max_length=12)


def structured_sources(db, ticker, mode):
    rows = db.all("SELECT id,payload FROM financials WHERE ticker=? AND mode=? ORDER BY period_end DESC", (ticker, mode))
    rows.sort(key=lambda r: (json.loads(r["payload"])["basis"] != "consolidated",
                             json.loads(r["payload"])["source_type"] == "screener"))
    chosen, seen, counts = [], set(), defaultdict(int)
    for row in rows:
        item = json.loads(row["payload"])
        key = (item["period_end"], item["frequency"], item["basis"], item["currency"], item["unit"])
        if key in seen or counts[item["frequency"]] >= (5 if item["frequency"] == "quarterly" else 2):
            continue
        seen.add(key)
        counts[item["frequency"]] += 1
        chosen.append({"citation_id": "table:" + row["id"], "document_id": row["id"],
                       "title": f"{ticker} {item['frequency']} financials · {item['period_end']}",
                       "kind": "financial_table", "published_on": None, "page": None, "mode": mode,
                       "url": item["source_url"], "text": json.dumps(item), "financial_record": item})
    return chosen


def guidance_claims(db, settings, evidence, use_model):
    claims, gaps = [], []
    grouped = defaultdict(list)
    for source in evidence:
        if source["kind"] == "transcript":
            grouped[source["document_id"]].append(source)
    for sources in grouped.values():
        rules = [claim for source in sources for claim in rule_claims(source)]
        claims.extend(rules)
        text = " ".join(s["text"] for s in sources)
        if any(c["kind"] == "guidance" for c in rules) or not re.search(r"guidance|guided|outlook", text, re.I):
            continue
        period = quarter_label(sources[0]["title"] + " " + text)
        if not period or not use_model or not settings.glm_api_key.get_secret_value():
            gaps.append("Quantified quarterly guidance could not be established for " + sources[0]["title"])
            continue
        periods = [period, next_period(period)]
        schema = Claims.model_json_schema()
        schema["$defs"]["Claim"]["properties"]["period"]["enum"] = periods
        payload = {"model": settings.glm_model, "temperature": 0, "stream": False, "max_tokens": 2000,
                   "response_format": {"type": "json_schema", "json_schema": {"name": "quarter_guidance", "strict": True, "schema": schema}},
                   "messages": [{"role": "system", "content": (PROMPTS / "guidance.md").read_text()},
                                {"role": "user", "content": json.dumps({"periods": periods, "excerpts": sources})}]}
        allowed = {s["citation_id"]: s for s in sources}

        def validate(raw):
            parsed = Claims.model_validate_json(raw["choices"][0]["message"]["content"])
            for item in parsed.claims:
                if item.period not in periods or item.low > item.high or not set(item.citation_ids) <= allowed.keys():
                    raise ValueError("Invalid guidance period/range/citation")
                quoted = " ".join(allowed[c]["text"] for c in item.citation_ids)
                numbers = [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*(?:\.\d+)?", quoted)]
                if item.low not in numbers or item.high not in numbers:
                    raise ValueError("Guidance values absent from source")

        raw = LLM(db, settings).complete(payload, "guidance-v1", validate)
        result = Claims.model_validate_json(raw["choices"][0]["message"]["content"])
        claims.extend({**c.model_dump(), "method": "source_cited_model"} for c in result.claims)
        gaps.extend(result.gaps)
    return claims, gaps


def supported_figures(finding, sources, comparisons):
    def numbers(text):
        return {float(value.replace(",", "")) for value in re.findall(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?", text)}

    cited = " ".join(source["text"] for source in sources if source["citation_id"] in finding.citation_ids)
    allowed = numbers(cited) | numbers(json.dumps(comparisons))
    return numbers(finding.text) <= allowed


def build_brief(db, settings, ticker, question, mode="live", use_model=True):
    indexed = db.all("SELECT id,kind FROM documents WHERE ticker=? AND mode=? ORDER BY published_on DESC,rowid DESC", (ticker, mode))
    selected = [r["id"] for kind, limit in (("transcript", 4), ("annual_report", 1))
                for r in [d for d in indexed if d["kind"] == kind][:limit]]
    evidence = retrieve(db, ticker, question, mode, selected)
    tables = structured_sources(db, ticker, mode)
    sources = evidence + tables
    claims, extraction_gaps = guidance_claims(db, settings, evidence, use_model)
    comparisons = compare_guidance(claims)
    sections = [{"id": key, "title": title, "findings": [], "empty_message": "Not found in primary sources."}
                for key, title in SECTION_NAMES.items()]
    result = {"ticker": ticker, "question": question, "mode": mode, "status": "evidence_only" if sources else "needs_sources",
              "sections": sections, "sources": sources, "guidance": comparisons, "financials": [s["financial_record"] for s in tables],
              "network": recommend(db, ticker=ticker, theme=question)[:5], "gaps": extraction_gaps,
              "coverage": {"documents": len({s["document_id"] for s in evidence}),
                           "transcripts": len({s["document_id"] for s in evidence if s["kind"] == "transcript"}),
                           "annual_reports": len({s["document_id"] for s in evidence if s["kind"] == "annual_report"}),
                           "retrieved_excerpts": len(evidence)}, "cached": False}
    if not sources:
        result["gaps"].append("No primary sources are indexed for this company and mode.")
        return result
    if not use_model or not settings.glm_api_key.get_secret_value():
        result["gaps"].append("Showing source evidence and calculated comparisons; model narrative is unavailable.")
        return result
    schema = BriefAnalysis.model_json_schema()
    payload = {"model": settings.glm_model, "temperature": 0, "max_tokens": 4000, "stream": False,
               "response_format": {"type": "json_schema", "json_schema": {"name": "research_brief", "strict": True, "schema": schema}},
               "messages": [{"role": "system", "content": (PROMPTS / "brief.md").read_text()},
                            {"role": "user", "content": json.dumps({"ticker": ticker, "question": question,
                             "sources": sources, "computed_comparisons": comparisons})}]}
    ids = {s["citation_id"] for s in sources}

    def validate(raw):
        parsed = BriefAnalysis.model_validate_json(raw["choices"][0]["message"]["content"])
        if not parsed.findings and not parsed.gaps:
            raise ValueError("Empty brief")
        if any(not set(f.citation_ids) <= ids for f in parsed.findings):
            raise ValueError("Unknown brief citation")

    before = db.one("SELECT COUNT(*) AS n FROM llm_calls WHERE status='completed'")["n"]
    raw = LLM(db, settings).complete(payload, "brief-v3", validate)
    analysis = BriefAnalysis.model_validate_json(raw["choices"][0]["message"]["content"])
    grounded = [finding for finding in analysis.findings if supported_figures(finding, sources, comparisons)]
    if len(grounded) != len(analysis.findings):
        analysis.gaps.append("Some numerical claims could not be verified against the cited sources.")
    analysis.findings = grounded
    unique = {}
    for finding in analysis.findings:
        if any(char.isalnum() for char in finding.text):
            unique.setdefault((finding.section, finding.text), finding)
    analysis.findings = list(unique.values())
    for section in sections:
        section["findings"] = [f.model_dump() for f in analysis.findings if f.section == section["id"]]
    return {**result, "status": "analysed" if analysis.findings else "evidence_only", "gaps": extraction_gaps + analysis.gaps,
            "model": settings.glm_model, "usage": raw.get("usage", {}),
            "cached": before == db.one("SELECT COUNT(*) AS n FROM llm_calls WHERE status='completed'")["n"],
            "validation": "References and computed comparisons checked; interpretation remains reviewable against source excerpts."}
