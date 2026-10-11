"""Authored phrase spans verify note attachments, numbering and staff projection."""

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
    Measure,
    NoteTies,
    Part,
    PartGroup,
    Pitch,
    Score,
    Slur,
    SlurEndpoint,
    Voice,
)

_NOTE = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 0),))


def _measure(number: int) -> Measure:
    return Measure(number, (Voice(1, (_NOTE,) * 4),))


def _score(*spans: Slur) -> Score:
    return Score(parts=(Part("P1", "Authored", (_measure(1), _measure(2)), slurs=spans),))


def _tree(score: Score) -> ET.Element:
    return DET.fromstring(to_musicxml(score))


def _marks(root: ET.Element) -> list[tuple[str, str | None, str | None, int, dict[str, str]]]:
    result = []
    for measure in root.findall("part/measure"):
        indices: dict[tuple[str | None, str | None], int] = {}
        for note in measure.findall("note"):
            voice, staff = note.findtext("voice"), note.findtext("staff")
            key = voice, staff
            if note.find("chord") is None:
                indices[key] = indices.get(key, -1) + 1
            for slur in note.findall("notations/slur"):
                result.append((measure.get("number", ""), voice, staff, indices[key], slur.attrib))
    return result


@pytest.mark.parametrize(
    ("placement", "extra"),
    [
        (None, {}),
        ("above", {"placement": "above", "orientation": "over"}),
        ("below", {"placement": "below", "orientation": "under"}),
    ],
)
def test_nonadjacent_cross_measure_slurs_attach_only_to_the_exact_endpoint_notes(
    placement: str | None, extra: dict[str, str]
) -> None:
    root = _tree(_score(Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 3), placement)))
    assert _marks(root) == [
        ("1", "1", None, 0, {"type": "start", "number": "1", **extra}),
        ("2", "1", None, 3, {"type": "stop", "number": "1", **extra}),
    ]
    assert root.findall(".//tie") == []
    assert root.findall(".//tied") == []


def test_nested_slurs_pair_independently_when_the_inner_phrase_ends_first() -> None:
    root = _tree(
        _score(
            Slur(SlurEndpoint(1, 1, 1), SlurEndpoint(2, 1, 0)),
            Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 3)),
        )
    )
    assert [mark[-1] for mark in _marks(root)] == [
        {"type": "start", "number": "1"},
        {"type": "start", "number": "2"},
        {"type": "stop", "number": "2"},
        {"type": "stop", "number": "1"},
    ]


def test_touching_slurs_close_before_opening_the_next_span_on_the_same_note() -> None:
    root = _tree(
        _score(
            Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 2)),
            Slur(SlurEndpoint(1, 1, 2), SlurEndpoint(2, 1, 3)),
        )
    )
    assert [(mark[3], mark[-1]) for mark in _marks(root)] == [
        (0, {"type": "start", "number": "1"}),
        (2, {"type": "stop", "number": "1"}),
        (2, {"type": "start", "number": "1"}),
        (3, {"type": "stop", "number": "1"}),
    ]


def test_individual_grace_notes_are_not_replaced_by_the_main_note_at_the_same_onset() -> None:
    grace = replace(
        _NOTE,
        duration=Fraction(0),
        written_duration=Fraction(1, 8),
        is_grace=True,
        grace_slash=True,
    )
    measures = (Measure(1, (Voice(1, (grace, grace, _NOTE, _NOTE, _NOTE, _NOTE)),)),)
    spans = (Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 1)),)
    root = _tree(Score(parts=(Part("P1", "Authored", measures, slurs=spans),)))
    assert [(mark[3], mark[-1]["type"]) for mark in _marks(root)] == [(0, "start"), (1, "stop")]
    notes = root.findall(".//note")
    assert all(
        note.find("grace") is not None and note.find("duration") is None for note in notes[:2]
    )
    assert all(note.find("notations") is None for note in notes[2:])


def test_a_slur_can_start_on_a_grace_and_stop_on_the_following_main_note() -> None:
    grace = replace(_NOTE, duration=Fraction(0), is_grace=True)
    measure = Measure(1, (Voice(1, (grace, _NOTE)),))
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 1))
    root = _tree(Score(parts=(Part("P1", "Authored", (measure,), slurs=(span,)),)))
    assert [mark[3] for mark in _marks(root)] == [0, 1]


def test_chords_keep_one_phrase_endpoint_while_individual_ties_survive() -> None:
    chord = replace(
        _NOTE, pitches=(*_NOTE.pitches, Pitch("E", 4, 0)), note_ties=(NoteTies(True), NoteTies())
    )
    measure = Measure(1, (Voice(1, (chord, _NOTE, _NOTE, _NOTE)),))
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 3))
    root = _tree(Score(parts=(Part("P1", "Authored", (measure,), slurs=(span,)),)))
    notes = root.findall(".//note")
    assert notes[0].find("notations/slur") is not None
    assert notes[0].find("notations/tied") is not None
    assert notes[0].find("tie") is not None
    assert notes[1].find("notations/slur") is None
    assert notes[1].find("notations/tied") is None
    assert len(root.findall(".//slur")) == 2


def _bundle() -> Score:
    roll = Arpeggio("joined", ("RH", "LH"))
    first = replace(_NOTE, arpeggios=(roll,))
    measure = Measure(1, (Voice(1, (first, _NOTE, _NOTE, _NOTE)),))
    upper = Slur(SlurEndpoint(1, 1, 3), SlurEndpoint(2, 1, 0))
    lower = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 1))
    return Score(
        parts=(
            Part("RH", "Authored", (measure, _measure(2)), slurs=(upper,)),
            Part("LH", "Authored", (measure, _measure(2)), slurs=(lower,)),
        ),
        groups=(PartGroup(("RH", "LH"), "brace", True),),
    )


