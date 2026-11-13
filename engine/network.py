"""Pure relationship logic. Only supplied connection edges create introduction paths."""

import re
from collections import deque
from datetime import date, timedelta


def normalise_name(name):
    tokens = re.findall(r"[a-z]+", name.casefold())
    return [t for t in tokens if t not in {"mr", "mrs", "ms", "dr", "shri", "smt", "prof", "fictional"}]


def same_org(a, b):
    return bool(a.get("ticker") and a.get("ticker") == b.get("ticker")) or (
        a["company"].casefold().strip() == b["company"].casefold().strip()
    )


def work_overlap(a, b, as_of=None):
    year = (as_of or date.today()).year
    result = []
    for x in a.get("roles", []):
        for y in b.get("roles", []):
            start, end = max(x["start_year"], y["start_year"]), min(x.get("end_year") or year, y.get("end_year") or year)
            if same_org(x, y) and start <= end:
                result.append({"company": x["company"], "start_year": start, "end_year": end,
                               "years": end - start, "acquaintance_verified": False})
    return result


def study_overlap(a, b):
    result = []
    for x in a.get("education", []):
        for y in b.get("education", []):
            left, right = x if isinstance(x, dict) else {"institution": x}, y if isinstance(y, dict) else {"institution": y}
            if left["institution"].casefold() != right["institution"].casefold():
                continue
            dated = all(k in left and k in right for k in ("start_year", "end_year"))
            start = max(left["start_year"], right["start_year"]) if dated else None
            end = min(left["end_year"], right["end_year"]) if dated else None
            if not dated or start <= end:
                result.append({"institution": left["institution"], "start_year": start, "end_year": end,
                               "attendance_overlap_verified": dated, "acquaintance_verified": False})
    return result


def resolve_person(profile, people):
    wanted = normalise_name(profile["name"])
    result = []
    for person in people:
        actual = normalise_name(person["name"])
        if not wanted or not actual or wanted[-1] != actual[-1] or wanted[0][0] != actual[0][0]:
            continue
        exact = wanted == actual
        if wanted[0] != actual[0] and len(wanted[0]) > 1 and len(actual[0]) > 1:
            continue  # A shared first initial does not make different full first names equal.
        overlaps = work_overlap(profile, person)
        confidence = (1.0 if exact else 0.8) if overlaps else (0.65 if exact else 0.45)
        result.append({"person_id": person["id"], "confidence": confidence,
                       "status": "matched" if confidence >= 0.7 else "possible_match",
                       "reason": "Name and dated employer match" if overlaps else "Name only; employer/time evidence missing"})
    return sorted(result, key=lambda r: (-r["confidence"], r["person_id"]))


def paths_to(people, investor, target_id, max_hops=2):
    max_hops = min(2, max(1, max_hops))
    nodes = {p["id"]: p for p in [*people, investor]}
    if target_id not in nodes or target_id == investor["id"]:
        return []
    edges = {identifier: set() for identifier in nodes}
    for person in nodes.values():
        for other in person.get("knows", []):
            if other in nodes:
                edges[person["id"]].add(other)
                edges[other].add(person["id"])
    queue, found = deque([[investor["id"]]]), []
    while queue:
        path = queue.popleft()
        if path[-1] == target_id:
            strength = min(nodes[i].get("relationship_strength", 3) for i in path[1:])
            found.append({"person_ids": path, "names": [nodes[i]["name"] for i in path],
                          "hops": len(path) - 1, "strength": strength,
                          "explanation": " → ".join(nodes[i]["name"] for i in path) + "; recorded connections only"})
        elif len(path) - 1 < max_hops:
            queue.extend(path + [other] for other in sorted(edges[path[-1]]) if other not in path)
    return sorted(found, key=lambda p: (p["hops"], -p["strength"], p["person_ids"]))


def reconnect_nudges(people, events, as_of=None, days=270):
    today = as_of or date.today()
    result = []
    for person in people:
        last = person.get("last_contacted")
        if not last or not person.get("direct_contact", True):
            continue
        last = date.fromisoformat(last) if isinstance(last, str) else last
        if last > today - timedelta(days=days):
            continue
        tickers = {r.get("ticker") for r in person.get("roles", [])}
        for event in events:
            if event["ticker"] in tickers:
                result.append({"person_id": person["id"], "name": person["name"],
                               "event_id": event["id"], "days_since_contact": (today-last).days,
                               "reason": f"Their current/former employer {event['ticker']} has a new {event['category']} filing.",
                               "provenance": person["provenance"]})
    return result


def expertise_map(people, theme):
    tokens = set(re.findall(r"[a-z0-9]+", theme.casefold())) - {"the", "and", "who", "can", "with"}
    result = []
    for person in people:
        matched = [tag for tag in person.get("expertise", [])
                   if tokens.intersection(re.findall(r"[a-z0-9]+", tag.casefold()))]
        if matched and person.get("direct_contact", True):
            result.append({"person_id": person["id"], "name": person["name"], "expertise": matched,
                           "score": 3 * len(matched), "provenance": person["provenance"]})
    return sorted(result, key=lambda r: (-r["score"], r["name"]))


def best_contact_for(people, ticker, sector=""):
    expertise = {p["person_id"]: p["score"] for p in expertise_map(people, sector)}
    ranked = []
    for person in people:
        if not person.get("direct_contact", True):
            continue
        roles = [r for r in person.get("roles", []) if r.get("ticker") == ticker]
        relations = [r for r in person.get("related_companies", []) if r["ticker"] == ticker]
        score = max([10 if r.get("end_year") is None else 8 for r in roles] or [0])
        score += 4 * len(relations) + expertise.get(person["id"], 0)
        if score:
            ranked.append({"person_id": person["id"], "name": person["name"], "score": score,
                           "roles": roles, "relationships": relations, "provenance": person["provenance"]})
    return sorted(ranked, key=lambda r: (-r["score"], r["name"]))
