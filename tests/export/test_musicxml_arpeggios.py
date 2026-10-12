"""Authored chords verify arpeggio semantics and multi-staff XML timing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import (
    Arpeggio,
    Beam,
    ClefChange,
    Event,
    Expression,
    Fermata,
    Lyric,
    Measure,
    NoteTies,
    Part,
    PartGroup,
    Pitch,
    Score,
    Tempo,
    TimeSignature,
    Voice,
)


def _event(*pitches: Pitch, duration: Fraction = Fraction(1, 4), marked: bool = True) -> Event:
    return Event(duration, duration, pitches, arpeggios=(Arpeggio(),) if marked else ())


def _score() -> Score:
    connection = Arpeggio("roll", ("RH", "LH"))
    upper = _event(Pitch("C", 5, 0), Pitch("E", 5, 0))
    lower = _event(Pitch("C", 4, 0), Pitch("E", 4, 0))
    return Score(
        parts=(
            Part(
                "RH",
                "Keyboard",
                (
                    Measure(
                        1,
                        (Voice(1, (replace(upper, arpeggios=(connection,)),)),),
                        key_fifths=0,
                        time=TimeSignature(1, 4),
                        clef_sign="G",
                        clef_line=2,
                    ),
                ),
            ),
            Part(
                "LH",
                "Keyboard",
                (
                    Measure(
                        1,
                        (Voice(1, (replace(lower, arpeggios=(connection,)),)),),
                        key_fifths=0,
                        time=TimeSignature(1, 4),
                        clef_sign="F",
                        clef_line=4,
                    ),
                ),
            ),
        ),
        groups=(PartGroup(("RH", "LH"), "brace", True),),
    )


def _tree(score: Score) -> ET.Element:
    return DET.fromstring(to_musicxml(score))


def test_every_pitch_of_a_rolled_chord_has_an_arpeggiate_without_an_arrow() -> None:
    event = _event(Pitch("C", 4, 0), Pitch("E", 4, 0), Pitch("G", 4, 0))
    event = replace(
        event,
        note_ties=(NoteTies(start=True), NoteTies(), NoteTies(stop=True)),
        fermatas=(Fermata(),),
        articulations=("accent",),
        lyrics=(Lyric(1, "word"),),
    )
    root = _tree(Score(parts=(Part("P1", "Piano", (Measure(1, (Voice(1, (event,)),)),)),)))
    notes = root.findall("part/measure/note")
    assert len(notes) == 3 and all(note.find("notations/arpeggiate") is not None for note in notes)
    assert all(mark.attrib == {"number": "1"} for mark in root.findall(".//arpeggiate"))
    assert (
        len(root.findall(".//fermata"))
        == len(root.findall(".//accent"))
        == len(root.findall(".//lyric"))
        == 1
    )
    assert [tie.get("type") for tie in root.findall(".//tied")] == ["start", "stop"]
    assert [note.findtext("duration") for note in notes] == ["1"] * 3


@pytest.mark.parametrize("direction", ["up", "down"])
def test_explicit_arpeggio_arrow_is_exported_on_every_covered_pitch(direction: str) -> None:
    event = replace(
        _event(Pitch("C", 4, 0), Pitch("E", 4, 0), Pitch("G", 4, 0)),
        arpeggios=(Arpeggio(pitch_indices=(0, 2), direction=direction),),
    )
    score = Score(parts=(Part("P1", "Test", (Measure(1, (Voice(1, (event,)),)),)),))
    root = _tree(score)
    assert [m.get("direction") for m in root.findall(".//arpeggiate")] == [direction] * 2


def test_unsupported_arpeggio_direction_raises_a_clear_error() -> None:
    event = replace(_event(Pitch("C", 4, 0)), arpeggios=(Arpeggio(direction="sideways"),))
    score = Score(parts=(Part("P1", "Test", (Measure(1, (Voice(1, (event,)),)),)),))
    with pytest.raises(ExportError, match="unsupported arpeggio direction"):
        to_musicxml(score)


def test_a_rest_never_exports_an_arpeggiate_even_when_authored_with_one() -> None:
    score = Score(parts=(Part("P1", "Test", (Measure(1, (Voice(1, (_event(),)),)),)),))
    assert _tree(score).find(".//arpeggiate") is None


def test_a_connected_roll_exports_one_part_with_two_clefs_and_distinct_voices() -> None:
    score = _score()
    root = _tree(score)
    assert len(score.parts) == 2
    assert len(root.findall("part")) == len(root.findall("part-list/score-part")) == 1
    assert root.findall("part-list/part-group") == []
    attrs = root.find("part/measure/attributes")
    assert attrs is not None and attrs.findtext("staves") == "2"
    assert attrs.findtext("part-symbol") == "brace"
    assert [(clef.get("number"), clef.findtext("sign")) for clef in attrs.findall("clef")] == [
        ("1", "G"),
        ("2", "F"),
    ]
    notes = root.findall("part/measure/note")
    assert [(note.findtext("staff"), note.findtext("voice")) for note in notes] == [
        ("1", "1")
    ] * 2 + [("2", "2")] * 2
    assert [backup.findtext("duration") for backup in root.findall(".//backup")] == ["1"]
    assert all(
        mark.attrib == {"number": "1", "unbroken": "yes"} for mark in root.findall(".//arpeggiate")
    )


def test_expression_time_survives_connected_staff_projection() -> None:
    score = _score()
    parts = tuple(
        replace(
            part,
            measures=(
                replace(
                    part.measures[0],
                    expressions=(Expression("mf", "", marking="mf", offset=Fraction(1, 8)),),
                ),
            ),
        )
        for part in score.parts
    )
    root = _tree(replace(score, parts=parts))
    directions = root.findall("part/measure/direction")
    assert [(d.findtext("staff"), d.findtext("offset")) for d in directions] == [
        ("1", "1"),
        ("2", "1"),
    ]
    assert [d.tag for d in directions[0]] == ["direction-type", "offset", "staff"]


def test_timed_clefs_survive_projection_and_voice_backups_once_per_staff() -> None:
    score = _score()
    parts = tuple(
        replace(
            part,
            measures=(
                replace(
                    part.measures[0],
                    clef_changes=(ClefChange(Fraction(1, 8), "C", 3, False),),
                    voices=(
                        *part.measures[0].voices,
                        Voice(2, (_event(Pitch("G", 4, 0), marked=False),)),
                    ),
                ),
            ),
        )
        for part in score.parts
    )
    root = _tree(replace(score, parts=parts))
    cursor = 0
    changes = []
    onsets = []
    measure = root.find("part/measure")
    assert measure is not None
    for node in measure:
        if node.tag == "backup":
            cursor -= int(node.findtext("duration", "0"))
        elif node.tag == "forward":
            cursor += int(node.findtext("duration", "0"))
        elif node.tag == "attributes":
            for clef in node.findall("clef"):
                if clef.findtext("sign") == "C":
                    changes.append((clef.get("number"), cursor, clef.get("print-object")))
        elif node.tag == "note" and node.find("chord") is None:
            onsets.append(cursor)
            cursor += int(node.findtext("duration", "0"))
    assert changes == [("1", 1, "no"), ("2", 1, "no")]
    assert onsets == [0, 0, 0, 0]


def test_a_brace_and_simultaneous_independent_rolls_keep_separate_parts() -> None:
    score = _score()
    parts = tuple(
        replace(
            part,
            measures=(
                replace(
                    part.measures[0],
                    voices=(
                        Voice(
                            1,
                            (
                                replace(
                                    part.measures[0].voices[0].events[0], arpeggios=(Arpeggio(),)
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        for part in score.parts
    )
    root = _tree(replace(score, parts=parts))
    assert len(root.findall("part")) == 2
    assert root.find(".//staves") is None
    assert root.find(".//arpeggiate[@unbroken]") is None


def test_independent_rolls_in_an_already_connected_part_have_different_numbers() -> None:
    score = _score()
    parts = tuple(
        replace(
            part,
            measures=(
                *part.measures,
                replace(
                    part.measures[0],
                    number=2,
                    voices=(
                        Voice(
                            1,
                            (
                                replace(
                                    part.measures[0].voices[0].events[0], arpeggios=(Arpeggio(),)
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        for part in score.parts
    )
    root = _tree(replace(score, parts=parts))
    marks = root.findall("part/measure[@number='2']//arpeggiate")
    assert [mark.get("number") for mark in marks] == ["1", "1", "2", "2"]
    assert all("unbroken" not in mark.attrib for mark in marks)


def test_merging_staves_keeps_triplets_graces_beams_ties_and_directions() -> None:
    score = _score()
    upper, lower = score.parts
    grace = replace(
        _event(Pitch("D", 5, 0), duration=Fraction(1, 8), marked=False),
        duration=Fraction(0),
        is_grace=True,
        grace_slash=True,
    )
    triplet = replace(
        _event(Pitch("F", 5, 0), duration=Fraction(1, 8), marked=False),
        duration=Fraction(1, 12),
        tuplet_ratio=Fraction(2, 3),
        beams=(Beam(1, "begin"),),
        note_ties=(NoteTies(start=True),),
    )
    upper_measure = replace(
        upper.measures[0],
        voices=(
            upper.measures[0].voices[0],
            Voice(4, (grace, triplet)),
        ),
        expressions=(Expression("", "", tempo=Tempo(Fraction(1, 4), Fraction(90))),),
    )
    lower_measure = replace(lower.measures[0], expressions=(Expression("softly", ""),))
    root = _tree(
        replace(
            score,
            parts=(
                replace(upper, measures=(upper_measure,)),
                replace(lower, measures=(lower_measure,)),
            ),
        )
    )
    measure = root.find("part/measure")
    assert measure is not None and measure.findtext("attributes/divisions") == "3"
    assert [backup.findtext("duration") for backup in measure.findall("backup")] == ["3", "1"]
    assert [
        (note.findtext("staff"), note.findtext("voice")) for note in measure.findall("note")
    ] == [("1", "1")] * 2 + [("1", "2")] * 2 + [("2", "3")] * 2
    grace_note = measure.find("note[grace]")
    assert grace_note is not None and grace_note.find("grace").get("slash") == "yes"  # type: ignore[union-attr]
    assert grace_note.find("duration") is None
    assert root.findtext(".//beam") == "begin"
    assert root.find(".//tied[@type='start']") is not None
    assert [
        (direction.findtext("staff"), direction.findtext("direction-type/words"))
        for direction in measure.findall("direction")
    ] == [("1", None), ("2", "softly")]
    tempo = measure.find("direction[sound]")
    assert tempo is not None and [child.tag for child in tempo][-2:] == ["staff", "sound"]


def test_surrounding_groups_and_an_unconnected_instrument_keep_their_structure() -> None:
    score = _score()
    solo = Part("S", "Flute", (Measure(1, (Voice(1, (_event(Pitch("G", 5, 0), marked=False),)),)),))
    outer = PartGroup(("RH", "LH", "S"), "bracket", name="Ensemble")
    root = _tree(replace(score, parts=(*score.parts, solo), groups=(outer, *score.groups)))
    assert [part.get("id") for part in root.findall("part")] == ["RH", "S"]
    assert [part.get("id") for part in root.findall("part-list/score-part")] == ["RH", "S"]
    assert root.findtext("part-list/part-group/group-name") == "Ensemble"
    assert root.findtext("part-list/part-group/group-symbol") == "bracket"
    assert len(root.findall("part-list/part-group")) == 2


@pytest.mark.parametrize("ids", [("RH", "missing"), ("LH", "RH"), ("missing",), ("LH",), ("RH",)])
def test_invalid_span_members_raise_a_clear_export_error(ids: tuple[str, ...]) -> None:
    score = _score()
    upper = score.parts[0]
    measure = upper.measures[0]
    event = replace(measure.voices[0].events[0], arpeggios=(Arpeggio("roll", ids),))
    upper = replace(upper, measures=(replace(measure, voices=(Voice(1, (event,)),)),))
    with pytest.raises(ExportError, match="consecutive score parts"):
        to_musicxml(replace(score, parts=(upper, score.parts[1])))


def test_conflicting_barlines_and_measure_sequences_are_not_silently_discarded() -> None:
    score = _score()
    lower = score.parts[1]
    for measure, error in (
        (replace(lower.measures[0], number=2), "measure sequence"),
        (replace(lower.measures[0], repeat_backward=True), "conflicting barlines"),
    ):
        with pytest.raises(ExportError, match=error):
            to_musicxml(replace(score, parts=(score.parts[0], replace(lower, measures=(measure,)))))


def test_a_named_brace_labels_the_part_and_a_surrounding_bracket_survives() -> None:
    score = _score()
    outer = PartGroup(("RH", "LH"), "bracket", name="Ensemble")
    inner = replace(score.groups[0], name="Keyboard", abbreviation="Kbd.")
    root = _tree(replace(score, groups=(outer, inner)))
    assert root.findtext("part-list/score-part/part-name") == "Keyboard"
    assert root.findtext("part-list/score-part/part-abbreviation") == "Kbd."
    assert root.findtext("part-list/part-group/group-name") == "Ensemble"
    assert root.findtext("part-list/part-group/group-symbol") == "bracket"
    assert root.findtext("part/measure/attributes/part-symbol") == "brace"


def test_simultaneous_independent_rolls_in_two_voices_of_one_staff_remain_separate() -> None:
    first = _event(Pitch("C", 5, 0), Pitch("E", 5, 0))
    second = _event(Pitch("C", 4, 0), Pitch("E", 4, 0))
    measure = Measure(1, (Voice(1, (first,)), Voice(2, (second,))))
    root = _tree(Score(parts=(Part("P1", "Test", (measure,)),)))
    assert [mark.get("number") for mark in root.findall(".//arpeggiate")] == ["1", "1", "2", "2"]


def test_too_many_simultaneous_rolls_raise_instead_of_writing_invalid_numbers() -> None:
    event = replace(_event(Pitch("C", 4, 0)), arpeggios=(Arpeggio(),) * 17)
    score = Score(parts=(Part("P1", "Test", (Measure(1, (Voice(1, (event,)),)),)),))
    with pytest.raises(ExportError, match="more than 16 simultaneous arpeggios"):
        to_musicxml(score)
