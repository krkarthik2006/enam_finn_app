import json

from fastapi import APIRouter, HTTPException

from engine.financials import compare_records, save_financial
from finn.models import FinancialRecord, Mode, normalize_ticker


def router(db):
    routes = APIRouter()

    @routes.post("/api/financials", tags=["ingestion"], status_code=201)
    def import_financial(body: FinancialRecord):
        result = save_financial(db, body)
        from finn.enrichment import refresh_cards
        refresh_cards(db)
        return result

    @routes.get("/api/companies/{symbol}/financials", tags=["portfolio"])
    def financials(symbol: str, mode: Mode = "live"):
        try:
            symbol = normalize_ticker(symbol)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        records = [FinancialRecord(**json.loads(r["payload"])) for r in db.all(
            "SELECT payload FROM financials WHERE ticker=? AND mode=? ORDER BY period_end DESC",
            (symbol, mode),
        )]
        return {"ticker": symbol, "mode": mode, "records": [r.model_dump(mode="json") for r in records],
                "comparisons": compare_records(records[0], records) if records else {}}

    return routes
