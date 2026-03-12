import re
from typing import Dict

_DOC_TYPE_MAP: Dict[str, str] = {
    "act": "Act",
    "act of parliament": "Act",
    "primary legislation": "Act",
    "regulations": "SI / Statutory Instrument",
    "statutory instrument": "SI / Statutory Instrument",
    "si": "SI / Statutory Instrument",
    "secondary legislation": "SI / Statutory Instrument",
    "explanatory notes": "Explanatory Notes",
    "explanatory note": "Explanatory Notes",
    "guidance": "Regulator Guidance",
    "regulator guidance": "Regulator Guidance",
    "ofcom guidance": "Regulator Guidance",
    "regulator_guidance": "Regulator Guidance",
    "ofcom_guidance": "Regulator Guidance",
    "policy docs guidance": "Regulator Guidance",
    "policy docs and guidance": "Regulator Guidance",
    "hansard": "Debates / Hansard",
    "debate": "Debates / Hansard",
    "debates": "Debates / Hansard",
}

_UNKNOWN_LABEL = "Unknown / Missing doc_type"


def canonical_doc_type(raw_type: str | None) -> str:
    """
    Normalise document types into a small, canonical set for inventory/debug views.
    """
    if not raw_type:
        return _UNKNOWN_LABEL

    s_raw_type = str(raw_type).strip()
    if not s_raw_type:
        return _UNKNOWN_LABEL

    # Replace separators and collapse whitespace in one go
    cleaned = re.sub(r"[\s_\-/&]+", " ", s_raw_type).strip().lower()

    if cleaned in _DOC_TYPE_MAP:
        return _DOC_TYPE_MAP[cleaned]

    return s_raw_type
