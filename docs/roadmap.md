# DCMS Evidence Bot — Roadmap

Last updated: 9 April 2026

## What's working

- **KB retrieval** — 28,548 chunks across 23 source types. BM25
  retrieval producing good results. Hybrid (BM25 + embeddings)
  available once OpenAI key is added.
- **LLM synthesis** — factual and strategic registers both
  producing grounded, cited answers. No hallucination observed.
- **Query guard** — routing factual/strategic/parliamentary
  questions correctly. Plurals fixed (risks/risk). Definition
  mode tightened.
- **Evidence sufficiency gates** — refusing when evidence is
  weak, not refusing when answer is substantive but hedged.
- **Citation system** — KB [C###], Written Answers [WA###],
  Hansard [H###], Bills [B###] all working with titles and URLs.
- **Parliament integration** — Bills API returning data. Written
  Answers and Hansard APIs connected (date_to fix applied).
- **Strategic register** — [analysis] tags appearing on
  strategic questions, grounded in cited evidence. Decoupled
  from parliamentary classification. Edge case (parliamentary +
  strategic) handled via pattern check.
- **Refusal detection** — long substantive answers no longer
  falsely flagged as refusals.

## Fixed this session (8-9 April 2026)

1. `load_dotenv(override=True)` — API key wasn't loading
   because shell had empty ANTHROPIC_API_KEY
2. `\brisk\b` → `\brisks?\b` — plural matching
3. "what is" definition pattern tightened — no longer triggers
   on "what is the government's position"
4. `needs_strategic_synthesis()` decoupled from parliamentary
   classification, with pattern-based fallback for edge cases
5. `bottl-commons` installed + `beautifulsoup4` dependency
6. `date_to` added to Written Answers and Hansard API calls
7. `synthesis_mode` in app.py now uses `needs_strategic_synthesis()`
   instead of hardcoding "strategic" for parliament queries
8. Refusal detection: removed "however" as qualifier, added
   800-char length check so substantive answers aren't flagged
9. Written Answer titles: using question_text instead of empty
   "title" field
10. Bill URLs: using bill ID instead of hardcoded search URL
11. Search term ordering: base terms first, not randomised by set()
12. Written Answers filtered by DCMS/DSIT answering body —
    no more irrelevant results about carers, education etc.
13. Analytics refusal now suggests a rephrased question
14. Section lock expanded to fetch adjacent chunks from the KB —
    Section 12 now returns the actual duties, not just the heading

## Current issues — to fix

### High priority

- [ ] **Analysis tagging must be universal** — the [analysis]
  tags currently only appear when the strategic register is
  activated by keyword matching. But any answer can contain
  interpretation, and the line between fact and analysis must
  ALWAYS be visible. This is core to the "AI that shows its
  working" pitch. Fix: move the [analysis] tagging instruction
  into the base system prompt so every answer separates fact
  from interpretation, regardless of classification. The
  strategic supplement controls depth of analysis, not whether
  analysis is tagged.

- [x] **Written Answers returning noise** — FIXED: filtered by
  DCMS/DSIT answering body in parliament_fetch.py.

- [x] **Analytics refusal too terse** — FIXED: now suggests
  rephrasing with a concrete example.

- [x] **Section 12 retrieval weak** — FIXED: section lock now
  fetches adjacent chunks from the KB when a section match is
  found. Root cause: continuation chunks had no section_number
  metadata, and MAX_CHUNKS_PER_DOC=1 dropped all but the intro.
  Fix: adjacent chunk expansion + per-doc limit raised to 5
  when section-locked.

### Medium priority

- [ ] **LLM doesn't know today's date** — deadlines like
  "16 March 2025" are quoted without noting they've already
  passed. Fix: inject today's date into the system prompt so
  the LLM can contextualise timelines (e.g. "this deadline
  has now passed" vs "this is upcoming").

- [ ] **Written Answers search too slow** — 15s for a single
  topic search. Consider parallel fetching of WA + Hansard,
  or per-source timeouts.

- [ ] **Age assurance comparison retrieval** — "How does
  Ofcom's approach compare with Parliament's intent?" produces
  a weak answer because enforcement documents crowd out the
  parliamentary debate chunks. Need to adjust retrieval ranking
  or boost debate sources for comparison questions.

- [ ] **Hansard returning 0 results** — connected and searching
  but finding nothing. May need broader search terms or
  different date range.

- [ ] **Category 1 answers don't mention register not yet
  published** — the bot discusses Category 1 duties as if
  they're in effect, but no service has been categorised yet
  (expected July 2026). The "what's coming next" answer gets
  this right but the Category 1 duty answers don't.

- [ ] **Frontend not displaying Parliament sources distinctly**
  — no visual difference between KB and Parliament citations.
  No freshness indicators. No synthesis mode badge.

### Low priority / future

- [ ] **Embeddings not active** — waiting for OpenAI API key.
  Hybrid retrieval would improve result quality.

- [ ] **Reusability** — parliament_fetch.py hardcodes DCMS
  answering bodies and search terms. Extract to config for
  FCA/NHS reuse.

- [ ] **No Ofcom API** — Ofcom has no online safety data API.
  Best source remains scraping their publications into the KB.

## Decisions made

1. **No manual strategic toggle** — auto-detection from question
   phrasing. Users shouldn't have to pick a mode.

2. **KB is the foundation, Parliament is supplementary** — the
   bot is a knowledge retrieval product that also uses Parliament
   data, not a Parliament search tool.

3. **Discussion threads vs build threads** — thinking before
   building. Launch prompts in docs/ for implementation work.

4. **Bot Clean workflow still needed** — Parliament API only
   covers Written Answers, Hansard, and bill metadata. The full
   Act text, Ofcom guidance, committee evidence, impact
   assessments etc. all require document chunking.

## Test results summary

See docs/testing/testing-2.md for full results.

**Strong answers:**
- Enforcement patterns — named investigations, three programmes
- Age assurance enforcement — 8 named companies, penalty framework
- Small platform compliance — practical with [analysis] tag
- What's coming next — timeline with strategic observation
- Category 1 duties — 17 citations across 7 source types

**Weak answers:**
- Section 12 — only intro chunk, no substance
- Written Answers — 9/10 irrelevant to online safety
- Category 1 comparisons — missing "not yet categorised" context
