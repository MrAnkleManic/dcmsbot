# DCMS Evidence Bot Demo Script

## Preflight (5 minutes before call)

Run these checks:

```bash
fly status -a nickangel
curl -sS https://nickangel.fly.dev/api/status | python3 -m json.tool | head -n 40
curl -sS https://nickangel.fly.dev/api/readyz
```

Confirm:
- one machine is `started` (or two if you intentionally scaled up),
- `kb_loaded` is `true`,
- `total_chunks` is `28548`,
- `retrieval_mode` is `bm25`,
- `/api/readyz` returns `status: "ready"`.

## Demo Flow (10–15 minutes)

## 1) Baseline legal definition
Ask:
- `How does the Act define illegal content?`

What to point out:
- grounded citations,
- explicit limits when full statutory wording is not in retrieved chunks.

## 2) Enforcement powers
Ask:
- `What enforcement powers does Ofcom have under the Act?`

What to point out:
- multi-source synthesis from Act + explanatory + guidance material.

## 3) Scope distinction
Ask:
- `What is the difference between user-to-user services and search services duties?`

What to point out:
- structured comparative answer with evidence citations.

## 4) Section-specific precision
Ask:
- `What does section 59 say?`

What to point out:
- section-targeted retrieval behavior and confidence label.

## 5) Practical regulator angle
Ask:
- `How does Ofcom guidance describe highly effective age assurance?`

What to point out:
- regulator guidance integration, not just statute text.

## 6) Refusal behavior (safety)
Ask:
- `Who won the Premier League in 2024?`

What to point out:
- clear out-of-scope refusal,
- no hallucinated legal answer.

## 7) Filter awareness
In settings, disable `Regulator Guidance`, then ask:
- `What does Ofcom say about record-keeping for online safety compliance?`

What to point out:
- weaker/partial answer with suggestions.
Then re-enable and rerun to show stronger retrieval.

## 8) Share workflow
After a good answer:
- click `Copy to Clipboard`,
- click `Email This Answer`.

What to point out:
- immediate handoff into legal team workflow.

## Backup Questions (if one underperforms)
- `What duties apply to illegal content risk assessments?`
- `How does the Act treat CSEA content in illegal content duties?`
- `What powers does the Secretary of State have to direct Ofcom, and what are the limits?`

## Recovery Commands During Demo

If app feels slow or stale:

```bash
fly apps restart nickangel
```

If you want temporary redundancy for a high-stakes session:

```bash
fly scale count 2 -a nickangel
```

After session (cost control):

```bash
fly scale count 1 -a nickangel
```
