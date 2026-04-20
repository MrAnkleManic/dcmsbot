"""Brief 11 factual-pointed regression anchors (DCMS-adapted).

Every Brief 11 cue / pattern addition must be checked against these
anchors. If any flips from factual to survey, the precision path is
compromised and the survey pack will widen for pointed queries that
shouldn't widen.
"""

from __future__ import annotations

import pytest

from backend.core.query_classifier import classify_query_kind


FACTUAL_ANCHORS = [
    "What does Section 64 of the Online Safety Act say?",
    "What is the commencement date of Part 4?",
    "Quote the definition of 'regulated service'.",
    "What is the penalty under Section 10 for a regulated search service?",
    "What does Schedule 7 list as priority offences?",
    "What did the Written Answer on 14 March 2024 say?",
    "Who is the regulator under the Online Safety Act?",
    "What is the meaning of 'user-to-user service' in the Act?",
    "What Ofcom code of practice applies to illegal content?",
    "When did Part 7 come into force?",
]


@pytest.mark.parametrize("question", FACTUAL_ANCHORS)
def test_factual_anchor_stays_factual(question):
    """No Brief 11 cue / pattern may leak onto a factual-pointed query."""
    result = classify_query_kind(question)
    assert result.kind == "factual", (
        f"Regression: {question!r} now routes survey "
        f"(signals={result.signals})"
    )
