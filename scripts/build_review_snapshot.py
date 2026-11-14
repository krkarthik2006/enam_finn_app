"""Publish only freshly seeded fictional data; never export a user's database."""
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from finn.brief import build_brief
from finn.config import Settings
from finn.main import create_app
from finn.review import REVIEW_TICKERS, seed_review

QUESTION = "Explain the business, financial trajectory, management guidance delivery, positives and risks."


def main():
    with TemporaryDirectory(prefix="finn-public-demo-") as folder:
        settings = Settings(database_path=Path(folder) / "public.sqlite", api_token="")
        if not settings.glm_api_key.get_secret_value():
            raise SystemExit("Configure the model key before generating the review snapshot")
        with TestClient(create_app(settings)) as client:
            db = client.app.state.db
            scenario = seed_review(db)
            contacts = client.get("/api/network").json()["contacts"]
            assert len(contacts) == 40 and all(p["provenance"] == "synthetic" for p in contacts)
            snapshot = {"generated_at": datetime.now(timezone.utc).isoformat(), "scenario": scenario,
                        "portfolio": client.get("/api/portfolio").json()["companies"], "contacts": contacts,
                        "digest": client.get("/api/digest", params={"mode": "demo", "since": scenario["digest_since"], "include_routine": True}).json(),
                        "investor": client.get("/api/network/investor").json(),
                        "settings": client.get("/api/alerts/settings").json(),
                        "nudges": client.get("/api/network/reconnect?mode=demo").json()["nudges"],
                        "paths": {p["id"]: client.get("/api/network/paths", params={"person_id": p["id"]}).json()["paths"] for p in contacts},
                        "briefs": {}}
            for ticker in REVIEW_TICKERS:
                print("Generating source-cited demo brief:", ticker, flush=True)
                snapshot["briefs"][ticker] = build_brief(db, settings, ticker, QUESTION, "demo")
            encoded = json.dumps(snapshot, indent=2)
            assert settings.glm_api_key.get_secret_value() not in encoded
            Path("web/public/demo.json").write_text(encoded + "\n")
            print("Saved five real-model briefs using fictional source documents; no credentials or private profiles exported.")


if __name__ == "__main__":
    main()
