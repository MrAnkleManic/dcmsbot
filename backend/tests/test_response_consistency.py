import unittest

from backend.core.evidence import (
    build_citations,
    enforce_response_consistency,
    generate_answer,
)
from backend.core.models import Answer, Confidence, KBChunk


def _fake_chunk(idx: int = 1) -> KBChunk:
    return KBChunk(
        doc_id=f"D{idx}",
        title=f"Doc {idx}",
        source_type="report",
        publisher="Test",
        date_published="2024-01-01",
        chunk_id=f"chunk-{idx}",
        chunk_text="Evidence text content.",
        location_pointer="p1",
        authority_weight=5.0,
    )


class ResponseConsistencyTests(unittest.TestCase):
    def test_empty_retrieval_refuses_with_no_citations(self) -> None:
        evidence: list[KBChunk] = []
        citations = build_citations(evidence)
        answer = generate_answer("Q", evidence, citations)

        answer, citations, evidence_out, retrieved_out = enforce_response_consistency(
            answer=answer,
            citations=citations,
            evidence_pack=evidence,
            retrieved_sources=[],
            include_debug=False,
        )

        self.assertTrue(answer.refused)
        self.assertEqual([], citations)
        self.assertIsNone(evidence_out)
        self.assertIsNone(retrieved_out)

    def test_irrelevant_retrieval_refuses_and_hides_citations(self) -> None:
        evidence = [_fake_chunk()]
        citations = build_citations(evidence)
        answer = Answer(
            text="No relevant evidence found for this question.",
            confidence=Confidence(level="low", reason="No relevant evidence was available."),
            refused=True,
            refusal_reason="No relevant evidence was available to support an answer.",
        )

        answer, citations, evidence_out, retrieved_out = enforce_response_consistency(
            answer=answer,
            citations=citations,
            evidence_pack=evidence,
            retrieved_sources=evidence,
            include_debug=True,
        )

        self.assertTrue(answer.refused)
        self.assertEqual([], citations)
        self.assertEqual([], evidence_out)
        self.assertEqual(evidence, retrieved_out)

    def test_supported_answer_requires_citations(self) -> None:
        evidence = [_fake_chunk()]
        citations = build_citations(evidence)
        answer = generate_answer("Q", evidence, citations)

        answer, citations, evidence_out, retrieved_out = enforce_response_consistency(
            answer=answer,
            citations=citations,
            evidence_pack=evidence,
            retrieved_sources=evidence,
            include_debug=True,
        )

        self.assertFalse(answer.refused)
        self.assertEqual(1, len(citations))
        self.assertEqual(evidence, evidence_out)
        self.assertEqual(evidence, retrieved_out)


if __name__ == "__main__":
    unittest.main()
