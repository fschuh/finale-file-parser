"""Authored phrases exercise explicit source attachments, including grace notes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.slurs import slurs_by_staff
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.ir import Slur, SlurEndpoint


def _shape(
    *,
    kind: str = "slurAuto",
    attrs: str = "",
    flags: str = "<entryBased/>",
    extra: str = "",
    start_staff: str = "1",
    end_staff: str = "1",
    start_measure: str = "1",
    end_measure: str = "2",
    start_entry: str = "1",
    end_entry: str = "5",
) -> str:
    return f"""
      <smartShape cmper="7"{attrs}>
        <shapeType>{kind}</shapeType>{flags}{extra}
        <startTermSeg><endPt>
          <inst>{start_staff}</inst><meas>{start_measure}</meas><entryNum>{start_entry}</entryNum>
        </endPt></startTermSeg>
        <endTermSeg><endPt>
          <inst>{end_staff}</inst><meas>{end_measure}</meas><entryNum>{end_entry}</entryNum>
        </endPt></endTermSeg>
      </smartShape>
    """


_MARK = '<smartShapeMeasMark cmper="1"><shapeNum>7</shapeNum></smartShapeMeasMark>'
_NOTE = "<note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>"


def _document(shape: str = "", marks: str = _MARK, details: str = "") -> EnigmaDocument:
    # Two independently authored staff-parts mirror the same entries. The
    # source endpoint must select the intended placement, not copy the slur.
    return parse_enigma(
        f"""
        <finale><others>
          <staffSpec cmper="1"/><staffSpec cmper="2"/>
          <instUsed cmper="0" inci="0"><inst>1</inst></instUsed>
          <instUsed cmper="0" inci="1"><inst>2</inst></instUsed>
          <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
          <measSpec cmper="2"><beats>4</beats><divbeat>1024</divbeat></measSpec>
          <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>3</endEntry></frameSpec>
          <frameSpec cmper="2"><startEntry>4</startEntry><endEntry>6</endEntry></frameSpec>
          {shape}{marks}
        </others><details>
          <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
          <gfhold cmper1="1" cmper2="2"><frame1>2</frame1></gfhold>
          <gfhold cmper1="2" cmper2="1"><frame1>1</frame1></gfhold>
          <gfhold cmper1="2" cmper2="2"><frame1>2</frame1></gfhold>
          {details}
        </details><entries>
          <entry entnum="1" prev="0" next="2"><dura>1024</dura><numNotes>1</numNotes>{_NOTE}</entry>
          <entry entnum="2" prev="1" next="3"><dura>1024</dura><numNotes>1</numNotes>{_NOTE}</entry>
          <entry entnum="3" prev="2" next="0"><dura>2048</dura><numNotes>1</numNotes>{_NOTE}</entry>
          <entry entnum="4" prev="0" next="5">
            <dura>512</dura><graceNote/><numNotes>1</numNotes>{_NOTE}
          </entry>
          <entry entnum="5" prev="4" next="6"><dura>2048</dura><numNotes>1</numNotes>{_NOTE}</entry>
          <entry entnum="6" prev="5" next="0"><dura>2048</dura><numNotes>1</numNotes>{_NOTE}</entry>
        </entries></finale>
        """.encode()
    )


@pytest.mark.parametrize(
    ("kind", "placement"), [("slurAuto", None), ("slurUp", "above"), ("slurDown", "below")]
)
def test_source_spans_preserve_nonadjacent_cross_measure_note_references(
    kind: str, placement: str | None
) -> None:
    score = build_score(_document(_shape(kind=kind)))
    assert score.parts[0].slurs == (Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 1), placement),)
    assert score.parts[1].slurs == ()


def test_grace_and_following_main_note_keep_different_references_at_the_same_onset() -> None:
    score = build_score(_document(_shape(start_measure="2", start_entry="4")))
    assert score.parts[0].slurs == (Slur(SlurEndpoint(2, 1, 0), SlurEndpoint(2, 1, 1)),)
    assert score.parts[0].measures[1].voices[0].events[0].is_grace


@pytest.mark.parametrize(
    ("kind", "direction", "placement"),
    [
        ("slurAuto", "automatic", None),
        ("slurAuto", "over", "above"),
        ("slurAuto", "under", "below"),
        ("slurDown", "over", "above"),
    ],
)
def test_explicit_xml_direction_is_retained(
    kind: str, direction: str, placement: str | None
) -> None:
    document = _document(_shape(kind=kind, extra=f"<dir>{direction}</dir>"))
    assert build_score(document).parts[0].slurs[0].placement == placement


def test_malformed_xml_direction_is_rejected() -> None:
    with pytest.raises(CorruptScoreError, match="invalid slur direction"):
        build_score(_document(_shape(extra="<dir>nonsense</dir>")))


def test_a_mirrored_entry_does_not_put_the_slur_on_an_unassigned_staff() -> None:
    score = build_score(_document(_shape(start_staff="2", end_staff="2")))
    assert score.parts[0].slurs == ()
    assert score.parts[1].slurs == (Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 1)),)


def test_entry_marks_alone_establish_an_assigned_shape() -> None:
    mark = '<smartShapeEntryMark entnum="1"><shapeNum>7</shapeNum></smartShapeEntryMark>'
    score = build_score(_document(_shape(), marks="", details=mark))
    assert len(score.parts[0].slurs) == 1


def test_multiple_assignment_kinds_and_linked_definitions_resolve_one_complete_span() -> None:
    details = """
      <smartShapeEntryMark entnum="1"><shapeNum>7</shapeNum></smartShapeEntryMark>
      <smartShapeEntryMark entnum="5"><shapeNum>7</shapeNum></smartShapeEntryMark>
    """
    marks = _MARK + _MARK.replace('cmper="1"', 'cmper="2"')
    shapes = _shape() + _shape(attrs=' part="1"')
    assert len(build_score(_document(shapes, marks, details)).parts[0].slurs) == 1


def test_unassigned_or_linked_only_marks_do_not_place_library_shapes() -> None:
    assert build_score(_document(_shape(), marks="")).parts[0].slurs == ()
    linked = _MARK.replace('cmper="1"', 'cmper="1" part="1"')
    detail = '<smartShapeEntryMark entnum="1" part="1"><shapeNum>7</shapeNum></smartShapeEntryMark>'
    assert build_score(_document(_shape(), linked, detail)).parts[0].slurs == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "cresc"},
        {"kind": "unknown"},
        {"kind": "dashSlurAuto"},
        {"attrs": ' part="1"'},
        {"flags": "<entryBased/><hidden/>"},
        {"flags": "<entryBased/><noPresetShape/>"},
        {"flags": "<entryBased/><lyricBased/>"},
        {"flags": ""},
        {"extra": "<startNoteID>1</startNoteID>"},
        {"extra": "<endNoteID>2</endNoteID>"},
    ],
)
def test_unsupported_or_invisible_shapes_do_not_become_entry_slurs(kwargs: dict[str, str]) -> None:
    assert build_score(_document(_shape(**kwargs))).parts[0].slurs == ()


def test_cross_staff_shapes_are_not_shortened_to_one_staff() -> None:
    assert all(not part.slurs for part in build_score(_document(_shape(end_staff="2"))).parts)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_staff": "0"},
        {"end_staff": "-1"},
        {"start_measure": "nonsense"},
        {"end_measure": "0"},
        {"start_entry": "0"},
        {"end_entry": "2147483648"},
        {"start_entry": "nonsense"},
    ],
)
def test_malformed_supported_endpoint_fields_fail_clearly(kwargs: dict[str, str]) -> None:
    with pytest.raises(CorruptScoreError, match="invalid .* entry position"):
        build_score(_document(_shape(**kwargs)))


def test_missing_entries_or_mismatched_staff_measure_are_not_guessed() -> None:
    for shape in (_shape(end_entry="999"), _shape(end_measure="1")):
        with pytest.raises(CorruptScoreError, match="0 placements"):
            build_score(_document(shape))


def test_a_missing_segment_or_measure_position_cannot_replace_an_entry_attachment() -> None:
    with pytest.raises(CorruptScoreError, match="missing startTermSeg.endPt"):
        build_score(_document(_shape().replace("startTermSeg", "unknownSeg")))
    with pytest.raises(CorruptScoreError, match="invalid .* entry position"):
        build_score(_document(_shape().replace("<entryNum>1</entryNum>", "<edu>0</edu>")))


@pytest.mark.parametrize("note_id", ["-1", "nonsense"])
def test_malformed_note_ids_are_rejected(note_id: str) -> None:
    with pytest.raises(CorruptScoreError, match="invalid slur note id"):
        build_score(_document(_shape(extra=f"<startNoteID>{note_id}</startNoteID>")))


@pytest.mark.parametrize(("start", "end"), [("1", "1"), ("3", "1")])
def test_zero_and_reversed_entry_spans_fail_clearly(start: str, end: str) -> None:
    with pytest.raises(CorruptScoreError, match="end must follow"):
        build_score(_document(_shape(start_entry=start, end_entry=end, end_measure="1")))


def test_an_entry_placed_twice_in_one_cell_is_an_ambiguous_attachment() -> None:
    positions = {
        (1, 1, 1): (SlurEndpoint(1, 1, 0), SlurEndpoint(1, 2, 0)),
        (1, 2, 5): (SlurEndpoint(2, 1, 1),),
    }
    with pytest.raises(CorruptScoreError, match="2 placements"):
        slurs_by_staff(_document(_shape()), positions)


def test_a_rest_cannot_replace_a_pitched_slur_endpoint() -> None:
    document = _document(_shape())
    source = document.entries.get(5)
    assert source is not None
    rest = replace(source, fields={"dura": "2048", "numNotes": "0"})
    document.entries = replace(
        document.entries,
        records=tuple(rest if record is source else record for record in document.entries.records),
    )
    with pytest.raises(CorruptScoreError, match="not a pitched event"):
        build_score(document)


def test_slurs_do_not_change_any_existing_event_or_measure_data() -> None:
    with_slur = build_score(_document(_shape()))
    without_slur = build_score(_document(marks=""))
    assert (
        replace(with_slur, parts=tuple(replace(part, slurs=()) for part in with_slur.parts))
        == without_slur
    )
