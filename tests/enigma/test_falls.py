"""Falls drawn as wavy lines; fixtures authored for this project."""

from fractions import Fraction

from finale_file_parser.enigma.to_ir import _with_falls
from finale_file_parser.ir import Event, LineSpan, Measure, Part, Pitch, Voice

QUARTER = Fraction(1, 4)


def _part(start_y: Fraction, end_y: Fraction) -> Part:
    notes = tuple(Event(QUARTER, QUARTER, (Pitch("C", 3, 0),)) for _ in range(4))
    line = LineSpan(1, Fraction(1), 1, Fraction(1), "wavy", start_y=start_y, end_y=end_y)
    return Part("P1", "P", (Measure(1, (Voice(1, notes),)),), lines=(line,))


def test_a_descending_wavy_line_becomes_the_last_notes_fall() -> None:
    part = _with_falls(_part(Fraction(-5), Fraction(-9)))
    events = part.measures[0].voices[0].events
    assert [e.articulations for e in events] == [(), (), (), ("falloff",)]
    assert part.lines == ()


def test_a_level_wavy_line_stays_a_line() -> None:
    part = _part(Fraction(-5), Fraction(-5))
    assert _with_falls(part) == part
