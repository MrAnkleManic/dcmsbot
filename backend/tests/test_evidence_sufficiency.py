import unittest

from backend import config
from backend.core.evidence_sufficiency import assess_evidence_sufficiency
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk


def _candidate(
    chunk_id: str, text: str, score: float, authority_weight: float = 1.0
) -> RetrievedChunk:
    chunk = KBChunk(
        doc_id=f"D-{chunk_id}",
        title="Sample",
        source_type="Act of Parliament",
        publisher="Test Publisher",
        date_published="2024-01-01",
        chunk_id=chunk_id,
        chunk_text=text,
        location_pointer="s.1",
        authority_weight=authority_weight,
    )
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score, embedding_score=None)


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_strong_match_is_ok(self) -> None:
        candidates = [
            _candidate("c1", "Section 12 covers safety duties for regulated services.", 0.9),
            _candidate("c2", "Safety duties and user protections are expanded.", 0.4),
        ]

        result = assess_evidence_sufficiency(
            "What does section 12 say about safety duties for regulated services?",
            candidates,
        )

        self.assertEqual("ok", result.status)
        self.assertGreaterEqual(result.top_score, config.EVIDENCE_MIN_TOP_SCORE)
        self.assertGreaterEqual(result.coverage, config.EVIDENCE_MIN_COVERAGE)

    def test_low_score_triggers_insufficient(self) -> None:
        candidates = [
            _candidate("c1", "Section 3 provides guidance on reporting duties.", 0.1),
            _candidate("c2", "General notes on the Act.", 0.05),
        ]

        result = assess_evidence_sufficiency("What are the reporting duties?", candidates)

        self.assertEqual("insufficient_evidence", result.status)
        self.assertLess(result.top_score, config.EVIDENCE_MIN_TOP_SCORE)

    def test_low_coverage_triggers_insufficient(self) -> None:
        candidates = [
            _candidate("c1", "Unrelated introductory material.", 0.8),
            _candidate("c2", "Background context with no overlap.", 0.6),
        ]

        result = assess_evidence_sufficiency("qwertyuiop policy xyz", candidates)

        self.assertEqual("insufficient_evidence", result.status)
        self.assertLess(result.coverage, config.EVIDENCE_MIN_COVERAGE)

    def test_low_separation_triggers_insufficient(self) -> None:
        candidates = [
            _candidate("c1", "Section 5 imposes reporting duties on providers.", 0.5),
            _candidate("c2", "Section 5 includes additional detail on reporting duties.", 0.48),
        ]

        result = assess_evidence_sufficiency("reporting duties on providers", candidates)

        self.assertEqual("insufficient_evidence", result.status)
        self.assertLess(result.separation, config.EVIDENCE_MIN_SEPARATION)


    def test_multi_source_authority_override_passes(self) -> None:
        """Broad analytical query with multiple Act chunks + supporting material passes."""
        # Scores are close together (low separation) and coverage may be low,
        # but multi-source authority override should kick in.
        candidates = [
            _candidate("a1", "Secretary of State direction powers under section 44.", 0.5, authority_weight=10),
            _candidate("a2", "Section 176 limits on Secretary of State directions.", 0.48, authority_weight=10),
            _candidate("a3", "Ofcom must comply with directions from the Secretary.", 0.46, authority_weight=10),
            _candidate("d1", "Lords debate on Secretary of State powers over Ofcom.", 0.40, authority_weight=6),
            _candidate("d2", "Commons discussion of direction-making powers.", 0.38, authority_weight=6),
            _candidate("d3", "Draft Bill clause on Ofcom accountability.", 0.35, authority_weight=5),
            _candidate("d4", "Lords further discussion of limits on directions.", 0.33, authority_weight=6),
        ]

        result = assess_evidence_sufficiency(
            "What powers does the Secretary of State have to direct Ofcom under the Online Safety Act, and where are the limits?",
            candidates,
        )

        self.assertEqual("ok", result.status)

    def test_multi_source_authority_override_needs_enough_act_chunks(self) -> None:
        """Only 1 Act chunk + supporting material is NOT enough for the override."""
        candidates = [
            _candidate("a1", "Secretary of State direction powers.", 0.5, authority_weight=10),
            _candidate("d1", "Lords debate on Secretary of State powers.", 0.48, authority_weight=6),
            _candidate("d2", "Commons discussion of direction-making powers.", 0.46, authority_weight=6),
            _candidate("d3", "Draft Bill clause on Ofcom accountability.", 0.44, authority_weight=5),
            _candidate("d4", "Lords further discussion of limits.", 0.42, authority_weight=6),
            _candidate("d5", "Additional debate material.", 0.40, authority_weight=5),
        ]

        result = assess_evidence_sufficiency(
            "What powers does the Secretary of State have to direct Ofcom?",
            candidates,
        )

        # Only 1 Act chunk (>= 8), so the override should NOT fire.
        # The low separation (0.5 / 0.48 ≈ 1.04) should cause insufficient.
        self.assertEqual("insufficient_evidence", result.status)

    def test_multi_source_authority_override_needs_enough_supporting(self) -> None:
        """2 Act chunks but fewer than 5 supporting chunks is NOT enough."""
        candidates = [
            _candidate("a1", "Secretary of State direction powers.", 0.5, authority_weight=10),
            _candidate("a2", "Section 176 limits.", 0.48, authority_weight=10),
            _candidate("d1", "Lords debate on powers.", 0.46, authority_weight=6),
            _candidate("d2", "Commons discussion.", 0.44, authority_weight=6),
        ]

        result = assess_evidence_sufficiency(
            "What powers does the Secretary of State have to direct Ofcom?",
            candidates,
        )

        # 2 Act chunks but only 4 supporting (>= 4), needs 5 — override should NOT fire.
        self.assertEqual("insufficient_evidence", result.status)


if __name__ == "__main__":
    unittest.main()
