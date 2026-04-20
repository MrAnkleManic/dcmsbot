"""Tests for query_classifier.classify_query_kind (Brief 9 sub-job A).

Survey routing is the heuristic gate on the widened evidence-pack caps in
query_flow. These tests pin which shapes route survey vs factual for
DCMS's OSA / Hansard / Ofcom domain. See iln_bot@4fb41e3 + iln_bot@0eaed1b
for upstream; cues here are DCMS-specific.
"""

from __future__ import annotations

import pytest

from backend.core.query_classifier import classify_query_kind


# ── Survey-shaped queries should route survey ──────────────────────────────

SURVEY_QUERIES = [
    pytest.param(
        "What were the main debates on online safety duties during the 2022-23 Parliament?",
        id="main-debates-osa",
    ),
    pytest.param(
        "Give me an overview of Ofcom's enforcement actions so far.",
        id="overview-enforcement",
    ),
    pytest.param(
        "What are the key provisions of the Online Safety Act on illegal content?",
        id="key-provisions",
    ),
    pytest.param(
        "Tell me everything about the risk assessment duties.",
        id="tell-me-everything",
    ),
    pytest.param(
        "All the Ofcom guidance on record-keeping please.",
        id="all-guidance",
    ),
    pytest.param(
        "Summarise the Select Committee findings on the Bill.",
        id="summarise-committee",
    ),
    # Brief 11 editorial / curation shapes kept from iln_bot upstream:
    pytest.param(
        "Top 5 most notable debates on age verification.",
        id="top-5-notable",
    ),
    pytest.param(
        "What are the most significant provisions for search services?",
        id="most-significant",
    ),
    pytest.param(
        "Were there any fines imposed under the Online Safety Act?",
        id="any-fines-imposed",
    ),
    pytest.param(
        "Any enforcement actions taken by Ofcom against user-to-user platforms?",
        id="any-enforcement-taken",
    ),
    pytest.param(
        "Write a narrative of the Online Safety Bill's progress through Parliament.",
        id="write-narrative",
    ),
]


@pytest.mark.parametrize("question", SURVEY_QUERIES)
def test_survey_shapes_route_as_survey(question):
    result = classify_query_kind(question)
    assert result.kind == "survey", (
        f"{question!r} should route as survey; kind={result.kind}, signals={result.signals}"
    )
    assert result.signals, "Survey result must expose at least one signal"


# ── Factual-pointed queries must stay factual ──────────────────────────────

FACTUAL_POINTED_QUERIES = [
    "What does Section 64 of the Online Safety Act say?",
    "What is the commencement date of Part 4?",
    "Who is the current regulator under the Online Safety Act?",
    "Quote the definition of 'regulated service' from the Act.",
    "What is the penalty for non-compliance with Section 10?",
    "What does Schedule 7 list as priority offences?",
    "What did the Minister say in the Written Answer on 2024-03-14?",
]


@pytest.mark.parametrize("question", FACTUAL_POINTED_QUERIES)
def test_factual_pointed_queries_route_as_factual(question):
    result = classify_query_kind(question)
    assert result.kind == "factual", (
        f"{question!r} should route as factual; signals={result.signals}"
    )


# ── Empty / degenerate inputs ──────────────────────────────────────────────

class TestEmptyAndDegenerate:
    def test_empty_question_is_factual(self):
        assert classify_query_kind("").kind == "factual"

    def test_whitespace_question_is_factual(self):
        assert classify_query_kind("   \n").kind == "factual"


# ── Env override of cue phrases ────────────────────────────────────────────

class TestCueEnvOverride:
    def test_env_override_replaces_defaults(self, monkeypatch):
        # With override, only the custom cue should fire.
        monkeypatch.setenv("SURVEY_QUERY_CUES", "deep dive, full writeup")
        # Default cue no longer fires.
        assert classify_query_kind("Give me an overview of Section 10").kind == "factual"
        # But regex patterns still apply — "top N" is in _SURVEY_PATTERNS
        # and not affected by the cue env var.
        assert classify_query_kind("Top 10 notable provisions").kind == "survey"
        # Custom cue hits.
        assert classify_query_kind("Deep dive on the risk assessment regime").kind == "survey"

    def test_empty_env_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setenv("SURVEY_QUERY_CUES", "")
        # Default cue fires.
        assert classify_query_kind("Give me an overview of Section 10").kind == "survey"
