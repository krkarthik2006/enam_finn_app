"""The new sectioned Pull contract is exercised against the actual configured model."""
import json
import os

import pytest

from finn.brief import build_brief
from finn.config import Settings
from finn.db import Database
from finn.documents import save_document
from finn.models import Document
from finn.review import seed_review

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.getenv("FINN_RUN_LIVE_TESTS") != "1", reason="Enable real-model acceptance")]


def test_live_sectioned_brief_cache_grounding_and_contact_refresh(tmp_path):
    settings = Settings(database_path=tmp_path / "brief.sqlite")
    assert settings.glm_api_key.get_secret_value()
    db = Database(settings.database_path)
    db.initialize()
    seed_review(db)
    question = "Explain the business and compare FY2027 Q2 EBITDA margin guidance with delivered outcomes."
    first = build_brief(db, settings, "MOCKIT", question, "demo")
    assert first["status"] == "analysed"
    assert first["coverage"] == {"documents": 5, "transcripts": 4, "annual_reports": 1, "retrieved_excerpts": 5}
    ids = {s["citation_id"] for s in first["sources"]}
    for section in first["sections"]:
        for finding in section["findings"]:
            assert set(finding["citation_ids"]) <= ids
    comparison = next(r for r in first["guidance"] if r["period"] == "FY2027 Q2")
    assert comparison["actual"] == 20 and comparison["delta"] == -2
    count = db.one("SELECT COUNT(*) n FROM llm_calls WHERE status='completed'")["n"]
    second = build_brief(db, settings, "MOCKIT", question, "demo")
    assert second["cached"] and count == db.one("SELECT COUNT(*) n FROM llm_calls WHERE status='completed'")["n"]
    assert first["network"]
    db.execute("DELETE FROM contacts WHERE owner_id=?", (db.owner_id,))
    assert not build_brief(db, settings, "MOCKIT", question, "demo")["network"]
    assert count == db.one("SELECT COUNT(*) n FROM llm_calls WHERE status='completed'")["n"]
    # A company absent from all demo lists works using its own supplied primary evidence.
    save_document(db, Document(ticker="UNSEEN", mode="demo", kind="annual_report", title="Unseen FY2026 annual report",
                               text="Fictional company Unseen supplies subscription software to factories. FY2026 consolidated revenue was INR 700 crore. Its main reported risk is a dependence on one customer. No EBITDA guidance or actual margin was supplied."))
    unseen = build_brief(db, settings, "UNSEEN", "Describe the business, revenue and risks; is EBITDA margin available?", "demo")
    assert unseen["status"] == "analysed" and unseen["guidance"] == []
    assert unseen["coverage"]["documents"] == 1
    assert all(s["title"].startswith("Unseen") for s in unseen["sources"])
    (tmp_path / "observations.json").write_text(json.dumps({"first": first, "cached": second, "unseen": unseen}, indent=2))
