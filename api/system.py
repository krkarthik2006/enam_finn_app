"""Operational information for the investor's review; never returns credentials."""
import json

from fastapi import APIRouter

from api.schemas import SystemStatus


def router(db, settings):
    routes = APIRouter()

    @routes.get("/api/system", tags=["system"], response_model=SystemStatus)
    def status():
        counts = {}
        for table in ("announcements", "documents", "financials", "prices"):
            counts[table] = {r["mode"]: r["n"] for r in db.all(f"SELECT mode,COUNT(*) n FROM {table} GROUP BY mode")}
        return {
            "status": "ok", "model": {"configured": bool(settings.glm_api_key.get_secret_value()), "name": settings.glm_model},
            "authentication_enabled": bool(settings.api_token.get_secret_value()), "counts": counts,
            "demo_as_of": db.one("SELECT MAX(published_at) latest FROM announcements WHERE mode='demo'")["latest"],
            "documents": db.all("SELECT d.id,d.ticker,d.kind,d.mode,d.title,d.url,d.published_on,"
                                "(SELECT COUNT(*) FROM doc_pages p WHERE p.document_id=d.id) pages "
                                "FROM documents d ORDER BY d.published_on DESC LIMIT 100"),
            "refresh_runs": [json.loads(r["payload"]) for r in db.all("SELECT payload FROM refresh_runs ORDER BY started_at DESC LIMIT 5")],
            "integrations": [{"name": "Primary documents", "status": "configured", "detail": "Company reports, call transcripts and Screener tables; availability is checked per request."},
                             {"name": "Network", "status": "synthetic", "detail": "Professional profiles and relationships are fictional for review."},
                             {"name": "Email", "status": "not_connected", "detail": "Not implemented yet."},
                             {"name": "WhatsApp", "status": "not_connected", "detail": "Not implemented yet."}],
        }

    return routes
