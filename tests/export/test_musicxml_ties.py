"""Tie-stop matching; fixtures authored for this project."""

from fractions import Fraction

from defusedxml import ElementTree as ET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Event, Measure, NoteTies, Part, Pitch, Score, Voice

F4 = Pitch("F", 4, 0)
F_SHARP4 = Pitch("F", 4, 1)
QUARTER = Fraction(1, 4)


def _event(pitch: Pitch, start: bool = False, stop: bool = False) -> Event:
    return Event(QUARTER, QUARTER, (pitch,), note_ties=(NoteTies(start=start, stop=stop),))


def _ties(*measures: Measure) -> list[list[str | None]]:
    root = ET.fromstring(to_musicxml(Score(parts=(Part("P1", "P", measures),))))
    return [[t.get("type") for t in n.findall("tie")] for n in root.iter("note")]


def test_a_stop_reached_by_a_start_on_the_same_pitch_is_kept() -> None:
    tied = Measure(1, (Voice(1, (_event(F4, start=True), _event(F4, stop=True))),))
    assert _ties(tied) == [["start"], ["stop"]]


def test_a_leftover_stop_behind_a_different_pitch_is_dropped() -> None:
    stale = Measure(1, (Voice(1, (_event(F4), _event(F_SHARP4, stop=True))),))
    assert _ties(stale) == [[], []]


def test_a_stop_reached_across_the_barline_is_kept() -> None:
    first = Measure(1, (Voice(1, (_event(F4), _event(F4, start=True))),))
    second = Measure(2, (Voice(1, (_event(F4, stop=True),)),))
    assert _ties(first, second) == [[], ["start"], ["stop"]]


def test_a_stop_reached_from_another_voice_is_kept() -> None:
    measure = Measure(
        1,
        (
            Voice(1, (_event(F4, start=True), _event(Pitch("C", 5, 0)))),
            Voice(2, (Event(QUARTER, QUARTER, ()), _event(F4, stop=True))),
        ),
    )
    assert _ties(measure) == [["start"], [], [], ["stop"]]


def test_a_stop_separated_from_its_start_by_another_note_is_dropped() -> None:
    measure = Measure(
        1, (Voice(1, (_event(F4, start=True), _event(Pitch("G", 4, 0)), _event(F4, stop=True))),)
    )
    assert _ties(measure) == [["start"], [], []]
