"""Resolve assigned visible entry-based SmartShape phrase slurs.

Complete source endpoints identify notes independently of duration or adjacency.
The IR retains those references, including individual grace events, rather than
confusing phrase slurs with per-pitch ties. See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import Slur, SlurEndpoint

__all__ = ["slurs_by_staff"]

_PLACEMENTS: dict[str, str | None] = {"slurDown": "below", "slurUp": "above", "slurAuto": None}
_DIRECTIONS: dict[str, str | None] = {"automatic": None, "over": "above", "under": "below"}
_UNSUPPORTED = frozenset({"hidden", "noPresetShape", "lyricBased"})
_MAX_ENTRY_NUMBER = 0x7FFFFFFF


def _drawing_adjustment(record: Record, name: str) -> tuple[Fraction, Fraction]:
    segment = record.fields.get(name)
    adjustment = segment.fields.get("endPtAdj") if isinstance(segment, Record) else None
    if adjustment is None:
        return Fraction(0), Fraction(0)
    if not isinstance(adjustment, Record):
        raise CorruptScoreError(
            f"smartShape {record.attrs.get('cmper')}: invalid drawing adjustment"
        )
    if "on" not in adjustment.fields:
        return Fraction(0), Fraction(0)
    values = [field_int(adjustment.fields.get(axis, "0")) for axis in ("x", "y")]
    if any(value is None or not -(2**31) <= value < 2**31 for value in values):
        raise CorruptScoreError(
            f"smartShape {record.attrs.get('cmper')}: invalid drawing coordinates"
        )
    x, y = values
    assert x is not None and y is not None
    return Fraction(x, 24), Fraction(y, 24)


def _endpoint(
    document: EnigmaDocument,
    record: Record,
    name: str,
    positions: Mapping[tuple[int, int, int], Sequence[SlurEndpoint]],
) -> tuple[int, SlurEndpoint]:
    segment = record.fields.get(name)
    point = segment.fields.get("endPt") if isinstance(segment, Record) else None
    identity = record.attrs.get("cmper")
    if not isinstance(point, Record):
        raise CorruptScoreError(f"smartShape {identity}: missing {name}.endPt")
    staff = field_int(point.fields.get("inst"))
    measure = field_int(point.fields.get("meas"))
    entry = field_int(point.fields.get("entryNum"))
    if (
        staff is None
        or staff <= 0
        or measure is None
        or measure <= 0
        or entry is None
        or not 0 < entry <= _MAX_ENTRY_NUMBER
    ):
        raise CorruptScoreError(f"smartShape {identity}: invalid {name} entry position")
    candidates = positions.get((staff, measure, entry), ())
    if len(candidates) != 1:
        raise CorruptScoreError(
            f"smartShape {identity}: {name} entry {entry} has "
            f"{len(candidates)} placements at staff {staff} measure {measure}"
        )
    source = document.entries.get(entry)
    if source is None or (field_int(source.fields.get("numNotes")) or 0) <= 0:
        raise CorruptScoreError(
            f"smartShape {identity}: {name} entry {entry} is not a pitched event"
        )
    return staff, candidates[0]


def slurs_by_staff(
    document: EnigmaDocument,
    positions: Mapping[tuple[int, int, int], Sequence[SlurEndpoint]],
    *,
    ignored_shapes: Collection[int] = (),
) -> dict[int, tuple[Slur, ...]]:
    """Join score assignments once per visible preset entry-attached slur.

    Positions are gathered during IR event construction, so source entry-chain
    order and grace-event indices exactly match the events that will be exported.
    Mirrored entries are narrowed by the source endpoint's staff and measure.
    """
    assigned = {
        shape
        for record in (
            *document.others.of_tag("smartShapeMeasMark"),
            *document.details.of_tag("smartShapeEntryMark"),
        )
        if "part" not in record.attrs
        and (shape := field_int(record.fields.get("shapeNum"))) is not None
        and shape > 0
    }
    result: dict[int, list[Slur]] = {}
    assigned.difference_update(ignored_shapes)
    for record in document.others.of_tag("smartShape"):
        kind = str(record.fields.get("shapeType"))
        if (
            "part" in record.attrs
            or field_int(record.attrs.get("cmper")) not in assigned
            or kind not in _PLACEMENTS
            or _UNSUPPORTED.intersection(record.fields)
            or "entryBased" not in record.fields
        ):
            continue
        # A particular chord pitch requires note-id resolution, which is
        # outside the evidenced entry-attached path. Preserve the source ids,
        # but do not silently move a note-attached slur to the chord's first pitch.
        note_ids = [
            field_int(record.fields.get(name, "0")) for name in ("startNoteID", "endNoteID")
        ]
        if any(value is None or value < 0 for value in note_ids):
            raise CorruptScoreError(f"smartShape {record.attrs.get('cmper')}: invalid slur note id")
        if any(note_ids):
            continue
        staff, start = _endpoint(document, record, "startTermSeg", positions)
        end_staff, end = _endpoint(document, record, "endTermSeg", positions)
        if staff != end_staff:
            continue
        graphical = start == end
        start_x, start_y = (
            _drawing_adjustment(record, "startTermSeg") if graphical else (Fraction(0), Fraction(0))
        )
        end_x, end_y = (
            _drawing_adjustment(record, "endTermSeg") if graphical else (Fraction(0), Fraction(0))
        )
        if graphical and start_x == end_x:
            raise CorruptScoreError(
                f"smartShape {record.attrs.get('cmper')}: slur end must follow its start"
            )
        if end.measure < start.measure or (
            end.measure == start.measure
            and start.voice == end.voice
            and end.event_index < start.event_index
        ):
            raise CorruptScoreError(
                f"smartShape {record.attrs.get('cmper')}: slur end must follow its start"
            )
        direction = record.fields.get("dir", "automatic")
        if not isinstance(direction, str) or direction not in _DIRECTIONS:
            raise CorruptScoreError(
                f"smartShape {record.attrs.get('cmper')}: invalid slur direction"
            )
        placement = _DIRECTIONS[direction] or _PLACEMENTS[kind]
        result.setdefault(staff, []).append(
            Slur(start, end, placement, graphical, start_x, start_y, end_x, end_y)
        )
    return {staff: tuple(spans) for staff, spans in result.items()}
