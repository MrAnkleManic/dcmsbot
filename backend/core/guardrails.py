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


def apply_section_lock(question: str, candidates: List[RetrievedChunk]) -> SectionLockOutcome:
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
