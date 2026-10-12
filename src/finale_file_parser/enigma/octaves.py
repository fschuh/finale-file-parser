"""Recover assigned standard octave lines without altering written pitches."""

from collections.abc import Collection

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.hairpins import _endpoint
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import OctaveShift

_KINDS = {
    "4": -1,
    "5": 1,
    "20": -2,
    "21": 2,
    "octaveDown": -1,
    "octaveUp": 1,
    "twoOctaveDown": -2,
    "twoOctaveUp": 2,
}
_UNSUPPORTED = frozenset({"hidden", "noPresetShape", "entryBased", "lyricBased"})


def octaves_by_staff(
    document: EnigmaDocument,
    *,
    ignored_shapes: Collection[int] = (),
) -> dict[int, tuple[OctaveShift, ...]]:
    assigned = {
        number
        for record in document.others.of_tag("smartShapeMeasMark")
        if "part" not in record.attrs
        and (number := field_int(record.fields.get("shapeNum"))) is not None
        and number > 0
    } - set(ignored_shapes)
    result: dict[int, list[OctaveShift]] = {}
    for record in document.others.of_tag("smartShape"):
        kind = _KINDS.get(str(record.fields.get("shapeType")))
        if (
            kind is None
            or "part" in record.attrs
            or _UNSUPPORTED.intersection(record.fields)
            or field_int(record.attrs.get("cmper")) not in assigned
        ):
            continue
        staff, measure, offset = _endpoint(record, "startTermSeg")
        end_staff, end_measure, end_offset = _endpoint(record, "endTermSeg")
        if staff != end_staff:
            continue
        if (end_measure, end_offset) < (measure, offset):
            raise CorruptScoreError(f"smartShape {record.attrs.get('cmper')}: reversed octave span")
        result.setdefault(staff, []).append(
            OctaveShift(kind, measure, offset, end_measure, end_offset)
        )
    return {staff: tuple(spans) for staff, spans in result.items()}
