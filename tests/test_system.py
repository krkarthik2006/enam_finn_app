from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app


def test_system_status_requires_auth_and_never_exposes_secrets(tmp_path):
    settings = Settings(database_path=tmp_path / "system.sqlite", glm_api_key="secret-provider-key", api_token="secret-api-token", _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/system").status_code == 401
        response = client.get("/api/system", headers={"Authorization": "Bearer secret-api-token"})
        assert response.status_code == 200
        body = response.json()
        assert body["model"]["configured"] and body["authentication_enabled"]
        assert body["documents"] == []
        assert "secret-provider-key" not in response.text and "secret-api-token" not in response.text
        assert {x["name"] for x in body["integrations"]} >= {"Email", "WhatsApp"}
        assert body["demo_as_of"] is None


def test_demo_clock_uses_saved_demo_events_not_live_events(tmp_path):
    settings = Settings(database_path=tmp_path / "clock.sqlite", glm_api_key="", api_token="", _env_file=None)
    with TestClient(create_app(settings)) as client:
        from finn.review import seed_review
        seed_review(client.app.state.db)
        saved = client.app.state.db.one("SELECT MAX(published_at) latest FROM announcements WHERE mode='demo'")["latest"]
        client.app.state.db.execute("INSERT INTO announcements VALUES (?,?,?,?,?,?)",
                                    ("future-live", "INFY", "2099-01-01T00:00:00Z", "results", "live", "{}"))
        assert client.get("/api/system").json()["demo_as_of"] == saved


def test_demo_reconnect_survives_after_seed_day(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from finn.review import seed_review

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2100, 1, 1, tzinfo=timezone.utc)

    settings = Settings(database_path=tmp_path / "nudges.sqlite", glm_api_key="", api_token="", _env_file=None)
    with TestClient(create_app(settings)) as client:
        seed_review(client.app.state.db)
        monkeypatch.setattr("api.network.datetime", Later)
        nudges = client.get("/api/network/reconnect?mode=demo").json()["nudges"]
        assert any(n["person_id"] == "network-reconnect" for n in nudges)
        assert client.get("/api/network/reconnect?mode=live").json()["nudges"] == []
