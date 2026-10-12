"""Authored exact tempo equivalents, ranges and font-specific beat symbols."""

from fractions import Fraction

import pytest

from finale_file_parser.enigma.expressions import _tempo
from finale_file_parser.enigma.fonts import FontRun


def test_consistent_multiple_rates_remain_explicit_equivalent_markings() -> None:
    tempo = _tempo("Bright q = 180 (e = 360)")
    assert tempo is not None
    assert (tempo.quarter_bpm, tempo.words) == (Fraction(180), "Bright")
    assert [(t.beat_unit, t.per_minute) for t in tempo.equivalents] == [
        (Fraction(1, 8), Fraction(360))
    ]
    assert _tempo("q = 180 (e = 359)") is None


def test_ordered_ranges_are_preserved_without_inventing_an_exact_speed() -> None:
    tempo = _tempo("Slow h = 64–68")
    assert tempo is not None
    assert (tempo.beat_unit, tempo.per_minute, tempo.upper_per_minute, tempo.words) == (
        Fraction(1, 2),
        Fraction(64),
        Fraction(68),
        "Slow",
    )
    assert _tempo("h = 68–64") is None


@pytest.mark.parametrize("symbol", ["Œ", "\uf0ce"])
def test_extended_quarter_glyphs_require_the_supported_font(symbol: str) -> None:
    assert _tempo(f"{symbol} = 120") is None
    assert (
        _tempo(f"{symbol} = 120", runs=(FontRun(f"{symbol} = 120", "Times New Roman", False),))
        is None
    )
    tempo = _tempo(
        f"{symbol} = 120",
        runs=(FontRun(symbol, "MaestroTimes", False), FontRun("= 120", "Times New Roman", False)),
    )
    assert tempo is not None and tempo.quarter_bpm == 120


def test_engraver_text_dot_is_part_of_the_beat_not_the_rate() -> None:
    tempo = _tempo("qd = 88", runs=(FontRun("qd = 88", "EngraverTextT", False),))
    assert tempo is not None
    assert (tempo.dots, tempo.per_minute, tempo.quarter_bpm) == (1, Fraction(88), Fraction(132))
    assert _tempo("qd = 88") is None
