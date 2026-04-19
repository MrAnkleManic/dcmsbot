"""Append-only monthly JSON store for LLM usage + cost records.

One file per calendar month: ``<store_dir>/<YYYY-MM>.json``. Each
request produces exactly one record appended under an exclusive lock
(see `_store_io.update_json_store`), so concurrent requests can't
clobber each other's entries.

Record shape (matches the `api_usage` response field so one summary
serves both wire format and persistence):

    {
      "timestamp": "2026-04-19T12:34:56.000Z",
      "request_id": "...",
      "query_text": "...",          # NOTE: private-deployment assumption.
                                    # If DCMS ever goes public-facing,
                                    # hash this (SHA-256) or drop the field.
      "calls":           [ {...}, ... ],  # per-call records from UsageAggregator
      "totals":          {...},           # token totals across calls
      "total_cost_usd":  0.00123,
    }

`get_usage_summary(since, until)` walks the monthly files and returns
aggregate cost + per-model breakdown for the given range. Useful for
"how much has DCMS cost me this month?" style questions from the
terminal or an admin endpoint.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from backend.core._store_io import load_json_store, update_json_store

# Default store root. Overridable via USAGE_STORE_DIR so deployments
# (Fly.io volume mount, tests with tmp_path) can redirect.
DEFAULT_STORE_DIR = Path(os.getenv("USAGE_STORE_DIR", "data/cache/api_usage"))


def _month_path(when: datetime, store_dir: Path) -> Path:
    return store_dir / f"{when.strftime('%Y-%m')}.json"


def _iter_month_files(
    since: datetime,
    until: datetime,
    store_dir: Path,
) -> Iterable[Path]:
    """Yield every month file whose YYYY-MM falls within [since, until]."""
    if not store_dir.exists():
        return
    start = datetime(since.year, since.month, 1, tzinfo=since.tzinfo)
    end = datetime(until.year, until.month, 1, tzinfo=until.tzinfo)
    cursor = start
    while cursor <= end:
        candidate = _month_path(cursor, store_dir)
        if candidate.exists():
            yield candidate
        year, month = cursor.year, cursor.month + 1
        if month > 12:
            year, month = year + 1, 1
        cursor = cursor.replace(year=year, month=month)


def append_usage_record(
    *,
    request_id: str,
    query_text: Optional[str],
    summary: dict,
    timestamp: Optional[datetime] = None,
    store_dir: Path = DEFAULT_STORE_DIR,
) -> dict:
    """Append one request's usage record to the current month's file.

    `summary` is the dict returned by `UsageAggregator.summary()` — it
    already carries calls + totals + total_cost_usd. We wrap it with
    request metadata.

    Returns the appended record (useful for logging + tests).
    """
    ts = timestamp or datetime.now(timezone.utc)
    record = {
        "timestamp": ts.isoformat(),
        "request_id": request_id,
        "query_text": query_text,
        "calls": summary.get("calls", []),
        "totals": summary.get("totals", {}),
        "total_cost_usd": summary.get("total_cost_usd", 0.0),
    }
    path = _month_path(ts, Path(store_dir))
    with update_json_store(str(path), default=[]) as records:
        records.append(record)
    return record


def get_usage_summary(
    since: datetime,
    until: Optional[datetime] = None,
    *,
    store_dir: Path = DEFAULT_STORE_DIR,
) -> dict:
    """Aggregate cost + per-model breakdown across [since, until].

    `until` defaults to now (UTC). Both bounds are inclusive on the
    timestamp field; records with `timestamp` < since or > until are
    skipped. Returns:

        {
          "since":  "ISO 8601",
          "until":  "ISO 8601",
          "request_count":    int,
          "total_cost_usd":   float,
          "totals": { input_tokens, cache_creation_input_tokens,
                      cache_read_input_tokens, output_tokens },
          "per_model": {
            "<model>": { cost_usd, input_tokens, cache_creation_input_tokens,
                         cache_read_input_tokens, output_tokens, call_count }
          }
        }
    """
    if until is None:
        until = datetime.now(timezone.utc)

    store_path = Path(store_dir)
    totals = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    per_model: dict[str, dict] = {}
    total_cost = 0.0
    request_count = 0

    for month_file in _iter_month_files(since, until, store_path):
        records = load_json_store(str(month_file), default=[])
        for rec in records:
            rec_ts_str = rec.get("timestamp")
            if not rec_ts_str:
                continue
            try:
                rec_ts = datetime.fromisoformat(rec_ts_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if rec_ts < since or rec_ts > until:
                continue

            request_count += 1
            total_cost += float(rec.get("total_cost_usd", 0.0) or 0.0)
            rec_totals = rec.get("totals") or {}
            for key in totals:
                totals[key] += int(rec_totals.get(key, 0) or 0)

            for call in rec.get("calls") or []:
                model = call.get("model") or "unknown"
                entry = per_model.setdefault(
                    model,
                    {
                        "cost_usd": 0.0,
                        "input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 0,
                        "call_count": 0,
                    },
                )
                entry["cost_usd"] += float(call.get("cost_usd", 0.0) or 0.0)
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                    "output_tokens",
                ):
                    entry[key] += int(call.get(key, 0) or 0)
                entry["call_count"] += 1

    for entry in per_model.values():
        entry["cost_usd"] = round(entry["cost_usd"], 6)

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "request_count": request_count,
        "total_cost_usd": round(total_cost, 6),
        "totals": totals,
        "per_model": per_model,
    }
