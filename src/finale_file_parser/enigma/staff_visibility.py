"""Explicit staff print policy, independent of musical/playback inclusion."""

from typing import Literal

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError

HideMode = Literal["score", "score-parts", "cutaway"]
_MODES: dict[str, HideMode] = {"score": "score", "scoreParts": "score-parts", "cutaway": "cutaway"}


def staff_hide_modes(document: EnigmaDocument) -> dict[int, HideMode]:
    """Read score definitions; linked-part definitions cannot hide score staves."""
    result: dict[int, HideMode] = {}
    for record in document.others.of_tag("staffSpec"):
        if record.attrs.get("part", "0") != "0" or "hideMode" not in record.fields:
            continue
        raw = record.fields["hideMode"]
        if not isinstance(raw, str) or raw not in _MODES:
            raise CorruptScoreError("staffSpec: unsupported hideMode")
        staff = field_int(record.attrs.get("cmper"))
        if staff is None:
            raise CorruptScoreError("staffSpec: hideMode has no valid staff ID")
        result[staff] = _MODES[raw]
    return result
