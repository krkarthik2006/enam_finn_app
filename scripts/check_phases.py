"""Produce an isolated P0–P4 review: python scripts/check_phases.py > /tmp/finn-review.json."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app


def main():
    with TemporaryDirectory(prefix="finn-phase-review-") as folder:
        settings = Settings(database_path=Path(folder) / "review.sqlite", glm_api_key="", api_token="", _env_file=None)
        with TestClient(create_app(settings)) as client:
            seeded = client.post("/api/demo/phases")
            seeded.raise_for_status()
            scenario = seeded.json()
            digest = client.get("/api/digest", params={"mode": "demo", "since": scenario["digest_since"]})
            digest.raise_for_status()
            paths = client.get("/api/network/paths?person_id=workflow-cfo").json()
            reconnect = client.get("/api/network/reconnect?mode=demo").json()
            results = next(i["enrichment"]["results"] for i in digest.json()["items"] if i["id"] == scenario["results_event_id"])
            checks = {"forty_synthetic_people": len(client.get("/api/network").json()["contacts"]) == 40,
                      "recorded_cfo_introduction": bool(paths["paths"]),
                      "qoq_revenue_20_percent": results["comparisons"]["qoq"]["revenue"]["percent"] == 20,
                      "reference_mismatch_visible": results["cross_check"]["metrics"]["revenue"]["status"] == "mismatch",
                      "reconnect_nudge": any(n["person_id"] == "network-reconnect" for n in reconnect["nudges"]),
                      "no_live_demo_mix": client.get("/api/digest").json()["items"] == [],
                      "no_model_call_for_digest": not client.app.state.db.all("SELECT * FROM llm_calls")}
            print(json.dumps({"checks": checks, "scenario": scenario, "digest": digest.json(),
                              "cfo_paths": paths, "reconnect": reconnect}, indent=2))
            return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
