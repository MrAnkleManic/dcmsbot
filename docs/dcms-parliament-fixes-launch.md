# DCMS Bot — Parliament Fixes + Strategic Edge Case

## Purpose

This is a BUILD thread. Two targeted fixes from the
discussion thread testing on 8 April 2026.

The Parliament integration is mostly working — the Bills API
returns data, the routing is correct, the citation system
handles all source types. But Written Answers and Hansard are
broken due to an API mismatch, and there's an edge case where
questions that are both parliamentary AND strategic lose
their analysis mode.

---

## Working directory
/Users/nickangel/Local/AI/bottl/dcms/

## Key files
- `backend/core/parliament_fetch.py` — where Parliament API
  calls are made
- `backend/core/query_guard.py` — where classification and
  synthesis mode are decided
- `backend/app.py` — where synthesis_mode is set before
  calling the LLM

---

## Fix 1: Written Answers and Hansard not returning data

### What's happening

The bottl-commons ParliamentClient now requires both a start
date AND an end date when searching. Our code only sends the
start date. So Written Answers and Hansard calls fail with:

```
ParliamentClient.get_written_questions() missing 1 required
positional argument: 'date_to'
```

The Bills API works fine because it doesn't need dates the
same way.

### What to do

In `backend/core/parliament_fetch.py`, find where `date_from`
is calculated (around line 93):

```python
date_from = (datetime.now() - timedelta(days=_DEFAULT_DATE_RANGE_DAYS)).strftime("%Y-%m-%d")
```

Add `date_to` right after it:

```python
date_to = datetime.now().strftime("%Y-%m-%d")
```

Then pass `date_to` to both API calls:

**Written Answers call** (around line 151):
```python
results = client.get_written_questions(
    topic=topic,
    date_from=date_from,
    date_to=date_to,      # <-- add this
    max_results=10,
)
```

**Hansard call** (around line 208):
```python
results = client.search_hansard(
    query=query,
    date_from=date_from,
    date_to=date_to,      # <-- add this
    max_results=10,
)
```

### How to verify

Run a parliamentary query like "What is the government's
current position on age verification?" and check that
`parliament_health` shows `written_answers: ok` and
`hansard: ok` instead of errors.

---

## Fix 2: Questions that are both parliamentary AND strategic

### What's happening

Some questions need both Parliament data AND the strategic
analysis register. For example:

> "Advise on the implications of the recent Select Committee
> report for platform compliance teams"

This contains parliamentary words ("recent", "Select
Committee") AND strategic words ("Advise", "implications").

The classifier correctly routes it as PARLIAMENTARY so it
fetches Parliament data. But since we decoupled the
strategic register from parliamentary classification (correct
decision — most parliamentary questions are factual), this
question now gets a plain factual answer when it's clearly
asking for strategic analysis.

### What to do

In `backend/core/query_guard.py`, change
`needs_strategic_synthesis()` so it doesn't just check the
classification label — it also checks whether the question
itself contains strategic language:

```python
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
```

Then update the two places that call this function to also
pass the question text:

**In `backend/app.py`** (where synthesis_mode is set):
```python
synthesis_mode = "strategic" if needs_strategic_synthesis(classification, effective_question) else "factual"
```

**In `backend/app.py`** (where the LLM call decides whether
to use the strategic supplement):
```python
strategic = needs_strategic_synthesis(classification, effective_question)
```

### How to verify

Run "Advise on the implications of the recent Select
Committee report for platform compliance teams" and check
that:
- Classification is `IN_SCOPE_PARLIAMENTARY` (fetches
  Parliament data)
- Synthesis mode is `strategic` (gets the analysis register)
- The answer contains `[analysis]`-tagged interpretation

---

## Test plan

Re-run all 8 test queries from the discussion thread and
confirm:

| Query | Expected class | Expected synth | Parliament |
|-------|---------------|----------------|------------|
| Section 23 | IN_SCOPE | factual | none |
| Duties of regulated services | IN_SCOPE | factual | none |
| Government position on age verification | PARLIAMENTARY | factual | WA + Hansard + Bills |
| Amended since Royal Assent | PARLIAMENTARY | factual | WA + Hansard + Bills |
| Select Committee on enforcement | PARLIAMENTARY | factual | WA + Hansard + Bills |
| Small platforms | STRATEGIC | strategic | WA + Hansard + Bills |
| Enforcement timeline risks | STRATEGIC | strategic | WA + Hansard + Bills |
| Select Committee implications | PARLIAMENTARY | **strategic** | WA + Hansard + Bills |

The last row is the edge case — parliamentary routing with
strategic synthesis.

Also run a consistency check: ask Strategic 1 ("How is the
implementation likely to affect small platforms?") twice and
compare the [analysis]-tagged claims. If they cite the same
evidence and reach similar conclusions, the strategic register
is grounded. If they diverge, it's making things up.

---

## What NOT to do

- Don't change the classification enum — we don't need a
  fourth category. The fix is in `needs_strategic_synthesis()`,
  not in the classifier.
- Don't change how Parliament data is fetched for strategic
  questions — that already works correctly.
- Don't touch the base system prompt or the evidence
  sufficiency gates — they're working well.
- Don't add the OpenAI API key or change retrieval mode —
  that's a separate concern Nick is handling.

---

## Definition of done

- [ ] Written Answers return data (not errors)
- [ ] Hansard returns data (not errors)
- [ ] "Advise on implications..." gets both Parliament data
      AND strategic synthesis
- [ ] Pure parliamentary questions ("Has it been amended?")
      still get factual synthesis
- [ ] All 8 test queries produce correct classification,
      synthesis mode, and Parliament source status
- [ ] Strategic consistency check passes (same question twice
      → same grounded analysis)
