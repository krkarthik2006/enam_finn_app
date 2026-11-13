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

Add your Hyde-issued key as `FINN_GLM_API_KEY` in `.env`, then restart. The current working baseline uses `FINN_GLM_BASE_URL=https://inference.hyde.tech/v1` and `FINN_GLM_MODEL=hyde/glm-5.3-flash`, following the [Hyde quickstart](https://inference.hyde.tech/docs/quickstart). Hyde keys must be sent to the Hyde gateway. FINN has no GLM-only restriction: providers/models per task, including smaller models for efficiency, will be decided with the user after workflow validation (see PLAN.md). The existing adapter accepts OpenAI-compatible chat-completions APIs; other API formats will need an adapter. Keys are read by the backend only, never returned to API clients or committed.

With no key, research returns relevant source excerpts with `status=evidence_only`. It does not pretend a generated answer exists. A missing corpus returns `status=needs_sources`.

## Review P0–P4

The supplied plan is implemented incrementally on the existing backend. Next.js stays in P6;
model selection per task stays undecided. Existing /api routes remain available.

Create an isolated review without changing your database or spending model tokens:

```sh
PYTHONPATH=. uv run python scripts/check_phases.py > /tmp/finn-review.json
```

The JSON includes a ranked digest, CFO introduction paths, financial comparisons, a deliberately
mismatched synthetic reference and a reconnect nudge. All 40 demo people, histories and financial
examples are fictional. For interactive review, start the server, call `POST /api/demo/phases`
(prefer a fresh demo database), then use `/docs`:

- `GET /api/digest?mode=demo` — management, results and material-event cards; routine filings collapse.
- `GET /api/network/paths?person_id=workflow-cfo` — recorded introduction; overlaps alone are not edges.
- `GET /api/network/expertise?theme=IT%20services` and `/api/network/reconnect?mode=demo`.
- `POST /api/announcements/{id}/enrich` — explicitly request original filing extraction/model fallback.
- `GET /api/companies/MOCKIT/financials?mode=demo` and `/api/usage`.

The real portfolio is separate: `data/mock/portfolio.json` records a 90-day scan of all 100
official Nifty 100 constituents, 18 selections, four off-portfolio research candidates, dated
source links and coverage. Its `mode=live` records public events, not mock financial figures.
It does not automatically replace an existing investor portfolio.

```sh
python -m ingest.portfolio --days 90
python -m ingest.all --tickers TCS INFY --days 90 --fundamentals
python -m ingest.all --tickers TCS INFY --days 90 --fundamentals --offline
```

Ingestion is repeatable and reports failures and fallback provenance. Public responses and
original PDFs live under `data/cache/live`; six dated TCS/INFY snapshots ship under
`data/cache/demo_sources`. Cached data retains its original timestamp. Date-window filings
require a matching saved request; uncached windows fail visibly. BSE codes come from Screener's
BSE links. Live BSE access failed during verification; the explicit NSE fallback succeeded.
Use `--document-manifest path.json` for selected documents with confirmed dates. Add `--enrich`
(or refresh JSON `enrich=true`) when model extraction is wanted; routine refreshes don't spend
model tokens by default.

Quarterly/annual financials share one typed table. Growth calculations require compatible
periods, basis, currency and units; missing quarters, absent metrics and nonpositive bases are
flagged. Operating profit is never relabelled EBITDA. Recognised PDF statements are parsed in
code; other layouts use a strict model schema with validated source-line citations and numeric
anchors. Compatible metric fragments are merged; conflicting values are rejected before caching.
Original page numbers and verbatim rows remain available for review. The original 22-page TCS
filing was compared with Screener: consolidated revenue/PBT/PAT matched; EBITDA was unavailable.
This is representative validation, not support for every PDF layout. OCR and ZIP attachments
remain unsupported.

All model calls pass through `engine/llm.py`; versioned prompts live in `engine/prompts/`.
It caches validated output, retries transient failures once and records tokens/latency without
keys or contact profiles. `/api/usage` leaves monetary cost unset until model choices/pricing
are supplied. Digest enrichment is computed at ingestion and refreshed on relevant writes;
viewing the digest makes no model calls. `FINN_OWNER_ID` scopes contact storage and queries;
it is server configuration, not multi-user authentication or full tenant isolation.

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

### Inspect one complete fictional workflow

Run this without a server or API key:

```sh
PYTHONPATH=. uv run python scripts/check_workflow.py > /tmp/finn-workflow.json
```

This uses a temporary database, exercises the actual API and document retrieval, and mocks only
the model HTTP response. The JSON contains the Push event, retrieved excerpts, model request,
cited answer, chosen contacts with scores/reasons, and pass/fail checks. It does not change your
portfolio or local database. The scripted answer checks wiring, not model reasoning.

The fictional company `MOCKIT` has Q1 guidance for Q2 EBITDA margin of 22% and Q2 delivered margin
of 20%. Its appointment filing links to a fictional incoming CFO. Both the filing and research
select Ananya (industry expert), Vikram (current employee), and Neha (recorded connection to the CFO).
An unrelated agriculture contact is excluded. Vikram's employment overlap is explicitly unverified.
The person ID is supplied in the fixture; automatic identification of executives is still future work.

To run the same scenario against your configured GLM account, with possible model usage charges:

```sh
PYTHONPATH=. uv run python scripts/check_workflow.py --live-model > /tmp/finn-workflow-live.json
```

The live run also uses a temporary database. Review whether its findings accurately cite the
retrieved Q1/Q2 excerpts, distinguish guidance from actual performance, and explain missing Q3
guidance. Citation-ID checks alone do not establish factual accuracy.

To explore the scenario in the running API, call `POST /api/demo/workflow`. This adds the fictional
company to your portfolio and seeds its contacts/documents; repeated calls preserve contact edits
and replace the scenario's filing. Send its returned `research_request` to `POST /api/research`,
and read `GET /api/digest?mode=demo` for the Push event.

Research accepts an optional `person_id` for recorded relationships and `include_trace=true` to
return the prepared model request, retrieved document/chunk counts, and whether a model call
actually happened. Evidence-only and cached answers have `model_called=false`. The prepared
request contains the question and document excerpts, without API credentials or contact profiles.
Network selection remains rule-based and returns `match_types`, scores and reasons independently
of model generation. Announcement imports can supply `subject_person_id` to use the same person
context in Push suggestions.

### Routes

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
| `POST /api/demo/workflow` | Seed a focused fictional Push/Pull/network scenario and return its research request |

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
- **Announcements:** BSE adapter when a verified code is available, with NSE fallback and recorded source failures; deterministic deduplication and category rules. Original filing URLs are retained. ZIP attachments remain unsupported.
- **Fundamentals:** Screener discovers links, while original PDFs/text supply the research corpus. Parsing and indexing are deterministic. SQLite FTS5 retrieves chunks across documents; no embedding API is needed. Replacing a document atomically updates its search index. No news or broker research is fetched for Pull.
- **Model:** Research and explicitly requested filing extraction use the shared gateway. Recognised financial statements, graph operations and digest reads use no model. Prompts treat source text as untrusted evidence. Contact profiles are not sent to the model. Cache keys include input, prompt version, model and endpoint.
- **Network:** Explicit employment tickers, expertise tags, recorded connection edges, and temporal employment overlaps. An overlap is not proof of acquaintance. No LinkedIn scraping, name-based identity guessing, or invented second-degree links. Incoming-person profiles must be provided before their relationships can be queried.
- **Refresh:** Manual background jobs, with optional interval polling via `FINN_REFRESH_INTERVAL_SECONDS`. Use one server worker. Job progress is persisted; jobs interrupted by restart are marked accordingly. This is not a distributed durable queue. Scheduling refreshes updates stored data; phone notification delivery is a future frontend/infrastructure task.

## Privacy and deployment boundary

This version stores **one investor's** portfolio and network in one local database. `FINN_API_TOKEN` protects that instance; it is not multi-user authentication. It stores contact names, supplied career/education/expertise, explicit relationship IDs, provenance, notes and optional last-contact dates. Data stays until deleted; contact deletion also removes inbound relationship edges. Document deletion clears research caches. SQLite files and backups may retain deleted bytes until maintenance and backup expiry.

The database is not encrypted at rest by this application. Keep its directory private and use host disk encryption. Before a shared/production deployment, add real authentication and tenant isolation, TLS, rate limits, provider/consent policy checks, retention and backup deletion, a persistent worker queue, monitored source freshness, and appropriate managed storage. None of those cloud choices are required to run locally. Public repositories should contain only code, synthetic fixtures and the lockfile; `.env`, database files and private network data are ignored.

## Validation

```sh
uv run pytest -q
uv run ruff check finn engine ingest api tests scripts
PYTHONPATH=. uv run python scripts/check_sources.py TCS
```

The default suite uses a temporary real SQLite database and mocked external HTTP responses. It checks exact alert calculations, lookback rules, live/demo separation, document replacement/deletion, contact relationships, authentication, URL restrictions, partial refresh failure, invalid citations, cache invalidation and API schemas. These checks isolate backend behaviour; they do not prove that a live model follows the prompt.

Run the real-model acceptance suite explicitly (uses the current `.env` provider/model and spends tokens):

```sh
FINN_RUN_LIVE_TESTS=1 uv run pytest -m live -q --junitxml=/tmp/finn-live-results.xml
```

The eight cases check two different margin misses and a beat, correct source-linked percentages
and percentage-point differences, stated causes, Q1/Q2 retrieval, unrelated-company exclusion,
the three expected contacts and relationship types, missing forecasts, cache reuse, fresh analysis
after source replacement, document prompt injection, and no model call when sources are absent.
The Push case also checks source-cited extraction into a results card and repeated-call caching.
The live tests use the actual API, SQLite, retrieval and configured model HTTP calls; no model
response is mocked. A missing key or provider/schema error fails an explicitly enabled live run.
Each case writes `observations.json` with imported fixtures and research requests/responses to its
pytest temporary directory; `--basetemp` can select a fresh directory for inspection. Credentials
and HTTP auth headers are excluded. The XML contains test outcomes.

These are bounded acceptance checks against known synthetic facts, not a universal factuality
judge or evidence of reliable real-company ingestion. Assertions accept ordinary phrasing variants;
historical figures are allowed in missing-evidence answers when supported by their cited sources.
Review the saved answers and add cases from real documents before claiming broader reliability.
Providers used for research must support strict `json_schema` structured output. Invalid output
and unknown citations still fail validation. Changing the output contract invalidates old analysis caches.

The read-only source check is separate because external sites can rate-limit, block requests or change response formats. Default tests skip the paid live suite; report offline and live results separately.

GitHub Actions runs the backend tests and lint on every push and pull request, using Python 3.11
and 3.12 with the committed lockfile. See [Backend tests](https://github.com/krkarthik2006/enam_finn_app/actions/workflows/tests.yml).
To run the real-model suite, select **Run workflow** and enable **run_live**. It runs after the
backend checks pass. Configure the repository Actions secret `FINN_GLM_API_KEY`; repository
variables `FINN_GLM_BASE_URL` and `FINN_GLM_MODEL` select the provider/model (default: current
Hyde baseline). Future model choices can change these variables without changing the workflow.
Live calls run only on manual dispatch. Missing credentials or failed model checks fail the job.
JUnit results and fictional research observations are uploaded as artifacts even on test failure,
retained for seven days; database files and `.env` are excluded.

## Deliberately left for the next stage

The frontend and mobile interaction design; broader filing-layout/OCR coverage; reliable live BSE access; automatic report/transcript selection; verified real-person biographies; advanced four-quarter guidance comparisons; notification delivery; stronger retrieval/semantic evaluation; and production hosting/privacy infrastructure. Calculations exist for explicitly sourced, compatible records; financial interpretation is not universally verified. P5/P6 expansion awaits user review of P0–P4.
