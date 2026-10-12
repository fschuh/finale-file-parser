"""Written spelling, performed pitch and inclusive octave endpoints are independent."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import (
    Arpeggio,
    ClefChange,
    Event,
    Measure,
    OctaveShift,
    Part,
    PartGroup,
    Pitch,
    Score,
    Voice,
)

NOTE = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 1), Pitch("E", 4, 0)))
GRACE = replace(NOTE, duration=Fraction(0), written_duration=Fraction(1, 8), is_grace=True)


def _part(span: OctaveShift, *, events: tuple[Event, ...] = (NOTE,) * 4) -> Part:
    return Part("P1", "Authored", (Measure(1, (Voice(1, events),)),), octave_shifts=(span,))


@pytest.mark.parametrize(
    ("octaves", "kind", "size"),
    [(-2, "up", "15"), (-1, "up", "8"), (1, "down", "8"), (2, "down", "15")],
)
def test_performed_xml_pitches_change_once_and_ir_spelling_remains_written(
    octaves: int,
    kind: str,
    size: str,
) -> None:
    part = _part(OctaveShift(octaves, 1, Fraction(1, 4), 1, Fraction(1, 2)))
    root = DET.fromstring(to_musicxml(Score(parts=(part,))))
    assert [n.text for n in root.findall(".//note/pitch/octave")] == [
        str(n) for n in (4, 4, 4 + octaves, 4 + octaves, 4 + octaves, 4 + octaves, 4, 4)
    ]
    assert root.findtext(".//pitch/step") == "C"
    assert root.findtext(".//pitch/alter") == "1"
    assert [p.octave for p in part.measures[0].voices[0].events[1].pitches] == [4, 4]
    marks = root.findall(".//octave-shift")
    assert [(m.get("type"), m.get("size")) for m in marks] == [(kind, size), ("stop", size)]
    assert [e.text for e in root.findall(".//direction/offset")] == ["1", "3"]


def test_point_span_covers_graces_and_anchor_but_not_the_following_attack() -> None:
    part = _part(OctaveShift(-1, 1, Fraction(0), 1, Fraction(0)), events=(GRACE, NOTE, NOTE))
    root = DET.fromstring(to_musicxml(Score(parts=(part,))))
    assert [n.text for n in root.findall(".//note/pitch/octave")] == ["3", "3", "3", "3", "4", "4"]
    assert [e.text for e in root.findall(".//direction/offset")] == ["0", "1"]
    assert root.findall(".//note/grace")


def test_cross_bar_span_obeys_voice_offsets_and_clef_changes() -> None:
    part = Part(
        "P1",
        "Authored",
        (
            Measure(
                1,
                (Voice(1, (NOTE,), start_offset=Fraction(1, 8)),),
                clef_changes=(ClefChange(Fraction(1, 4), "F", 4),),
            ),
            Measure(2, (Voice(1, (NOTE, NOTE)),)),
        ),
        octave_shifts=(OctaveShift(1, 1, Fraction(1, 8), 2, Fraction(0)),),
    )
    root = DET.fromstring(to_musicxml(Score(parts=(part,))))
    assert root.findtext(".//attributes/divisions") == "2"
    assert [n.text for n in root.findall(".//note/pitch/octave")] == ["5", "5", "5", "5", "4", "4"]
    assert [e.text for e in root.findall(".//direction/offset")] == ["1", "2"]
    assert root.findtext(".//clef/sign") == "F"


def test_independent_projected_staves_do_not_share_octave_numbers_or_pitches() -> None:
    ids = ("P1", "P2")
    roll = Arpeggio("authored-roll", ids)
    first = _part(
        OctaveShift(1, 1, Fraction(0), 1, Fraction(1, 2)),
        events=(replace(NOTE, arpeggios=(roll,)), NOTE, NOTE, NOTE),
    )
    second = replace(
        first, id="P2", octave_shifts=(OctaveShift(-1, 1, Fraction(0), 1, Fraction(1, 2)),)
    )
    root = DET.fromstring(
        to_musicxml(Score(parts=(first, second), groups=(PartGroup(ids, "brace"),)))
    )
    assert len(root.findall("part")) == 1
    assert [d.findtext("staff") for d in root.findall(".//direction")] == ["1", "1", "2", "2"]
    assert [n.text for n in root.findall(".//note/pitch/octave")] == ["5"] * 6 + ["4"] * 2 + [
        "3"
    ] * 6 + ["4"] * 2


@pytest.mark.parametrize(
    "span",
    [
        OctaveShift(0, 1, Fraction(0), 1, Fraction(1)),
        OctaveShift(1, 1, Fraction(-1), 1, Fraction(1)),
        OctaveShift(1, 1, Fraction(0), 3, Fraction(1)),
        OctaveShift(1, 1, Fraction(1), 1, Fraction(0)),
    ],
)
def test_invalid_octaves_and_endpoints_fail_clearly(span: OctaveShift) -> None:
    with pytest.raises(ExportError):
        to_musicxml(Score(parts=(_part(span),)))


def test_overlapping_staff_spans_are_reported_instead_of_summing_guessed_octaves() -> None:
    part = _part(OctaveShift(1, 1, Fraction(0), 1, Fraction(1, 2)))
    part = replace(
        part,
        octave_shifts=part.octave_shifts + (OctaveShift(1, 1, Fraction(1, 4), 1, Fraction(3, 4)),),
    )
    with pytest.raises(ExportError, match="overlapping octave"):
        to_musicxml(Score(parts=(part,)))
