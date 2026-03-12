# DCMS Evidence Bot (Online Safety Act)

A proof-of-concept system that answers questions about the Online Safety Act using an evidence-first pipeline. The bot refuses to answer when the knowledge base cannot support a reliable response, and every material claim is backed by inspectable citations.

## Project Layout
- `backend/` — FastAPI service and retrieval core
- `frontend/` — static HTML/CSS/JS UI
- `eval/` — evaluation harness and canned questions
- `processed_knowledge_base/` — sample knowledge base folder (place JSON chunks here)

## Backend

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in your API keys
```

### Run the API
```bash
uvicorn backend.app:app --reload
```
The API listens on `http://localhost:8000` with:
- `POST /query` — answer a question with filters and citations
- `GET /status` — knowledge base status, counts, validation errors, config limits, and config flags
- `POST /refresh` — reload the KB from disk and rebuild indexes
- `POST /debug/retrieve` — inspect ranked retrieval results (no LLM call)

### Configuration
Key limits and defaults live in `backend/config.py`:
- `KB_DIR` — folder containing JSON chunk files (defaults to `processed_knowledge_base`)
- `MAX_CHUNKS_TO_LLM`, `MAX_CHARS_TO_LLM`, `MAX_EXCERPT_WORDS` — hard caps for evidence sent to the model
- `AUTHORITY_WEIGHTS` — simple weighting by source type
- `CORS_ALLOW_ORIGINS` — comma-separated list of allowed origins (defaults include `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5174`, `http://127.0.0.1:5174`, `http://localhost:3000`, `http://127.0.0.1:3000`)
- Retrieval mode: `RETRIEVAL_MODE` env var accepts `bm25`, `embeddings`, or `hybrid` (default).
- LLM and embeddings: set `OPENAI_API_KEY` plus optional `LLM_MODEL`, `EMBEDDINGS_MODEL`, and `EMBEDDINGS_BATCH_SIZE` (defaults to 50, minimum 1). If keys are missing, `/status` will show `llm_configured=false` and `embeddings_configured=false` but the service still runs in BM25 mode.

Run **without keys (BM25-only)**:
```bash
uvicorn backend.app:app --reload
# /status will show llm_configured=false and embeddings_configured=false
```

Enable embeddings + LLM (hybrid or embeddings mode):
```bash
export OPENAI_API_KEY=sk-...
export RETRIEVAL_MODE=hybrid  # or embeddings
uvicorn backend.app:app --reload
```
If you request an LLM-generated answer (`use_llm=true`) without `OPENAI_API_KEY`, `/query` returns a clear 400 error listing the missing variables.

Status and debugging helpers:
- `/status` now returns `kb_loaded`, `total_chunks`, `doc_counts_by_type`, `llm_configured`, `embeddings_configured`, `retrieval_mode`, and `index_ready`.
- `/debug/retrieve` echoes the ranked chunks (bm25 + embedding scores, headers, pages, excerpts) without calling the LLM.

Structured logs are written to `backend/logs/app.log`.

## Fly Deployment
For a production-style demo deployment on Fly.io, follow:

- `DEPLOY_FLY.md`
- `DEMO_SCRIPT.md` (live demo runbook and sample questions)

## Knowledge Base Format
Place JSON chunk files under `processed_knowledge_base/` (folders are allowed). Each file should resemble the sample Act file and include:
- `metadata`: `id`/`doc_id`, `title`, `type`/`source_type`, `author`/`publisher`, `date` (ISO if possible), optional `authority_weight`, `reliability_flags`
- `chunks`: list of objects with `text`, optional `header`, `page`/`location_pointer`, optional `chunk_id`

The loader validates required fields; missing items are surfaced in `/status` and logs. Authority weights default from `config.AUTHORITY_WEIGHTS` if not provided.

## Frontend
The primary UI is a React app in `frontend-v2/` (Vite + Tailwind). To run locally:
```bash
cd frontend-v2
npm install
npm run dev
# Visit http://localhost:5173
```
The Vite dev server proxies `/api` requests to the backend at `http://localhost:8000`.

A legacy static HTML UI is also available in `frontend/index.html`.

## Refresh / Reindex
Call the API endpoint after updating KB files:
```bash
curl -X POST http://localhost:8000/refresh
```
This reloads the JSON files, rebuilds the BM25 index, and updates the `last_refreshed` timestamp.

Verify CORS headers (adjust the Origin if you customized `CORS_ALLOW_ORIGINS`):
```bash
curl -i -X OPTIONS http://localhost:8000/query \
  -H "Origin: http://localhost:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```
The response should include `Access-Control-Allow-Origin: http://localhost:5173`. Note that `localhost` and `127.0.0.1` are different origins; both are whitelisted for local dev (ports 5173/5174 and 3000 by default).

## Embeddings Cache

Embeddings are pre-cached for the current knowledge base in `processed_knowledge_base/embeddings_cache.json`. This means first boot is instant — no OpenAI API calls required.

If you modify the knowledge base (add, remove, or edit documents), delete the cache file and regenerate:

```bash
rm processed_knowledge_base/embeddings_cache.json
.venv/bin/python scripts/generate_embeddings_cache.py
```

The regeneration script requires `OPENAI_API_KEY` to be set. It calls the OpenAI embeddings API and writes a new cache file. Commit the updated cache so other users also get instant boot.

On subsequent restarts after KB changes, if the committed cache is stale the system falls back to a runtime cache in `processed_knowledge_base/.cache/` (gitignored), then to live API calls as a last resort.

## Multi-Turn Conversation

The bot supports follow-up questions. Ask "What does section 64 say?" then follow up with "And what about section 65?" — the system rewrites the follow-up into a standalone query before retrieval, and passes conversation history to the LLM for coherent multi-turn responses.

- **Query rewriting**: A heuristic detects follow-ups (pronouns, "what about...", short questions) and rewrites them via the LLM into standalone form.
- **Frontend-managed state**: Conversation history lives in the browser (no server-side sessions). Click "New conversation" to reset.
- **Backward compatible**: Single-turn queries work identically — the `conversation_history` field is optional.

Configuration (in `.env` or environment):
- `CONVERSATION_MAX_HISTORY_TURNS` — max previous exchanges for rewriting context (default 3)
- `CONVERSATION_MAX_HISTORY_CHARS` — max chars of history included in LLM synthesis (default 10000)

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

74 unit tests covering the evidence sufficiency gate, section-lock guardrail, query classification, refusal paths, evidence pack building, query rewriting, and multi-turn message construction.

## Smoke Test
Run a lightweight retrieval smoke test:
```bash
python scripts/smoke_retrieval.py
```
It loads the KB and asserts that the “illegal content” query surfaces section 59 context among the top results.

## Evaluation Harness
Prerequisite: the backend server must be running locally.
```bash
pip install -r eval/requirements.txt
python eval/run_eval.py
```
- `eval/questions.json` contains 35 questions (including 5 traps expecting refusal).
- `eval/report.md` is generated with pass/fail details, citation checks, and refusal validation.

Quality eval against gold-standard summaries (token-overlap scoring):
```bash
.venv/bin/python -m eval.run_quality_eval
```
- Compares bot answers against `backend/config/gold_summaries.json` using precision, recall, F1, and sentence coverage.
- `eval/quality_report.md` is generated with per-question scores and aggregate metrics.

## Notes on Behavior
- Retrieval is BM25 with authority weighting and strict caps on chunk counts and total characters.
- If evidence is too weak, the bot refuses and surfaces the nearest sources as “possibly relevant” citations.
- Every citation object includes metadata, location pointers, and short excerpts for inspection.
