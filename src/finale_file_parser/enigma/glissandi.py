"""Recover assigned preset glissandi with exact entry and individual-note IDs."""

from collections.abc import Collection, Mapping, Sequence

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.enigma.slurs import _drawing_adjustment
from finale_file_parser.enigma.smart_shapes import entry_endpoint
from finale_file_parser.ir import Glissando, NoteEndpoint, SlurEndpoint


def _note_endpoint(
    document: EnigmaDocument,
    shape: Record,
    name: str,
    positions: Mapping[tuple[int, int, int], Sequence[SlurEndpoint]],
) -> tuple[int, NoteEndpoint]:
    staff, event = entry_endpoint(document, shape, name + "TermSeg", positions)
    segment = shape.fields[name + "TermSeg"]
    assert isinstance(segment, Record)
    point = segment.fields["endPt"]
    assert isinstance(point, Record)
    number = field_int(point.fields.get("entryNum"))
    source = document.entries.get(number) if number is not None else None
    assert source is not None
    note_id = field_int(shape.fields.get(name + "NoteID"))
    candidates = [
        i
        for i, note in enumerate(read_entry(source).notes)
        if note.note_id == note_id and note_id is not None and note_id > 0
    ]
    if len(candidates) != 1:
        raise CorruptScoreError(
            f"glissando {shape.attrs.get('cmper')}: note ID {note_id} has "
            f"{len(candidates)} matches in entry {number}"
        )
    return staff, NoteEndpoint(event, candidates[0])


def glissandi_by_staff(
    document: EnigmaDocument,
    positions: Mapping[tuple[int, int, int], Sequence[SlurEndpoint]],
    *,
    ignored_shapes: Collection[int] = (),
) -> dict[int, tuple[Glissando, ...]]:
    assigned = {
        n
        for r in (
            *document.others.of_tag("smartShapeMeasMark"),
            *document.details.of_tag("smartShapeEntryMark"),
        )
        if "part" not in r.attrs and (n := field_int(r.fields.get("shapeNum"))) is not None
    }
    out: dict[int, list[Glissando]] = {}
    for shape in document.others.of_tag("smartShape"):
        if (
            field_int(shape.attrs.get("cmper")) not in assigned
            or field_int(shape.attrs.get("cmper")) in ignored_shapes
            or "part" in shape.attrs
            or shape.fields.get("shapeType") != "glissando"
            or {"hidden", "noPresetShape", "lyricBased"}.intersection(shape.fields)
            or "entryBased" not in shape.fields
        ):
            continue
        staff, start = _note_endpoint(document, shape, "start", positions)
        end_staff, end = _note_endpoint(document, shape, "end", positions)
        if staff != end_staff:
            raise CorruptScoreError(
                "cross-staff glissando is not yet representable as a part-local span"
            )
        start_x, start_y = _drawing_adjustment(shape, "startTermSeg")
        end_x, end_y = _drawing_adjustment(shape, "endTermSeg")
        out.setdefault(staff, []).append(
            Glissando(start, end, "wavy", start_x, start_y, end_x, end_y)
        )
    return {staff: tuple(spans) for staff, spans in out.items()}
