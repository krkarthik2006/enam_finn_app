import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from engine.network import expertise_map, paths_to, reconnect_nudges, resolve_person, study_overlap, work_overlap
from finn.models import Contact, Mode


def load_people(db):
    return [{"id": r["id"], **json.loads(r["payload"])} for r in db.all(
        "SELECT id,payload FROM contacts WHERE owner_id=?", (db.owner_id,),
    )]


def investor(db):
    return db.setting(f"investor:{db.owner_id}", {"id": "investor-" + db.owner_id, "name": "You", "knows": []})


def router(db):
    routes = APIRouter()

    @routes.get("/api/network/investor", tags=["network"])
    def get_investor():
        return investor(db)

    @routes.put("/api/network/investor", tags=["network"])
    def update_investor(body: Contact):
        ids = {p["id"] for p in load_people(db)}
        if not set(body.knows) <= ids:
            raise HTTPException(422, "Investor connections must reference contacts owned by this instance")
        payload = {"id": "investor-" + db.owner_id, **body.model_dump(mode="json")}
        db.set_setting(f"investor:{db.owner_id}", payload)
        from finn.enrichment import refresh_cards
        refresh_cards(db)
        return payload

    @routes.get("/api/network/paths", tags=["network"])
    def paths(person_id: str):
        people = load_people(db)
        if person_id not in {p["id"] for p in people}:
            raise HTTPException(404, "Person not found")
        target = next(person for person in people if person["id"] == person_id)
        overlaps = [{"person_id": person["id"], "name": person["name"], "work": work_overlap(target, person), "education": study_overlap(target, person)} for person in people if person["id"] != person_id]
        return {"paths": paths_to(people, investor(db), person_id), "overlaps": [item for item in overlaps if item["work"] or item["education"]],
                "note": "Only recorded connections form paths; employment/education overlap is not acquaintance."}

    @routes.post("/api/network/resolve", tags=["network"])
    def resolve(body: Contact):
        return {"matches": resolve_person(body.model_dump(mode="json"), load_people(db))}

    @routes.get("/api/network/expertise", tags=["network"])
    def expertise(theme: str = Query(min_length=1, max_length=200)):
        return {"matches": expertise_map(load_people(db), theme)}

    @routes.get("/api/network/reconnect", tags=["network"])
    def reconnect(mode: Mode = "live"):
        as_of = datetime.now(timezone.utc)
        if mode == "demo":
            latest = db.one("SELECT MAX(published_at) latest FROM announcements WHERE mode='demo'")["latest"]
            if latest:
                as_of = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        since = (as_of - timedelta(days=1)).isoformat()
        events = [json.loads(r["payload"]) for r in db.all(
            "SELECT payload FROM announcements WHERE mode=? AND julianday(published_at)>=julianday(?)",
            (mode, since),
        )]
        return {"nudges": reconnect_nudges(load_people(db), events, as_of.date())}

    return routes
