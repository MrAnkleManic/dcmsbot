import re
from typing import Optional

from backend.core.models import KBChunk

_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsection\s+(?P<number>[\dA-Za-z]+)", re.IGNORECASE),
    re.compile(r"\bsec\.?\s+(?P<number>[\dA-Za-z]+)", re.IGNORECASE),
    re.compile(r"\bs\.?\s*(?P<number>[\dA-Za-z]+)", re.IGNORECASE),
    re.compile(r"§\s*(?P<number>[\dA-Za-z]+)", re.IGNORECASE),
    re.compile(r"\barticle\s+(?P<number>[\dA-Za-z]+)", re.IGNORECASE),
]

_SECTION_HEADING_PREFIX = r"(?:section heading:\s*)?"
_SECTION_NUMBER_PATTERN = re.compile(
    rf"^\s*{_SECTION_HEADING_PREFIX}section\s+(?P<number>\d+)", re.IGNORECASE
)


def parse_target_section(query: str) -> Optional[int]:
    """
    Extract a target section number (as an integer) from a free-text query.

    Supports variants such as "section 64", "s.64", "s 64", "sec 64", and "Section 64".
    Returns None if no numeric section reference is detected.
    """
    for pattern in _SECTION_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        value = match.group("number")
        digits = re.match(r"(\d+)", value)
        if digits:
            try:
                return int(digits.group(1))
            except ValueError:
                return None
    return None


def chunk_section_number(chunk: KBChunk) -> Optional[int]:
    """
    Attempt to extract an explicit section number from chunk metadata (header or location).
    """
    for candidate in (chunk.header, chunk.location_pointer):
        if not candidate:
            continue
        match = _SECTION_NUMBER_PATTERN.match(candidate)
        if match:
            return int(match.group("number"))
    return None


def section_matches_chunk(chunk: KBChunk, target_section: int) -> bool:
    """
    Determine whether the chunk clearly belongs to the target section based on metadata.
    """
    metadata_section = chunk_section_number(chunk)
    return metadata_section == target_section if metadata_section is not None else False
