"""Fetch live Parliament data relevant to DCMS / Online Safety Act questions.

Uses bottl-commons ParliamentClient to search Written Answers, Hansard debates,
and the Bills API.  Follows the pattern established in Iron Resolve's
parliament_bridge.py but scoped to the DCMS answering body and online safety
search terms.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from backend.logging_config import get_logger

logger = get_logger(__name__)

# DCMS-specific search configuration
_ANSWERING_BODIES = [
    "Department for Culture, Media and Sport",
    "Department for Science, Innovation and Technology",
]
_BASE_SEARCH_TERMS = ["online safety", "online safety act", "ofcom"]
_BILL_KEYWORDS = ["online safety"]
_TOTAL_DEADLINE_SECONDS = 25
_DEFAULT_DATE_RANGE_DAYS = 180


def _extract_search_keywords(question: str) -> list[str]:
    """Extract meaningful keywords from the question to augment search terms."""
    # Remove common question words and short filler
    stopwords = {
        "what", "when", "where", "who", "how", "why", "does", "did", "has",
        "have", "been", "the", "and", "for", "are", "was", "with", "that",
        "this", "from", "will", "its", "about", "which", "their", "would",
        "could", "should", "might", "into", "been", "being", "some", "than",
    }
    words = re.findall(r"[a-zA-Z]+", question.lower())
    keywords = [w for w in words if len(w) > 3 and w not in stopwords]
    return keywords[:5]


def _make_health(
    source: str,
    status: str,
    message: str,
    items_returned: int = 0,
    latency_ms: int = 0,
) -> dict:
    return {
        "source": source,
        "status": status,
        "message": message,
        "items_returned": items_returned,
        "latency_ms": latency_ms,
    }


@dataclass
class ParliamentContext:
    """Results from Parliament API queries."""
    written_answers: list[dict] = field(default_factory=list)
    hansard_results: list[dict] = field(default_factory=list)
    bills_data: list[dict] = field(default_factory=list)
    pipeline_health: list[dict] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "written_answers": self.written_answers,
            "hansard_results": self.hansard_results,
            "bills_data": self.bills_data,
            "pipeline_health": self.pipeline_health,
            "summaries": self.summaries,
        }


def fetch_parliament_context(question: str, classification: str) -> dict:
    """Fetch live Parliament data relevant to the question.

    Returns dict with:
        written_answers: list of relevant WAs
        hansard_results: list of relevant debate extracts
        bills_data: any relevant amendment/SI activity
        pipeline_health: list of source status entries
        summaries: dict of human-readable summaries per source
    """
    ctx = ParliamentContext()
    deadline = time.monotonic() + _TOTAL_DEADLINE_SECONDS
    date_from = (datetime.now() - timedelta(days=_DEFAULT_DATE_RANGE_DAYS)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")
    keywords = _extract_search_keywords(question)
    # Base terms first — they're the most relevant and the API only uses
    # the first few.  Deduplicate without losing that order.
    seen: set[str] = set()
    search_terms: list[str] = []
    for term in _BASE_SEARCH_TERMS + keywords:
        if term not in seen:
            seen.add(term)
            search_terms.append(term)

    try:
        from bottl_commons.parliament import (
            ParliamentClient,
            summarise_hansard_results,
            summarise_written_questions,
        )
    except ImportError:
        logger.warning("bottl-commons not installed — Parliament data unavailable")
        ctx.pipeline_health.append(
            _make_health("parliament_client", "error", "bottl-commons not installed")
        )
        return ctx.to_dict()

    try:
        client = ParliamentClient(mode="standard")
    except Exception:
        logger.exception("Failed to create ParliamentClient")
        ctx.pipeline_health.append(
            _make_health("parliament_client", "error", "Client initialisation failed")
        )
        return ctx.to_dict()

    with client:
        # 1. Written Answers — ministerial positions
        _fetch_written_answers(client, ctx, search_terms, date_from, date_to, deadline)

        # 2. Hansard debates — recent parliamentary discussion
        if time.monotonic() < deadline:
            _fetch_hansard(client, ctx, search_terms, date_from, date_to, deadline, summarise_hansard_results)

        # 3. Bills API — amendments, SIs
        if time.monotonic() < deadline:
            _fetch_bills(client, ctx, deadline)

    return ctx.to_dict()


def _fetch_written_answers(
    client: Any,
    ctx: ParliamentContext,
    search_terms: list[str],
    date_from: str,
    date_to: str,
    deadline: float,
) -> None:
    """Fetch Written Answers from DCMS answering bodies."""
    source = "written_answers"
    t0 = time.monotonic()
    try:
        if time.monotonic() >= deadline:
            ctx.pipeline_health.append(_make_health(source, "skipped", "Deadline reached"))
            return

        # Search across answering bodies with combined topic
        topic = " OR ".join(search_terms[:3])
        results = client.get_written_questions(
            topic=topic,
            date_from=date_from,
            date_to=date_to,
            max_results=10,
        )

        latency = int((time.monotonic() - t0) * 1000)

        # Filter to DCMS-relevant answering bodies only — the API
        # returns broad matches and we don't want questions about
        # education or housing cluttering the results.
        allowed_bodies = {b.lower() for b in _ANSWERING_BODIES}
        results = [
            r for r in results
            if (getattr(r, "answering_body", "") or "").lower() in allowed_bodies
        ]

        if results:
            from bottl_commons.parliament import summarise_written_questions
            ctx.written_answers = [
                {
                    "title": (getattr(r, "question_text", "") or "")[:120],
                    "date": getattr(r, "date_tabled", None) or getattr(r, "date_answered", None) or "",
                    "answering_body": getattr(r, "answering_body", ""),
                    "answer_text": getattr(r, "answer_text", ""),
                    "question_text": getattr(r, "question_text", ""),
                    "member_name": getattr(r, "member_name", ""),
                    "uin": getattr(r, "uin", ""),
                    "url": f"https://questions-statements.parliament.uk/written-questions/detail/{getattr(r, 'uin', '')}",
                }
                for r in results
            ]
            summary = summarise_written_questions(results, topic)
            ctx.summaries["written_answers"] = summary
            ctx.pipeline_health.append(
                _make_health(source, "ok", f"Found {len(results)} Written Answers", len(results), latency)
            )
        else:
            ctx.pipeline_health.append(
                _make_health(source, "ok", "No Written Answers found for topic", 0, latency)
            )
    except Exception as e:
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Written Answers fetch failed", extra={"error": str(e)})
        ctx.pipeline_health.append(
            _make_health(source, "error", f"Fetch failed: {e}", 0, latency)
        )


def _fetch_hansard(
    client: Any,
    ctx: ParliamentContext,
    search_terms: list[str],
    date_from: str,
    date_to: str,
    deadline: float,
    summarise_fn: Any,
) -> None:
    """Fetch Hansard debate extracts."""
    source = "hansard"
    t0 = time.monotonic()
    try:
        if time.monotonic() >= deadline:
            ctx.pipeline_health.append(_make_health(source, "skipped", "Deadline reached"))
            return

        query = " ".join(search_terms[:3])
        results = client.search_hansard(
            query=query,
            date_from=date_from,
            date_to=date_to,
            max_results=10,
        )

        latency = int((time.monotonic() - t0) * 1000)

        if results:
            # Deduplicate by external_id
            seen_ids: set[str] = set()
            unique_results = []
            for r in results:
                eid = getattr(r, "external_id", None)
                if eid and eid in seen_ids:
                    continue
                if eid:
                    seen_ids.add(eid)
                unique_results.append(r)

            ctx.hansard_results = [
                {
                    "title": getattr(r, "title", ""),
                    "date": getattr(r, "date", ""),
                    "house": getattr(r, "house", ""),
                    "section": getattr(r, "section", ""),
                    "external_id": getattr(r, "external_id", ""),
                    "url": f"https://hansard.parliament.uk/search/Contributions?searchTerm={query.replace(' ', '+')}"
                           if not getattr(r, "external_id", None)
                           else f"https://hansard.parliament.uk/{getattr(r, 'external_id', '')}",
                }
                for r in unique_results
            ]
            summary = summarise_fn(unique_results, query)
            ctx.summaries["hansard"] = summary
            ctx.pipeline_health.append(
                _make_health(source, "ok", f"Found {len(unique_results)} debate references", len(unique_results), latency)
            )
        else:
            ctx.pipeline_health.append(
                _make_health(source, "ok", "No Hansard results found", 0, latency)
            )
    except Exception as e:
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Hansard fetch failed", extra={"error": str(e)})
        ctx.pipeline_health.append(
            _make_health(source, "error", f"Fetch failed: {e}", 0, latency)
        )


def _fetch_bills(
    client: Any,
    ctx: ParliamentContext,
    deadline: float,
) -> None:
    """Check Bills API for Online Safety Act amendments and SIs."""
    source = "bills"
    t0 = time.monotonic()
    try:
        if time.monotonic() >= deadline:
            ctx.pipeline_health.append(_make_health(source, "skipped", "Deadline reached"))
            return

        results = []
        for keyword in _BILL_KEYWORDS:
            bills = client.get_bill_status(keyword=keyword)
            if bills:
                results.extend(bills)

        latency = int((time.monotonic() - t0) * 1000)

        if results:
            ctx.bills_data = [
                {
                    "short_title": getattr(b, "short_title", ""),
                    "current_stage": getattr(b, "current_stage", ""),
                    "is_act": getattr(b, "is_act", False),
                    "is_defeated": getattr(b, "is_defeated", False),
                    "url": f"https://bills.parliament.uk/bills/{getattr(b, 'id', '')}",
                }
                for b in results
            ]
            ctx.pipeline_health.append(
                _make_health(source, "ok", f"Found {len(results)} bill(s)", len(results), latency)
            )
        else:
            ctx.pipeline_health.append(
                _make_health(source, "ok", "No bill activity found", 0, latency)
            )
    except Exception as e:
        latency = int((time.monotonic() - t0) * 1000)
        logger.warning("Bills fetch failed", extra={"error": str(e)})
        ctx.pipeline_health.append(
            _make_health(source, "error", f"Fetch failed: {e}", 0, latency)
        )
