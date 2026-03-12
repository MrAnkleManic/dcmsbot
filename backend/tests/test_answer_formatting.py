from backend.core.evidence import build_citations, generate_answer
from backend.core.loader import _clean_chunk_text
from backend.core.models import Answer, KBChunk


def _make_chunk(text: str) -> KBChunk:
    return KBChunk(
        doc_id="DOC_044",
        title="Online Safety Act 2023 (c. 50)",
        source_type="Act of Parliament",
        publisher="Parliament",
        date_published="2023-10-26",
        chunk_id="DOC_044_0101",
        chunk_text=text,
        header="Section 64 User identity verification",
        location_pointer="page 1",
        authority_weight=10.0,
    )


def test_clean_chunk_text_removes_broken_artifacts() -> None:
    raw = (
        "Section heading: Section 64 User identity verification\n\n(5) The duty set out in subsection (1)\")"
        " applies.\n\nCommencement Information\n\nI106 S. 64 not in force at Royal Assent, see **s. 240(1)**\")"
    )
    cleaned = _clean_chunk_text(raw)
    assert '\")' not in cleaned
    assert '))' not in cleaned
    assert cleaned.endswith("s. 240(1)**")


def test_generate_answer_quotes_section_64_and_sets_high_confidence() -> None:
    chunk = _make_chunk(
        "Section heading: Section 64 User identity verification\n"
        "(1) A provider of a Category 1 service must offer all adult users of the service the option to verify"
        " their identity (if identity verification is not required for access to the service).\n"
        "(2) The verification process may be of any kind (and in particular, it need not require documentation to"
        " be provided).\n"
        "(3) A provider of a Category 1 service must include clear and accessible provisions in the terms of"
        " service explaining how the verification process works.\n"
        "(4) If a person is the provider of more than one Category 1 service, the duties set out in this section"
        " apply in relation to each such service.\n"
        "(5) The duty set out in subsection (1)\") applies in relation to all adult users, not just those who begin"
        " to use a service after that duty begins to apply.\n"
        "(6) The duties set out in this section extend only to—\n(a) the user-to-user part of a service, and\n"
        "(b) the design, operation and use of a service in the United Kingdom.\n"
        "(7) For the purposes of this section a person is an “adult user” of a service if the person is an adult in"
        " the United Kingdom who—\n(a) is a user of the service, or\n(b) seeks to begin to use the service."
        " (for example by setting up an account).\n"
        "(8) For the meaning of “Category 1 service”, see section 95 (register of categories of services).\n"
        "Commencement Information\nI106 S. 64 not in force at Royal Assent, see **s. 240(1)**"
    )
    citations = build_citations([chunk])
    answer: Answer = generate_answer(
        question="What does section 64 require?", evidence=[chunk], citations=citations
    )

    assert answer.confidence.level == "high"
    assert answer.text.startswith("Answer")
    assert 'From C001 (Online Safety Act 2023 (c. 50), page 1): "' in answer.text
    assert "need not require documentation to be provided" in answer.text


def test_missing_definition_is_called_out() -> None:
    chunk = _make_chunk(
        "Section heading: Section 64 User identity verification\n"
        "(1) A provider of a Category 1 service must offer all adult users of the service the option to verify"
        " their identity (if identity verification is not required for access to the service).\n"
        "(2) The verification process may be of any kind.\n"
    )
    citations = build_citations([chunk])
    answer: Answer = generate_answer(
        question="How does section 64 define \"adult user\"?", evidence=[chunk], citations=citations
    )

    lower_text = answer.text.lower()
    assert "not shown in the retrieved evidence" in lower_text
    assert "adult user\" means" not in lower_text
