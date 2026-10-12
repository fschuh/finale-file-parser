"""Scope assigned shapes against the score without altering source records."""

from collections.abc import Collection, Mapping, Sequence

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import ScoreDiagnostic, SlurEndpoint


def entry_endpoint(
    document: EnigmaDocument,
    record: Record,
    name: str,
    positions: Mapping[tuple[int, int, int], Sequence[SlurEndpoint]],
) -> tuple[int, SlurEndpoint]:
    """Resolve one exact entry attachment shared by slurs and note-based shapes."""
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
        or not 0 < entry <= 0x7FFFFFFF
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


def _position(record: Record, name: str) -> tuple[int, int] | None:
    segment = record.fields.get(name)
    point = segment.fields.get("endPt") if isinstance(segment, Record) else None
    if not isinstance(point, Record):
        return None
    staff, measure = field_int(point.fields.get("inst")), field_int(point.fields.get("meas"))
    time_field = "entryNum" if "entryBased" in record.fields else "edu"
    time = field_int(point.fields.get(time_field, "0"))
    if (
        staff is None
        or staff <= 0
        or measure is None
        or measure <= 0
        or time is None
        or not 0 <= time <= 0x7FFFFFFF
        or (time_field == "entryNum" and time == 0)
    ):
        return None
    return measure, time


def stale_smart_shapes(
    document: EnigmaDocument, measures: Collection[int]
) -> tuple[frozenset[int], tuple[ScoreDiagnostic, ...]]:
    """Quarantine visible assigned shapes wholly beyond the actual last bar.

    A partially missing span or an invalid endpoint remains subject to ordinary
    validation. Neither a palette definition nor a linked-part-only assignment
    establishes a visible score shape. Source records are never removed.
    """
    if not measures:
        return frozenset(), ()
    assigned = {
        number
        for record in (
            *document.others.of_tag("smartShapeMeasMark"),
            *document.details.of_tag("smartShapeEntryMark"),
        )
        if "part" not in record.attrs
        and (number := field_int(record.fields.get("shapeNum"))) is not None
        and number > 0
    }
    last = max(measures)
    ignored = set()
    diagnostics = []
    for record in document.others.of_tag("smartShape"):
        number = field_int(record.attrs.get("cmper"))
        if number not in assigned or "part" in record.attrs or "hidden" in record.fields:
            continue
        first, final = _position(record, "startTermSeg"), _position(record, "endTermSeg")
        if number is None or first is None or final is None:
            continue
        start, end = first[0], final[0]
        if start <= last or end <= last or end < start:
            continue
        if record.fields.get("shapeType") in {"cresc", "decresc"} and final <= first:
            continue
        ignored.add(number)
        diagnostics.append(
            ScoreDiagnostic(
                "stale-shape",
                f"Assigned shape {number} refers wholly beyond the score "
                f"(bars {start}–{end}; last bar {last}). Its source record is retained.",
                f"smartShape:{number}",
            )
        )
    return frozenset(ignored), tuple(diagnostics)
