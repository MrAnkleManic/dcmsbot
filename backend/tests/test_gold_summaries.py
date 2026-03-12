from backend.core.gold_summaries import get_gold_summary_sentences


def test_get_gold_summary_sentences_section_64() -> None:
    sentences = get_gold_summary_sentences("section_64")

    assert isinstance(sentences, list)
    assert sentences
    assert all(isinstance(s, str) for s in sentences)
