"""Import a bundled, allowlisted public-source corpus without replacing investor data."""
import gzip
import json
from pathlib import Path

COLUMNS = {
    "announcements": "id,ticker,published_at,category,mode,payload",
    "prices": "ticker,day,mode,close,volume",
    "financials": "id,ticker,period_end,frequency,source_type,mode,payload",
    "companies": "ticker,payload",
    "documents": "id,ticker,kind,mode,title,url,published_on,content_hash",
    "chunks": "id,document_id,position,page,text",
    "doc_pages": "document_id,page,text",
}


def bootstrap(db, path=None):
    path = path or Path(__file__).with_name("public_sources.json.gz")
    if db.setting("public_sources_v1", False) or not path.exists():
        return
    bundle = json.loads(gzip.decompress(path.read_bytes()))
    if bundle["version"] != 1 or set(bundle["tables"]) != set(COLUMNS):
        raise ValueError("Unrecognised public-source bundle")
    with db.connect() as conn:
        for table, columns in COLUMNS.items():
            names = columns.split(",")
            rows = bundle["tables"][table]
            if any("mode" in row and row["mode"] != "live" for row in rows):
                raise ValueError("Bootstrap contains non-public review records")
            conn.executemany(f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({','.join('?' for _ in names)})",
                             [tuple(row[name] for name in names) for row in rows])
        conn.execute("INSERT INTO chunk_search(id,text) SELECT c.id,c.text FROM chunks c "
                     "WHERE NOT EXISTS (SELECT 1 FROM chunk_search s WHERE s.id=c.id)")
    # Add this verified public company without replacing the investor's other picks.
    db.execute("INSERT OR IGNORE INTO portfolio VALUES (?,?)", ("INFY", json.dumps({"ticker": "INFY", "name": "Infosys", "sector": "IT services"})))
    from finn.enrichment import refresh_cards
    refresh_cards(db)
    db.set_setting("public_sources_v1", True)
