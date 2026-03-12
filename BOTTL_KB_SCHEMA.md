# bottl Knowledge Base Schema Standard v1.0

**Purpose:** Unified JSON schema for all bottl project knowledge bases (DCMS legal bot, King's training scenarios, OPEC negotiations, cross-cultural business, etc.)

**Last Updated:** 2026-01-29

---

## Design Principles

1. **Universal applicability** - Works for legal docs, transcripts, role-play scenarios, cultural guides
2. **Evidence-first** - Every chunk traceable to source document with location pointer
3. **Authority-weighted** - Source credibility explicit and configurable
4. **LLM-ready** - Rich metadata for synthesis, analysis, and reasoning
5. **Backwards compatible** - Existing DCMS bot and BotCleaner outputs can map to this schema

---

## JSON Structure

### Document-Level Schema

```json
{
  "metadata": {
    "id": "string (required)",
    "title": "string (required)",
    "source_type": "string (required)",
    "publisher": "string (required)",
    "date": "ISO 8601 date string (required)",
    "url": "string (optional)",
    "category": "string (optional)",
    "authority_weight": "float 0-10 (required)",
    "authority_tag": "enum (optional)",
    "encoding": "string (optional)",
    "ingestion_metadata": {
      "ingested_date": "ISO 8601 datetime (optional)",
      "ingestion_source": "string (optional)",
      "pdf_extractor": "string (optional)",
      "artifact_score": "integer (optional)"
    }
  },
  "chunks": [
    {
      "chunk_id": "string (required)",
      "header": "string (optional)",
      "text": "string (required)",
      "location_pointer": "string (required)",
      "page": "integer or 'All' (optional)",
      "chunk_hash": "string (optional)",
      "prev_chunk_id": "string or null (optional)",
      "next_chunk_id": "string or null (optional)",
      "speaker": "string (optional)",
      "turn_index": "integer (optional)",
      "column_ref": "string (optional)",
      "section_number": "string (optional)",
      "metadata": {
        "custom_field": "any (optional)"
      }
    }
  ]
}
```

---

## Field Specifications

### Metadata (Document Level)

| Field | Type | Required | Description | Examples |
|-------|------|----------|-------------|----------|
| `id` | string | **Yes** | Unique document identifier across entire KB | `"DOC_001"`, `"FALKLANDS_MEMO_042"`, `"OPEC_TRANSCRIPT_2024_03"` |
| `title` | string | **Yes** | Human-readable document title | `"Online Safety Act 2023"`, `"Carrington Memo: Argentine Threat Assessment"` |
| `source_type` | string | **Yes** | Canonical document type (see taxonomy below) | `"Act of Parliament"`, `"Diplomatic Cable"`, `"Committee Report"` |
| `publisher` | string | **Yes** | Authoring organization or individual | `"UK Parliament"`, `"Foreign Office"`, `"Ofcom"` |
| `date` | string | **Yes** | Publication/creation date (ISO 8601: YYYY-MM-DD) | `"2023-10-26"`, `"1982-03-15"` |
| `url` | string | No | Canonical URL if available | `"https://www.legislation.gov.uk/..."` |
| `category` | string | No | Organizational category (for KB folder structure) | `"01_Legislation"`, `"03_Hansard_Debate"`, `"Historical_Memos"` |
| `authority_weight` | float | **Yes** | Source credibility score (0-10, see weights below) | `10.0` (Act), `7.0` (Regulator), `5.0` (Analysis) |
| `authority_tag` | enum | No | Semantic authority label | `"PRIMARY_LEGISLATION"`, `"OFFICIAL_FINDING"`, `"EXPERT_OPINION"`, `"MEDIA_REPORT"` |
| `encoding` | string | No | Character encoding hint | `"utf-8"`, `"latin-1"` |
| `ingestion_metadata` | object | No | Technical metadata from ingestion process (nested object) | See below |

#### Ingestion Metadata (Nested Object)

| Field | Type | Description |
|-------|------|-------------|
| `ingested_date` | string | ISO 8601 datetime when document was ingested | `"2026-01-29T14:32:00Z"` |
| `ingestion_source` | string | Tool/process that ingested document | `"BotCleaner v2.1"`, `"Manual Entry"` |
| `pdf_extractor` | string | PDF parser used | `"pymupdf_words"`, `"pdfplumber"` |
| `artifact_score` | integer | PDF quality metric (lower = cleaner extraction) | `165` |

---

### Chunks (Document Sections)

| Field | Type | Required | Description | Examples |
|-------|------|----------|-------------|----------|
| `chunk_id` | string | **Yes** | Unique chunk identifier (can include doc_id prefix) | `"DOC_001::c000042"`, `"OSA_s64"` |
| `header` | string | No | Section heading or label | `"Section 64 User identity verification"`, `"Q227 Chair:"` |
| `text` | string | **Yes** | Chunk content | `"The Secretary of State may by regulations..."` |
| `location_pointer` | string | **Yes** | Human-readable location for citation | `"Section 64"`, `"Page 12"`, `"Column 227"`, `"Turn 5"` |
| `page` | int/string | No | Page number or "All" | `12`, `"All"` |
| `chunk_hash` | string | No | Hash of normalized text for deduplication | `"f2f113b37a4d"` |
| `prev_chunk_id` | string/null | No | Previous chunk ID for navigation | `"DOC_001::c000041"` |
| `next_chunk_id` | string/null | No | Next chunk ID for navigation | `"DOC_001::c000043"` |
| `speaker` | string | No | Speaker name (for transcripts/debates) | `"David Davis"`, `"Lord Carrington"` |
| `turn_index` | integer | No | Turn number in conversation/debate | `42` |
| `column_ref` | string | No | Hansard column reference | `"Column 227"` |
| `section_number` | string | No | Legislative section number (for filtering) | `"64"`, `"64(2)(a)"` |
| `metadata` | object | No | Custom fields for specific use cases | `{"sentiment": "critical", "topic": "privacy"}` |

---

## Taxonomy: Source Types

### Legal/Regulatory (DCMS Bot)

| Source Type | Authority Weight | Authority Tag | Description |
|-------------|------------------|---------------|-------------|
| Act of Parliament | 10.0 | PRIMARY_LEGISLATION | Primary legislation (e.g., Online Safety Act 2023) |
| Statutory Instrument | 9.0 | SECONDARY_LEGISLATION | Delegated legislation (SIs, regulations) |
| Draft Bill & Amendments | 8.0 | PROPOSED_LEGISLATION | Bills under consideration |
| Committee Report | 8.0 | OFFICIAL_FINDING | Select Committee reports, findings |
| Regulator Guidance | 7.0 | OFFICIAL_GUIDANCE | Ofcom, ICO, etc. guidance documents |
| Government Response | 7.0 | OFFICIAL_POSITION | Official government statements/responses |
| Explanatory Notes | 6.0 | EXPLANATORY_MATERIAL | Official explanatory materials |
| Oral Evidence Transcript | 6.0 | EXPERT_TESTIMONY | Witness testimony to committees |
| Ministerial Correspondence | 6.0 | OFFICIAL_CORRESPONDENCE | Letters from ministers |
| Debate (Commons/Lords) | 5.0 | PARLIAMENTARY_DEBATE | Hansard debate transcripts |
| Consultation | 5.0 | PUBLIC_INPUT | Public consultation responses |
| Impact Assessment | 5.0 | OFFICIAL_ANALYSIS | Regulatory impact assessments |
| News Article | 3.0 | MEDIA_REPORT | Press coverage |
| Opinion / Analysis | 3.0 | EXPERT_OPINION | Think tank reports, academic analysis |

### Historical/Training (King's Falklands Bot)

| Source Type | Authority Weight | Authority Tag | Description |
|-------------|------------------|---------------|-------------|
| Diplomatic Cable | 9.0 | PRIMARY_SOURCE | Official diplomatic communications |
| Cabinet Minutes | 9.0 | PRIMARY_SOURCE | Official government meeting records |
| Intelligence Report | 8.0 | CLASSIFIED_SOURCE | Intelligence assessments |
| Military Report | 8.0 | OFFICIAL_REPORT | Military situation reports |
| Ministerial Memo | 7.0 | OFFICIAL_CORRESPONDENCE | Internal government memos |
| Hansard (Historical) | 6.0 | PARLIAMENTARY_DEBATE | Historical parliamentary debates |
| Press Article (Contemporary) | 4.0 | MEDIA_REPORT | News from the period |
| Historical Analysis | 3.0 | SCHOLARLY_ANALYSIS | Academic retrospective analysis |

### Negotiation/Cultural (OPEC/Business Bots)

| Source Type | Authority Weight | Authority Tag | Description |
|-------------|------------------|---------------|-------------|
| Treaty Text | 10.0 | PRIMARY_SOURCE | Official treaty/agreement text |
| Negotiation Transcript | 9.0 | PRIMARY_SOURCE | Official negotiation records |
| Position Paper | 8.0 | OFFICIAL_POSITION | Formal position statements |
| Cultural Guide | 7.0 | EXPERT_GUIDANCE | Authoritative cultural guides |
| Business Protocol | 7.0 | EXPERT_GUIDANCE | Business etiquette guides |
| Case Study | 5.0 | APPLIED_EXAMPLE | Real-world examples |
| News Report | 3.0 | MEDIA_REPORT | Press coverage |

---

## Location Pointer Standards

Location pointers should be **human-readable citations** that allow users to find the original text.

| Document Type | Location Pointer Format | Examples |
|---------------|------------------------|----------|
| Legislation | `"Section N"` or `"Section N(subsection)"` or `"Schedule N"` | `"Section 64"`, `"Section 64(2)(a)"`, `"Schedule 2"` |
| Hansard Debates | `"Column N"` or `"Column N (Date)"` | `"Column 227"`, `"Column 42 (15 Nov 2022)"` |
| Committee Transcripts | `"Question N"` or `"Page N"` | `"Q227"`, `"Page 12"` |
| Reports/Papers | `"Page N"` or `"Paragraph N"` | `"Page 42"`, `"Para 3.14"` |
| Transcripts with Speakers | `"Turn N (Speaker)"` or `"Timestamp"` | `"Turn 5 (Carrington)"`, `"[14:32]"` |
| Generic Docs | `"Page N"` or `"All"` | `"Page 1"`, `"All"` |

**Fallback:** If no specific pointer available, use `"Page N"` or `"Full Document"`.

---

## Chunk ID Standards

Chunk IDs should be:
- **Unique** within the entire knowledge base
- **Stable** (don't change if document is reingested)
- **Optionally hierarchical** (include document ID as prefix)

### Recommended Format

```
{DOC_ID}::{CHUNK_SEQUENCE}
```

Examples:
- `"DOC_163::c000042"` - Document 163, chunk 42
- `"OSA_s64::c001"` - Online Safety Act Section 64, chunk 1
- `"FALKLANDS_CABLE_1982_03_15::c007"` - Falklands cable, chunk 7

### Alternative Format (Legacy DCMS)

```
{PREFIX}_{SECTION_OR_SEQ}
```

Examples:
- `"OSA_064"` - Online Safety Act, Section 64
- `"OFCOM_GUID_042"` - Ofcom Guidance, chunk 42

**Both formats are valid.** Choose based on your needs:
- Hierarchical (`DOC_ID::chunk`) for generic docs
- Semantic (`PREFIX_SECTION`) for legislation with stable section numbers

---

## Field Mapping: BotCleaner → bottl Standard

BotCleaner currently outputs a slightly different format. Here's the mapping:

| BotCleaner Field | bottl Standard Field | Transformation |
|------------------|----------------------|----------------|
| `metadata.id` | `metadata.id` | Direct copy |
| `metadata.title` | `metadata.title` | Direct copy |
| `metadata.type` | `metadata.source_type` | **Rename** |
| `metadata.author` | `metadata.publisher` | **Rename** |
| `metadata.date` | `metadata.date` | Direct copy |
| `metadata.url` | `metadata.url` | Direct copy |
| `metadata.category` | `metadata.category` | Direct copy |
| `metadata.authority_weight` | `metadata.authority_weight` | Direct copy |
| `metadata.authority_tag` | `metadata.authority_tag` | Direct copy |
| `metadata.pdf_extractor_used` | `metadata.ingestion_metadata.pdf_extractor` | **Nest** |
| `metadata.pdf_artifact_score` | `metadata.ingestion_metadata.artifact_score` | **Nest** |
| `chunks[].text` | `chunks[].text` | Direct copy |
| `chunks[].header` | `chunks[].header` | Direct copy |
| `chunks[].page` | `chunks[].page` | Direct copy |
| `chunks[].chunk_id` | `chunks[].chunk_id` | Direct copy |
| `chunks[].chunk_hash` | `chunks[].chunk_hash` | Direct copy |
| `chunks[].prev_chunk_id` | `chunks[].prev_chunk_id` | Direct copy |
| `chunks[].next_chunk_id` | `chunks[].next_chunk_id` | Direct copy |
| `chunks[].speaker` | `chunks[].speaker` | Direct copy |
| `chunks[].turn_index` | `chunks[].turn_index` | Direct copy |
| *(missing)* | `chunks[].location_pointer` | **Generate** from `page`, `header`, or `section_number` |
| *(missing)* | `chunks[].section_number` | **Extract** from `header` or `text` |

### Critical Missing Field: `location_pointer`

BotCleaner needs to generate this field. Logic:

```python
def generate_location_pointer(chunk, metadata):
    # Legislation: extract section from header
    if "Act" in metadata.source_type or "Bill" in metadata.source_type:
        section = extract_section_from_header(chunk.header)
        if section:
            return f"Section {section}"

    # Hansard: use column reference
    if "Hansard" in metadata.source_type or "Debate" in metadata.source_type:
        if chunk.column_ref:
            return f"Column {chunk.column_ref}"

    # Committee transcripts: question number
    if "Question" in chunk.header:
        return chunk.header  # e.g., "Q227"

    # Fallback to page
    if chunk.page and chunk.page != "All":
        return f"Page {chunk.page}"

    # Last resort
    return "Full Document"
```

---

## Field Mapping: Legacy DCMS → bottl Standard

The existing DCMS bot expects a slightly different format. Here's the mapping:

| Legacy DCMS Field | bottl Standard Field | Transformation |
|-------------------|----------------------|----------------|
| `metadata.doc_id` | `metadata.id` | **Rename** |
| `metadata.source_type` | `metadata.source_type` | Direct copy |
| `metadata.publisher` | `metadata.publisher` | Direct copy |
| `metadata.date_published` | `metadata.date` | **Rename** |
| `chunks[].chunk_text` | `chunks[].text` | **Rename** |
| `chunks[].location_pointer` | `chunks[].location_pointer` | Direct copy |

**Loader should accept both `doc_id` and `id`, both `chunk_text` and `text`.**

---

## Validation Rules

### Required Fields (Fail if Missing)

- `metadata.id`
- `metadata.title`
- `metadata.source_type`
- `metadata.publisher`
- `metadata.date` (must be valid ISO 8601 date)
- `metadata.authority_weight` (must be 0-10)
- `chunks` (must be non-empty array)
- `chunks[].chunk_id` (for each chunk)
- `chunks[].text` (for each chunk)
- `chunks[].location_pointer` (for each chunk)

### Optional But Recommended

- `metadata.url`
- `metadata.category`
- `chunks[].header`
- `chunks[].section_number` (for legislation)
- `chunks[].speaker` (for transcripts)

### Warnings (Log but Don't Fail)

- `authority_weight` outside 0-10 range → clamp to 0-10
- `date` not ISO 8601 format → attempt parse with heuristics
- `location_pointer` is empty string → default to "Full Document"
- Duplicate `chunk_id` values → append suffix to deduplicate

---

## Usage in DCMS Bot Loader

The loader should:

1. **Accept both formats** (BotCleaner and legacy DCMS)
2. **Map fields** to canonical schema internally
3. **Validate** required fields
4. **Log warnings** for optional missing fields
5. **Generate missing fields** where possible (e.g., `location_pointer` from `page`)

Example loader logic:

```python
def load_document(json_file):
    data = json.load(open(json_file))
    metadata = data["metadata"]

    # Field mapping (backwards compatibility)
    doc_id = metadata.get("id") or metadata.get("doc_id")
    source_type = metadata.get("source_type") or metadata.get("type")
    publisher = metadata.get("publisher") or metadata.get("author")
    date = metadata.get("date") or metadata.get("date_published")

    # Validate required fields
    if not doc_id or not source_type or not publisher:
        raise ValueError(f"Missing required metadata in {json_file}")

    # Process chunks
    for chunk in data["chunks"]:
        chunk_text = chunk.get("text") or chunk.get("chunk_text")
        location_pointer = chunk.get("location_pointer")

        # Generate location_pointer if missing
        if not location_pointer:
            location_pointer = generate_location_pointer(chunk, metadata)

        # Store in KB
        kb_chunk = KBChunk(
            chunk_id=chunk["chunk_id"],
            text=chunk_text,
            location_pointer=location_pointer,
            # ... other fields
        )
```

---

## Migration Path

### For BotCleaner

1. Add `location_pointer` generation to chunking pipeline
2. Add `section_number` extraction for legislation
3. Nest PDF metadata under `ingestion_metadata`
4. Rename `author` → `publisher`, `type` → `source_type`

### For DCMS Bot

1. Update `loader.py` to accept both field names (backwards compatible)
2. Map incoming JSON to canonical schema
3. Validate against required fields
4. Generate missing `location_pointer` if needed

### For Future Bots

- Use this schema from day one
- BotCleaner outputs compliant JSON
- All bots consume same format
- Taxonomy extensible (add new source types as needed)

---

## Version History

- **v1.0** (2026-01-29) - Initial schema definition for bottl Knowledge Base Standard

---

## Next Steps

1. Update BotCleaner to output compliant JSON (add `location_pointer`, rename fields)
2. Update DCMS bot loader to accept both legacy and canonical formats
3. Test end-to-end pipeline
4. Rebuild KB with canonical format once validated
5. Document schema in all bottl project READMEs
