import asyncio
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from finn.alerts import digest, save_announcement, save_prices
from finn.config import Settings
from finn.db import Database
from finn.demo import seed
from finn.documents import extract_pdf, save_document
from finn.models import (
    AlertSettings,
    Announcement,
    Contact,
    Document,
    Mode,
    Portfolio,
    PriceImport,
    Refresh,
    ResearchQuestion,
    normalize_ticker,
)
from finn.network import recommend
from finn.pipeline import run_refresh
from finn.providers import ProviderError, Providers
from finn.research import Research
from finn.scenario import seed_workflow


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    db = Database(settings.database_path)
    providers = Providers(settings)
    research = Research(db, settings)
    security = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        token = settings.api_token.get_secret_value()
        if token and (credentials is None or not secrets.compare_digest(credentials.credentials, token)):
            raise HTTPException(401, "Invalid API token", headers={"WWW-Authenticate": "Bearer"})

    def ticker(value):
        try:
            return normalize_ticker(value)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def enqueue(request: Refresh):
        tickers = request.tickers or [r["ticker"] for r in db.all("SELECT ticker FROM portfolio")]
        if not tickers:
            raise HTTPException(422, "Create a portfolio or provide tickers first")
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        report = {"id": run_id, "status": "queued", "tickers": tickers, "days": request.days, "sources": []}
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT id FROM refresh_runs WHERE finished_at IS NULL").fetchone():
                raise HTTPException(409, "A refresh is already queued or running")
            conn.execute("INSERT INTO refresh_runs VALUES (?,?,NULL,?)", (run_id, now, json.dumps(report)))
        return report

    async def poll():
        while True:
            await asyncio.sleep(settings.refresh_interval_seconds)
            try:
                report = enqueue(Refresh())
                await asyncio.to_thread(
                    run_refresh, db, providers, report["id"], report["tickers"], report["days"]
                )
            except HTTPException:
                continue
            except Exception:
                logging.getLogger(__name__).exception("Scheduled refresh failed")

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        # The prototype runs in a single process. Interrupted jobs are visible, never silently resumed.
        with db.connect() as conn:
            for row in conn.execute(
                "SELECT id,payload FROM refresh_runs WHERE finished_at IS NULL"
            ).fetchall():
                report = json.loads(row["payload"])
                report["status"] = "interrupted"
                conn.execute(
                    "UPDATE refresh_runs SET finished_at=?,payload=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), json.dumps(report), row["id"]),
                )
        if not settings.api_token.get_secret_value():
            logging.getLogger(__name__).warning(
                "Local development mode: API authentication is disabled. Bind to 127.0.0.1."
            )
        task = asyncio.create_task(poll()) if settings.refresh_interval_seconds else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="FINN API",
        version="0.1.0",
        lifespan=lifespan,
        description="Single-investor development backend. Demo and live data are explicitly separated.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.db, app.state.providers, app.state.research = db, providers, research

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/health", tags=["system"])
    def health():
        db.one("SELECT 1")
        return {
            "status": "ok",
            "glm_configured": bool(settings.glm_api_key.get_secret_value()),
            "authentication_enabled": bool(settings.api_token.get_secret_value()),
        }

    protected = [Depends(authorize)]

    @app.post("/api/demo/seed", dependencies=protected, tags=["demo"])
    def demo_seed():
        return seed(db)

    @app.post("/api/demo/workflow", dependencies=protected, tags=["demo"])
    def workflow_seed():
        return seed_workflow(db)

    @app.get("/api/portfolio", dependencies=protected, tags=["portfolio"])
    def get_portfolio():
        return {
            "companies": [
                json.loads(r["payload"]) for r in db.all("SELECT payload FROM portfolio ORDER BY ticker")
            ]
        }

    @app.put("/api/portfolio", dependencies=protected, tags=["portfolio"])
    def put_portfolio(body: Portfolio):
        with db.connect() as conn:
            conn.execute("DELETE FROM portfolio")
            conn.executemany(
                "INSERT INTO portfolio VALUES (?,?)",
                [(c.ticker, c.model_dump_json()) for c in body.companies],
            )
        return body

    @app.get("/api/alerts/settings", dependencies=protected, tags=["push"])
    def get_alert_settings():
        return AlertSettings(**db.setting("alerts", {}))

    @app.put("/api/alerts/settings", dependencies=protected, tags=["push"])
    def put_alert_settings(body: AlertSettings):
        db.set_setting("alerts", body.model_dump())
        return body

    @app.get("/api/digest", dependencies=protected, tags=["push"])
    def get_digest(
        since: datetime | None = None,
        until: datetime | None = None,
        mode: Mode = "live",
        include_routine: bool = False,
    ):
        until = until or datetime.now(timezone.utc)
        since = since or until - timedelta(hours=24)
        if since.tzinfo is None or until.tzinfo is None:
            raise HTTPException(422, "Use timezone-aware timestamps")
        if since >= until or until - since > timedelta(days=366):
            raise HTTPException(422, "Choose a positive window of at most 366 days")
        return digest(
            db, since.astimezone(timezone.utc), until.astimezone(timezone.utc), mode, include_routine
        )

    @app.post("/api/announcements", dependencies=protected, tags=["ingestion"])
    def import_announcement(body: Announcement):
        return save_announcement(db, body)

    @app.post("/api/prices", dependencies=protected, tags=["ingestion"])
    def import_prices(body: PriceImport):
        return save_prices(db, body)

    @app.get("/api/companies/{symbol}/prices", dependencies=protected, tags=["portfolio"])
    def get_prices(symbol: str, mode: Mode = "live", limit: int = Query(90, ge=1, le=365)):
        return {
            "ticker": ticker(symbol),
            "mode": mode,
            "prices": db.all(
                "SELECT day,close,volume FROM prices WHERE ticker=? AND mode=? ORDER BY day DESC LIMIT ?",
                (ticker(symbol), mode, limit),
            ),
        }

    @app.post("/api/refresh", status_code=202, dependencies=protected, tags=["ingestion"])
    def refresh(body: Refresh, background: BackgroundTasks):
        report = enqueue(body)
        background.add_task(run_refresh, db, providers, report["id"], report["tickers"], body.days)
        return report

    @app.get("/api/refresh", dependencies=protected, tags=["ingestion"])
    def refresh_history():
        return {
            "runs": [
                json.loads(r["payload"])
                for r in db.all("SELECT payload FROM refresh_runs ORDER BY started_at DESC LIMIT 20")
            ]
        }

    @app.get("/api/refresh/{run_id}", dependencies=protected, tags=["ingestion"])
    def refresh_status(run_id: str):
        row = db.one("SELECT payload FROM refresh_runs WHERE id=?", (run_id,))
        if not row:
            raise HTTPException(404, "Refresh not found")
        return json.loads(row["payload"])

    @app.get("/api/companies/{symbol}/discover", dependencies=protected, tags=["research"])
    def discover(symbol: str):
        return providers.discover(ticker(symbol))

    @app.post("/api/documents", status_code=201, dependencies=protected, tags=["ingestion"])
    def ingest(body: Document):
        try:
            pages = None
            if not body.text:
                if not body.url:
                    raise ValueError("Provide primary-source text or a PDF URL")
                pages = extract_pdf(providers.download(body.url))
            return save_document(db, body, pages)
        except httpx.HTTPError as exc:
            raise ProviderError("Document download failed") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/documents", dependencies=protected, tags=["research"])
    def list_documents(symbol: str | None = None, mode: Mode = "live"):
        sql, args = "SELECT * FROM documents WHERE mode=?", [mode]
        if symbol:
            sql += " AND ticker=?"
            args.append(ticker(symbol))
        return {"documents": db.all(sql + " ORDER BY published_on DESC", args)}

    @app.delete("/api/documents/{document_id}", dependencies=protected, tags=["ingestion"])
    def delete_document(document_id: str):
        with db.connect() as conn:
            if not conn.execute("SELECT id FROM documents WHERE id=?", (document_id,)).fetchone():
                raise HTTPException(404, "Document not found")
            conn.execute(
                "DELETE FROM chunk_search WHERE id IN (SELECT id FROM chunks WHERE document_id=?)",
                (document_id,),
            )
            conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
            conn.execute("DELETE FROM research_cache")
        return {"deleted": document_id}

    @app.post("/api/research", dependencies=protected, tags=["research"])
    def ask(body: ResearchQuestion):
        if body.person_id and not db.one("SELECT id FROM contacts WHERE id=?", (body.person_id,)):
            raise HTTPException(404, "Person not found")
        return research.answer(body)

    @app.get("/api/network", dependencies=protected, tags=["network"])
    def contacts():
        return {
            "contacts": [
                {"id": r["id"], **json.loads(r["payload"])} for r in db.all("SELECT * FROM contacts")
            ]
        }

    @app.post("/api/network", status_code=201, dependencies=protected, tags=["network"])
    def add_contact(body: Contact):
        identifier = str(uuid.uuid4())
        db.execute("INSERT INTO contacts VALUES (?,?)", (identifier, body.model_dump_json()))
        return {"id": identifier, **body.model_dump(mode="json")}

    @app.put("/api/network/{contact_id}", dependencies=protected, tags=["network"])
    def update_contact(contact_id: str, body: Contact):
        if not db.one("SELECT id FROM contacts WHERE id=?", (contact_id,)):
            raise HTTPException(404, "Contact not found")
        db.execute("UPDATE contacts SET payload=? WHERE id=?", (body.model_dump_json(), contact_id))
        return {"id": contact_id, **body.model_dump(mode="json")}

    @app.delete("/api/network/{contact_id}", dependencies=protected, tags=["network"])
    def delete_contact(contact_id: str):
        with db.connect() as conn:
            if not conn.execute("SELECT id FROM contacts WHERE id=?", (contact_id,)).fetchone():
                raise HTTPException(404, "Contact not found")
            conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
            for row in conn.execute("SELECT id,payload FROM contacts").fetchall():
                person = json.loads(row["payload"])
                person["knows"] = [i for i in person["knows"] if i != contact_id]
                conn.execute("UPDATE contacts SET payload=? WHERE id=?", (json.dumps(person), row["id"]))
        return {"deleted": contact_id}

    @app.get("/api/network/recommendations", dependencies=protected, tags=["network"])
    def network_recommendations(
        symbol: str | None = None, theme: str = Query("", max_length=200), person_id: str | None = None
    ):
        if not any((symbol, theme, person_id)):
            raise HTTPException(422, "Provide symbol, theme or person_id")
        if person_id and not db.one("SELECT id FROM contacts WHERE id=?", (person_id,)):
            raise HTTPException(404, "Person not found")
        return {"matches": recommend(db, ticker(symbol) if symbol else None, theme, person_id)}

    return app


app = create_app()
