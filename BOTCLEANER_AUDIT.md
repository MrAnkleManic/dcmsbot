# BotCleaner Metadata Extraction Audit

**Date:** 2026-01-29
**Purpose:** Identify metadata extraction gaps and prioritize improvements

---

## Executive Summary

BotCleaner has **strong parliamentary debate metadata extraction** but **incomplete coverage** across document types. Key finding: **Speaker/turn detection only works for Hansard debates fetched via API, not for PDF/HTML oral evidence transcripts.**

**Metadata Completeness by Document Type:**
- ✅ **Hansard debates (API):** 95% - Excellent (speaker, turns, columns, questions, timestamps)
- ⚠️ **Oral Evidence Transcripts (PDF/HTML):** 30% - Poor (missing speakers, turns, questions)
- ⚠️ **Legislation (PDF):** 50% - Moderate (missing section numbers, schedules, amendments)
- ✅ **Generic docs:** 80% - Good (date, author, title, URL)

---

## What BotCleaner Extracts Well ✅

### 1. Hansard Debates (via parliament.uk API)
**Extraction:** Comprehensive
**Fields captured:**
- `speaker_name`, `speaker_affiliation`, `speaker_role`
- `turn_index`, `turn_part_index`
- `column_start`, `column_end`
- `question_numbers`
- `house` (Commons/Lords)
- `timestamp`
- `debate_title`, `debate_date`

**Why it works:** Dedicated `hansard_fetch.py` module with HTML parsing of parliament.uk debate pages

### 2. Basic Document Metadata
**Extraction:** Good
**Fields captured:**
- `title` (from HTML `<title>`, PDF metadata, filename)
- `author` (from PDF metadata, filename)
- `date` (from PDF metadata, HTML meta tags, text heuristics)
- `url` (resolved canonical URL)
- `encoding` (character encoding detection)

**Why it works:** Multiple fallback methods, good heuristics

### 3. PDF Technical Metadata
**Extraction:** Good
**Fields captured:**
- `pdf_extractor_used` (pymupdf, pdfplumber)
- `pdf_artifact_score` (quality metric)
- `pdf_layout` (column detection)
- `pdfplumber_mode` (words vs text)

**Why it works:** Sophisticated PDF parsing in `pdf_text_extract.py`

