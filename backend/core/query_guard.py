import re
from enum import Enum

_SCOPE_TERMS = [
    "online safety act",
    "ofcom",
    "regulated service",
    "user-to-user",
    "user to user",
    "search service",
    "part ",
    "section",
    "schedule",
    "risk assessment",
    "code of practice",
    "information notice",
    "record-keeping",
    "record keeping",
    "adult user",
    "child user",
    "content reporting",
    "illegal content",
    "priority content",
    "provider duties",
]

_ANALYTICS_PATTERNS = [
    re.compile(r"\bhow many\b", re.IGNORECASE),
    re.compile(r"\bhow often\b", re.IGNORECASE),
    re.compile(r"\bmost often\b", re.IGNORECASE),
    re.compile(r"\bcount\b", re.IGNORECASE),
    re.compile(r"\bfrequency\b", re.IGNORECASE),
    re.compile(r"\brank\b", re.IGNORECASE),
    re.compile(r"\btop\s+\d+", re.IGNORECASE),
    re.compile(r"\baverage\b", re.IGNORECASE),
]

_CURRENT_AFFAIRS_PATTERNS = [
    re.compile(r"\bprime minister\b", re.IGNORECASE),
    re.compile(r"\bcurrent\s+(?:pm|president|government)\b", re.IGNORECASE),
    re.compile(r"\btoday\b", re.IGNORECASE),
    re.compile(r"\bthis week\b", re.IGNORECASE),
    re.compile(r"\bweather\b", re.IGNORECASE),
    re.compile(r"\bcelebrity\b", re.IGNORECASE),
    re.compile(r"\bfootball\b", re.IGNORECASE),
    re.compile(r"\bcapital of\b", re.IGNORECASE),
    re.compile(r"\bstock market\b", re.IGNORECASE),
    re.compile(r"one hand clapping", re.IGNORECASE),
]

_DEFINITION_PATTERNS = [
    re.compile(r"\bdefinition\b", re.IGNORECASE),
    re.compile(r"\bdefined\b", re.IGNORECASE),
    re.compile(r"\bdefine\b", re.IGNORECASE),
    re.compile(r"\bmeaning\b", re.IGNORECASE),
    re.compile(r"\binterpretation\b", re.IGNORECASE),
    re.compile(r"\bquote the definition\b", re.IGNORECASE),
    re.compile(r"\bwhat is\b", re.IGNORECASE),
]


class QueryClassification(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNSUPPORTED_ANALYTICS = "UNSUPPORTED_ANALYTICS"


def classify_query(question: str) -> QueryClassification:
    text = question.lower()
    if any(pattern.search(text) for pattern in _ANALYTICS_PATTERNS):
        return QueryClassification.UNSUPPORTED_ANALYTICS
    if any(pattern.search(text) for pattern in _CURRENT_AFFAIRS_PATTERNS):
        return QueryClassification.OUT_OF_SCOPE
    if any(term in text for term in _SCOPE_TERMS):
        return QueryClassification.IN_SCOPE
    return QueryClassification.IN_SCOPE


def has_definition_intent(question: str) -> bool:
    text = question.lower()
    if any(pattern.search(text) for pattern in _DEFINITION_PATTERNS):
        return True
    return False
