"""Persistent Q&A archive: one JSON file per answered request.

Layout
------

    <store_dir>/<YYYY-MM>/<request_id>.json

One-file-per-request rather than one-file-per-month (as the cost
store does) because archive records are bigger (answer text +
evidence pack + citations) and we want cheap single-record reads
for re-display. The UUID filename is the dedupe key — re-appending
the same request_id is a no-op.

Record shape
------------

    {
      "schema_version":  1,
      "timestamp":       "2026-04-19T...",
      "request_id":      "<uuid>",
      "query_text":      "<full text; PRIVATE-DEPLOYMENT ASSUMPTION,
                          see note below>",
      "answer_text":     "<plain flat text for listings / substring
                          search — duplicates answer.text>",
      "answer":          {...},   # full Answer: confidence, refused,
                                  # refusal_reason, section_lock, ...
      "citations":       [...],
      "evidence_pack":   [...],
      "api_usage":       {...} | null,
    }

`schema_version` is bumped on any breaking schema change. Old files
stay readable; list/load code branches on it as needed.

PRIVACY note: query_text is stored verbatim because DCMS is a
private deployment. If this ever becomes public-facing, hash
(SHA-256) or drop the field — mirrors the decision in
`usage_store.py` where the same question was resolved.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.core._store_io import load_json_store

SCHEMA_VERSION = 1

DEFAULT_STORE_DIR = Path(os.getenv("ANSWERS_STORE_DIR", "data/cache/answers"))

# Safe filename characters. request_ids are UUID4s so this regex
# is a belt-and-braces guard against path-traversal if a future
# caller supplies an attacker-controlled id.
_SAFE_ID_CHARS = set("0123456789abcdefABCDEF-")


def _validate_request_id(request_id: str) -> str:
    """Return the id if it looks like a safe UUID/hex string; else raise."""
    if not request_id or len(request_id) > 64:
        raise ValueError(f"invalid request_id: {request_id!r}")
    if not all(c in _SAFE_ID_CHARS for c in request_id):
        raise ValueError(f"invalid request_id (unsafe chars): {request_id!r}")
    return request_id


def _month_dir(when: datetime, store_dir: Path) -> Path:
    return store_dir / when.strftime("%Y-%m")


def _record_path(request_id: str, when: datetime, store_dir: Path) -> Path:
    return _month_dir(when, store_dir) / f"{_validate_request_id(request_id)}.json"


def _parse_ts(raw: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, trailing Z tolerated. None on failure."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def append_answer_record(
    *,
    request_id: str,
    query_text: str,
    answer: dict,
    citations: list,
    evidence_pack: list,
    api_usage: Optional[dict] = None,
    timestamp: Optional[datetime] = None,
    store_dir: Path = DEFAULT_STORE_DIR,
) -> dict:
    """Persist one answered-query record. Idempotent on `request_id`.

    If the target file already exists (duplicate submission or replay),
    the existing record is returned unchanged — we don't overwrite.
    """
    ts = timestamp or datetime.now(timezone.utc)
    path = _record_path(request_id, ts, Path(store_dir))

    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Corrupt existing file — overwrite rather than poison new writes.
            pass

    record = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": ts.isoformat(),
        "request_id": request_id,
        "query_text": query_text,
        "answer_text": answer.get("text", "") if isinstance(answer, dict) else "",
        "answer": answer,
        "citations": citations,
        "evidence_pack": evidence_pack,
        "api_usage": api_usage,
    }

    # One JSON per request. The UUID filename means there are no
    # concurrent writers to the same path, so we only need atomic
    # RENAME semantics (a half-written file never visible to a reader),
    # not a lock. Write to .tmp, fsync, os.replace.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return record


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def load_answer_record(
    request_id: str,
    *,
    store_dir: Path = DEFAULT_STORE_DIR,
) -> Optional[dict]:
    """Return the archived record for `request_id`, or None if absent.

    We don't know the month a priori, so scan month directories.
    Scales to ~hundreds of months before it matters — at which point
    add a tiny index file.
    """
    _validate_request_id(request_id)
    store_path = Path(store_dir)
    if not store_path.exists():
        return None
    for month_dir in sorted(store_path.iterdir(), reverse=True):
        if not month_dir.is_dir():
            continue
        candidate = month_dir / f"{request_id}.json"
        if candidate.exists():
            return load_json_store(str(candidate), default=None)
    return None


def _list_month_dirs(
    since: datetime,
    until: datetime,
    store_dir: Path,
) -> list[Path]:
    """Month directories whose YYYY-MM name falls in [since, until]."""
    if not store_dir.exists():
        return []
    start_key = since.strftime("%Y-%m")
    end_key = until.strftime("%Y-%m")
    result: list[Path] = []
    for entry in store_dir.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if len(name) == 7 and name[4] == "-" and start_key <= name <= end_key:
            result.append(entry)
    return result


def list_answers(
    *,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    q: Optional[str] = None,
    limit: int = 50,
    store_dir: Path = DEFAULT_STORE_DIR,
) -> list[dict]:
    """List archived answers, newest first.

    Parameters
    ----------
    since, until : datetime or None
        Inclusive bounds on `timestamp`. Defaults: epoch → now.
    q : str or None
        Case-insensitive substring applied to `query_text`. None = no filter.
    limit : int
        Cap on number of returned summaries. Caller sorts/paginates beyond.

    Returns a list of compact summaries (id, timestamp, query_text,
    answer_preview, refused, total_cost_usd). Full record available
    via `load_answer_record(id)`.
    """
    if since is None:
        since = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if until is None:
        until = datetime.now(timezone.utc)
    needle = q.lower().strip() if q else None

    store_path = Path(store_dir)
    summaries: list[dict] = []

    for month_dir in _list_month_dirs(since, until, store_path):
        for entry in month_dir.iterdir():
            if entry.suffix != ".json" or not entry.is_file():
                continue
            try:
                with open(entry) as f:
                    rec = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            ts = _parse_ts(rec.get("timestamp", ""))
            if ts is None or ts < since or ts > until:
                continue
            qt = rec.get("query_text", "") or ""
            if needle and needle not in qt.lower():
                continue

            answer_text = rec.get("answer_text") or (rec.get("answer") or {}).get("text") or ""
            api_usage = rec.get("api_usage") or {}
            cost = api_usage.get("total_cost_usd") if isinstance(api_usage, dict) else None

            summaries.append({
                "request_id": rec.get("request_id"),
                "timestamp": rec.get("timestamp"),
                "query_text": qt,
                "answer_preview": (answer_text[:200] + "\u2026") if len(answer_text) > 200 else answer_text,
                "refused": bool((rec.get("answer") or {}).get("refused")),
                "total_cost_usd": cost,
            })

    summaries.sort(key=lambda s: s.get("timestamp") or "", reverse=True)
    return summaries[:limit]
