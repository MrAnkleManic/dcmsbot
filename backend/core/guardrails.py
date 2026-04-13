import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk, chunk_belongs_to_section, _section_match_text
from backend.core.sections import chunk_section_number, parse_target_section

_DEF_QUERY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bdefine\s+(?P<term>.+)", re.IGNORECASE),
    re.compile(r"\bdefinition of\s+(?P<term>.+)", re.IGNORECASE),
    re.compile(r"\bmeaning of\s+(?P<term>.+)", re.IGNORECASE),
    re.compile(r"\bwhat does\s+(?P<term>.+?)\s+mean", re.IGNORECASE),
    re.compile(r"\binterpret(?:ation)? of\s+(?P<term>.+)", re.IGNORECASE),
]

_DEFINITION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmeans\b", re.IGNORECASE),
    re.compile(r"\bis defined as\b", re.IGNORECASE),
    re.compile(r"\bhas the meaning\b", re.IGNORECASE),
    re.compile(r"\bis to be read as\b", re.IGNORECASE),
]

_SENTENCE_SPLIT = re.compile(r"(?<=[\.;:])\s+|\n+")


@dataclass
class SectionLockOutcome:
    section_number: Optional[int]
    active: bool
    has_matches: bool
    filtered_candidates: List[RetrievedChunk]
    original_candidates: List[RetrievedChunk]

    @property
    def label(self) -> str:
        if not self.active or not self.section_number:
            return "off"
        return f"s.{self.section_number}"


def apply_section_lock(question: str, candidates: List[RetrievedChunk], kb=None) -> SectionLockOutcome:
    section_number = parse_target_section(question)
    if section_number is None:
        return SectionLockOutcome(
            section_number=None,
            active=False,
            has_matches=False,
            filtered_candidates=candidates,
            original_candidates=candidates,
        )

    matching = [
        candidate
        for candidate in candidates
        if chunk_section_number(candidate.chunk) == section_number
        or chunk_belongs_to_section(_section_match_text(candidate.chunk), str(section_number))
    ]

    # Legislative sections span multiple consecutive chunks but only
    # the intro chunk has the section_number metadata. Fetch the
    # continuation chunks directly from the KB so we get the full
    # section content, not just the heading.
    if matching and kb is not None:
        seen = {m.chunk.chunk_id for m in matching}
        for m in list(matching):
            cid = m.chunk.chunk_id
            if "::" not in cid:
                continue
            prefix, num_part = cid.rsplit("::", 1)
            try:
                num = int(num_part.lstrip("c"))
            except ValueError:
                continue
            for offset in range(1, 6):
                adj_id = f"{prefix}::c{num + offset:06d}"
                if adj_id in seen:
                    continue
                adj_chunk = kb.get_chunk(adj_id)
                if adj_chunk is None:
                    break  # no more consecutive chunks
                # Stop if we hit the next section heading
                if adj_chunk.section_number:
                    break
                seen.add(adj_id)
                matching.append(RetrievedChunk(
                    chunk=adj_chunk,
                    bm25_score=m.bm25_score * 0.9,
                    embedding_score=m.embedding_score * 0.9,
                    final_score=m.final_score * 0.9,
                ))

    filtered = matching or candidates
    return SectionLockOutcome(
        section_number=section_number,
        active=True,
        has_matches=bool(matching),
        filtered_candidates=filtered,
        original_candidates=candidates,
    )


def _clean_term(raw_term: str) -> str:
    cleaned = raw_term.strip(" ?\"'.,:;").strip()
    cleaned = re.sub(r"\bin\s+section\s+\d+[A-Za-z]?(?:\([^)]+\))?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ?\"'.,:;").strip()


def detect_definition_target(question: str) -> Optional[str]:
    for pattern in _DEF_QUERY_PATTERNS:
        match = pattern.search(question)
        if match:
            term = _clean_term(match.group("term"))
            return term if term else None
    return None


def find_definition_snippet(
    term: str, evidence: List[KBChunk]
) -> Optional[Tuple[str, KBChunk]]:
    term_pattern = re.compile(r'\b' + re.escape(term.lower().strip("'\"")) + r'\b')
    for chunk in evidence:
        sentences = _SENTENCE_SPLIT.split(chunk.chunk_text)
        for sentence in sentences:
            normalized_sentence = sentence.lower()
            if not term_pattern.search(normalized_sentence):
                continue
            if any(pattern.search(sentence) for pattern in _DEFINITION_PATTERNS):
                snippet = sentence.strip()
                if snippet:
                    return snippet, chunk
    return None
