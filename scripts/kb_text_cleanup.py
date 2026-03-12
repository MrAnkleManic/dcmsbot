#!/usr/bin/env python3
"""
Post-processing text cleanup for existing KB JSON files.

Fixes common OCR / PDF extraction artifacts WITHOUT re-ingesting from source:
  - Spurious spaces within words: "En for cement" → "Enforcement"
  - Concatenated words: "theneedtogo" → (left alone — too risky without dictionary)
  - Broken hyphens: "regu- lation" → "regulation"

Usage:
    python scripts/kb_text_cleanup.py                      # Dry run (report only)
    python scripts/kb_text_cleanup.py --apply              # Apply fixes in-place
    python scripts/kb_text_cleanup.py --apply --doc DOC_140  # Fix one document
    python scripts/kb_text_cleanup.py --min-score 500      # Only fix high-artifact docs
"""

from __future__ import annotations

import argparse
import json
import glob
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


# ---------- Known OCR break patterns ----------
# These are safe to fix because the broken form is never valid English.

# Pattern: lowercase letter, space, 1-2 lowercase letters, space, lowercase
# e.g. "En for cement", "a pplied", "disin for mation"
# We use a replacement approach with a known-breaks dictionary for safety.

KNOWN_BREAKS = {
    # "broken form" → "correct form"
    # Space-insertion patterns (from audit)
    "En for cement": "Enforcement",
    "en for cement": "enforcement",
    "en for ce": "enforce",
    "En for ce": "Enforce",
    "In for mation": "Information",
    "in for mation": "information",
    "disin for mation": "disinformation",
    "Disin for mation": "Disinformation",
    "misin for mation": "misinformation",
    "Misin for mation": "Misinformation",
    "con for mance": "conformance",
    "Con for mance": "Conformance",
    "in for med": "informed",
    "per for mance": "performance",
    "Per for mance": "Performance",
    "rein for ce": "reinforce",
    "Rein for ce": "Reinforce",
    "trans for m": "transform",
    "Trans for m": "Transform",
    "plat for m": "platform",
    "Plat for m": "Platform",
    "plat for ms": "platforms",
    "Plat for ms": "Platforms",
    # Single-letter space breaks
    "a pplied": "applied",
    "a pplies": "applies",
    "a pply": "apply",
    "a pproach": "approach",
    "a ppropriate": "appropriate",
    "a ppear": "appear",
    "a ppoint": "appoint",
    "a ssess": "assess",
    "a ssured": "assured",
    "a ssist": "assist",
    "a mend": "amend",
    "a chiev": "achiev",
    "a ffect": "affect",
    "a gree": "agree",
    "a lready": "already",
    "a llow": "allow",
    "a lter": "alter",
    "a ccept": "accept",
    "a ccess": "access",
    "a ccount": "account",
    "a ccord": "accord",
    "a ccur": "accur",
    "a dopt": "adopt",
    "a dvis": "advis",
    "a ddress": "address",
    "a dequat": "adequat",
    "a ware": "aware",
    # Broken words with 'd ating', 'severit y' patterns
    "d ating": "dating",
    "severit y": "severity",
    "safet y": "safety",
    "liabilit y": "liability",
    "societ y": "society",
    "propert y": "property",
    "authorit y": "authority",
    "responsibilit y": "responsibility",
    "functionalit y": "functionality",
    "opportunit y": "opportunity",
    "communit y": "community",
    "activit y": "activity",
    "capabilit y": "capability",
    "accessibilit y": "accessibility",
    "penalt y": "penalty",
    "capacit y": "capacity",
    "clarit y": "clarity",
    "majorit y": "majority",
    "minorit y": "minority",
    "priorit y": "priority",
    "securit y": "security",
    "privac y": "privacy",
    "democrac y": "democracy",
    "transparen cy": "transparency",
    "consisten cy": "consistency",
    "efficien cy": "efficiency",
    "complian ce": "compliance",
    "guidan ce": "guidance",
    "eviden ce": "evidence",
    "resilien ce": "resilience",
    "dependen ce": "dependence",
    "confiden ce": "confidence",
    "intelligen ce": "intelligence",
    "S ubmission": "Submission",
    "s ubmission": "submission",
    "respond ing": "responding",
    "train ed": "trained",
    "Domestic a buse": "Domestic abuse",
    "domestic a buse": "domestic abuse",
    # Bill/legislation-specific
    "B i ll": "Bill",
    "b i ll": "bill",
}

# Regex for broken hyphens at line boundaries: "regu- lation" → "regulation"
RE_BROKEN_HYPHEN = re.compile(r"([a-z])-\s+([a-z])")


@dataclass
class CleanupResult:
    file_path: str
    doc_id: str
    title: str
    artifact_score: float | None
    chunks_fixed: int
    total_fixes: int
    sample_fixes: List[Tuple[str, str]]  # (before, after)


def _apply_known_breaks(text: str) -> Tuple[str, int]:
    """Replace known broken patterns. Returns (fixed_text, fix_count)."""
    fix_count = 0
    for broken, correct in KNOWN_BREAKS.items():
        if broken in text:
            count = text.count(broken)
            text = text.replace(broken, correct)
            fix_count += count
    return text, fix_count


