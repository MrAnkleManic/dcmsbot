"""Render an archived answer record as standalone HTML or PDF.

Input is the dict shape produced by `answers_store.append_answer_record`
(the same shape returned by `GET /answers/{request_id}`):

    {
      "timestamp", "request_id", "query_text",
      "answer":       {"text", "confidence", "refused", ...},
      "citations":    [...],
      "evidence_pack":[...],
      "api_usage":    {...} | null,
    }

Output is self-contained — inline CSS, no external assets — so the
same HTML serves as the `Download as HTML` payload and as the input
to weasyprint for `Download as PDF`.

Rendering choices:
  • `[analysis]…[/analysis]` blocks become distinct callouts, matching
    the frontend's live presentation.
  • Citation markers `[C001]`, `[H001]`, `[WA001]`, `[B001]` become
    footnote-style superscript links to numbered sources.
  • Sources section lists every citation with title, date, location,
    chunk_id, and a short excerpt from the backing chunk.
  • If `api_usage` is present, a small footer reports total cost and
    per-call tokens — valuable for retrospective per-answer cost
    analysis (Brief 3 + 4 come together here).
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Iterable

# Matches bracketed citation markers in answer text. Supports the
# citation prefixes the DCMS synthesis prompt actually emits:
#   C   — KB chunks (Online Safety Act, Ofcom guidance, Hansard)
#   WA  — Parliamentary Written Answers
#   H   — Hansard debates
#   B   — Bills
_CITATION_MARKER = re.compile(r"\[([CWHB][A-Z]*)(\d+)\]")

_ANALYSIS_OPEN = re.compile(r"\[analysis\]", re.IGNORECASE)
_ANALYSIS_CLOSE = re.compile(r"\[/analysis\]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Answer text → HTML
# ---------------------------------------------------------------------------

def _split_analysis(text: str) -> list[tuple[str, str]]:
    """Split answer text into alternating ('content', ...) and ('analysis', ...) segments.

    Direct port of the frontend's `splitAnalysisBlocks` in AnswerPanel.jsx
    so exports look identical to the live view. Handles unterminated
    `[analysis]` (treats the rest of the text as analysis) the same way.
    """
    segments: list[tuple[str, str]] = []
    cursor = 0
    while cursor < len(text):
        open_match = _ANALYSIS_OPEN.search(text, cursor)
        if not open_match:
            tail = text[cursor:]
            if tail.strip():
                segments.append(("content", tail))
            break
        if open_match.start() > cursor:
            lead = text[cursor:open_match.start()]
            if lead.strip():
                segments.append(("content", lead))
        close_match = _ANALYSIS_CLOSE.search(text, open_match.end())
        if close_match:
            body = text[open_match.end():close_match.start()].strip()
            if body:
                segments.append(("analysis", body))
            cursor = close_match.end()
        else:
            body = text[open_match.end():].strip()
            if body:
                segments.append(("analysis", body))
            cursor = len(text)
    return segments


def _citation_map_from(citations: Iterable[dict]) -> dict[str, int]:
    """Map citation_id ('C001') to its 1-based footnote number."""
    return {c.get("citation_id", f"C{i+1:03d}"): i + 1 for i, c in enumerate(citations)}


def _render_with_citations(text: str, citation_map: dict[str, int]) -> str:
    """HTML-escape `text` then rewrite citation markers as superscript anchors."""

    escaped = _html.escape(text)

    def sub(m: re.Match) -> str:
        cid = m.group(0)[1:-1]  # strip [ and ]
        raw_id = cid
        num = citation_map.get(raw_id)
        if num is None:
            return m.group(0)
        return f'<sup class="cite"><a href="#src-{num}">{num}</a></sup>'

    return _CITATION_MARKER.sub(sub, escaped)


def _paragraphs(block_html: str) -> str:
    """Wrap double-newline-separated chunks in <p>, preserving existing HTML."""
    pieces = [p.strip() for p in re.split(r"\n\s*\n", block_html) if p.strip()]
    return "\n".join(
        f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in pieces
    )


def _render_answer_body(answer_text: str, citations: list[dict]) -> str:
    """Render the answer body: analysis callouts + citation superscripts."""
    cmap = _citation_map_from(citations)
    segments = _split_analysis(answer_text or "")
    if not segments:
        body = _render_with_citations(answer_text or "", cmap)
        return _paragraphs(body)

    parts: list[str] = []
    for kind, body in segments:
        rendered = _render_with_citations(body, cmap)
        rendered = _paragraphs(rendered)
        if kind == "analysis":
            parts.append(
                '<aside class="analysis">'
                '<div class="analysis-label">Strategic Assessment</div>'
                f'{rendered}'
                '</aside>'
            )
        else:
            parts.append(rendered)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sources section
# ---------------------------------------------------------------------------

def _excerpt_for_citation(cit: dict, evidence_pack: list[dict]) -> str:
    """Pull chunk_text for the cited chunk, truncated for the footer."""
    chunk_id = cit.get("chunk_id")
    for chunk in evidence_pack or []:
        if chunk.get("chunk_id") == chunk_id:
            full = chunk.get("chunk_text") or ""
            return (full[:400] + "\u2026") if len(full) > 400 else full
    return cit.get("excerpt") or ""


def _render_sources(citations: list[dict], evidence_pack: list[dict]) -> str:
    if not citations:
        return ""
    items: list[str] = []
    for i, cit in enumerate(citations, start=1):
        title = _html.escape(cit.get("title") or "(untitled)")
        source_type = _html.escape(cit.get("source_type") or "")
        publisher = _html.escape(cit.get("publisher") or "")
        date_published = _html.escape(cit.get("date_published") or "")
        location = _html.escape(cit.get("location_pointer") or "")
        chunk_id = _html.escape(cit.get("chunk_id") or "")
        excerpt = _html.escape(_excerpt_for_citation(cit, evidence_pack))

        meta_bits = [b for b in (source_type, publisher, date_published, location) if b]
        meta_line = " \u00b7 ".join(meta_bits)

        items.append(
            f'<li id="src-{i}"><div class="src-title">{title}</div>'
            f'<div class="src-meta">{meta_line}</div>'
            f'<div class="src-excerpt">\u201c{excerpt}\u201d</div>'
            f'<div class="src-id">chunk_id: <code>{chunk_id}</code></div></li>'
        )
    return (
        '<section class="sources">'
        '<h2>Sources</h2>'
        f'<ol>{"".join(items)}</ol>'
        '</section>'
    )


# ---------------------------------------------------------------------------
# Usage footer
# ---------------------------------------------------------------------------

def _render_usage(api_usage: dict | None) -> str:
    if not api_usage or not api_usage.get("calls"):
        return ""
    calls = api_usage.get("calls", [])
    total_cost = api_usage.get("total_cost_usd", 0.0)
    totals = api_usage.get("totals") or {}
    rows = "".join(
        f'<tr><td>{_html.escape(c.get("label") or "")}</td>'
        f'<td>{_html.escape(c.get("model") or "")}</td>'
        f'<td>{int(c.get("input_tokens") or 0):,}</td>'
        f'<td>{int(c.get("cache_creation_input_tokens") or 0):,}</td>'
        f'<td>{int(c.get("cache_read_input_tokens") or 0):,}</td>'
        f'<td>{int(c.get("output_tokens") or 0):,}</td>'
        f'<td class="num">${float(c.get("cost_usd") or 0):.6f}</td></tr>'
        for c in calls
    )
    return (
        '<section class="usage">'
        '<h2>API usage</h2>'
        '<table><thead><tr>'
        '<th>Call</th><th>Model</th>'
        '<th>Input</th><th>Cache write</th><th>Cache read</th><th>Output</th>'
        '<th class="num">Cost (USD)</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody>'
        '<tfoot><tr>'
        '<td colspan="2">Total</td>'
        f'<td>{int(totals.get("input_tokens") or 0):,}</td>'
        f'<td>{int(totals.get("cache_creation_input_tokens") or 0):,}</td>'
        f'<td>{int(totals.get("cache_read_input_tokens") or 0):,}</td>'
        f'<td>{int(totals.get("output_tokens") or 0):,}</td>'
        f'<td class="num"><strong>${float(total_cost):.6f}</strong></td>'
        '</tr></tfoot>'
        '</table></section>'
    )


# ---------------------------------------------------------------------------
# Full HTML document
# ---------------------------------------------------------------------------

_CSS = """
@page { size: A4; margin: 22mm 18mm 24mm 18mm; }
* { box-sizing: border-box; }
body {
  font-family: 'Georgia', 'Iowan Old Style', serif;
  font-size: 10.5pt; line-height: 1.55; color: #222;
  margin: 0;
}
h1, h2, .product, .analysis-label, .src-meta, .src-id, .meta {
  font-family: -apple-system, 'Helvetica Neue', 'Segoe UI', sans-serif;
}
header.doc-head {
  border-bottom: 1.5pt solid #222; padding-bottom: 6pt; margin-bottom: 16pt;
  display: flex; justify-content: space-between; align-items: baseline;
}
.product { font-weight: 600; letter-spacing: 0.3pt; }
.timestamp { color: #555; font-size: 9pt; }
h1 {
  font-size: 13pt; text-transform: uppercase; letter-spacing: 0.6pt;
  color: #555; margin: 16pt 0 6pt;
}
h2 {
  font-size: 11pt; text-transform: uppercase; letter-spacing: 0.5pt;
  color: #555; margin: 18pt 0 6pt;
}
.question {
  font-size: 14pt; line-height: 1.35; font-style: italic;
  margin: 0 0 10pt; color: #111;
}
.answer p { margin: 0 0 8pt; text-align: justify; }
sup.cite a {
  text-decoration: none; color: #b6551f; font-weight: 600;
  font-size: 7.5pt; vertical-align: super;
}
.analysis {
  margin: 10pt 0; padding: 8pt 12pt;
  background: #fbf5ea; border-left: 3pt solid #b6551f;
  page-break-inside: avoid;
}
.analysis-label {
  font-size: 8pt; text-transform: uppercase; letter-spacing: 1pt;
  color: #b6551f; font-weight: 700; margin-bottom: 4pt;
}
.analysis p { margin: 0 0 6pt; }
.refused {
  padding: 10pt 14pt; border: 1pt dashed #b6551f;
  background: #fff8ef; font-style: italic; color: #5a3a12;
}
section.sources { margin-top: 16pt; }
section.sources ol { padding-left: 20pt; }
section.sources li { margin: 0 0 8pt; page-break-inside: avoid; }
.src-title { font-weight: 600; }
.src-meta { font-size: 8.5pt; color: #666; margin: 1pt 0 3pt; }
.src-excerpt { font-size: 9.5pt; color: #333; line-height: 1.4; }
.src-id { font-size: 8pt; color: #888; margin-top: 2pt; }
code { font-family: 'SF Mono', Consolas, monospace; font-size: 8.5pt; }
section.usage { margin-top: 16pt; page-break-inside: avoid; }
section.usage table {
  width: 100%; border-collapse: collapse; font-size: 8.5pt;
  font-family: -apple-system, sans-serif;
}
section.usage th, section.usage td {
  border-bottom: 0.5pt solid #ddd; padding: 3pt 6pt; text-align: left;
}
section.usage th { background: #f4efe6; font-weight: 600; }
section.usage td.num, section.usage th.num { text-align: right; font-variant-numeric: tabular-nums; }
section.usage tfoot td { border-top: 1pt solid #222; font-weight: 600; }
"""


def _format_timestamp(raw: str) -> str:
    """Pretty-print an ISO timestamp as '14 May 2026, 09:23 UTC'."""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return dt.strftime("%d %B %Y, %H:%M %Z") or dt.strftime("%d %B %Y, %H:%M UTC")


def render_html(record: dict) -> str:
    """Produce a standalone HTML document for an archived answer record."""
    question = _html.escape(record.get("query_text") or "")
    answer_obj = record.get("answer") or {}
    answer_text = answer_obj.get("text") or record.get("answer_text") or ""
    refused = bool(answer_obj.get("refused"))
    citations = record.get("citations") or []
    evidence_pack = record.get("evidence_pack") or []
    api_usage = record.get("api_usage")
    ts_pretty = _format_timestamp(record.get("timestamp") or "")
    request_id = _html.escape(record.get("request_id") or "")

    if refused:
        body = (
            f'<div class="refused">{_html.escape(answer_text)}</div>'
        )
        sources_html = _render_sources(citations, evidence_pack) if citations else ""
    else:
        body = f'<div class="answer">{_render_answer_body(answer_text, citations)}</div>'
        sources_html = _render_sources(citations, evidence_pack)

    usage_html = _render_usage(api_usage)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        f"<title>DCMS Online Safety Evidence Bot \u2014 {question[:80]}</title>"
        f"<style>{_CSS}</style>"
        "</head><body>"
        '<header class="doc-head">'
        '<div class="product">DCMS Online Safety Evidence Bot</div>'
        f'<div class="timestamp">{_html.escape(ts_pretty)} \u00b7 request <code>{request_id}</code></div>'
        "</header>"
        "<h1>Question</h1>"
        f'<p class="question">{question}</p>'
        "<h1>Answer</h1>"
        f"{body}"
        f"{sources_html}"
        f"{usage_html}"
        "</body></html>"
    )


def render_pdf(record: dict) -> bytes:
    """Render a record as PDF bytes via weasyprint.

    Raises ImportError if weasyprint isn't installed (caller should
    surface as 501 with an actionable message — see app.py).
    """
    import weasyprint  # local import so HTML export works without weasyprint
    html = render_html(record)
    return weasyprint.HTML(string=html).write_pdf()


def filename_for(record: dict, ext: str) -> str:
    """Reasonable download filename: `dcms-answer-<ts>-<id6>.<ext>`."""
    ts = (record.get("timestamp") or "").replace(":", "").replace("-", "")[:15]
    rid = (record.get("request_id") or "")[:8]
    return f"dcms-answer-{ts}-{rid}.{ext}"
