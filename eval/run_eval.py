import json
from pathlib import Path
from typing import Dict, List

import requests

BASE_URL = "http://localhost:8000"
QUESTIONS_PATH = Path(__file__).parent / "questions.json"
REPORT_PATH = Path(__file__).parent / "report.md"
KB_DIR = Path(__file__).parent.parent / "processed_knowledge_base"


def load_chunk_ids() -> List[str]:
    chunk_ids: List[str] = []
    for file_path in KB_DIR.rglob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                for idx, ch in enumerate(data.get("chunks", [])):
                    chunk_ids.append(ch.get("chunk_id") or f"{data['metadata'].get('id')}_{idx:04d}")
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to read {file_path}: {exc}")
    return chunk_ids


def evaluate_question(question: Dict, valid_chunk_ids: List[str]) -> Dict:
    payload = {
        "question": question["question"],
        "filters": {
            "primary_only": False,
            "include_guidance": True,
            "include_debates": False,
        },
        "debug": {"include_evidence_pack": False},
    }
    resp = requests.post(f"{BASE_URL}/query", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    citations = data.get("citations", [])
    refused = data.get("answer", {}).get("refused", False)
    refusal_reason = data.get("answer", {}).get("refusal_reason")

    errors: List[str] = []
    if question["expected"] == "answer":
        if refused:
            errors.append("Expected an answer but bot refused.")
        if len(citations) < 1:
            errors.append("Expected at least one citation.")
    else:
        if not refused:
            errors.append("Expected refusal for unanswerable question.")
        if not refusal_reason:
            errors.append("Refusal reason missing.")

    for c in citations:
        if c.get("chunk_id") not in valid_chunk_ids:
            errors.append(f"Citation chunk_id {c.get('chunk_id')} not found in KB.")

    return {
        "question": question["question"],
        "expected": question["expected"],
        "errors": errors,
        "refused": refused,
        "citation_count": len(citations),
    }


def write_report(results: List[Dict]) -> None:
    passed = [r for r in results if not r["errors"]]
    failed = [r for r in results if r["errors"]]

    lines = ["# Evaluation Report", "", f"Total: {len(results)}", f"Passed: {len(passed)}", f"Failed: {len(failed)}", ""]

    if failed:
        lines.append("## Failures")
        for item in failed:
            lines.append(f"- **Q:** {item['question']} (expected {item['expected']})")
            for err in item["errors"]:
                lines.append(f"  - {err}")
        lines.append("")

    lines.append("## Summary")
    for item in results:
        status = "PASS" if not item["errors"] else "FAIL"
        lines.append(f"- {status}: {item['question']} (citations: {item['citation_count']}, refused: {item['refused']})")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")


def main() -> None:
    valid_chunk_ids = load_chunk_ids()
    with QUESTIONS_PATH.open("r", encoding="utf-8") as f:
        questions = json.load(f)

    results: List[Dict] = []
    for q in questions:
        try:
            results.append(evaluate_question(q, valid_chunk_ids))
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "question": q["question"],
                    "expected": q["expected"],
                    "errors": [f"Exception during evaluation: {exc}"],
                    "refused": False,
                    "citation_count": 0,
                }
            )
    write_report(results)


if __name__ == "__main__":
    main()