def test_projected_staves_keep_note_attachments_and_allocate_numbers_in_document_order() -> None:
    root = _tree(_bundle())
    assert len(root.findall("part")) == 1
    assert _marks(root) == [
        ("1", "1", "1", 3, {"type": "start", "number": "1"}),
        ("1", "2", "2", 0, {"type": "start", "number": "2"}),
        ("1", "2", "2", 1, {"type": "stop", "number": "2"}),
        ("2", "1", "1", 0, {"type": "stop", "number": "1"}),
    ]


def test_cross_voice_stop_before_start_in_xml_keeps_the_same_pairing_number() -> None:
    # The first serialized voice ends a span begun earlier in musical time
    # by the second voice. Its stop reserves the number until the start is seen.
    measure = Measure(1, (Voice(1, (_NOTE,) * 4), Voice(2, (_NOTE,) * 4)))
    span = Slur(SlurEndpoint(1, 2, 0), SlurEndpoint(1, 1, 1))
    root = _tree(Score(parts=(Part("P1", "Authored", (measure,), slurs=(span,)),)))
    assert _marks(root) == [
        ("1", "1", None, 1, {"type": "stop", "number": "1"}),
        ("1", "2", None, 0, {"type": "start", "number": "1"}),
    ]


def test_nonconsecutive_measure_labels_use_score_sequence_for_the_span() -> None:
    measures = (_measure(20), _measure(10))
    span = Slur(SlurEndpoint(20, 1, 0), SlurEndpoint(10, 1, 3))
    root = _tree(Score(parts=(Part("P1", "Authored", measures, slurs=(span,)),)))
    assert [mark[0] for mark in _marks(root)] == ["20", "10"]


@pytest.mark.parametrize(
    "span",
    [
        Slur(SlurEndpoint(0, 1, 0), SlurEndpoint(1, 1, 3)),
        Slur(SlurEndpoint(1, 2, 0), SlurEndpoint(1, 1, 3)),
        Slur(SlurEndpoint(1, 1, -1), SlurEndpoint(1, 1, 3)),
        Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 1_000_000_000)),
    ],
)
def test_missing_authored_endpoints_fail_without_expanding_their_indices(span: Slur) -> None:
    with pytest.raises(ExportError, match="missing measure, voice or event"):
        to_musicxml(_score(span))


@pytest.mark.parametrize(
    "span",
    [
        Slur(SlurEndpoint(2, 1, 0), SlurEndpoint(1, 1, 3)),
        Slur(SlurEndpoint(1, 1, 3), SlurEndpoint(1, 1, 0)),
        Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 0)),
    ],
)
def test_zero_and_reversed_authored_spans_fail_clearly(span: Slur) -> None:
    with pytest.raises(ExportError, match="end must follow"):
        to_musicxml(_score(span))


def test_a_rest_cannot_be_used_as_a_pitched_slur_endpoint() -> None:
    measure = Measure(1, (Voice(1, (replace(_NOTE, pitches=()), _NOTE)),))
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 1))
    with pytest.raises(ExportError, match="pitched events"):
        to_musicxml(Score(parts=(Part("P1", "Authored", (measure,), slurs=(span,)),)))


def test_invalid_placement_does_not_become_an_invalid_xml_attribute() -> None:
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 3), "unknown")
    with pytest.raises(ExportError, match="unsupported slur placement"):
        to_musicxml(_score(span))


def test_more_than_sixteen_overlapping_slurs_fail_clearly() -> None:
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 3))
    with pytest.raises(ExportError, match="more than 16 slurs overlap"):
        to_musicxml(_score(*((span,) * 17)))


def test_many_nonoverlapping_slurs_reuse_a_valid_number() -> None:
    measures = tuple(_measure(index) for index in range(1, 21))
    spans = tuple(
        Slur(SlurEndpoint(index, 1, 0), SlurEndpoint(index, 1, 3)) for index in range(1, 21)
    )
    root = _tree(Score(parts=(Part("P1", "Authored", measures, slurs=spans),)))
    assert len(root.findall(".//slur")) == 40
    assert {mark.get("number") for mark in root.findall(".//slur")} == {"1"}


def test_duplicate_measure_or_voice_labels_are_rejected() -> None:
    span = Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(1, 1, 3))
    for measures, message in (
        ((_measure(1), _measure(1)), "unique measure numbers"),
        ((Measure(1, (_measure(1).voices[0], _measure(1).voices[0])),), "unique voice numbers"),
    ):
        with pytest.raises(ExportError, match=message):
            to_musicxml(Score(parts=(Part("P1", "Authored", measures, slurs=(span,)),)))


def test_slurs_do_not_change_other_notation_or_cursor_timing() -> None:
    score = _bundle()
    root = _tree(score)
    baseline = _tree(replace(score, parts=tuple(replace(part, slurs=()) for part in score.parts)))
    for note in root.findall(".//note"):
        notations = note.find("notations")
        if notations is not None:
            for slur in notations.findall("slur"):
                notations.remove(slur)
            if not len(notations):
                note.remove(notations)
    for tree in (root, baseline):
        for element in tree.iter():
            if element.text is not None and element.text.isspace():
                element.text = None
            if element.tail is not None and element.tail.isspace():
                element.tail = None
    assert ET.tostring(root) == ET.tostring(baseline)