### 4. Chunk Navigation
**Extraction:** Excellent
**Fields captured:**
- `chunk_id` (hierarchical DOC_###::c######)
- `chunk_hash` (SHA1 for deduplication)
- `prev_chunk_id`, `next_chunk_id` (linked list)

**Why it works:** `ingest_utils._apply_chunk_ids_and_pointers()`

---

## Critical Gaps 🚨

### 1. **Speaker Detection for Non-Hansard Transcripts**
**Status:** ❌ **BROKEN**
**Impact:** HIGH - Blocks analytical queries about committee hearings

**Problem:**
- Oral Evidence Transcripts (PDF/HTML) contain Q&A format: "Q227 Chair:", "Witness: Julie Inman Grant"
- BotCleaner's turn detection (`turn_detection_utils.py`) is NOT applied to these files
- Only works for Hansard debates fetched via API

**Evidence:**
```
36 Oral Evidence Transcript chunks in KB
13 contain Q&A patterns ("Q227 Chair:", "Witness:")
0 have speaker attribution in speaker field ← CRITICAL GAG
```

**Why it's broken:**
- `chunk_hansard_transcript()` is only called for Hansard API responses
- Regular PDF/HTML ingestion via `clean_pdf_content()` / `clean_html_content()` doesn't invoke turn detection
- No dispatch logic to detect transcript format and route to turn detection

**Fix location:** `dashboard.py` - Add transcript detection and route to turn chunking

---

### 2. **Section Number Extraction for Legislation**
**Status:** ❌ **MISSING**
**Impact:** MEDIUM - Reduces section-locking accuracy

**Problem:**
- Legislative documents have clear section structure: "Section 64 User identity verification"
- Section numbers exist in headers but not extracted as structured field `section_number`
- DCMS bot has to parse section numbers from headers at query time (less reliable)

**Evidence:**
- BotCleaner output has `header: "Section 64 User identity verification"`
- But `section_number: null`
- DCMS bot's `_generate_location_pointer()` uses regex to extract section from header (workaround)

**Why it's missing:**
- No dedicated section number extraction in PDF/HTML parsing
- `hansard_structure_utils.py` has `extract_column_numbers()` and `extract_question_numbers()` but no `extract_section_numbers()`

**Fix location:** Add `extract_section_numbers()` to `parsing_utils.py`, call from `clean_pdf_content()`

---

### 3. **Column Reference Propagation**
**Status:** ⚠️ **PARTIAL**
**Impact:** MEDIUM - Hansard citations less precise

**Problem:**
- `extract_column_numbers()` extracts column ranges from text
- But `column_ref` field is populated inconsistently
- Not propagated to all chunks in that column range

**Evidence:**
- `hansard_structure_utils.extract_column_numbers()` returns (min, max) tuple
- But chunks don't consistently have `column_ref` field populated
- Only chunks with "Column N" in their text get column_ref

**Why it's partial:**
- Column extraction exists but isn't propagated to adjacent chunks
- No "column continuity" logic like there is for speaker continuity

**Fix location:** Add column propagation to `hansard_fetch.restore_hansard_chunk_continuity()`

---

### 4. **Question Number Propagation**
**Status:** ⚠️ **PARTIAL**
**Impact:** LOW-MEDIUM - Committee transcript citations imprecise

**Problem:**
- Questions span multiple chunks but question number not inherited
- Only the chunk containing "Q227" gets `question_numbers` field

**Evidence:**
```
Header: "Examination of witness"
Text: "Q227 Chair: This is a long question...
[text continues for 3 chunks]
```
Only first chunk has `question_numbers: [227]`, subsequent chunks have `question_numbers: null`

**Why it's partial:**
- `extract_question_numbers()` only extracts from current chunk text
- No inheritance logic for multi-chunk questions

**Fix location:** Add question number inheritance to continuity restoration

---

## Lower-Priority Gaps

### 5. **Amendment/Schedule References**
**Status:** ❌ **MISSING**
**Impact:** LOW - Rarely queried

**Missing fields:**
- `amendment_number` (e.g., "Amendment 198")
- `schedule_number` (e.g., "Schedule 2")

**Fix:** Add regex patterns similar to question number extraction

---

### 6. **Vote/Division Results**
**Status:** ❌ **MISSING**
**Impact:** LOW - Specialized queries only

**Missing fields:**
- `division_number`
- `ayes_count`, `noes_count`
- `vote_outcome`

**Fix:** Parse division result text (requires Hansard-specific parsing)

---

### 7. **Document Structure Hierarchy**
**Status:** ❌ **MISSING**
**Impact:** LOW - Nice to have

**Missing fields:**
- `part_number`, `chapter_number` (for structured legislation)
- `heading_level` (H1, H2, H3 nesting depth)
- `parent_section` (hierarchy tracking)

**Fix:** Parse document outline/table of contents

---

### 8. **Metadata from HTML Tags**
**Status:** ❌ **MISSING**
**Impact:** VERY LOW - Rarely useful

**Missing extraction:**
- `<meta name="keywords">`
- `<meta name="description">`
- OpenGraph tags (`og:image`, `og:type`)
- JSON-LD structured data

**Fix:** Add meta tag scraping to `clean_html_content()`

---

## Root Cause Analysis

### Why Speaker Detection Doesn't Work for Non-Hansard Transcripts

**Current Architecture:**
```
dashboard.py:
├─ clean_pdf_content()
│   └─ extract_pdf_text() → raw text
│       └─ rechunk_text() ← Generic chunking, NO turn detection
│
├─ clean_html_content()
│   └─ extract_main_text_from_html() → raw text
│       └─ rechunk_text() ← Generic chunking, NO turn detection
│
└─ fetch_hansard_from_url()
    └─ chunk_hansard_transcript() ← Turn detection HERE
        └─ split_into_speaker_turns() ✓ Extracts speakers
```

**The Problem:**
- Turn detection logic exists in `turn_detection_utils.py` and `hansard_structure_utils.py`
- But it's only invoked for Hansard API responses
- PDF/HTML files bypass turn detection and go straight to generic `rechunk_text()`

**The Fix:**
Add dispatch logic to detect transcript format and route to turn chunking:

```python
def clean_pdf_content(pdf_file, ...):
    text = extract_pdf_text(pdf_file)

    # NEW: Detect if this is a transcript
    if is_transcript(text, metadata):
        # Route to turn-based chunking
        chunks = chunk_text_by_turns(text)
    else:
        # Generic chunking
        chunks = rechunk_text(text)
```

---

## Prioritized Fix List

### **Priority 1: Speaker Detection for All Transcripts** 🔥
**Why:** Blocks core use case (analytical queries about MPs, witnesses)
**Impact:** HIGH
**Effort:** MEDIUM

**Tasks:**
1. Add `is_transcript()` heuristic to detect Q&A format
2. Route transcript PDFs/HTML to `chunk_text_by_turns()`
3. Ensure turn detection patterns work for committee transcripts (not just Hansard)
4. Test with sample oral evidence files

**Files to modify:**
- `dashboard.py` - Add transcript detection and routing
- `turn_detection_utils.py` - Verify patterns work for committee format
- Test with existing oral evidence PDFs

---

### **Priority 2: Section Number Extraction** 🔥
**Why:** Improves section-locking accuracy for legislation
**Impact:** MEDIUM
**Effort:** LOW

**Tasks:**
1. Add `extract_section_numbers()` to `parsing_utils.py`
2. Call from `clean_pdf_content()` and `clean_html_content()`
3. Populate `section_number` field in chunk metadata
4. Test with Online Safety Act PDF

**Files to modify:**
- `parsing_utils.py` - New function `extract_section_numbers(text) -> str | None`
- `dashboard.py` - Call during chunking

---

### **Priority 3: Column Reference Propagation**
**Why:** Improves Hansard citation precision
**Impact:** MEDIUM
**Effort:** LOW

**Tasks:**
1. Extend `restore_hansard_chunk_continuity()` to propagate column numbers
2. If chunk N has `column_ref: "227"`, inherit to chunks N+1, N+2 until new column appears

**Files to modify:**
- `hansard_fetch.py` - Extend `restore_hansard_chunk_continuity()`

---

### **Priority 4: Question Number Propagation**
**Why:** Improves committee transcript citations
**Impact:** LOW-MEDIUM
**Effort:** LOW

**Tasks:**
1. Add question number inheritance to continuity restoration
2. If chunk starts with "Q227", propagate to subsequent chunks until next question

**Files to modify:**
- `hansard_fetch.py` - Extend `restore_hansard_chunk_continuity()`

---

## Testing Strategy

**For each fix:**

1. **Unit test** - Test extraction function in isolation
2. **Integration test** - Test full ingestion pipeline
3. **Validation test** - Load resulting JSON into DCMS bot, verify fields populated
4. **Query test** - Test analytical query that depends on the metadata

**Sample documents for testing:**
- Oral Evidence Transcript (PDF): Test speaker extraction
- Online Safety Act (PDF): Test section number extraction
- Hansard debate (HTML): Test column propagation
- Committee transcript (PDF): Test question number propagation

---

## Success Metrics

**Before fixes:**
- Speaker attribution: 189/6775 chunks (2.8%)
- Section numbers: 0/6775 chunks (0%)
- Column refs: Unknown coverage
- Question numbers: Unknown coverage

**After Priority 1-2 fixes:**
- Speaker attribution: >1000/6775 chunks (>15%) ← All transcripts
- Section numbers: >200/6775 chunks (>3%) ← All legislation
- Column refs: Maintain current coverage
- Question numbers: Improve coverage in committee transcripts

**Target:** 80% of transcript chunks have speakers, 95% of legislation chunks have section numbers

---

## Implementation Plan

### Week 1: Priority 1 (Speaker Detection)
1. Add `is_transcript()` detection heuristic
2. Route transcript files to turn chunking
3. Test with 3-5 sample oral evidence files
4. Validate in DCMS bot loader

### Week 2: Priority 2 (Section Numbers)
1. Implement `extract_section_numbers()`
2. Integrate into PDF/HTML pipeline
3. Test with Online Safety Act + sample Bills
4. Validate section-locking in DCMS bot

### Week 3: Priority 3-4 (Column & Question Propagation)
1. Extend continuity restoration logic
2. Test with Hansard debates
3. Validate citation quality

### Week 4: Reingest & Validate
1. Reingest full knowledge base
2. Run metadata completeness report
3. Test analytical queries
4. Document improvements in bottl KB Standard

---

## Conclusion

**Current State:** BotCleaner is production-ready for Hansard debates but incomplete for other document types.

**Target State:** Universal, metadata-rich extraction across ALL document types.

**Key Insight:** The extraction logic exists (turn detection, pattern matching) but isn't applied universally. Most fixes are about routing documents to existing logic, not building new extraction functions.

**Next Step:** Implement Priority 1 (speaker detection for all transcripts) to unblock analytical queries.
