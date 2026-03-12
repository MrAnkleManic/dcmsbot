import glob as glob_mod
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from backend import config
from backend.core.doc_types import canonical_doc_type
from backend.core.models import KBChunk, KBStatus
from backend.logging_config import get_logger

logger = get_logger(__name__)


_BROKEN_ARTIFACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*\"\)\s*$"), "**"),
    (re.compile(r"\)\s*\""), ")"),
    (re.compile(r"\"(?=\))"), ""),
    (re.compile(r"\)\)"), ")"),
    (re.compile(r"\*\*\)\s*$"), "**"),
]


def _clean_chunk_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    for pattern, replacement in _BROKEN_ARTIFACT_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


class KnowledgeBase:
    def __init__(self) -> None:
        self.chunks: List[KBChunk] = []
        self.validation_errors: List[str] = []
        self.doc_counts_by_type: Dict[str, int] = {}
        self.doc_counts_by_raw_type: Dict[str, int] = {}
        self.chunk_counts_by_type: Dict[str, int] = {}
        self.guidance_source_counts: Dict[str, int] = {}
        self.last_refreshed: Optional[datetime] = None
        self.ingestion_summary: Dict[str, int] = {}

    def load(self, kb_dir: Path = config.KB_DIR) -> None:
        self.chunks.clear()
        self.validation_errors.clear()
        self.doc_counts_by_type.clear()
        self.doc_counts_by_raw_type.clear()
        self.chunk_counts_by_type.clear()
        self.guidance_source_counts.clear()
        self.ingestion_summary = {}
        self.last_refreshed = None

        if not kb_dir.exists():
            self.validation_errors.append(f"KB path not found: {kb_dir}")
            logger.error("Knowledge base path missing", extra={"path": str(kb_dir)})
            return

        seen_chunk_ids: Set[str] = set()
        parse_failures = 0
        missing_meta = 0
        missing_text = 0
        duplicate_chunks = 0

        # Use glob (not pathlib.rglob) because rglob doesn't follow symlinks.
        # The KB category dirs may be symlinked to BotCleaner's output.
        files = [Path(p) for p in glob_mod.glob(str(kb_dir / "**" / "*.json"), recursive=True)]
        for file_path in files:
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                doc_chunks, errors = self._extract_chunks(data, file_path)
                if any("Missing doc_id/title" in err for err in errors):
                    missing_meta += 1
                missing_text_errors = [err for err in errors if "Missing text" in err]
                missing_text += len(missing_text_errors)
                for err in errors:
                    self.validation_errors.append(err)
                for ch in doc_chunks:
                    if ch.chunk_id in seen_chunk_ids:
                        dedup_error = f"Duplicate chunk_id {ch.chunk_id} in {file_path}"
                        self.validation_errors.append(dedup_error)
                        logger.warning(dedup_error)
                        duplicate_chunks += 1
                        continue
                    seen_chunk_ids.add(ch.chunk_id)
                    self.chunks.append(ch)
            except Exception as exc:  # noqa: BLE001
                err = f"Failed to parse {file_path}: {exc}"
                self.validation_errors.append(err)
                parse_failures += 1
                logger.exception(err)

        self._rebuild_inventory()
        self.last_refreshed = datetime.utcnow()
        skipped_total = parse_failures + missing_meta + missing_text + duplicate_chunks
        self.ingestion_summary = {
            "files_found": len(files),
            "loaded_chunks": len(self.chunks),
            "loaded_documents": sum(self.doc_counts_by_type.values()),
            "skipped_total": skipped_total,
            "skipped_parse_errors": parse_failures,
            "skipped_missing_meta": missing_meta,
            "skipped_missing_text": missing_text,
            "skipped_duplicate_chunks": duplicate_chunks,
        }
        logger.info(
            "KB load: found %s files, loaded %s, skipped %s (parse %s, missing_text %s, missing_meta %s, dup_chunks %s)",
            len(files),
            len(self.chunks),
            skipped_total,
            parse_failures,
            missing_text,
            missing_meta,
            duplicate_chunks,
            extra={
                "path": str(kb_dir),
                "chunks": len(self.chunks),
                "errors": len(self.validation_errors),
                "ingestion_summary": self.ingestion_summary,
            },
        )

    def _extract_chunks(self, data: dict, file_path: Path) -> Tuple[List[KBChunk], List[str]]:
        errors: List[str] = []
        doc_chunks: List[KBChunk] = []
        metadata = data.get("metadata", {})
        doc_id = metadata.get("doc_id") or metadata.get("id")
        title = metadata.get("title")
        source_type = metadata.get("type") or metadata.get("source_type") or "Other"
        publisher = metadata.get("author") or metadata.get("publisher") or "Unknown"
        date_published = metadata.get("date") or metadata.get("date_published")
        authority_weight = metadata.get("authority_weight") or config.AUTHORITY_WEIGHTS.get(
            source_type, config.AUTHORITY_WEIGHTS.get("Other", 1.0)
        )
        reliability_flags = metadata.get("reliability_flags")
        source_url = metadata.get("url") or metadata.get("source_url")

        # Derive source format for troubleshooting
        pdf_extractor = metadata.get("pdf_extractor_used")
        if pdf_extractor:
            source_format = f"PDF ({pdf_extractor})"
        elif metadata.get("encoding"):
            source_format = "HTML"
        else:
            source_format = "Unknown"

        if not doc_id or not title:
            errors.append(f"Missing doc_id/title in {file_path}")
            return doc_chunks, errors

        chunks = data.get("chunks") or []
        for idx, chunk in enumerate(chunks):
            raw_text = chunk.get("text")
            if not raw_text:
                errors.append(f"Missing text for chunk {idx} in {file_path}")
                continue
            chunk_text = _clean_chunk_text(raw_text)

            # Extract core fields
            header = chunk.get("header")
            page = chunk.get("page")

            # BotCleaner extended fields (bottl KB Standard v1.0)
            speaker = chunk.get("speaker")
            turn_index = chunk.get("turn_index")
            column_ref = chunk.get("column_ref")
            section_number = chunk.get("section_number")
            prev_chunk_id = chunk.get("prev_chunk_id")
            next_chunk_id = chunk.get("next_chunk_id")
            chunk_hash = chunk.get("chunk_hash")

            # Generate location_pointer (bottl KB Standard v1.0 compliant)
            location_pointer = chunk.get("location_pointer")
            if not location_pointer:
                location_pointer = self._generate_location_pointer(
                    header=header,
                    page=page,
                    column_ref=column_ref,
                    section_number=section_number,
                    source_type=source_type,
                )

            chunk_id = chunk.get("chunk_id") or f"{doc_id}_{idx:04d}"
            try:
                doc_chunks.append(
                    KBChunk(
                        doc_id=doc_id,
                        title=title,
                        source_type=source_type,
                        publisher=publisher,
                        date_published=date_published,
                        chunk_id=chunk_id,
                        chunk_text=chunk_text,
                        header=header,
                        location_pointer=location_pointer,
                        authority_weight=authority_weight,
                        reliability_flags=reliability_flags,
                        # Extended fields
                        speaker=speaker,
                        turn_index=turn_index,
                        column_ref=column_ref,
                        section_number=section_number,
                        page=page,
                        prev_chunk_id=prev_chunk_id,
                        next_chunk_id=next_chunk_id,
                        chunk_hash=chunk_hash,
                        source_url=source_url,
                        source_format=source_format,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Validation error for chunk {chunk_id} in {file_path}: {exc}")

        # Count documents by source type only once per file
        canonical_type = canonical_doc_type(source_type)
        self.doc_counts_by_type[canonical_type] = self.doc_counts_by_type.get(canonical_type, 0) + 1
        self.doc_counts_by_raw_type[source_type] = self.doc_counts_by_raw_type.get(
            source_type, 0
        ) + 1
        return doc_chunks, errors

    def _generate_location_pointer(
        self,
        header: Optional[str],
        page: Optional[int],
        column_ref: Optional[str],
        section_number: Optional[str],
        source_type: str,
    ) -> str:
        """
        Generate location_pointer following bottl KB Standard v1.0.
        Priority: section > column > header > page > fallback
        """
        # Legislative documents: extract section from header or use section_number
        if any(keyword in source_type.lower() for keyword in ["act", "bill", "legislation", "si", "statutory"]):
            if section_number:
                return f"Section {section_number}"
            if header:
                section_match = re.search(r'\bsection\s+(\d+[A-Za-z]?(?:\([^)]+\))?)', header, re.IGNORECASE)
                if section_match:
                    return f"Section {section_match.group(1)}"
                # Also check for schedule
                schedule_match = re.search(r'\bschedule\s+(\d+)', header, re.IGNORECASE)
                if schedule_match:
                    return f"Schedule {schedule_match.group(1)}"

        # Hansard debates: use column reference
        if column_ref:
            return f"Column {column_ref}"
        if any(keyword in source_type.lower() for keyword in ["hansard", "debate"]) and header:
            col_match = re.search(r'\bcolumn\s+(\d+)', header, re.IGNORECASE)
            if col_match:
                return f"Column {col_match.group(1)}"

        # Committee transcripts: check for question numbers
        if header and re.match(r'^Q\d+', header):
            return header

        # Fallback to page
        if isinstance(page, int):
            return f"Page {page}"
        if page and page != "All":
            return f"Page {page}"

        # Last resort: use header or "Full Document"
        if header:
            return header
        return "Full Document"

    def status(self) -> KBStatus:
        return KBStatus.from_counts(
            self.last_refreshed,
            len(self.chunks),
            self.doc_counts_by_type,
            self.validation_errors,
            {
                "max_chunks_to_llm": config.MAX_CHUNKS_TO_LLM,
                "max_chars_to_llm": config.MAX_CHARS_TO_LLM,
                "max_excerpt_words": config.MAX_EXCERPT_WORDS,
            },
            self.chunk_counts_by_type,
            self.guidance_source_counts,
            self.doc_counts_by_raw_type,
            self.ingestion_summary,
        )

    def _rebuild_inventory(self) -> None:
        chunk_counter: Counter[str] = Counter()
        guidance_counter: defaultdict[str, int] = defaultdict(int)

        for chunk in self.chunks:
            doc_type = canonical_doc_type(chunk.source_type)
            chunk_counter[doc_type] += 1
            if doc_type == "Regulator Guidance":
                guidance_counter[chunk.title] += 1

        self.chunk_counts_by_type = dict(chunk_counter)
        self.guidance_source_counts = dict(guidance_counter)


kb = KnowledgeBase()
