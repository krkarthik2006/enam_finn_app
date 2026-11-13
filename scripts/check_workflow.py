"""Run the fictional workflow in an isolated database; optionally call the configured model."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from finn.config import Settings
from finn.main import create_app


def run_workflow(client):
    scenario_response = client.post("/api/demo/workflow")
    scenario_response.raise_for_status()
    scenario = scenario_response.json()
    digest = client.get("/api/digest", params={"mode": "demo"})
    digest.raise_for_status()
    research_response = client.post("/api/research", json=scenario["research_request"])
    research_response.raise_for_status()
    research = research_response.json()
    event = next(i for i in digest.json()["items"] if i["id"] == scenario["announcement_id"])
    expected = set(scenario["expected_contacts"].values())
    checks = {
        "push_selects_all_three_contacts": {c["contact_id"] for c in event["network"]} == expected,
        "pull_selects_all_three_contacts": {c["contact_id"] for c in research["network"]} == expected,
        "retrieves_q1_and_q2": all(
            any(period in s["title"] for s in research["sources"]) for period in ("Q1", "Q2")
        ),
        "unrelated_contact_excluded": all(
            c["contact_id"] != "workflow-unrelated" for c in research["network"]
        ),
        "model_analysis_returned": research["status"] == "analysed",
    }
    return {"scenario": scenario, "checks": checks, "push": event, "pull": research}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="Use the configured GLM account (may incur usage)")
    args = parser.parse_args()
    original_client = httpx.Client
    captured = []

    def mock_model(request):
        payload = json.loads(request.content)
        captured.append(payload)
        evidence = json.loads(payload["messages"][1]["content"])["excerpts"]
        q1 = next(e for e in evidence if "Q1 transcript" in e["title"])
        q2 = next(e for e in evidence if "Q2 transcript" in e["title"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "findings": [{
                "text": "Synthetic FY2026 Q2 EBITDA margin was 20% versus Q1 guidance of 22%, "
                        "a shortfall of 2 percentage points. Management cited delayed customer "
                        "approvals and higher hiring costs.",
                "citation_ids": [q1["citation_id"], q2["citation_id"]],
            }],
            "gaps": ["No numerical Q3 guidance was supplied."],
        })}}]})

    with TemporaryDirectory(prefix="finn-workflow-") as folder:
        settings = Settings(
            database_path=Path(folder) / "workflow.sqlite", api_token="", refresh_interval_seconds=0,
            **({} if args.live_model else {"glm_api_key": "mock-key", "_env_file": None}),
        )
        if args.live_model and not settings.glm_api_key.get_secret_value():
            parser.error("--live-model requires FINN_GLM_API_KEY in the environment or .env")
        with TestClient(create_app(settings)) as client:
            if args.live_model:
                result = run_workflow(client)
            else:
                with patch("finn.research.httpx.Client", lambda **kw: original_client(
                    transport=httpx.MockTransport(mock_model), **kw,
                )):
                    result = run_workflow(client)
                result["checks"]["trace_matches_actual_model_request"] = (
                    captured == [result["pull"]["trace"]["model_request"]]
                )
    result["model_execution"] = "live_configured_provider" if args.live_model else "mocked_http_response"
    result["review_required"] = (
        "Mock output is scripted: it validates wiring, not model reasoning. "
        "For a live run, review whether each finding is supported by its cited excerpts."
    )
    print(json.dumps(result, indent=2))
    return 0 if all(result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
