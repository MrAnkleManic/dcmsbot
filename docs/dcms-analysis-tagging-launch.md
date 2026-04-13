# DCMS Bot — Universal Analysis Tagging

## Purpose

BUILD thread. This is about the core product promise:
"AI that shows its working." Every answer must visibly
separate fact from interpretation. Currently, analysis
tagging only happens when the strategic register is
activated by keyword matching — which means analytical
content in "factual" answers blends invisibly into the
facts. That's the opposite of what we're selling.

---

## Working directory
/Users/nickangel/Local/AI/bottl/dcms/

## Key files
- `backend/core/llm_synthesis.py` — base system prompt
  and strategic supplement
- `backend/core/query_guard.py` — classification and
  strategic pattern matching
- `frontend-v2/src/components/AnswerPanel.jsx` — the
  [analysis] panel rendering (lightbulb icon, accent border)

---

## The principle

Any time the bot draws a conclusion that isn't a direct
quote or paraphrase from a cited source, that conclusion
must be visually marked as interpretation. This applies to
ALL answers, not just ones the classifier labels "strategic."

Examples of interpretation that should be tagged:

- "This pattern shows Ofcom prioritising child protection"
  — that's the bot identifying a pattern, not quoting a source
- "The delay suggests a cautious regulatory approach"
  — that's inference, not fact
- "Compliance teams should focus on risk assessments first"
  — that's advice derived from evidence, not a citation

Examples of fact that should NOT be tagged:

- "Section 12 sets out the duties to protect children" [C001]
  — direct citation
- "Ofcom opened 18 investigations covering 83 sites" [C009]
  — factual claim with source
- "The deadline was 16 March 2025" [C003]
  — stated fact from evidence

---

## What to change

### 1. Base system prompt (every answer)

In `_BASE_SYSTEM_PROMPT` in `llm_synthesis.py`, add a new
rule (after the existing rules) that applies to ALL answers:

```
8. IMPORTANT: If your answer includes ANY interpretive
content — conclusions you've drawn, patterns you've
identified, advice you're offering, or inferences beyond
what the sources directly state — wrap that content in
[analysis] and [/analysis] tags. This is not optional.
The frontend renders these as a visually distinct panel
so the reader can always tell what is sourced fact and
what is your interpretation. Even a single sentence of
interpretation should be tagged. If your answer is purely
factual with no interpretation, no tags are needed.
```

### 2. Strategic supplement (strategic answers)

The strategic supplement in `_STRATEGIC_SUPPLEMENT` should
no longer be the place where [analysis] tags are introduced
— the base prompt already handles that. Instead, the
supplement should focus on what it adds beyond tagging:

- Permission to go deeper with interpretation
- Policy-adviser register and tone
- Structured analysis (gaps, risks, what to watch for)
- The instruction to lead with facts, then analysis

Remove the [analysis] tag instructions from the supplement
since they're now in the base prompt. Keep everything else.

### 3. Strategic register role

After this change, the strategic register controls:
- **Depth** — how much interpretation to offer
- **Tone** — policy-adviser vs researcher
- **Structure** — gaps/risks/outlook sections

It does NOT control:
- **Whether analysis is tagged** — that's always on
- **Whether interpretation is allowed** — it's always
  allowed, the strategic register just encourages more of it

### 4. No changes to the frontend

The `AnswerPanel.jsx` already splits on [analysis]/[/analysis]
tags and renders the lightbulb panel. No frontend changes
needed — the same visual treatment applies regardless of
which mode generated the tags.

### 5. No changes to the classifier

The strategic patterns in `query_guard.py` still control
whether the strategic supplement is appended. They don't
need to be exhaustive any more — missing a strategic keyword
no longer means analysis goes untagged. It just means the
answer will have less interpretation overall, but whatever
interpretation it does include will still be tagged.

---

## Test plan

### Factual questions (should have minimal or no analysis)

- "What does Section 12 say about children's safety duties?"
  → Mostly factual. If the bot adds any interpretation,
  it should be tagged. If purely factual, no tags needed.

- "What are the duties of regulated services?"
  → Factual summary. Probably no analysis tags.

### Questions that look factual but produce interpretation

- "What patterns are emerging in how Ofcom prioritises
  its enforcement investigations?"
  → Currently classified as factual (despite "patterns" and
  "emerging"). The answer WILL contain interpretation
  (identifying patterns is inherently analytical). That
  interpretation must now be tagged even without the
  strategic register.

- "What enforcement action has Ofcom taken so far?"
  → Mostly factual, but if the bot draws conclusions about
  enforcement trends, those conclusions should be tagged.

### Strategic questions (should have substantial analysis)

- "What should a compliance team at a mid-sized platform
  be doing right now?"
  → Strategic register active. Should have a substantial
  [analysis] section with policy-adviser tone.

- "How is the implementation of the Online Safety Act
  likely to affect small platforms?"
  → Strategic register active. Deep analysis expected.

### The key test

Run "What patterns are emerging in how Ofcom prioritises
its enforcement investigations?" twice:

1. Before this change: no [analysis] tags, interpretation
   blended into facts invisibly.
2. After this change: interpretation wrapped in [analysis]
   tags, rendered in the lightbulb panel.

The factual content (specific investigations, dates, numbers)
should remain outside the tags. The pattern identification
and conclusions should be inside them.

---

## What NOT to do

- Don't make every answer have an analysis section — purely
  factual answers ("What does Section 23 say?") should have
  no tags at all.
- Don't remove the strategic supplement — it still controls
  depth and tone for genuinely strategic questions.
- Don't change the frontend — it already handles the tags.
- Don't try to make the classifier perfect — the whole point
  of this change is that tagging doesn't depend on
  classification any more.

---

## Definition of done

- [ ] Base system prompt instructs [analysis] tagging on
      ALL answers, not just strategic ones
- [ ] Strategic supplement focuses on depth/tone, not tag
      introduction
- [ ] Factual questions with no interpretation produce no
      tags (clean pass-through)
- [ ] Factual questions that happen to contain interpretation
      produce tagged interpretation
- [ ] Strategic questions produce substantial tagged analysis
- [ ] The lightbulb panel appears on any answer that contains
      interpretation, regardless of classification
