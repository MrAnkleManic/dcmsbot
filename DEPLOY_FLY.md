# Deploy To Fly.io

This repo now deploys as a single Fly app:
- FastAPI backend on port `8080`
- `frontend-v2` built into static assets and served by FastAPI
- API available at both `/...` and `/api/...` routes

## 1) Prerequisites

- `flyctl` installed and authenticated:

```bash
fly auth login
```

## 2) Create app (first time only)

```bash
fly launch --no-deploy
```

When prompted:
- App name: keep existing (`dcms-evidence-bot`) or choose your own.
- Region: `lhr` (already set in `fly.toml`).
- Postgres/Redis: **No**.

## 3) Set secrets

Required for LLM answers:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
```

Optional (only if you want embeddings enabled):

```bash
fly secrets set OPENAI_API_KEY=sk-...
```

## 4) Deploy

```bash
fly deploy
```

First build/push is large because it includes the processed knowledge base and frontend bundle.

## 5) Verify

```bash
fly status
fly logs
fly open
```

API health checks:

```bash
curl https://<your-app>.fly.dev/status
curl https://<your-app>.fly.dev/api/status
curl https://<your-app>.fly.dev/api/kb-stats
```

## Notes

- `fly.toml` is configured for demo reliability:
  - `min_machines_running = 1`
  - `auto_stop_machines = "off"`
  - `memory = "2gb"`
- If you need lower cost after demos, you can switch `min_machines_running` back to `0` and `auto_stop_machines` to `"stop"`.
