"""Tests for the answer exporter — HTML structure + PDF round-trip.

Backported from iln_bot@d817bc3; fixtures adapted to DCMS (Online
Safety Act) corpus and DCMS branding in the rendered title.
"""

from __future__ import annotations

import pytest

from backend.core.answer_export import (
    _citation_map_from,
    _split_analysis,
    filename_for,
    render_html,
    render_pdf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fixture_record(
    *,
    refused: bool = False,
    with_usage: bool = True,
    answer_text: str | None = None,
) -> dict:
    text = answer_text or (
        "Section 9 [C001] imposes the illegal-content risk-assessment duty. "
        "Section 10 [C002] imposes the corresponding safety duty.\n\n"
        "[analysis]\nThe split between assessment (s.9) and mitigation (s.10) "
        "lets Ofcom enforce procedurally — bad assessment is itself a breach, "
        "even before any specific harm crystallises [C001]. This is the "
        "structural innovation of the Online Safety Act.\n[/analysis]\n\n"
        "Follow-up sections [C002] specify the duty in greater detail."
    )
    answer = {
        "text": text,
        "confidence": {"level": "high", "reason": "Strong evidence."},
        "refused": refused,
        "refusal_reason": "Out of scope." if refused else None,
        "section_lock": "off",
        "allow_citations_on_refusal": False,
    }
    citations = [
        {
            "citation_id": "C001",
            "doc_id": "DOC_OSA",
            "title": "Online Safety Act 2023",
            "source_type": "Act",
            "publisher": "HMSO",
            "date_published": "2023-10-26",
            "location_pointer": "Section 9",
            "chunk_id": "DOC_OSA_0009",
            "excerpt": "Risk-assessment duty \u2026",
            "authority_weight": 10.0,
        },
        {
            "citation_id": "C002",
            "doc_id": "DOC_OSA",
            "title": "Online Safety Act 2023",
            "source_type": "Act",
            "publisher": "HMSO",
            "date_published": "2023-10-26",
            "location_pointer": "Section 10",
            "chunk_id": "DOC_OSA_0010",
            "excerpt": "Safety duty \u2026",
            "authority_weight": 10.0,
        },
    ]
    evidence_pack = [
        {
            "doc_id": "DOC_OSA", "title": "Online Safety Act 2023",
            "source_type": "Act", "publisher": "HMSO",
            "date_published": "2023-10-26", "chunk_id": "DOC_OSA_0009",
            "chunk_text": "Section 9 imposes the illegal-content risk-assessment duty on user-to-user services.",
            "location_pointer": "Section 9", "authority_weight": 10.0,
        },
        {
            "doc_id": "DOC_OSA", "title": "Online Safety Act 2023",
            "source_type": "Act", "publisher": "HMSO",
            "date_published": "2023-10-26", "chunk_id": "DOC_OSA_0010",
            "chunk_text": "Section 10 imposes the safety duty corresponding to the s.9 risk assessment.",
            "location_pointer": "Section 10", "authority_weight": 10.0,
        },
    ]
    api_usage = None
    if with_usage:
        api_usage = {
            "calls": [{
                "label": "synthesis",
                "model": "claude-sonnet-4-6",
                "input_tokens": 5925,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1194,
                "output_tokens": 387,
                "cost_usd": 0.023938,
            }],
            "totals": {
                "input_tokens": 5925,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1194,
                "output_tokens": 387,
            },
            "total_cost_usd": 0.023938,
        }
    return {
        "schema_version": 1,
        "timestamp": "2026-04-19T09:23:45+00:00",
        "request_id": "7a568bbf-bd4d-425d-8368-ea22535e53f2",
        "query_text": "What does section 9 of the OSA require?",
        "answer_text": text,
        "answer": answer,
        "citations": citations,
        "evidence_pack": evidence_pack,
        "api_usage": api_usage,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def test_split_analysis_interleaves_content_and_analysis() -> None:
    text = "Intro.\n\n[analysis]A middle.[/analysis]\n\nOutro."
    segs = _split_analysis(text)
    kinds = [k for k, _ in segs]
    assert kinds == ["content", "analysis", "content"]
    assert segs[1][1] == "A middle."


def test_split_analysis_handles_unterminated_block() -> None:
    text = "Intro.\n\n[analysis]Hanging tail with no close tag"
    segs = _split_analysis(text)
    assert segs[-1][0] == "analysis"
    assert "Hanging tail" in segs[-1][1]


def test_split_analysis_is_case_insensitive() -> None:
    text = "[Analysis]upper case tags[/ANALYSIS]"
    segs = _split_analysis(text)
    assert [k for k, _ in segs] == ["analysis"]


def test_citation_map_numbers_in_order() -> None:
    cmap = _citation_map_from([{"citation_id": "C001"}, {"citation_id": "C002"}])
    assert cmap == {"C001": 1, "C002": 2}


# ---------------------------------------------------------------------------
# HTML render
# ---------------------------------------------------------------------------

def test_html_contains_question_answer_sources_usage_sections() -> None:
    html = render_html(_fixture_record())
    assert "<title>DCMS Online Safety Evidence Bot" in html
    assert "<h1>Question</h1>" in html
    assert "What does section 9 of the OSA require?" in html
    assert "<h1>Answer</h1>" in html
    assert "<section class=\"sources\">" in html
    assert "<h2>Sources</h2>" in html
    assert "<section class=\"usage\">" in html
    assert "<h2>API usage</h2>" in html


def test_html_rewrites_citation_markers_to_superscript_anchors() -> None:
    html = render_html(_fixture_record())
    assert "[C001]" not in html
    assert "[C002]" not in html
    assert '<sup class="cite"><a href="#src-1">1</a></sup>' in html
    assert '<sup class="cite"><a href="#src-2">2</a></sup>' in html
    assert 'id="src-1"' in html
    assert 'id="src-2"' in html


def test_html_wraps_analysis_blocks_in_aside() -> None:
    html = render_html(_fixture_record())
    assert '<aside class="analysis">' in html
    assert 'Strategic Assessment' in html
    assert "[analysis]" not in html
    assert "[/analysis]" not in html


def test_html_includes_source_metadata_and_excerpt_from_evidence_pack() -> None:
    html = render_html(_fixture_record())
    assert "Online Safety Act 2023" in html
    assert "Act" in html
    assert "Section 9" in html
    assert "DOC_OSA_0009" in html
    assert "Section 9 imposes the illegal-content risk-assessment duty" in html


def test_html_excerpt_falls_back_when_chunk_not_in_pack() -> None:
    record = _fixture_record()
    record["evidence_pack"] = []
    html = render_html(record)
    assert "Risk-assessment duty \u2026" in html


def test_html_refusal_renders_as_refused_block_without_sources() -> None:
    record = _fixture_record(
        refused=True,
        answer_text="I cannot answer this from the OSA corpus.",
    )
    record["citations"] = []
    record["evidence_pack"] = []
    html = render_html(record)
    assert 'class="refused"' in html
    assert "I cannot answer this from the OSA corpus." in html
    assert "<h2>Sources</h2>" not in html


def test_html_escapes_user_supplied_content() -> None:
    """Question text must be HTML-escaped — no XSS via query_text."""
    record = _fixture_record()
    record["query_text"] = "What about <script>alert('x')</script>?"
    html = render_html(record)
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_omits_usage_section_when_api_usage_missing() -> None:
    record = _fixture_record(with_usage=False)
    html = render_html(record)
    assert "<h2>API usage</h2>" not in html


def test_html_usage_section_reports_total_cost() -> None:
    html = render_html(_fixture_record())
    assert "$0.023938" in html
    assert "5,925" in html
    assert "1,194" in html


# ---------------------------------------------------------------------------
# PDF render
# ---------------------------------------------------------------------------

def test_render_pdf_returns_valid_pdf_bytes() -> None:
    pdf = render_pdf(_fixture_record())
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-", f"expected PDF magic bytes, got {pdf[:20]!r}"
    assert len(pdf) > 1500


def test_render_pdf_handles_refusal_path() -> None:
    """PDF renderer must not crash on the refused branch (no sources)."""
    record = _fixture_record(refused=True, answer_text="Refused.")
    record["citations"] = []
    record["evidence_pack"] = []
    pdf = render_pdf(record)
    assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Filename helper
# ---------------------------------------------------------------------------

def test_filename_for_has_timestamp_and_short_id() -> None:
    record = _fixture_record()
    assert filename_for(record, "pdf") == "dcms-answer-20260419T092345-7a568bbf.pdf"
    assert filename_for(record, "html") == "dcms-answer-20260419T092345-7a568bbf.html"
