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

# Current affairs that are genuinely out of scope.
# NOTE: "current" removed — "current government position" is now a valid
# parliamentary query, not an out-of-scope current affairs question.
_CURRENT_AFFAIRS_PATTERNS = [
    re.compile(r"\bprime minister\b", re.IGNORECASE),
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
    re.compile(r"\bwhat is (a|an|the meaning|the definition)\b", re.IGNORECASE),
]

# Parliamentary patterns — questions that need live Parliament data
_PARLIAMENTARY_PATTERNS = [
    re.compile(r"\bcurrent position\b", re.IGNORECASE),
    re.compile(r"\bgovernment('s)?\s+(view|position|stance)\b", re.IGNORECASE),
    re.compile(r"\bwritten (answer|question|statement)\b", re.IGNORECASE),
    re.compile(r"\bminister\b", re.IGNORECASE),
    re.compile(r"\bparliament\b", re.IGNORECASE),
    re.compile(r"\bdebate\b", re.IGNORECASE),
    re.compile(r"\bselect committee\b", re.IGNORECASE),
    re.compile(r"\bamended?\b", re.IGNORECASE),
    re.compile(r"\bsince (royal assent|enacted|passed)\b", re.IGNORECASE),
    re.compile(r"\brecent(ly)?\b", re.IGNORECASE),
    re.compile(r"\blatest\b", re.IGNORECASE),
    re.compile(r"\bthis (year|month|session)\b", re.IGNORECASE),
]

# Strategic patterns — questions needing analysis beyond factual retrieval
_STRATEGIC_PATTERNS = [
    re.compile(r"\bhow (will|might|could|should)\b", re.IGNORECASE),
    re.compile(r"\bimplications?\b", re.IGNORECASE),
    re.compile(r"\bimpact\b", re.IGNORECASE),
    re.compile(r"\bstrateg(y|ic)\b", re.IGNORECASE),
    re.compile(r"\brisks?\b", re.IGNORECASE),
    re.compile(r"\badvise\b", re.IGNORECASE),
    re.compile(r"\bwhat should\b", re.IGNORECASE),
    re.compile(r"\bplay out\b", re.IGNORECASE),
    re.compile(r"\blikely\b", re.IGNORECASE),
    re.compile(r"\boutlook\b", re.IGNORECASE),
    re.compile(r"\bcompare\b", re.IGNORECASE),
    re.compile(r"\bdifferences?\b", re.IGNORECASE),
    re.compile(r"\bassess\b", re.IGNORECASE),
    re.compile(r"\bevaluat(e|ion)\b", re.IGNORECASE),
    re.compile(r"\bpatterns?\b", re.IGNORECASE),
    re.compile(r"\bemerging\b", re.IGNORECASE),
    re.compile(r"\btrends?\b", re.IGNORECASE),
    re.compile(r"\bevolv(e|ing)\b", re.IGNORECASE),
]


class QueryClassification(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    IN_SCOPE_STRATEGIC = "IN_SCOPE_STRATEGIC"
    IN_SCOPE_PARLIAMENTARY = "IN_SCOPE_PARLIAMENTARY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNSUPPORTED_ANALYTICS = "UNSUPPORTED_ANALYTICS"


def classify_query(question: str) -> QueryClassification:
    text = question.lower()

    # Analytics check first — counts/rankings are unsupported regardless
    if any(pattern.search(text) for pattern in _ANALYTICS_PATTERNS):
        return QueryClassification.UNSUPPORTED_ANALYTICS

    # Check parliamentary patterns BEFORE current affairs.
    # "What did the minister say last week?" is parliamentary, not out-of-scope.
    has_parliamentary = any(pattern.search(text) for pattern in _PARLIAMENTARY_PATTERNS)

    # Current affairs check — but only if not a parliamentary question
    if not has_parliamentary and any(pattern.search(text) for pattern in _CURRENT_AFFAIRS_PATTERNS):
        return QueryClassification.OUT_OF_SCOPE

    # Parliamentary questions need live data — classify even if also strategic
    if has_parliamentary:
        return QueryClassification.IN_SCOPE_PARLIAMENTARY

    # Strategic questions get analysis-mode synthesis
    if any(pattern.search(text) for pattern in _STRATEGIC_PATTERNS):
        return QueryClassification.IN_SCOPE_STRATEGIC

    # Default: factual KB question (scope terms no longer required —
    # the bot is domain-specific, so assume in-scope unless excluded)
    return QueryClassification.IN_SCOPE


def is_in_scope(classification: QueryClassification) -> bool:
    """Return True for any IN_SCOPE variant (factual, strategic, parliamentary)."""
    return classification in (
        QueryClassification.IN_SCOPE,
        QueryClassification.IN_SCOPE_STRATEGIC,
        QueryClassification.IN_SCOPE_PARLIAMENTARY,
    )


def needs_parliament_data(classification: QueryClassification) -> bool:
    """Return True if the classification requires live Parliament data."""
    return classification in (
        QueryClassification.IN_SCOPE_STRATEGIC,
        QueryClassification.IN_SCOPE_PARLIAMENTARY,
    )


def needs_strategic_synthesis(classification: QueryClassification,
                              question: str = "") -> bool:
    """Return True if the question warrants strategic analysis.

    Activated for:
    - Any question classified as IN_SCOPE_STRATEGIC
    - Any question (including PARLIAMENTARY) that contains
      strategic language like 'advise', 'implications', 'risk'
    """
    if classification == QueryClassification.IN_SCOPE_STRATEGIC:
        return True
    if question and any(p.search(question) for p in _STRATEGIC_PATTERNS):
        return True
    return False


def has_definition_intent(question: str) -> bool:
    text = question.lower()
    if any(pattern.search(text) for pattern in _DEFINITION_PATTERNS):
        return True
    return False
