import hashlib
import io
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from finn.db import Database
from finn.models import Document


def extract_pdf(content: bytes):
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if len(reader.pages) > 600:
            raise ValueError("Document exceeds 600 pages")
        pages = [(i, p.extract_text() or "") for i, p in enumerate(reader.pages, 1)]
    except PyPdfError as exc:
        raise ValueError(
            "PDF could not be read; supply an unencrypted text PDF or extracted source text"
        ) from exc
    if sum(len(text.strip()) for _, text in pages) < 50:
        raise ValueError("No usable PDF text. Scanned documents need OCR, which is not enabled yet.")
    if sum(len(text) for _, text in pages) > 2_000_000:
        raise ValueError("Extracted document exceeds 2 million characters")
    return pages


def save_document(db: Database, item: Document, pages: list[tuple[int | None, str]] | None = None):
    pages = pages or [(None, item.text)]
    content = "\n".join(text for _, text in pages)
    if len(content.strip()) < 50:
        raise ValueError("Provide at least 50 characters of source text or a downloadable PDF URL")
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    # A source URL (or title for pasted text) identifies a document; re-ingestion replaces its chunks atomically.
    identifier = hashlib.sha256(
        f"{item.mode}|{item.ticker}|{item.kind}|{item.url or item.title}|{item.published_on}".encode()
    ).hexdigest()[:24]
    chunks = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", text).strip()
        for start in range(0, len(text), 1600):
            part = text[start : start + 1900]
            if part.strip():
                chunks.append((f"{identifier}:{len(chunks)}", identifier, len(chunks), page, part))
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM chunk_search WHERE id IN (SELECT id FROM chunks WHERE document_id=?)", (identifier,)
        )
        conn.execute("DELETE FROM chunks WHERE document_id=?", (identifier,))
        conn.execute("DELETE FROM doc_pages WHERE document_id=?", (identifier,))
        conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?)",
            (
                identifier,
                item.ticker,
                item.kind,
                item.mode,
                item.title,
                item.url,
                item.published_on.isoformat() if item.published_on else "",
                content_hash,
            ),
        )
        conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)", chunks)
        conn.executemany("INSERT INTO doc_pages VALUES (?,?,?)", [
            (identifier, page, text) for page, text in pages if page is not None
        ])
        conn.executemany("INSERT INTO chunk_search(id,text) VALUES (?,?)", [(c[0], c[4]) for c in chunks])
    return {
        "id": identifier,
        "ticker": item.ticker,
        "kind": item.kind,
        "mode": item.mode,
        "chunks": len(chunks),
        "content_hash": content_hash,
    }


def retrieve(db: Database, ticker: str, question: str, mode: str, document_ids: list[str] | None = None):
    tokens = list(dict.fromkeys(re.findall(r"[A-Za-z0-9]{3,}", question)))[:30]
    stop = {"the", "and", "what", "how", "this", "company", "explain", "its", "for", "with"}
    query = " OR ".join(f'"{t}"' for t in tokens if t.lower() not in stop)
    fields = """c.id, c.text, c.page, d.id AS document_id, d.title, d.url, d.kind, d.published_on, d.mode"""
    base = f"SELECT {fields} FROM chunks c JOIN documents d ON d.id=c.document_id"
    args = (ticker, mode)
    restriction = ""
    if document_ids is not None:
        if not document_ids:
            return []
        restriction = " AND d.id IN (" + ",".join("?" for _ in document_ids) + ") "
        args = (*args, *document_ids)
    if query:
        rows = db.all(
            base + " JOIN chunk_search s ON s.id=c.id WHERE d.ticker=? AND d.mode=? " + restriction +
            "AND d.kind IN ('annual_report','transcript') "
            "AND chunk_search MATCH ? ORDER BY bm25(chunk_search),d.published_on DESC LIMIT 60",
            (*args, query),
        )
    else:
        rows = []
    # Broad questions such as "what is happening" still need business, financial
    # and risk evidence, rather than only a long annual report's cover pages.
    if not rows:
        for topic in ('"business" OR "products" OR "customers"', '"revenue" OR "net income" OR "cash flows"', '"risk" OR "competition" OR "outlook"'):
            rows.extend(db.all(base + " JOIN chunk_search s ON s.id=c.id WHERE d.ticker=? AND d.mode=? " + restriction +
                "AND d.kind IN ('annual_report','transcript') AND chunk_search MATCH ? ORDER BY bm25(chunk_search) LIMIT 4",
                (*args, topic)))
        rows = list({row['id']: row for row in rows}.values())
    # Keep an excerpt even when none of the usual overview terms appears.
    if not rows:
        rows = db.all(
            base + " WHERE d.ticker=? AND d.mode=? " + restriction + " AND d.kind IN ('annual_report','transcript') "
            "ORDER BY d.published_on DESC,c.position LIMIT 8", args
        )
    # A long report can occupy all global search hits. Give each selected report/call
    # one relevant business, financial or guidance excerpt before filling the context.
    for document_id in document_ids or []:
        if any(row["document_id"] == document_id for row in rows):
            continue
        rows.extend(db.all(
            base + " JOIN chunk_search s ON s.id=c.id WHERE d.ticker=? AND d.mode=? AND d.id=? "
            "AND d.kind IN ('annual_report','transcript') AND chunk_search MATCH ? ORDER BY bm25(chunk_search) LIMIT 1",
            (ticker, mode, document_id, '"guidance" OR "outlook" OR "revenue" OR "business" OR "risk"'),
        ))
    # Give multiple periods a chance to appear instead of filling context with one long annual report.
    selected, remaining, seen = [], [], set()
    for row in rows:
        if row["document_id"] not in seen and len(selected) < 12:
            selected.append(row)
            seen.add(row["document_id"])
        else:
            remaining.append(row)
    selected.extend(remaining[: 12 - len(selected)])
    return [{"citation_id": r.pop("id"), **r, "published_on": r["published_on"] or None} for r in selected]
