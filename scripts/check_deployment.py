"""Check the hosted demo without printing credentials or changing investor settings.

Run from the repository root. The public demo requires no password or cookies.
"""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="https://finn-investor-workspace.vercel.app")
    parser.add_argument("--backend", default="https://finn-api-production-e5f13f8d.up.railway.app")
    parser.add_argument("--report", type=Path, default=Path("/private/tmp/finn-hosted-check.json"))
    args = parser.parse_args()
    with httpx.Client(timeout=240) as client:
        assert client.get(args.web).status_code == 200, "Frontend unavailable"
        assert client.get(args.web + "/api/system").status_code == 200, "Public API unavailable"
        assert client.get(args.backend + "/health").json()["status"] == "ok", "Backend unhealthy"
        assert client.get(args.backend + "/api/system").status_code == 401, "Backend is unprotected"
        system = client.get(args.web + "/api/system").json()
        assert system["model"]["configured"] and system["authentication_enabled"]
        assert system["counts"]["documents"].get("live", 0) > 0, "Real documents missing"
        assert any(doc["mode"] == "live" and doc["pages"] > 0 for doc in system["documents"])
        briefs = []
        for _ in range(2):
            response = client.post(args.web + "/api/research/MOCKIT/brief", json={
                "question": "Evaluate FY2027 Q2 EBITDA margin guidance versus actual, citing the specific source evidence.",
                "mode": "demo", "prepare_sources": False,
            })
            assert response.status_code == 200, "Research request failed"
            events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            assert events[-1]["type"] == "result", "Research stream failed"
            brief = events[-1]["data"]
            assert brief["status"] == "analysed", "Expected model-generated analysis"
            comparison = next(g for g in brief["guidance"] if g["period"] == "FY2027 Q2")
            assert comparison["actual"] == 20 and comparison["delta"] == -2, "Incorrect guidance comparison"
            source_ids = {source["citation_id"] for source in brief["sources"]}
            assert all(f["citation_ids"] and set(f["citation_ids"]) <= source_ids
                       for section in brief["sections"] for f in section["findings"]), "Invalid citations"
            briefs.append({"cached": brief["cached"], "sources": len(source_ids), "delta": comparison["delta"]})
        assert briefs[-1]["cached"], "Repeated research should use its cache"
        report = {"web": args.web, "backend": args.backend, "counts": system["counts"],
                  "demo_as_of": system["demo_as_of"], "research_runs": briefs,
                  "checks": "Password-free access, backend protection, persistent corpus, streaming, citations, guidance math and cache passed"}
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
