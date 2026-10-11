"""Authored spans verify wedge pairing, cursor timing and staff projection."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import (
    Arpeggio,
    Event,
    Hairpin,
    Measure,
    Part,
    PartGroup,
    Pitch,
    Score,
    TimeSignature,
    Voice,
)


def _measure(number: int) -> Measure:
    note = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 0),))
    return Measure(number, (Voice(1, (note,) * 4),), time=TimeSignature(4, 4))


def _score(*hairpins: Hairpin) -> Score:
    return Score(parts=(Part("P1", "Authored", (_measure(1), _measure(2)), hairpins),))


def _tree(score: Score) -> ET.Element:
    return DET.fromstring(to_musicxml(score))


def _positions(root: ET.Element) -> list[tuple[str, str | None, Fraction, str | None, str | None]]:
    """Interpret offsets relative to the real XML cursor, including staff backups."""
    result = []
    divisions = 1
    for measure in root.findall("part/measure"):
        value = measure.findtext("attributes/divisions")
        if value is not None:
            divisions = int(value)
        cursor = Fraction(0)
        for element in measure:
            if element.tag in {"backup", "forward"}:
                delta = Fraction(int(element.findtext("duration", "0")), divisions * 4)
                cursor += delta if element.tag == "forward" else -delta
            elif element.tag == "note" and element.find("chord") is None:
                cursor += Fraction(int(element.findtext("duration", "0")), divisions * 4)
            elif (wedge := element.find("direction-type/wedge")) is not None:
                offset = Fraction(int(element.findtext("offset", "0")), divisions * 4)
                result.append(
                    (
                        measure.get("number", ""),
                        element.findtext("staff"),
                        cursor + offset,
                        wedge.get("type"),
                        wedge.get("number"),
                    )
                )
    return result


@pytest.mark.parametrize("kind", ["crescendo", "diminuendo"])
def test_wedges_keep_exact_offsets_and_pairing_without_overriding_the_readers_height(
    kind: str,
) -> None:
    root = _tree(_score(Hairpin(kind, 1, Fraction(1, 4), 1, Fraction(7, 8))))
    assert root.findtext("part/measure/attributes/divisions") == "2"
    assert _positions(root) == [
        ("1", None, Fraction(1, 4), kind, "1"),
        ("1", None, Fraction(7, 8), "stop", "1"),
    ]
    # MuseScore uses a start spread=0 as overall height and ignores the stop
    # spread. The former explicit 0/15 pair passed schema/Verovio checks but
    # imported as a flat line. Both kinds must use the reader's normal opening.
    assert [wedge.attrib for wedge in root.findall(".//wedge")] == [
        {"type": kind, "number": "1"},
        {"type": "stop", "number": "1"},
    ]
    assert all(direction.get("placement") == "below" for direction in root.findall(".//direction"))
    assert all(offset.get("sound") == "yes" for offset in root.findall(".//direction/offset"))
    assert root.find(".//sound") is None


def test_a_fractional_position_can_require_more_precision_than_any_note() -> None:
    root = _tree(_score(Hairpin("crescendo", 1, Fraction(1, 12), 1, Fraction(1))))
    assert root.findtext("part/measure/attributes/divisions") == "3"
    assert _positions(root)[0][2] == Fraction(1, 12)
    assert [note.findtext("duration") for note in root.findall(".//note")] == ["3"] * 8


def test_a_cross_measure_span_has_one_start_and_one_stop_at_the_barline() -> None:
    root = _tree(_score(Hairpin("crescendo", 1, Fraction(1, 4), 2, Fraction(1))))
    assert _positions(root) == [
        ("1", None, Fraction(1, 4), "crescendo", "1"),
        ("2", None, Fraction(1), "stop", "1"),
    ]


def test_overlapping_spans_pair_independently_even_when_the_shorter_one_closes_first() -> None:
    spans = (
        Hairpin("diminuendo", 1, Fraction(1, 4), 1, Fraction(3, 4)),
        Hairpin("crescendo", 1, Fraction(0), 2, Fraction(1)),
    )
    positions = _positions(_tree(_score(*spans)))
    assert [(position[3], position[4]) for position in positions] == [
        ("crescendo", "1"),
        ("diminuendo", "2"),
        ("stop", "2"),
        ("stop", "1"),
    ]


def test_touching_spans_close_before_reusing_the_number() -> None:
    root = _tree(
        _score(
            Hairpin("crescendo", 1, Fraction(0), 1, Fraction(1, 2)),
            Hairpin("diminuendo", 1, Fraction(1, 2), 1, Fraction(1)),
        )
    )
    assert [(position[3], position[4]) for position in _positions(root)] == [
        ("crescendo", "1"),
        ("stop", "1"),
        ("diminuendo", "1"),
        ("stop", "1"),
    ]


def _bundle(upper: Hairpin, lower: Hairpin) -> Score:
    connection = Arpeggio("roll", ("RH", "LH"))
    measure = _measure(1)
    first = replace(measure.voices[0].events[0], arpeggios=(connection,))
    measure = replace(measure, voices=(Voice(1, (first, *measure.voices[0].events[1:])),))
    return Score(
        parts=(
            Part("RH", "Keyboard", (measure, _measure(2)), (upper,)),
            Part("LH", "Keyboard", (measure, _measure(2)), (lower,)),
        ),
        groups=(PartGroup(("RH", "LH"), "brace", True),),
    )


def test_projected_staves_keep_their_offsets_after_the_cursor_rewinds() -> None:
    root = _tree(
        _bundle(
            Hairpin("crescendo", 1, Fraction(1, 8), 2, Fraction(1)),
            Hairpin("diminuendo", 1, Fraction(1, 4), 2, Fraction(3, 4)),
        )
    )
    assert len(root.findall("part")) == 1
    assert _positions(root) == [
        ("1", "1", Fraction(1, 8), "crescendo", "1"),
        ("1", "2", Fraction(1, 4), "diminuendo", "2"),
        ("2", "1", Fraction(1), "stop", "1"),
        ("2", "2", Fraction(3, 4), "stop", "2"),
    ]


def test_numbering_respects_staff_document_order_when_musical_spans_do_not_overlap() -> None:
    # RH's later start is serialized before LH's earlier start/stop. Reusing
    # number 1 based only on musical time would overlap it in the XML document.
    root = _tree(
        _bundle(
            Hairpin("crescendo", 1, Fraction(3, 4), 2, Fraction(1, 4)),
            Hairpin("diminuendo", 1, Fraction(1, 4), 1, Fraction(1, 2)),
        )
    )
    assert [(position[1], position[3], position[4]) for position in _positions(root)] == [
        ("1", "crescendo", "1"),
        ("2", "diminuendo", "2"),
        ("2", "stop", "2"),
        ("1", "stop", "1"),
    ]


def test_an_empty_measure_and_nonconsecutive_measure_labels_keep_their_span() -> None:
    measures = (Measure(10, time=TimeSignature(3, 4)), Measure(20))
    part = Part(
        "P1", "Authored", measures, (Hairpin("crescendo", 10, Fraction(0), 20, Fraction(3, 4)),)
    )
    assert _positions(_tree(Score(parts=(part,)))) == [
        ("10", None, Fraction(0), "crescendo", "1"),
        ("20", None, Fraction(3, 4), "stop", "1"),
    ]


@pytest.mark.parametrize(
    ("span", "message"),
    [
        (Hairpin("unknown", 1, Fraction(0), 1, Fraction(1)), "unsupported hairpin kind"),
        (Hairpin("crescendo", 0, Fraction(0), 1, Fraction(1)), "missing measure"),
        (Hairpin("crescendo", 1, Fraction(0), 9, Fraction(1)), "missing measure"),
        (Hairpin("crescendo", 1, Fraction(-1, 8), 1, Fraction(1)), "outside measure"),
        (Hairpin("crescendo", 1, Fraction(0), 1, Fraction(2)), "outside measure"),
        (Hairpin("crescendo", 2, Fraction(0), 1, Fraction(1)), "end must follow"),
        (Hairpin("crescendo", 1, Fraction(1, 2), 1, Fraction(1, 2)), "end must follow"),
    ],
)
def test_invalid_authored_spans_fail_clearly(span: Hairpin, message: str) -> None:
    with pytest.raises(ExportError, match=message):
        to_musicxml(_score(span))


def test_a_pathological_offset_is_subject_to_the_divisions_guard() -> None:
    with pytest.raises(ExportError, match="divisions per quarter; refusing"):
        to_musicxml(_score(Hairpin("crescendo", 1, Fraction(1, 1_000_003), 1, Fraction(1))))


def test_more_than_sixteen_document_overlaps_fail_instead_of_writing_invalid_numbers() -> None:
    span = Hairpin("crescendo", 1, Fraction(0), 2, Fraction(1))
    with pytest.raises(ExportError, match="more than 16 hairpins overlap"):
        to_musicxml(_score(*(span for _ in range(17))))


def test_many_nonoverlapping_spans_reuse_a_valid_number() -> None:
    measures = tuple(_measure(index) for index in range(1, 21))
    spans = tuple(
        Hairpin("crescendo", index, Fraction(0), index, Fraction(1)) for index in range(1, 21)
    )
    root = _tree(Score(parts=(Part("P1", "Authored", measures, spans),)))
    assert len(root.findall(".//wedge")) == 40
    assert {wedge.get("number") for wedge in root.findall(".//wedge")} == {"1"}


def test_hairpins_do_not_change_note_onsets_in_multiple_voices() -> None:
    score = _score(Hairpin("crescendo", 1, Fraction(1, 8), 1, Fraction(7, 8)))
    part = score.parts[0]
    measure = part.measures[0]
    measure = replace(measure, voices=(*measure.voices, replace(measure.voices[0], number=2)))
    score = replace(score, parts=(replace(part, measures=(measure, part.measures[1])),))
    root = _tree(score)
    assert [backup.findtext("duration") for backup in root.findall(".//backup")] == ["8"]
    assert [note.findtext("duration") for note in root.findall(".//note")] == ["2"] * 12
    assert _positions(root) == [
        ("1", None, Fraction(1, 8), "crescendo", "1"),
        ("1", None, Fraction(7, 8), "stop", "1"),
    ]


def test_duplicate_measure_labels_do_not_make_span_placement_ambiguous() -> None:
    score = _score(Hairpin("crescendo", 1, Fraction(0), 1, Fraction(1)))
    part = replace(score.parts[0], measures=(_measure(1), _measure(1)))
    with pytest.raises(ExportError, match="unique measure numbers"):
        to_musicxml(replace(score, parts=(part,)))


@pytest.mark.parametrize("kind", ["crescendo", "diminuendo"])
def test_horizontal_adjustments_change_only_visual_wedge_positions(kind: str) -> None:
    span = Hairpin(kind, 1, Fraction(0), 1, Fraction(1))
    before = _tree(_score(span))
    after = _tree(
        _score(replace(span, start_x_offset=Fraction(1, 2), end_x_offset=Fraction(-3, 4)))
    )
    wedges = after.findall(".//wedge")
    assert [wedge.get("relative-x") for wedge in wedges] == ["5", "-7.5"]
    assert _positions(after) == _positions(before)
    for wedge in wedges:
        assert "spread" not in wedge.attrib and "default-x" not in wedge.attrib
        del wedge.attrib["relative-x"]
    assert ET.tostring(after) == ET.tostring(before)


def test_nonterminating_space_adjustments_export_valid_decimal_tenths() -> None:
    span = Hairpin("crescendo", 1, Fraction(0), 1, Fraction(1), end_x_offset=Fraction(-37, 24))
    text = _tree(_score(span)).findall(".//wedge")[1].get("relative-x")
    assert text is not None and "e" not in text.lower()
    assert abs(Fraction(text) - Fraction(-185, 12)) < Fraction(1, 10**25)


def test_visual_adjustment_denominators_do_not_change_time_divisions() -> None:
    span = Hairpin(
        "crescendo", 1, Fraction(0), 1, Fraction(1), end_x_offset=Fraction(-1, 1_000_003)
    )
    root = _tree(_score(span))
    assert root.findtext("part/measure/attributes/divisions") == "1"
    assert _positions(root) == [
        ("1", None, Fraction(0), "crescendo", "1"),
        ("1", None, Fraction(1), "stop", "1"),
    ]


def test_projected_staff_hairpins_keep_their_own_horizontal_adjustments() -> None:
    first = Hairpin("crescendo", 1, Fraction(0), 2, Fraction(1), Fraction(1, 2), Fraction(-3, 4))
    second = Hairpin("diminuendo", 1, Fraction(0), 2, Fraction(1), Fraction(1), Fraction(-1, 4))
    root = _tree(_bundle(first, second))
    assert [wedge.get("relative-x") for wedge in root.findall(".//wedge")] == [
        "5",
        "10",
        "-7.5",
        "-2.5",
    ]
