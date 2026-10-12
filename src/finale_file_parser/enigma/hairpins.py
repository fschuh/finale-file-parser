"""Resolve assigned visible measure-based SmartShape hairpins in either format.

Finale's named cresc/decresc shapes carry complete termination segments. Library
definitions, linked-part copies, custom shapes and entry/lyric-based endpoints
do not establish a visible measure-based span; see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from collections.abc import Collection
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import Hairpin

__all__ = ["hairpins_by_staff"]

_KINDS = {"cresc": "crescendo", "decresc": "diminuendo"}
_WHOLE_EDU = 4096
_MAX_EDU = 0x7FFFFFFF
_EVPU_PER_SPACE = 24
_MIN_ADJUSTMENT = -0x80000000
_MAX_ADJUSTMENT = 0x7FFFFFFF
_UNSUPPORTED = frozenset({"hidden", "noPresetShape", "entryBased", "lyricBased"})


def _endpoint(record: Record, name: str) -> tuple[int, int, Fraction]:
    segment = record.fields.get(name)
    point = segment.fields.get("endPt") if isinstance(segment, Record) else None
    if not isinstance(point, Record):
        raise CorruptScoreError(f"smartShape {record.attrs.get('cmper')}: missing {name}.endPt")
    staff = field_int(point.fields.get("inst"))
    measure = field_int(point.fields.get("meas"))
    # EnigmaXML can omit the default zero, as it does for other scalar fields.
    edu = field_int(point.fields.get("edu", "0"))
    if (
        staff is None
        or staff <= 0
        or measure is None
        or measure <= 0
        or edu is None
        or not 0 <= edu <= _MAX_EDU
        or "entryNum" in point.fields
    ):
        raise CorruptScoreError(f"smartShape {record.attrs.get('cmper')}: invalid {name} position")
    return staff, measure, Fraction(edu, _WHOLE_EDU)


def _horizontal_adjustment(record: Record, name: str) -> Fraction:
    """Active Finale EVPU adjustments become exact staff-space distances."""
    segment = record.fields.get(name)
    adjustment = segment.fields.get("endPtAdj") if isinstance(segment, Record) else None
    if adjustment is None:
        return Fraction(0)
    if not isinstance(adjustment, Record):
        raise CorruptScoreError(f"smartShape {record.attrs.get('cmper')}: invalid {name}.endPtAdj")
    if "on" not in adjustment.fields:
        return Fraction(0)
    x = field_int(adjustment.fields.get("x", "0"))
    if x is None or not _MIN_ADJUSTMENT <= x <= _MAX_ADJUSTMENT:
        raise CorruptScoreError(
            f"smartShape {record.attrs.get('cmper')}: invalid {name} horizontal adjustment"
        )
    return Fraction(x, _EVPU_PER_SPACE)


def hairpins_by_staff(
    document: EnigmaDocument, *, ignored_shapes: Collection[int] = ()
) -> dict[int, tuple[Hairpin, ...]]:
    """Join score measure assignments once per visible standard hairpin."""
    assigned = {
        shape
        for record in document.others.of_tag("smartShapeMeasMark")
        if "part" not in record.attrs
        and (shape := field_int(record.fields.get("shapeNum"))) is not None
        and shape > 0
    }
    result: dict[int, list[Hairpin]] = {}
    assigned.difference_update(ignored_shapes)
    for record in document.others.of_tag("smartShape"):
        shape = field_int(record.attrs.get("cmper"))
        kind = _KINDS.get(str(record.fields.get("shapeType")))
        if (
            "part" in record.attrs
            or shape not in assigned
            or kind is None
            or _UNSUPPORTED.intersection(record.fields)
        ):
            continue
        staff, start_measure, start_offset = _endpoint(record, "startTermSeg")
        end_staff, end_measure, end_offset = _endpoint(record, "endTermSeg")
        if staff != end_staff:
            # The current IR's parts are separate staves; don't shorten a
            # cross-staff span by pretending both endpoints live on one staff.
            continue
        if (end_measure, end_offset) <= (start_measure, start_offset):
            raise CorruptScoreError(f"smartShape {shape}: hairpin end must follow its start")
        result.setdefault(staff, []).append(
            Hairpin(
                kind,
                start_measure,
                start_offset,
                end_measure,
                end_offset,
                _horizontal_adjustment(record, "startTermSeg"),
                _horizontal_adjustment(record, "endTermSeg"),
            )
        )
    return {staff: tuple(spans) for staff, spans in result.items()}
