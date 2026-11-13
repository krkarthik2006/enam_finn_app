"""Pure Push enrichment from supplied events, financial records and investor-owned people."""

from datetime import date

from engine.financials import compare_records, cross_check
from engine.network import best_contact_for, paths_to, study_overlap, work_overlap

WEIGHTS = {"management_change": 8, "results": 7, "M&A": 9, "capex": 6, "litigation": 8}


def attention_score(event, contacts, preferences=None):
    preferences = preferences or {}
    category = event["category"]
    weight = WEIGHTS.get(category, 1)
    materiality = event.get("materiality", 1)
    preference = preferences.get(category, 1)
    boost = min(3, len(contacts))
    return {"value": round(weight * materiality * preference + boost, 4),
            "components": {"type_weight": weight, "materiality": materiality,
                           "investor_preference": preference, "network_boost": boost}}


def enrich(event, people, investor, financials, sector="", preferences=None):
    candidates = best_contact_for(people, event["ticker"], sector + " " + event["title"])
    contacts = candidates[:3]
    # Include a distinct supply-chain/competitive perspective instead of filling every
    # slot with employees whose profiles provide the same kind of evidence.
    if event["category"] in ("capex", "M&A", "litigation"):
        related = next((p for p in candidates if p["relationships"]), None)
        if related and related not in contacts:
            contacts = contacts[:2] + [{**related, "selection_reason": "Recorded supplier/competitor/customer perspective"}]
    result = {"category": event["category"], "summary": event["title"], "summary_method": "filing_title",
              "contacts": contacts, "attention_score": attention_score(event, contacts, preferences), "gaps": []}
    if event["category"] == "management_change":
        target = next((p for p in people if p["id"] == event.get("subject_person_id")), None)
        result["management"] = {
            "person": target,
            "profile_provenance": target["provenance"] if target else None,
            "paths": paths_to(people, investor, target["id"]) if target else [],
            "overlaps": [{"person_id": p["id"], "name": p["name"],
                          "work": work_overlap(p, target), "education": study_overlap(p, target)}
                         for p in people if target and p["id"] != target["id"]
                         and (work_overlap(p, target) or study_overlap(p, target))],
        }
        if not target:
            result["gaps"].append("Incoming person has no supplied profile; no biography or introduction path is inferred.")
    elif event["category"] == "results":
        matching = [r for r in financials if r.ticker == event["ticker"] and r.mode == event["mode"]
                    and r.frequency == "quarterly" and r.source_type in ("filing", "synthetic")
                    and r.period_end <= date.fromisoformat(event["published_at"][:10])
                    and ((event.get("financial_period_end") == r.period_end.isoformat())
                         or (event.get("url") and r.source_url == event["url"]))]
        current = max(matching, key=lambda r: (r.period_end, r.source_type == "filing", r.basis == "consolidated")) if matching else None
        if current:
            history = sorted(financials, key=lambda r: r.source_type != "filing")
            reference = next((r for r in financials if r.source_type == "screener" and r.ticker == current.ticker
                              and r.period_end == current.period_end and r.basis == current.basis
                              and r.frequency == current.frequency and r.mode == current.mode), None)
            result["results"] = {"period": current.model_dump(mode="json"),
                                 "comparisons": compare_records(current, history),
                                 "cross_check": cross_check(current, reference) if reference else {"status": "needs_screener"}}
            if current.source and current.source.get("extraction") in ("explicit_three_quarter_statement", "model_source_lines"):
                result["extraction_method"] = current.source["extraction"]
                result["summary_method"] = ("structured_financial_table" if current.source["extraction"] == "explicit_three_quarter_statement"
                                            else "source_cited_financials")
                result["summary"] = f"Quarter ended {current.period_end} ({current.basis}, INR {current.unit}): " + "; ".join(
                    f"{m.upper()} {v:g}" for m, v in current.metrics.items() if v is not None
                )
        else:
            result["results"] = None
            result["gaps"].append("No extracted financial period linked to this results filing; no numbers are invented.")
    return result
