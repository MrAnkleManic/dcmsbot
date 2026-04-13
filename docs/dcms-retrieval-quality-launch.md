# DCMS Bot — Retrieval Quality + Response Polish

## Purpose

BUILD thread for two related issues found during testing
on 13 April 2026. Both affect the quality of answers for
the bot's most impressive question types — exactly the
ones we'd show in a demo.

---

## Working directory
/Users/nickangel/Local/AI/bottl/dcms/

## Key files
- `backend/core/retriever.py` — BM25 scoring, authority
  weights, section locking
- `backend/core/evidence.py` — evidence pack assembly,
  diversification, citation building
- `backend/core/llm_synthesis.py` — system prompts, refusal
  handling
- `backend/config.py` — authority weights, MAX_CHUNKS_PER_DOC

---

## Issue 1: Enforcement documents crowd out debate sources

### What's happening

Questions like "How does Ofcom's approach to age assurance
compare with what Parliament intended?" produce weak answers
because the retriever returns mostly enforcement investigation
documents. There are 15+ enforcement docs about age assurance
investigations, each with high authority weight (10.0), and
they dominate the results. The parliamentary debate chunks
that discuss the *policy intent* behind "highly effective"
get pushed out.

The evidence pack ends up with 15 enforcement citations and
1 Hansard citation, when the question needs a balanced mix
of both.

### Why it happens

Two things combine:
1. **Authority weight for enforcement** is 10.0 (same as the
   Act itself). This was set high because enforcement docs
   are authoritative — but for comparison questions, debate
   sources matter more.
2. **MAX_CHUNKS_PER_DOC = 1** keeps diversity across documents,
   but all the enforcement docs are different documents about
   the same topic (different company investigations), so
   they each get their one slot.

### What to do

The fix isn't to lower enforcement authority — it's to ensure
source type diversity in the evidence pack. When building the
evidence pack, enforce a spread across source types, not just
across documents. For example: no more than 5 chunks from
any single source_type (Enforcement, Lords, Commons, etc.),
so that a question always gets a mix.

In `backend/core/evidence.py`, update `_diversify_by_document`
(or add a new `_diversify_by_source_type` pass) to cap chunks
per source_type. This should run after document diversification.

Suggested cap: 5 chunks per source_type, configurable via
config.py.

### How to verify

Run: "How does Ofcom's approach to age assurance compare with
what Parliament intended during the Bill's passage?"

Before fix: ~15 enforcement citations, ~1 debate citation.
After fix: a mix of enforcement, Ofcom guidance, Lords debates,
Commons debates, and Written Evidence.

---

## Issue 2: "Check other filters" is a bad suggestion

### What's happening

When the bot can't fully answer a question, it sometimes
suggests: "You might also want to check Parliamentary Debates
or Select Committee Evidence filters, as these could contain
more detailed discussion..."

This tells the user to go and search the KB manually — which
defeats the purpose of the bot. The bot should be doing that
search, not outsourcing it.

### Why it happens

The system prompt in `llm_synthesis.py` includes this
instruction (rule 4c):

```
c) If the evidence chunks come from only one or two source
types, suggest the user check whether other document filters
(e.g. Select Committee Evidence, Parliamentary Debates,
Regulator Guidance) might contain relevant material.
```

This was written when the bot was KB-only with user-controlled
filters. Now that the bot has automated retrieval and Parliament
integration, telling users to manually check filters is wrong.

### What to do

Replace rule 4c in `_BASE_SYSTEM_PROMPT` with something like:

```
c) If the evidence comes from a narrow range of source types,
note this limitation (e.g. "The evidence I found is primarily
from enforcement documents — parliamentary debates may offer
additional context on the policy intent"). Do NOT suggest the
user manually check filters or search other document types —
the system handles retrieval automatically.
```

The bot should acknowledge source gaps honestly but never tell
the user to do the bot's job.

### How to verify

Run any question where evidence is partial. The answer should
acknowledge gaps ("I found limited parliamentary material on
this topic") without suggesting the user manually navigate
the KB.

---

## Test plan

Re-run these questions after both fixes:

1. "How does Ofcom's approach to age assurance compare with
   what Parliament intended during the Bill's passage?"
   — Should produce a balanced answer with both Ofcom guidance
   and parliamentary debate sources.

2. "What impact did the Select Committee's scrutiny have on
   the final shape of the Act?"
   — Should pull committee reports, government responses,
   and debate sources, not just enforcement docs.

3. "What should a compliance team at a mid-sized platform
   be doing right now?"
   — Strategic question. Should get the [analysis] panel.
   Should NOT suggest checking other filters.

4. Any question that gets a partial answer — verify it
   doesn't tell the user to "check other filters."

---

## What NOT to do

- Don't change authority weights for enforcement documents —
  they're correctly weighted for enforcement questions.
- Don't remove the source type labels from citations.
- Don't change the strategic register or analysis tagging.
- Don't touch the section lock or adjacent chunk expansion.

---

## Definition of done

- [ ] Evidence pack includes a mix of source types, not
      dominated by one type
- [ ] Source type cap is configurable in config.py
- [ ] "Check other filters" language removed from system prompt
- [ ] Partial answers acknowledge gaps without outsourcing
      work to the user
- [ ] All 4 test questions produce balanced, well-sourced
      answers
