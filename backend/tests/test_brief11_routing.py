"""Brief 11 (open-threads #83 follow-up) — routing regressions.

DCMS-adapted from iln_bot@0eaed1b. The three classes of query shape Brief
11 targets:
  1. Editorial curation ("Top 5 main debates") — was refused by the pre-
     Brief-11 analytics guard before classification could widen the pack.
  2. Survey intent without obvious cues ("main debates on X", "were
     there any fines imposed") — routed factual pre-Brief-11 because the
     cue list was too narrow.
  3. Narrative / inventory shapes ("write a narrative of", "actions
     during") — same diagnosis.

These tests pin the fix contract:
  - Brief 11 survey cues fire on all three classes.
  - query_guard.classify_query(question, query_kind="survey") returns
    IN_SCOPE for "top N" / "rank" editorial-curation shapes.
  - Strict-analytics patterns ("how many", "frequency", "average") still
    refuse even when kind="survey" — that refusal is LEGITIMATE for DCMS
    because BM25 retrieval genuinely cannot count.
  - Factual-pointed regression anchors stay factual.
"""

from __future__ import annotations

import pytest

from backend.core.query_classifier import classify_query_kind
from backend.core.query_guard import QueryClassification, classify_query


# ── Classifier cue coverage ─────────────────────────────────────────────────

BRIEF_11_SURVEY_QUERIES = [
    pytest.param(
        "What are the top 5 most notable debates on age verification?",
        id="top-5-notable-curation",
    ),
    pytest.param(
        "Main debates on online safety duties during 2023.",
        id="main-debates",
    ),
    pytest.param(
        "Were there any fines imposed under the Online Safety Act?",
        id="any-fines-imposed",
    ),
    pytest.param(
        "Write a narrative of the Online Safety Bill's passage through Parliament.",
        id="write-narrative",
    ),
    pytest.param("Top 10 most significant provisions.", id="top-10"),
    pytest.param("What are the most controversial duties in the Act?", id="most-controversial"),
    pytest.param(
        "Any enforcement actions taken by Ofcom against search services?",
        id="any-enforcement-taken",
    ),
]


@pytest.mark.parametrize("question", BRIEF_11_SURVEY_QUERIES)
def test_brief_11_survey_shapes_route_as_survey(question):
    result = classify_query_kind(question)
    assert result.kind == "survey", (
        f"{question!r} should route as survey post-Brief-11 "
        f"(kind={result.kind}, signals={result.signals})"
    )
    assert result.signals, "Survey result must expose at least one signal"


# ── query_guard kind-aware gating ───────────────────────────────────────────

class TestQueryGuardKindGating:
    """Editorial-curation shapes ("top N", "rank") must not refuse when
    kind=survey; strict-analytics shapes ("how many", "frequency") must
    still refuse regardless of kind — BM25 retrieval genuinely cannot
    answer them and the refusal is LEGITIMATE for DCMS."""

    def test_top_n_with_survey_kind_passes(self):
        classification = classify_query(
            "Top 5 main debates on online safety duties",
            query_kind="survey",
        )
        # With the "main debates" survey cue + "top N" curation pattern,
        # the guard should let it through to retrieval / synthesis.
        assert classification in (
            QueryClassification.IN_SCOPE,
            QueryClassification.IN_SCOPE_PARLIAMENTARY,
        )

    def test_top_n_with_factual_kind_still_refuses(self):
        classification = classify_query(
            "Give me the top 5 DOCs by chunk count",
            query_kind="factual",
        )
        assert classification == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_top_n_with_no_kind_preserves_pre_brief_11_behaviour(self):
        # Callers that haven't threaded kind through still get the
        # pre-Brief-11 refusal; nothing breaks silently.
        classification = classify_query("Top 5 enforcement actions")
        assert classification == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_rank_with_survey_kind_passes(self):
        classification = classify_query(
            "How would you rank the Ofcom enforcement priorities by impact?",
            query_kind="survey",
        )
        # "impact" → strategic; "rank" is curation-compatible when kind=survey.
        assert classification in (
            QueryClassification.IN_SCOPE,
            QueryClassification.IN_SCOPE_STRATEGIC,
            QueryClassification.IN_SCOPE_PARLIAMENTARY,
        )

    @pytest.mark.parametrize(
        "analytics_query",
        [
            "How many platforms has Ofcom fined?",
            "How often do enforcement notices get issued?",
            "Count the sections in Part 4.",
            "What is the frequency of amendment between versions?",
            "What was the average penalty size?",
            "Most often cited source?",
        ],
    )
    def test_strict_analytics_patterns_refuse_even_for_survey(self, analytics_query):
        # Quantitative analytics cannot be answered from BM25 retrieval even
        # in survey mode — the strict-patterns branch stays. This refusal
        # is LEGITIMATE in DCMS context.
        classification = classify_query(analytics_query, query_kind="survey")
        assert classification == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_out_of_scope_refusal_independent_of_kind(self):
        assert (
            classify_query("What is the capital of France?", query_kind="survey")
            == QueryClassification.OUT_OF_SCOPE
        )


# ── Factual regression anchors stay factual ────────────────────────────────

FACTUAL_POINTED_QUERIES = [
    "What does Section 64 of the Online Safety Act say?",
    "What is the commencement date of Part 4?",
    "Quote the definition of 'regulated service'.",
    "What is the penalty for non-compliance with Section 10?",
    "What does Schedule 7 list as priority offences?",
    "What did the Written Answer on 14 March 2024 state?",
    "Who is the current regulator under the Online Safety Act?",
]


@pytest.mark.parametrize("question", FACTUAL_POINTED_QUERIES)
def test_brief_11_preserves_factual_regression_anchors(question):
    """No Brief 11 cue may leak onto the pre-existing factual queries."""
    result = classify_query_kind(question)
    assert result.kind == "factual", (
        f"Brief 11 regression: {question!r} now routes survey "
        f"(signals={result.signals})"
    )
