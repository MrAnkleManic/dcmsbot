#!/usr/bin/env python3
"""
KB Quality Audit — scan processed_knowledge_base for text quality issues.

Produces a ranked report of documents with the worst OCR / extraction
artifacts, with sample broken text and actionable remediation suggestions.

Usage:
    python scripts/kb_quality_audit.py                    # Full report
    python scripts/kb_quality_audit.py --top 20           # Top 20 worst
    python scripts/kb_quality_audit.py --format csv       # CSV output
    python scripts/kb_quality_audit.py --category 01      # Filter by category
    python scripts/kb_quality_audit.py --fix-candidates   # Only show fixable docs
"""

import argparse
import csv
import json
import glob
import io
import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------- artifact detection heuristics ----------

# Words broken by spurious spaces: "En for cement", "disin for mation", "a pplied"
RE_SPACE_BREAK = re.compile(
    r"""(?<=[a-z])           # preceded by lowercase
        \s                   # spurious space
        ([a-z]{1,3})         # 1-3 letter fragment
        \s                   # another spurious space
        (?=[a-z])            # followed by lowercase
    """,
    re.VERBOSE,
)

# Concatenated words: 15+ lowercase chars with no spaces (normal English maxes ~14)
RE_CONCAT = re.compile(r"[a-z]{15,}")

# Garbled characters / encoding issues
RE_GARBLE = re.compile(r"[^\x20-\x7E\n\r\t£€§±°²³àáâãäåæçèéêëìíîïðñòóôõöùúûüýþÿ]")

# Broken hyphenation at line boundaries: "regu-\nlation" -> "regu- lation"
RE_BROKEN_HYPHEN = re.compile(r"[a-z]-\s+[a-z]")


@dataclass
class ChunkIssue:
    chunk_id: str
    issue_type: str  # space_break | concat | garble | broken_hyphen
    sample: str      # surrounding context


@dataclass
class DocReport:
    doc_id: str
    title: str
    category: str
    source_type: str
    source_format: str
    artifact_score: Optional[float]
    url: str
    total_chunks: int
    affected_chunks: int
    issues: List[ChunkIssue] = field(default_factory=list)

    @property
    def severity(self) -> str:
        if self.artifact_score and self.artifact_score > 500:
            return "HIGH"
        elif self.artifact_score and self.artifact_score > 200:
            return "MEDIUM"
        elif self.affected_chunks > 0:
            return "LOW"
        return "CLEAN"

    @property
    def remediation(self) -> str:
        if self.source_format.startswith("PDF"):
            if self.artifact_score and self.artifact_score > 500:
                return "RE-INGEST: Try alternative PDF extractor (pymupdf_words) or source HTML version"
            elif self.artifact_score and self.artifact_score > 200:
                return "RE-INGEST: Try pdfplumber text mode or manual cleanup"
            return "MINOR: Acceptable quality, cosmetic fixes only"
        elif self.source_format == "HTML":
            return "CHECK: HTML source should be clean — verify BotCleaner HTML parsing"
        return "INVESTIGATE: Unknown source format"

    @property
    def sort_key(self) -> float:
        """Higher = worse quality."""
        return (self.artifact_score or 0) + self.affected_chunks * 10


def _context(text: str, match: re.Match, radius: int = 40) -> str:
    """Extract context around a regex match."""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    ctx = text[start:end].replace("\n", " ").strip()
    return f"...{ctx}..."


def audit_chunk(chunk_id: str, text: str, max_samples: int = 3) -> List[ChunkIssue]:
    """Detect quality issues in a single chunk."""
    issues = []

    for m in RE_SPACE_BREAK.finditer(text):
        if len(issues) < max_samples:
            issues.append(ChunkIssue(chunk_id, "space_break", _context(text, m)))

    for m in RE_CONCAT.finditer(text):
        word = m.group()
        # Filter out URLs, email-like strings, known long words
        if any(skip in word for skip in ("http", "www", "@", "committee", "parliamentary")):
            continue
        if len(issues) < max_samples:
            issues.append(ChunkIssue(chunk_id, "concat", _context(text, m, 50)))

    for m in RE_GARBLE.finditer(text):
        if len(issues) < max_samples:
            issues.append(ChunkIssue(chunk_id, "garble", _context(text, m, 30)))

    return issues


