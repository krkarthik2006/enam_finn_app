# FINN backend

A working backend for the ENAM build challenge. Python/FastAPI handles the API, SQLite stores the data and searchable document chunks, and a configurable GLM adapter produces cited research. No frontend or cloud deployment is included yet.

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --python python3.12
cp .env.example .env
uv run uvicorn finn.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000/docs for the interactive API. Health: http://127.0.0.1:8000/health.

Add `FINN_GLM_API_KEY` in `.env` when ready, then restart. Select a model enabled for your account with `FINN_GLM_MODEL`. The default endpoint follows the [official Z.ai chat-completions API](https://docs.z.ai/api-reference/llm/chat-completion). The base URL is configurable for a different GLM provider. A coding subscription may have different endpoint and usage rules; verify the account before using it for an application. Keys are read by the backend only, never returned to API clients or committed.

With no key, research returns relevant source excerpts with `status=evidence_only`. It does not pretend a generated answer exists. A missing corpus returns `status=needs_sources`.

## Try the complete demo

```sh
curl -X POST http://127.0.0.1:8000/api/demo/seed
curl 'http://127.0.0.1:8000/api/digest?mode=demo&include_routine=true'
curl -X POST http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"TCS","question":"Compare management margin guidance with delivered margins across the available quarters.","mode":"demo"}'
curl 'http://127.0.0.1:8000/api/network/recommendations?symbol=TCS'
curl 'http://127.0.0.1:8000/api/network/recommendations?person_id=demo-arjun'
```

The seed adds an 18-company portfolio only if the portfolio is empty. It adds six fictional contacts, synthetic daily prices and announcements, and synthetic reports/transcripts for TCS, INFY, TITAN plus CDSL, COFORGE and DIXON for off-portfolio research. Repeating the seed updates demo fixtures without duplicating documents or contacts. Real company names do **not** make these financial figures real. `mode=demo` is explicit; live queries never fall back to these records. Synthetic contacts are labelled in recommendations, including when they overlap with live companies.

## API contract

All `/api/*` routes require a bearer token when `FINN_API_TOKEN` is set. No token means local development mode, for one investor, bound to localhost. The schema is also available at `/openapi.json`.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Database health and configuration flags, without secrets |
| `GET / PUT /api/portfolio` | Read or replace the portfolio |
| `GET / PUT /api/alerts/settings` | Price threshold, volume threshold/lookback, material categories |
| `GET /api/digest` | Prioritised filing digest and calculated EOD alerts, with embedded contacts |
| `POST /api/announcements` | Import a filing and classify it using explicit keyword rules |
| `POST /api/prices` | Import completed daily price/volume observations |
| `GET /api/companies/{symbol}/prices` | Stored price history |
| `POST /api/refresh` | Queue live market/filing refresh; returns a run ID |
| `GET /api/refresh`, `GET /api/refresh/{id}` | Inspect refresh history, progress and source failures |
| `GET /api/companies/{symbol}/discover` | Discover annual-report and transcript links via Screener |
| `POST /api/documents` | Ingest an original PDF URL or pasted primary-source text |
| `GET /api/documents` | List indexed documents, optionally by `symbol` and `mode` |
| `DELETE /api/documents/{id}` | Delete document, chunks and cached analysis |
| `POST /api/research` | Source-grounded research with citations and relevant contacts |
| `GET / POST /api/network` | List or create contacts |
| `PUT / DELETE /api/network/{id}` | Update or delete a contact |
| `GET /api/network/recommendations` | Match by `symbol`, `theme`, or a target `person_id` |
| `POST /api/demo/seed` | Seed explicitly synthetic demonstration data |

`since` and `until` on the digest must include timezones; the default is the preceding 24 hours. Routine filings are counted but hidden unless `include_routine=true`. Categories can be overridden on import. Classification and summaries are explicitly labelled as rule-based and filing-title-based, respectively.

### Ingest and research a real company

```sh
curl -X POST http://127.0.0.1:8000/api/refresh \
  -H 'Content-Type: application/json' -d '{"tickers":["TCS"],"days":7}'
curl http://127.0.0.1:8000/api/companies/TCS/discover
```

Discovery returns links; it does not automatically download every report. Select useful annual reports and the latest four quarterly transcripts, confirm their dates, and ingest the originals. Add the exact official IR host to `FINN_DOCUMENT_HOSTS` if necessary. There is no ticker-specific research logic.

Example pasted-source ingestion (replace the illustrative text with actual source material):

```json
{
  "ticker": "TCS",
  "kind": "transcript",
  "title": "Company earnings call, quarter and year",
  "published_on": "2026-10-15",
  "url": "https://official-company-host.example/transcript.pdf",
  "text": "Paste the actual primary-source transcript here, at least 50 characters.",
  "mode": "live"
}
```

Send this to `POST /api/documents`. Omit `text` to download the URL as a PDF instead. For downloaded PDFs, citations preserve page numbers. For pasted text, page is `null`. The caller is responsible for providing authentic primary sources; the service cannot authenticate pasted text. Downloads require HTTPS, an exact allowed host and public DNS addresses; redirects are checked and downloads are limited to 20 MB. OCR and encrypted PDFs are not supported.

Then call `POST /api/research` with `{"ticker":"TCS","question":"What was guided versus delivered?"}`. Each generated finding includes citation IDs pointing to returned source excerpts. Unknown or missing citation IDs and invalid JSON are rejected. This verifies the reference structure, not the truth of every model sentence; investor review remains necessary. A question can be answered only to the extent covered by the indexed corpus and retrieved excerpts.

## How the backend works

```mermaid
flowchart LR
  UI[Future mobile frontend] --> API[FastAPI]
  API --> DB[(SQLite + FTS5)]
  Sources[Yahoo / NSE / original company PDFs] --> Pipeline[Ingestion and parsing]
  Pipeline --> DB
  DB --> Rules[Alert calculations and contact matching]
  Rules --> API
  DB --> Retrieval[Relevant document excerpts]
  Retrieval --> GLM[GLM analysis]
  GLM --> Validation[Citation validation and cache]
  Validation --> API
```

- **Prices:** Yahoo daily chart adapter; today's bar is excluded so an intraday quote is never treated as a completed day. Price alerts compare consecutive stored closes. Volume alerts compare the latest day with the preceding N trading observations, excluding that day, and require the full lookback. Bars are not adjusted for all corporate actions; investigate split-driven alerts.
- **Announcements:** NSE adapter with cookie bootstrap; deterministic deduplication and category rules. A blocked or changed provider yields a visible failure. BSE price suffixes are supported; automatic BSE filings are not yet implemented, so use announcement import for those.
- **Fundamentals:** Screener discovers links, while original PDFs/text supply the research corpus. Parsing and indexing are deterministic. SQLite FTS5 retrieves chunks across documents; no embedding API is needed. Replacing a document atomically updates its search index. No news or broker research is fetched for Pull.
- **Model:** Only research generation calls GLM. No autonomous actions, web tools or contact messaging. The prompt treats documents as untrusted evidence, and source excerpts—not the entire corpus—are sent. Contact profiles are not sent to GLM. Cache keys include the question, retrieved source content, prompt version, model and endpoint. Network suggestions are recalculated on every request.
- **Network:** Explicit employment tickers, expertise tags, recorded connection edges, and temporal employment overlaps. An overlap is not proof of acquaintance. No LinkedIn scraping, name-based identity guessing, or invented second-degree links. Incoming-person profiles must be provided before their relationships can be queried.
- **Refresh:** Manual background jobs, with optional interval polling via `FINN_REFRESH_INTERVAL_SECONDS`. Use one server worker. Job progress is persisted; jobs interrupted by restart are marked accordingly. This is not a distributed durable queue. Scheduling refreshes updates stored data; phone notification delivery is a future frontend/infrastructure task.

## Privacy and deployment boundary

This version stores **one investor's** portfolio and network in one local database. `FINN_API_TOKEN` protects that instance; it is not multi-user authentication. It stores contact names, supplied career/education/expertise, explicit relationship IDs, provenance, notes and optional last-contact dates. Data stays until deleted; contact deletion also removes inbound relationship edges. Document deletion clears research caches. SQLite files and backups may retain deleted bytes until maintenance and backup expiry.

The database is not encrypted at rest by this application. Keep its directory private and use host disk encryption. Before a shared/production deployment, add real authentication and tenant isolation, TLS, rate limits, provider/consent policy checks, retention and backup deletion, a persistent worker queue, monitored source freshness, and appropriate managed storage. None of those cloud choices are required to run locally. Public repositories should contain only code, synthetic fixtures and the lockfile; `.env`, database files and private network data are ignored.

## Validation

```sh
uv run pytest -q
uv run ruff check finn tests scripts
PYTHONPATH=. uv run python scripts/check_sources.py TCS
```

The automated suite uses a temporary real SQLite database and mocked external HTTP responses. It exercises the full demo, live/demo separation, arbitrary-ticker retrieval, document replacement/deletion, exact alert calculations and lookback rules, timezone/deduplication handling, contact relationships/deletion, bearer authentication, URL restrictions, partial refresh failure, model citation validation, cache invalidation and API schema generation.

The read-only source check is separate because external sites can rate-limit, block requests or change response formats. A GLM account/key is required to validate a real paid model request; tests exercise its request/response contract without spending credits.

## Deliberately left for the next stage

The frontend and mobile interaction design; real portfolio source coverage; automatic document selection/refresh; extraction of results tables into verified Revenue/EBITDA/PBT/PAT QoQ/YoY comparisons; incoming-management biographies/entity resolution; advanced financial comparison across four quarters; notification delivery; stronger retrieval evaluation; and production hosting/privacy infrastructure. The current research endpoint can discuss these metrics when they appear in supplied excerpts, but it is not yet a verified financial calculation engine.