def _fix_broken_hyphens(text: str) -> Tuple[str, int]:
    """Fix 'regu- lation' → 'regulation'. Returns (fixed_text, fix_count)."""
    fixes = RE_BROKEN_HYPHEN.findall(text)
    fix_count = len(fixes)
    if fix_count:
        text = RE_BROKEN_HYPHEN.sub(r"\1\2", text)
    return text, fix_count


def cleanup_file(filepath: str, apply: bool = False) -> CleanupResult | None:
    """Clean up a single KB JSON file."""
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    meta = data.get("metadata", {})
    doc_id = meta.get("id") or meta.get("doc_id") or "unknown"
    title = meta.get("title") or "untitled"
    artifact_score = meta.get("pdf_artifact_score")

    chunks = data.get("chunks", [])
    total_fixes = 0
    chunks_fixed = 0
    sample_fixes = []
    modified = False

    for chunk in chunks:
        text = chunk.get("text", "")
        original = text
        chunk_fixes = 0

        # Apply known break fixes
        text, n = _apply_known_breaks(text)
        chunk_fixes += n

        # Fix broken hyphens
        text, n = _fix_broken_hyphens(text)
        chunk_fixes += n

        if chunk_fixes > 0:
            total_fixes += chunk_fixes
            chunks_fixed += 1
            modified = True

            if len(sample_fixes) < 5:
                # Find a short diff example
                for broken, correct in KNOWN_BREAKS.items():
                    if broken in original:
                        idx = original.index(broken)
                        start = max(0, idx - 20)
                        end = min(len(original), idx + len(broken) + 20)
                        before = original[start:end].replace("\n", " ")
                        after = text[start:start + (end - start) + (len(correct) - len(broken))].replace("\n", " ")
                        sample_fixes.append((f"...{before}...", f"...{after}..."))
                        break

            if apply:
                chunk["text"] = text

    if apply and modified:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    if total_fixes == 0:
        return None

    return CleanupResult(
        file_path=filepath,
        doc_id=doc_id,
        title=title[:60],
        artifact_score=artifact_score,
        chunks_fixed=chunks_fixed,
        total_fixes=total_fixes,
        sample_fixes=sample_fixes,
    )


def main():
    parser = argparse.ArgumentParser(description="KB Text Cleanup")
    parser.add_argument("--kb-dir", default="processed_knowledge_base",
                        help="Path to knowledge base directory")
    parser.add_argument("--apply", action="store_true",
                        help="Apply fixes in-place (without this flag, dry run only)")
    parser.add_argument("--doc", default=None,
                        help="Only process a specific doc_id (e.g. DOC_140)")
    parser.add_argument("--min-score", type=float, default=0,
                        help="Only process docs with artifact score >= this value")

    args = parser.parse_args()

    files = glob.glob(os.path.join(args.kb_dir, "**/*.json"), recursive=True)
    results = []
    files_scanned = 0

    for filepath in files:
        if "embeddings_cache" in filepath:
            continue
        if ".cache" in filepath:
            continue

        # Filter by doc_id if specified
        if args.doc:
            try:
                with open(filepath) as f:
                    data = json.load(f)
                doc_id = data.get("metadata", {}).get("id", "")
                if doc_id != args.doc:
                    continue
            except Exception:
                continue

        # Filter by artifact score if specified
        if args.min_score > 0:
            try:
                with open(filepath) as f:
                    data = json.load(f)
                score = data.get("metadata", {}).get("pdf_artifact_score", 0)
                if (score or 0) < args.min_score:
                    continue
            except Exception:
                continue

        files_scanned += 1
        result = cleanup_file(filepath, apply=args.apply)
        if result:
            results.append(result)

    # Report
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"\n{'=' * 70}")
    print(f"KB TEXT CLEANUP — {mode}")
    print(f"{'=' * 70}")
    print(f"Files scanned: {files_scanned}")
    print(f"Files with fixes: {len(results)}")
    total_fixes = sum(r.total_fixes for r in results)
    total_chunks = sum(r.chunks_fixed for r in results)
    print(f"Total fixes: {total_fixes} across {total_chunks} chunks")

    if not args.apply:
        print(f"\nRun with --apply to write changes.")

    print()

    results.sort(key=lambda r: r.total_fixes, reverse=True)
    for r in results[:30]:
        print(f"  {r.doc_id:<12} {r.total_fixes:>4} fixes in {r.chunks_fixed:>4} chunks  "
              f"(score: {r.artifact_score or 'N/A':>6})  {r.title}")
        for before, after in r.sample_fixes[:2]:
            print(f"    BEFORE: {before}")
            print(f"    AFTER:  {after}")

    if args.apply:
        print(f"\n{'=' * 70}")
        print(f"IMPORTANT: Embeddings cache is now stale.")
        print(f"Run: .venv/bin/python scripts/generate_embeddings_cache.py")
        print(f"Or:  .venv/bin/python scripts/generate_embeddings_cache.py --incremental")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
