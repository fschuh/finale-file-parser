"""Parenthesized dynamics; fixtures authored for this project."""

from fractions import Fraction

from defusedxml import ElementTree as ET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Event, Expression, Measure, Part, Pitch, Score, Voice


def _dynamics(text: str, marking: str) -> list[tuple[str, str | None]]:
    note = Event(Fraction(1), Fraction(1), (Pitch("C", 4, 0),))
    measure = Measure(1, (Voice(1, (note,)),), expressions=(Expression(text, "", marking=marking),))
    root = ET.fromstring(to_musicxml(Score(parts=(Part("P1", "P", (measure,)),))))
    return [(child.tag, child.text) for d in root.iter("dynamics") for child in d]


def test_a_parenthesized_dynamic_keeps_its_parentheses() -> None:
    assert _dynamics("(F)", "mf") == [("other-dynamics", "(mf)")]


def test_a_plain_dynamic_stays_a_standard_element() -> None:
    assert _dynamics("F", "mf") == [("mf", None)]