def audit_file(filepath: str) -> Optional[DocReport]:
    """Audit a single KB JSON file."""
    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    meta = data.get("metadata", {})
    doc_id = meta.get("id") or meta.get("doc_id") or "unknown"
    title = meta.get("title") or "untitled"

    # Derive category from filepath
    parts = filepath.split("/")
    category = ""
    for p in parts:
        if p.startswith(("01_", "02_", "03_", "04_")):
            category = p
            break

    # Derive source format
    pdf_ext = meta.get("pdf_extractor_used")
    if pdf_ext:
        source_format = f"PDF ({pdf_ext})"
    elif meta.get("encoding"):
        source_format = "HTML"
    else:
        source_format = "Unknown"

    chunks = data.get("chunks", [])
    all_issues = []
    affected_set = set()

    for chunk in chunks:
        text = chunk.get("text", "")
        chunk_id = chunk.get("chunk_id", "unknown")
        issues = audit_chunk(chunk_id, text)
        if issues:
            affected_set.add(chunk_id)
            all_issues.extend(issues)

    return DocReport(
        doc_id=doc_id,
        title=title[:80],
        category=category,
        source_type=meta.get("type") or meta.get("source_type") or "Unknown",
        source_format=source_format,
        artifact_score=meta.get("pdf_artifact_score"),
        url=meta.get("url") or "",
        total_chunks=len(chunks),
        affected_chunks=len(affected_set),
        issues=all_issues[:10],  # cap at 10 sample issues per doc
    )


def run_audit(
    kb_dir: str,
    top_n: int = 50,
    category_filter: str = "",
    fix_candidates_only: bool = False,
) -> List[DocReport]:
    """Scan all KB JSON files and return ranked quality reports."""
    files = glob.glob(os.path.join(kb_dir, "**/*.json"), recursive=True)
    reports = []

    for filepath in files:
        if "embeddings_cache" in filepath:
            continue
        if category_filter and category_filter not in filepath:
            continue

        report = audit_file(filepath)
        if report:
            if fix_candidates_only and report.severity == "CLEAN":
                continue
            reports.append(report)

    reports.sort(key=lambda r: r.sort_key, reverse=True)
    return reports[:top_n]


def format_text(reports: List[DocReport]) -> str:
    """Format reports as readable text."""
    lines = []
    lines.append("=" * 80)
    lines.append("KB QUALITY AUDIT REPORT")
    lines.append("=" * 80)

    total = len(reports)
    high = sum(1 for r in reports if r.severity == "HIGH")
    medium = sum(1 for r in reports if r.severity == "MEDIUM")
    low = sum(1 for r in reports if r.severity == "LOW")
    clean = sum(1 for r in reports if r.severity == "CLEAN")

    lines.append(f"\nDocuments scanned: {total}")
    lines.append(f"  HIGH severity:   {high}")
    lines.append(f"  MEDIUM severity: {medium}")
    lines.append(f"  LOW severity:    {low}")
    lines.append(f"  CLEAN:           {clean}")
    lines.append("")

    for i, r in enumerate(reports, 1):
        if r.severity == "CLEAN":
            continue

        lines.append("-" * 80)
        lines.append(f"#{i}  [{r.severity}]  {r.doc_id} — {r.title}")
        lines.append(f"    Category:       {r.category}")
        lines.append(f"    Source type:     {r.source_type}")
        lines.append(f"    Source format:   {r.source_format}")
        lines.append(f"    Artifact score:  {r.artifact_score or 'N/A'}")
        lines.append(f"    Chunks:          {r.affected_chunks}/{r.total_chunks} affected")
        lines.append(f"    Has URL:         {'Yes' if r.url else 'No'}")
        lines.append(f"    Remediation:     {r.remediation}")

        if r.issues:
            lines.append(f"    Sample issues:")
            for issue in r.issues[:5]:
                lines.append(f"      [{issue.issue_type}] {issue.sample}")

        lines.append("")

    return "\n".join(lines)


def format_csv(reports: List[DocReport]) -> str:
    """Format reports as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "rank", "severity", "doc_id", "title", "category", "source_type",
        "source_format", "artifact_score", "affected_chunks", "total_chunks",
        "has_url", "remediation", "sample_issue",
    ])

    for i, r in enumerate(reports, 1):
        sample = r.issues[0].sample if r.issues else ""
        writer.writerow([
            i, r.severity, r.doc_id, r.title, r.category, r.source_type,
            r.source_format, r.artifact_score or "", r.affected_chunks,
            r.total_chunks, "Yes" if r.url else "No", r.remediation, sample,
        ])

    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description="KB Quality Audit")
    parser.add_argument("--kb-dir", default="processed_knowledge_base",
                        help="Path to knowledge base directory")
    parser.add_argument("--top", type=int, default=50,
                        help="Show top N worst documents")
    parser.add_argument("--format", choices=["text", "csv"], default="text",
                        help="Output format")
    parser.add_argument("--category", default="",
                        help="Filter by category prefix (e.g. '01' for Legislation)")
    parser.add_argument("--fix-candidates", action="store_true",
                        help="Only show documents that need fixing")
    parser.add_argument("--output", default=None,
                        help="Write output to file instead of stdout")

    args = parser.parse_args()

    reports = run_audit(
        kb_dir=args.kb_dir,
        top_n=args.top,
        category_filter=args.category,
        fix_candidates_only=args.fix_candidates,
    )

    if args.format == "csv":
        output = format_csv(reports)
    else:
        output = format_text(reports)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
