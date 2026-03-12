"""Quality evaluation harness: scores bot answers against gold-standard summaries.

Usage:
    python -m eval.run_quality_eval            # run against localhost:8000
    python -m eval.run_quality_eval --base-url http://example.com

Requires the server to be running.  Produces eval/quality_report.md with
per-question token-overlap scores and an aggregate summary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests

BASE_URL_DEFAULT = "http://localhost:8000"
GOLD_PATH = Path(__file__).resolve().parent.parent / "backend" / "config" / "gold_summaries.json"
REPORT_PATH = Path(__file__).resolve().parent / "quality_report.md"

# ---------------------------------------------------------------------------
# Token-overlap scoring (no external ML dependencies required)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")
_STOPWORDS: Set[str] = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "how", "i", "in", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "them", "this", "to", "was", "were", "what",
    "when", "where", "which", "who", "will", "with",
}


def _content_tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) > 2]


def _token_set(text: str) -> Set[str]:
    return set(_content_tokens(text))


def token_precision(candidate: str, reference_sentences: List[str]) -> float:
    """What fraction of the candidate's content tokens appear in the gold text."""
    cand_tokens = _token_set(candidate)
    ref_tokens = _token_set(" ".join(reference_sentences))
    if not cand_tokens:
        return 0.0
    return len(cand_tokens & ref_tokens) / len(cand_tokens)


def token_recall(candidate: str, reference_sentences: List[str]) -> float:
    """What fraction of the gold text's content tokens appear in the candidate."""
    cand_tokens = _token_set(candidate)
    ref_tokens = _token_set(" ".join(reference_sentences))
    if not ref_tokens:
        return 0.0
    return len(cand_tokens & ref_tokens) / len(ref_tokens)


def token_f1(candidate: str, reference_sentences: List[str]) -> float:
    p = token_precision(candidate, reference_sentences)
    r = token_recall(candidate, reference_sentences)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def sentence_recall(candidate: str, reference_sentences: List[str]) -> float:
    """What fraction of gold sentences have at least one key-term hit in the answer."""
    if not reference_sentences:
        return 0.0
    cand_tokens = _token_set(candidate)
    hits = 0
    for sentence in reference_sentences:
        sentence_tokens = _token_set(sentence)
        # A sentence counts as "covered" if ≥50% of its content tokens appear
        if not sentence_tokens:
            hits += 1
            continue
        overlap = len(cand_tokens & sentence_tokens) / len(sentence_tokens)
        if overlap >= 0.5:
            hits += 1
    return hits / len(reference_sentences)


# ---------------------------------------------------------------------------
# Gold questions: map gold summary keys to natural-language queries
# ---------------------------------------------------------------------------

GOLD_QUESTIONS: Dict[str, str] = {
    "section_64": "What does section 64 of the Online Safety Act say about user identity verification?",
}


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------

