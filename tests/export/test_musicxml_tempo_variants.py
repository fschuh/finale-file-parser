"""Exact rate equivalences and printed ranges survive standard MusicXML export."""

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Expression, Measure, Part, Score, Tempo


def _xml(tempo: Tempo) -> bytes:
    measure = Measure(1, expressions=(Expression("authored", "", tempo=tempo),))
    return to_musicxml(Score(parts=(Part("P1", "Authored", (measure,)),)))


def test_range_prints_both_limits_without_choosing_a_playback_tempo() -> None:
    root = DET.fromstring(_xml(Tempo(Fraction(1, 2), Fraction(64), upper_per_minute=Fraction(68))))
    assert root.findtext(".//metronome/beat-unit") == "half"
    assert root.findtext(".//metronome/per-minute") == "64–68"
    assert root.find(".//sound") is None


def test_multiple_equivalent_marks_have_a_single_identical_playback_rate() -> None:
    tempo = Tempo(
        Fraction(1, 4),
        Fraction(180),
        words="Bright",
        equivalents=(Tempo(Fraction(1, 8), Fraction(360)),),
    )
    root = DET.fromstring(_xml(tempo))
    # MuseScore keeps one <metronome> per direction, so the equivalence prints
    # as words while the single rate plays through <sound tempo>.
    assert root.findall(".//metronome") == []
    assert root.find(".//sound").get("tempo") == "180"  # type: ignore[union-attr]
    assert [w.text for w in root.findall(".//words")] == ["Bright \u2669 = 180 (\u266a = 360)"]
