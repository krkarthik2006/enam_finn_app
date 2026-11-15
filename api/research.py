import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import Field

from api.schemas import ResearchIdentity
from finn.brief import build_brief
from finn.corpus import prepare_corpus
from finn.models import Input, Mode, normalize_ticker
from finn.providers import ProviderError
from ingest.company import resolve_company


class BriefRequest(Input):
    question: str = Field(default="Explain the business, financial trajectory, management guidance delivery, positives and risks.", min_length=5, max_length=2000)
    mode: Mode = "live"
    use_model: bool = True
    prepare_sources: bool = True


def router(db, providers):
    routes = APIRouter()

    @routes.post("/api/research/{symbol}/brief", tags=["research"])
    @routes.post("/research/{symbol}", tags=["research"])
    def brief(symbol: str, body: BriefRequest):
        query = symbol.strip()
        if not 1 <= len(query) <= 120 or not re.fullmatch(r"[\w &.,:()'-]+", query):
            raise HTTPException(422, 'Enter a company name or ticker.')
        if body.mode == 'demo':
            try:
                query = normalize_ticker(query)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        def stream():
            def event(kind, data):
                return json.dumps({"type": kind, "data": data}) + "\n"
            yield event("progress", "Checking indexed primary sources")
            corpus = {"gaps": []}
            try:
                company = None
                symbol = query
                if body.mode == 'live':
                    company = resolve_company(db, providers, query, fetch=body.prepare_sources)
                    symbol = company['id']
                if body.mode == "live" and body.prepare_sources:
                    yield event("progress", "Discovering annual report, transcripts and financial tables")
                    corpus = prepare_corpus(db, providers, symbol, company)
                yield event("progress", "Retrieving source excerpts and checking guidance against delivered results")
                result = build_brief(db, providers.settings, symbol, body.question, body.mode, body.use_model)
                result["gaps"] = list(dict.fromkeys(result["gaps"] + corpus["gaps"]))
                if company:
                    result.update(ResearchIdentity(ticker=company['ticker'], company_id=company['id'],
                                                  company_name=company['name'], market=company['market']).model_dump())
                yield event("result", result)
            except (ProviderError, ValueError) as exc:
                yield event("error", str(exc))
        return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})

    @routes.get("/api/documents/{document_id}/pages/{page}", tags=["research"])
    def source_page(document_id: str, page: int):
        row = db.one("SELECT p.page,p.text,d.title,d.url,d.mode FROM doc_pages p JOIN documents d ON d.id=p.document_id "
                     "WHERE p.document_id=? AND p.page=?", (document_id, page))
        if not row:
            raise HTTPException(404, "Source page not found; pasted text has no page number")
        return row

    return routes
