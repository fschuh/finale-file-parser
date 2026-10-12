"""Source triplet swing, straight resets and global settings preserve written rhythm."""

from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import (
    Event,
    Expression,
    ExpressionPlayback,
    Measure,
    Part,
    Pitch,
    PlaybackPreferences,
    Score,
    TimeSignature,
    Voice,
)

NOTE = Event(Fraction(1, 8), Fraction(1, 8), (Pitch("C", 4, 0),))


def _score(value: int, unit: Fraction = Fraction(1, 8)) -> Score:
    expression = Expression(
        "authored glyph", "", score_wide=True, playback=ExpressionPlayback("swing", value, unit)
    )
    measure = Measure(
        1, (Voice(1, (NOTE, NOTE)),), time=TimeSignature(4, 4), expressions=(expression,)
    )
    return Score(parts=(Part("P1", "Authored", (measure,)),))


def test_standard_swing_uses_the_documented_ratio_and_global_scope() -> None:
    root = DET.fromstring(to_musicxml(_score(1024)))
    assert root.findtext(".//swing/first") == "2"
    assert root.findtext(".//swing/second") == "1"
    assert root.findtext(".//swing/swing-type") == "eighth"
    assert root.findtext(".//words") == "Swing"
    direction = root.find(".//direction")
    assert direction is not None and direction.get("system") == "only-top"
    assert [n.text for n in root.findall(".//note/duration")] == ["1", "1"]


def test_zero_swing_is_an_explicit_straight_change() -> None:
    root = DET.fromstring(to_musicxml(_score(0)))
    assert root.find(".//swing/straight") is not None
    assert root.findtext(".//words") == "Straight"


def test_the_metric_eighth_beat_can_swing_sixteenths_without_rewriting_them() -> None:
    root = DET.fromstring(to_musicxml(_score(1024, Fraction(1, 16))))
    assert root.findtext(".//swing/swing-type") == "16th"


def test_global_swing_preferences_supply_an_initial_instruction_without_an_expression() -> None:
    measure = Measure(1, (Voice(1, (NOTE, NOTE)),), time=TimeSignature(4, 4))
    score = Score(
        parts=(Part("P1", "Authored", (measure,)),),
        playback=PlaybackPreferences(
            Fraction(1, 4), Fraction(100), Fraction(1), swing_unit=Fraction(1, 8)
        ),
    )
    root = DET.fromstring(to_musicxml(score))
    assert root.findtext(".//swing/first") == "2"
    assert root.findtext(".//swing/swing-type") == "eighth"


def test_unestablished_interpolation_is_not_guessed_from_midi() -> None:
    with pytest.raises(ExportError, match="established triplet"):
        to_musicxml(_score(512))


def test_equivalent_coincident_swing_assignments_print_one_instruction() -> None:
    from dataclasses import replace

    score = _score(1024)
    part = score.parts[0]
    measure = part.measures[0]
    duplicate = replace(measure.expressions[0], text="Second source glyph")
    measure = replace(measure, expressions=(*measure.expressions, duplicate))
    root = DET.fromstring(to_musicxml(replace(score, parts=(replace(part, measures=(measure,)),))))
    assert len(root.findall(".//swing")) == 1


def test_global_subdivision_uses_actual_meter_even_when_displayed_meter_differs() -> None:
    measure = Measure(1, (Voice(1, (NOTE, NOTE)),), time=TimeSignature(4, 4))
    score = Score(
        parts=(Part("P1", "Authored", (measure,)),),
        playback=PlaybackPreferences(
            Fraction(1, 4), Fraction(100), Fraction(1), swing_unit=Fraction(1, 16)
        ),
    )
    assert DET.fromstring(to_musicxml(score)).findtext(".//swing/swing-type") == "16th"
