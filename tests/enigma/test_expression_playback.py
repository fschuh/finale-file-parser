"""Authored definitions separate printed rates from typed playback values."""

import struct
from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import Record
from finale_file_parser.enigma.expressions import _playback
from finale_file_parser.enigma.mus_document import _text_expr_def
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Expression, ExpressionPlayback, Measure, Part, Score, Tempo


def _definition(flags: int, value: int, unit: int = 0) -> Record:
    payload = bytearray(36)
    struct.pack_into("<HH", payload, 4, value, unit)
    struct.pack_into("<H", payload, 10, flags)
    return Record("textExprDef", {"cmper": "1"}, "", _text_expr_def(bytes(payload), "cp1252", 2011))


def _xml(expression: Expression) -> bytes:
    return to_musicxml(
        Score(parts=(Part("P1", "Authored", (Measure(1, expressions=(expression,)),)),))
    )


def test_playback_tempo_does_not_change_the_printed_metronome() -> None:
    playback = _playback(_definition(0x1001, 178, 1024))
    assert playback == ExpressionPlayback("tempo", 178, Fraction(1, 4))
    expression = Expression(
        "q = 180", "", tempo=Tempo(Fraction(1, 4), Fraction(180)), playback=playback
    )
    root = DET.fromstring(_xml(expression))
    assert root.findtext(".//metronome/per-minute") == "180"
    sound = root.find(".//sound")
    assert sound is not None and sound.get("tempo") == "178"


def test_an_untyped_value_cannot_be_exported_as_key_velocity() -> None:
    root = DET.fromstring(_xml(Expression("P", "", marking="mp", velocity=1024)))
    assert root.find(".//sound") is None
    typed = _playback(_definition(2, 90))
    assert typed == ExpressionPlayback("amplitude", 90)
    root = DET.fromstring(_xml(Expression("F", "", marking="mf", playback=typed)))
    sound = root.find(".//sound")
    assert sound is not None and sound.get("dynamics") == "100"


def test_straight_swing_zero_is_a_typed_value_and_executable_shapes_are_not_rates() -> None:
    assert _playback(_definition(14, 0)) == ExpressionPlayback("swing", 0)
    assert _playback(_definition(0x3001, 8, 1024)) is None


def test_nonabsolute_source_values_remain_data_without_impossible_xml_controls() -> None:
    negative = _playback(_definition(2, 0xFF9C))
    assert negative == ExpressionPlayback("amplitude", -100)
    root = DET.fromstring(_xml(Expression("f", "", marking="f", playback=negative)))
    assert root.find(".//sound") is None
    zero_tempo = _playback(_definition(0x1001, 0, 512))
    assert zero_tempo == ExpressionPlayback("tempo", 0, Fraction(1, 8))
    root = DET.fromstring(_xml(Expression("Swing es", "", playback=zero_tempo)))
    assert root.find(".//sound") is None


def test_an_explicit_no_playback_mark_keeps_printed_tempo_without_sound() -> None:
    expression = Expression(
        "q = 96",
        "",
        tempo=Tempo(Fraction(1, 4), Fraction(96)),
        playback=_playback(_definition(0, 0)),
    )
    root = DET.fromstring(_xml(expression))
    assert root.findtext(".//metronome/per-minute") == "96"
    assert root.find(".//sound") is None


def test_typed_rate_with_a_pass_condition_preserves_it_in_musicxml() -> None:
    root = DET.fromstring(
        _xml(Expression("tempo", "", playback=ExpressionPlayback("tempo", 80, Fraction(1, 4), 2)))
    )
    sound = root.find(".//sound")
    assert sound is not None and sound.attrib == {"tempo": "80", "time-only": "2"}
