# PLAN.md — FINN build plan

**Deadline:** Sun 15 Nov 2026. **Start:** Fri 13 Nov, 22:00.
**Principle:** protect a working demo first, polish second. Finish, test and commit each phase before starting the next.
**Hero workflows (never cut):** (1) management-change card with a network path, (2) results card QoQ/YoY, (3) promised-vs-delivered research, each with the Network on top.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[-]` cut

---

## Implementation agreement — P0–P4

The supplied `PLAN (1).md` matches this plan. Extend the existing `finn/` backend and preserve
its working API; introduce shared logic under `engine/` and fetch/CLI helpers under `ingest/`
without a wholesale directory rewrite. The Next.js scaffold and build move to P6. Keep the
current model as a configurable baseline; provider/model allocation remains undecided.
Each phase has code checks and an explicit live-source result. Synthetic fixtures remain
separate from real sources; failed/blocked sources and unverified portfolio picks stay labelled.
Stop implementation after P4 so the user can review before P5/P6 work.

## Product point of view

One ranked attention surface, not a dashboard. Three tabs:
- **Today (Push):** a digest of cards sorted by attention score; the window picker defaults to 24h; routine filings collapse into a single "N routine filings" row.
- **Ask (Pull):** command bar → research brief with citations on every claim.
- **People (Network):** paths, expertise search, reconnect nudges.

The Network is **woven in**: every Push card and Pull brief can show a **"Who to call"** chip, and the feed shows **"Reason to reconnect"** nudges.

---

## Phase 0 — Setup (Fri night, ~1h)
- [ ] Decide providers/models per task with the user after workflow validation: benchmark smaller models for classification/extraction/summary and stronger models for reasoning; compare accuracy, latency and token cost. Current Hyde GLM is a baseline, not a project restriction.
- [x] Keep the working backend layout and uv lockfile; add engine/ingest modules incrementally. Frontend scaffold/build deferred to P6.
- [x] `engine/llm.py`: shared model boundary, validated SQLite `llm_cache`, bounded retries and token/latency log. Model allocation and monetary rates remain undecided.
- [x] CI workflow: lint and backend tests on push/PR for Python 3.11/3.12; manual real-model acceptance with repository secret and saved diagnostics.
- [x] Retry previously blocked hosted backend checks: original workflow commit 1b8ca6b passed on Python 3.11 and 3.12 (31 tests each); GitHub reported zero billable runner milliseconds for that run.
- [ ] Verify the newer P0–P4 commit on hosted CI after user review; configure the live-test secret only with explicit approval, then verify the manual live job.
- **Done when:** backend and shared model gateway checks pass; frontend build is verified in P6. Hosted CI status is reported separately.

## Phase 1 — Check the data sources, then choose the portfolio (Fri night/Sat early, ~2–3h) ★ most important
- [x] Probe prices, BSE/NSE announcements and Screener tables/doc links: Yahoo, NSE and Screener passed live; BSE access failed and the explicit NSE fallback succeeded.
- [x] Scan 90 days across the official Nifty 100: 100/100 symbols scanned, no failures.
- [x] Choose 18 event-backed portfolio stocks and 4 off-portfolio research candidates; event coverage includes 22 results and other material filings.
- [x] Record picks, sectors, dated source links, executive-change examples, coverage and reasons in `data/mock/portfolio.json` (real sources, not synthetic financials).
- [ ] Restore reliable live BSE access; the adapter contract and NSE fallback are tested, but upstream access remains blocked/unavailable.
- **Done when:** at least one real management change, ≥5 results filings and ≥1 material event are in the portfolio window.

## Phase 2 — Data layer + ingestion (Sat morning, ~3h)
- [x] Schema: companies, prices, announcements, documents, doc_pages, llm_cache; quarterly/annual financials share one typed `financials` table with explicit frequency, basis, currency, units and mode.
- [x] Repeatable `python -m ingest.all`: prices, filings, optional fundamentals, and selected document manifests with authentic dates; per-page text and original PDF cache retained.
- [x] Verified NSE→BSE scrip codes extracted from official BSE links on Screener pages and stored with company metadata.
- [x] Retry transient fetch failures and retain raw snapshots under data/cache; matching cached responses preserve original timestamps and expose fallback provenance. Invalid/uncached requests fail visibly.
- [x] Packaged real TCS/INFY source snapshots plus original statement-page fixture; live 2-company ingestion completed and cached fallback verified.
- **Done when:** `python -m ingest.all --tickers <portfolio>` fills the DB and the tests pass offline.

## Phase 3 — Mock network + graph engine (Sat morning, ~3h, no LLM)
- [x] data/mock/investor.json and network.json: 40 synthetic profiles, dated roles/education, expertise, strength, contact dates and recorded edges; contact storage/queries are owner-scoped with legacy migration.
- [x] **Planted stories**, explicitly fictional and independently tested:
  - [x] Riya (incoming MOCKIT CFO) and Neha overlapped at Harbor Finance; recorded path You → Neha → Riya.
  - [x] Leela is a recorded supplier contact for SRF's synthetic capex event.
  - [x] Devika's education dates overlap with fictional promoter Karan; recorded path is separate from attendance overlap.
  - [x] Sameer last contacted in January; TCS's synthetic results produce a reconnect nudge.
- [x] Pure engine/network.py functions: resolve_person, work_overlap, study_overlap, paths_to(max_hops=2), best_contact_for, expertise_map, reconnect_nudges. Unknown acquaintance is never promoted to a recorded edge.
- **Done when:** a test exists for each planted story and passes.

## Phase 4 — Push engine (Sat afternoon, ~4–5h)
- [x] Existing classifier keeps explicit overrides and keyword decisions; optional source-cited model extraction supplies classification only on a rule miss. Provider categories remain source metadata rather than trusted taxonomy.
- [x] engine/push.py: type weight × materiality × investor category preference + capped network boost; expose score components and rank digest cards.
- [x] Configurable close/volume thresholds, complete prior-20-observation baseline, category preferences and routine collapse.
- [x] Enrichers:
  - [x] Management: source-cited incoming name/title, conservative person resolution, labelled synthetic profile, dated overlaps and recorded paths; unmatched identities remain gaps.
  - [x] Results: rule-first recognised PDF statements; model fallback selects validated source-line IDs. Preserve units/basis/periods, calculate QoQ/YoY in code and cross-check available Screener values at 2%; absent EBITDA remains absent.
  - [x] Material events: explainable employee/industry contacts plus a distinct recorded supplier/competitor perspective when available.
  - [x] Other filings: title-based fallback or source-cited model summary; methods are labelled.
- [x] Preserve /api routes and add /digest?from&to, /alerts and /settings/alerts aliases; financials, graph, enrichment and usage endpoints available in /docs.
- [x] Persist ingest-time enrichment; refresh deterministic cards on relevant data/settings/contact changes. GET digest never invokes a model. Model extraction is explicit via an enrichment request or refresh `enrich=true`/CLI --enrich.
- **Done when:** the digest for the demo window returns ranked cards with all 3 hero enrichments.

## Phase 5 — Pull engine (Sat evening/night, ~5–6h)
- [x] Run live-model acceptance tests against known synthetic facts: financial accuracy, missing evidence, source isolation, citations, network selection, cache invalidation and document prompt injection; keep response artifacts for review (7 passed).
- [ ] Extend acceptance coverage to real company documents, longer corpora, multiple periods/units and unsupported prose in findings/gaps; review factual support beyond the bounded numeric checks.
- [ ] Works for **any NSE ticker**: fetch screener tables + last 4 concall transcripts + latest annual report (fetched live, then cached)
- [ ] Split documents into chunks by page; simple retrieval (BM25 or small embeddings)
- [ ] Guidance extractor (cheap model, JSON): `{quarter, metric, guided_value_or_range, quote_page}`
- [ ] Promised-vs-delivered **computed in code** against the actual figures
- [ ] Strong model writes the narrative + bull/bear **using only the cited chunks**
- [ ] Sections (in priority order): Business snapshot → Financial snapshot + trajectory → **Promised vs delivered** → Bull/Bear
- [ ] A "People who'd know" panel from the network engine
- [ ] API: `POST /research/{ticker}` (cached; streams progress)
- **Done when:** briefs for the 3–5 research tickers plus one unseen ticker render with citations.

## Phase 6 — Frontend (Sun morning/afternoon, ~6–8h)
Build in this order:
- [ ] Today feed + card components (results card, management-change card, event card, collapsed routine row)
- [ ] Card detail: bio, overlap timeline, path view (You → A → Target)
- [ ] Ask: command bar → research brief with citation chips (tap → doc + page)
- [ ] People: search by company/theme, expertise map, reconnect nudges
- [ ] Alert settings sheet
- [ ] Design pass: one type scale, one accent colour, dense but calm, readable in 2 seconds
- **Done when:** the whole demo works on a real phone.

## Phase 7 — Deploy + make the demo safe (Sun afternoon, ~3h)
- [ ] Deploy the API (Render/Railway) and the web app (Vercel)
- [ ] Seed snapshots for all demo tickers; the frontend falls back to them if the API is cold
- [ ] Keep-warm ping; loading states for live research
- [ ] Run the demo end to end twice on mobile data

## Phase 8 — Writeup + submission (Sun evening, ~2–3h)
- [ ] Architecture diagram (pipelines, DB, LLM routing, cloud)
- [ ] Sections: what I built · key decisions/tradeoffs · data pipelines · security & privacy · LLMs/agents · cloud · what I left out · what's next
- [ ] State clearly that the network profiles are synthetic, and how real profiles would be handled (consent, official APIs, the contact sharing their own profile)
- [ ] Cost table from the `llm.py` token log
- [ ] Export the Codex/Claude sessions → links
- [ ] Email assessment@enam.com, subject: **"IIT Delhi – Founding AI Engineer - 2027"**

---

## Cut list (cut in this order if behind)
1. Annual-report parsing (keep transcripts)
2. Bull/Bear
3. Expertise map
4. People-tab visual polish
5. Alert settings UI (hard-code sensible defaults)

**Never cut:** the hero workflows, deploy, writeup.
