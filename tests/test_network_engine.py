import json
import sqlite3
from datetime import date

from fastapi.testclient import TestClient

from api.network import investor, load_people
from engine.network import (
    best_contact_for,
    expertise_map,
    paths_to,
    reconnect_nudges,
    resolve_person,
    study_overlap,
    work_overlap,
)
from finn.config import Settings
from finn.db import Database
from finn.main import create_app
from finn.mock_network import seed_network


def network(tmp_path):
    db = Database(tmp_path / "network.sqlite")
    db.initialize()
    seed_network(db)
    return db, load_people(db)


def test_planted_cfo_overlap_and_recorded_introduction(tmp_path):
    db, people = network(tmp_path)
    by_id = {p["id"]: p for p in people}
    overlap = work_overlap(by_id["workflow-connector"], by_id["workflow-cfo"], date(2026, 11, 13))
    assert overlap[0]["years"] >= 2
    assert not overlap[0]["acquaintance_verified"]
    paths = paths_to(people, investor(db), "workflow-cfo")
    assert paths[0]["person_ids"] == ["investor-local", "workflow-connector", "workflow-cfo"]
    by_id["workflow-connector"]["knows"] = []
    assert paths_to(people, investor(db), "workflow-cfo") == []


def test_supplier_and_education_stories(tmp_path):
    db, people = network(tmp_path)
    by_id = {p["id"]: p for p in people}
    supplier = next(p for p in best_contact_for(people, "SRF") if p["person_id"] == "network-supplier")
    assert supplier["relationships"] == [{"ticker": "SRF", "kind": "supplier"}]
    overlap = study_overlap(by_id["network-peer"], by_id["network-promoter"])
    assert overlap[0]["attendance_overlap_verified"]
    assert (overlap[0]["start_year"], overlap[0]["end_year"]) == (2008, 2011)
    assert not overlap[0]["acquaintance_verified"]
    assert paths_to(people, investor(db), "network-promoter")[0]["person_ids"] == [
        "investor-local", "network-peer", "network-promoter",
    ]


def test_reconnect_story_and_expertise(tmp_path):
    _, people = network(tmp_path)
    events = [{"id": "results-1", "ticker": "TCS", "category": "results"}]
    nudges = reconnect_nudges(people, events, date(2026, 11, 13))
    assert [n["person_id"] for n in nudges] == ["network-reconnect"]
    assert nudges[0]["days_since_contact"] >= 270
    assert "workflow-expert" in {p["person_id"] for p in expertise_map(people, "IT services operating margins")}


def test_name_resolution_requires_employer_and_time(tmp_path):
    _, people = network(tmp_path)
    profile = {"name": "Ms. R. Sen", "roles": [{"company": "Harbor Finance", "ticker": "HARBOR",
                                               "start_year": 2017, "end_year": 2020}]}
    match = resolve_person(profile, people)[0]
    assert match["person_id"] == "workflow-cfo" and match["confidence"] >= 0.7
    profile["name"] = "Dr Riya Sen"
    profile["roles"] = []
    assert resolve_person(profile, people)[0]["status"] == "possible_match"
    profile["name"] = "Rohan Sen"
    assert resolve_person(profile, people) == []


def test_unknown_education_dates_and_nonoverlapping_dates():
    a = {"education": ["IIT Delhi"]}
    b = {"education": [{"institution": "IIT Delhi", "start_year": 2007, "end_year": 2011}]}
    assert not study_overlap(a, b)[0]["attendance_overlap_verified"]
    a["education"] = [{"institution": "IIT Delhi", "start_year": 1990, "end_year": 1994}]
    assert study_overlap(a, b) == []


def test_contact_owner_migration_and_api_isolation(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE contacts(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        conn.execute("INSERT INTO contacts VALUES (?,?)", ("old", json.dumps({"name": "Existing user contact"})))
    local = Database(path)
    local.initialize()
    assert local.one("SELECT owner_id FROM contacts WHERE id='old'")["owner_id"] == "local"
    settings = Settings(database_path=path, owner_id="other", glm_api_key="", api_token="", _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/network").json()["contacts"] == []
        assert client.get("/api/network/paths?person_id=old").status_code == 404
        assert client.delete("/api/network/old").status_code == 404
        assert client.put("/api/network/old", json={"name": "Overwrite"}).status_code == 404
        assert client.post("/api/network", json={"name": "Owner two"}).status_code == 201
    assert local.one("SELECT payload FROM contacts WHERE id='old'")["payload"] == json.dumps({"name": "Existing user contact"})


def test_synthetic_seed_is_owner_scoped_and_preserves_changes(tmp_path):
    db, people = network(tmp_path)
    assert len(people) == 40
    first = people[0]
    db.execute("UPDATE contacts SET payload=? WHERE id=? AND owner_id=?", (
        json.dumps({**first, "notes": "User edit"}), first["id"], db.owner_id,
    ))
    seed_network(db)
    assert len(load_people(db)) == 40
    assert next(p for p in load_people(db) if p["id"] == first["id"])["notes"] == "User edit"
    other = Database(db.path, "other")
    seed_network(other)
    assert len(load_people(other)) == 40
    assert not {p["id"] for p in load_people(db)} & {p["id"] for p in load_people(other)}
