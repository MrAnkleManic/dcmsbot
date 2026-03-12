import pytest

from backend.core.doc_types import canonical_doc_type


@pytest.mark.parametrize(
    "raw",
    [
        "guidance",
        "Regulator Guidance",
        "ofcom_guidance",
        "regulator guidance",
        "Policy Docs & Guidance",
    ],
)
def test_guidance_variants_normalize_to_regulator_guidance(raw: str) -> None:
    assert canonical_doc_type(raw) == "Regulator Guidance"