def query_bot(base_url: str, question: str) -> dict:
    payload = {
        "question": question,
        "filters": {"primary_only": False, "include_guidance": True, "include_debates": True},
        "debug": {"include_evidence_pack": False},
        "use_llm": True,
    }
    resp = requests.post(f"{base_url}/query", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def evaluate_gold(base_url: str) -> List[dict]:
    with GOLD_PATH.open("r", encoding="utf-8") as f:
        gold_data = json.load(f)

    results: List[dict] = []
    for key, entry in gold_data.items():
        question = GOLD_QUESTIONS.get(key)
        if not question:
            print(f"  ⚠  No question mapped for gold key '{key}', skipping")
            continue

        gold_sentences = entry["sentences"]
        source_section = entry.get("source_section", key)

        print(f"  → Evaluating: {question}")
        try:
            response = query_bot(base_url, question)
        except Exception as exc:
            results.append({
                "key": key,
                "question": question,
                "source_section": source_section,
                "error": str(exc),
                "refused": True,
                "answer_text": "",
                "citation_count": 0,
                "token_precision": 0.0,
                "token_recall": 0.0,
                "token_f1": 0.0,
                "sentence_recall": 0.0,
            })
            continue

        answer_text = response.get("answer", {}).get("text", "")
        refused = response.get("answer", {}).get("refused", False)
        citations = response.get("citations", [])

        results.append({
            "key": key,
            "question": question,
            "source_section": source_section,
            "error": None,
            "refused": refused,
            "answer_text": answer_text,
            "citation_count": len(citations),
            "token_precision": token_precision(answer_text, gold_sentences),
            "token_recall": token_recall(answer_text, gold_sentences),
            "token_f1": token_f1(answer_text, gold_sentences),
            "sentence_recall": sentence_recall(answer_text, gold_sentences),
        })

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def write_report(results: List[dict]) -> None:
    lines = [
        "# Quality Evaluation Report",
        "",
        "Compares bot answers against gold-standard summaries using token-overlap metrics.",
        "",
        "| Metric | Description |",
        "|--------|-------------|",
        "| **Token Precision** | % of answer's content words that appear in gold text (penalises hallucination) |",
        "| **Token Recall** | % of gold text's content words that appear in answer (penalises omission) |",
        "| **Token F1** | Harmonic mean of precision and recall |",
        "| **Sentence Recall** | % of gold sentences with ≥50% key-term coverage in answer |",
        "",
    ]

    scored = [r for r in results if not r.get("error") and not r["refused"]]
    errored = [r for r in results if r.get("error")]
    refused = [r for r in results if r["refused"] and not r.get("error")]

    if scored:
        avg_f1 = sum(r["token_f1"] for r in scored) / len(scored)
        avg_sr = sum(r["sentence_recall"] for r in scored) / len(scored)
        lines.append(f"## Aggregate ({len(scored)} scored, {len(refused)} refused, {len(errored)} errors)")
        lines.append("")
        lines.append(f"- **Average Token F1:** {avg_f1:.2%}")
        lines.append(f"- **Average Sentence Recall:** {avg_sr:.2%}")
        lines.append("")

    lines.append("## Per-question results")
    lines.append("")

    for r in results:
        status = "❌ ERROR" if r.get("error") else ("⚠️ REFUSED" if r["refused"] else "✅ ANSWERED")
        lines.append(f"### {r['source_section']} — {status}")
        lines.append(f"**Q:** {r['question']}")
        lines.append("")
        if r.get("error"):
            lines.append(f"Error: `{r['error']}`")
        elif r["refused"]:
            lines.append(f"Bot refused to answer. Refusal text: _{r['answer_text'][:200]}_")
        else:
            lines.append(f"| Metric | Score |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Token Precision | {r['token_precision']:.2%} |")
            lines.append(f"| Token Recall | {r['token_recall']:.2%} |")
            lines.append(f"| Token F1 | {r['token_f1']:.2%} |")
            lines.append(f"| Sentence Recall | {r['sentence_recall']:.2%} |")
            lines.append(f"| Citations | {r['citation_count']} |")
            lines.append("")
            # Show first 300 chars of answer for quick review
            preview = r["answer_text"][:300].replace("\n", " ")
            lines.append(f"**Answer preview:** {preview}...")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📝 Report written to {REPORT_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Quality eval against gold summaries")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT, help="Bot API base URL")
    args = parser.parse_args()

    print(f"Running quality eval against {args.base_url}")
    print(f"Gold summaries: {GOLD_PATH}")
    results = evaluate_gold(args.base_url)
    write_report(results)

    # Exit with non-zero if any scored question has F1 < 0.30
    scored = [r for r in results if not r.get("error") and not r["refused"]]
    if scored:
        worst_f1 = min(r["token_f1"] for r in scored)
        if worst_f1 < 0.30:
            print(f"\n⚠  Worst Token F1 = {worst_f1:.2%} (below 0.30 threshold)")
            sys.exit(1)
    print("\n✅ All scored questions above minimum quality threshold.")


if __name__ == "__main__":
    main()
