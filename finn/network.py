import json
import re
from datetime import date

from engine.network import study_overlap
from finn.db import Database


def recommend(db: Database, ticker: str | None = None, theme: str = "", person_id: str | None = None):
    contacts = [{"id": r["id"], **json.loads(r["payload"])} for r in db.all("SELECT * FROM contacts WHERE owner_id=?", (db.owner_id,))]
    target = next((c for c in contacts if c["id"] == person_id), None)
    tokens = set(re.findall(r"[a-z0-9]+", theme.lower())) - {"the", "and", "who", "can", "help", "with"}
    matches = []
    for contact in contacts:
        if contact["id"] == person_id or not contact.get("direct_contact", True):
            continue
        reasons, score, match_types = [], 0, set()
        for role in contact["roles"]:
            if ticker and role.get("ticker") == ticker:
                current = role.get("end_year") is None
                score += 10 if current else 8
                match_types.add("company_insider" if current else "company_alumnus")
                reasons.append(
                    f"{'Works' if current else 'Worked'} at {role['company']} as {role['title']} "
                    f"({role['start_year']}–{role.get('end_year') or 'present'})."
                )
        for expertise in contact["expertise"]:
            if tokens.intersection(re.findall(r"[a-z0-9]+", expertise.lower())):
                score += 3
                match_types.add("industry_expert")
                reasons.append(f"Listed expertise: {expertise}.")
        for relation in contact.get("related_companies", []):
            if ticker and relation["ticker"] == ticker:
                score += 4
                match_types.add(relation["kind"])
                reasons.append(f"Recorded {relation['kind']} relationship to {ticker}.")
        relationship = None
        if target:
            if target["id"] in contact["knows"] or contact["id"] in target["knows"]:
                score += 15
                relationship = "explicit_connection"
                match_types.add("recorded_connection")
                reasons.append(f"Explicit recorded connection to {target['name']}.")
            for a in contact["roles"]:
                for b in target["roles"]:
                    same = (a.get("ticker") and a.get("ticker") == b.get("ticker")) or (
                        a["company"].casefold() == b["company"].casefold()
                    )
                    overlap = max(a["start_year"], b["start_year"]) <= min(
                        a.get("end_year") or date.today().year, b.get("end_year") or date.today().year
                    )
                    if same and overlap:
                        score += 5
                        reasons.append(
                            f"Employment dates overlap at {a['company']}; acquaintance is unverified."
                        )
                        relationship = relationship or "possible_employment_overlap"
                        match_types.add("employment_overlap")
            schools = study_overlap(contact, target)
            if schools:
                score += 1
                reasons.append(
                    "Shared educational institution; attendance overlap and acquaintance unverified."
                )
        if reasons:
            matches.append(
                {
                    "contact_id": contact["id"],
                    "name": contact["name"],
                    "score": score,
                    "reasons": list(dict.fromkeys(reasons)),
                    "relationship": relationship,
                    "match_types": sorted(match_types),
                    "provenance": contact["provenance"],
                    "last_contacted": contact["last_contacted"],
                }
            )
    return sorted(matches, key=lambda x: (-x["score"], x["name"]))[:10]
