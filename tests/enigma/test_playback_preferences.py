"""Independently authored preference fragments, including high-word-first EDU."""

import struct
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _playback_options
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.playback_preferences import playback_preferences
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Expression, Measure, Part, PlaybackPreferences, Score, Tempo


def _fragments() -> tuple[MusOther, ...]:
    values = {
        27: (0, 2048, 0, 0, 0, 0),
        53: (0, 0, 0, 130, 0, 0),
        50: (512, 0, 0, 0, 0, 72),
        51: (1, 0, 8, 0, 0, 0),
        61: (1, 2, 0, 0, 1, 2),
    }
    return tuple(
        MusOther(tag, 65534, 0, struct.pack("<6H", *words)) for tag, words in values.items()
    )


def test_numeric_fragments_preserve_units_and_signed_word_conversion() -> None:
    record = _playback_options(_fragments())
    assert record is not None
    assert record.fields["metronomeBeat"] == "2048"
    assert record.fields["metronomeSpeed"] == "130"
    assert record.fields["startEdu"] == "65538"
    assert record.fields["stopAtMeas"] == "8"
    assert record.fields["swing"] == "512"


def test_incomplete_or_linked_part_preference_sets_do_not_invent_document_controls() -> None:
    assert _playback_options(_fragments()[:-1]) is None
    assert (
        _playback_options(tuple(MusOther(r.tag, r.cmper, 1, r.payload) for r in _fragments()))
        is None
    )


def test_a_truncated_known_preference_is_rejected() -> None:
    records = list(_fragments())
    records[0] = MusOther(27, 65534, 0, b"short")
    with pytest.raises(CorruptScoreError, match="requires twelve bytes"):
        _playback_options(tuple(records))


def test_document_preferences_are_typed_without_creating_a_printed_tempo() -> None:
    doc = parse_enigma(b"""<finale><options><playbackOptions>
      <metronomeBeat>2048</metronomeBeat><metronomeSpeed>130</metronomeSpeed>
      <stopAtMeas>8</stopAtMeas><endPass>2</endPass><swing>512</swing>
    </playbackOptions></options></finale>""")
    prefs = playback_preferences(doc)
    assert prefs is not None
    assert (prefs.quarter_bpm, prefs.swing_amount, prefs.stop_measure, prefs.stop_pass) == (
        Fraction(260),
        Fraction(1, 2),
        7,
        2,
    )


def test_default_tempo_exports_as_sound_only_and_an_initial_marking_takes_precedence() -> None:
    prefs = PlaybackPreferences(Fraction(1, 2), Fraction(130))
    score = Score(parts=(Part("P1", "Authored", (Measure(1),)),), playback=prefs)
    root = DET.fromstring(to_musicxml(score))
    sound = root.find("part/measure/sound")
    assert sound is not None and sound.get("tempo") == "260"
    assert root.find(".//metronome") is None
    score = Score(
        parts=(
            Part(
                "P1",
                "Authored",
                (
                    Measure(
                        1,
                        expressions=(
                            Expression("q = 90", "", tempo=Tempo(Fraction(1, 4), Fraction(90))),
                        ),
                    ),
                ),
            ),
        ),
        playback=prefs,
    )
    root = DET.fromstring(to_musicxml(score))
    assert root.find("part/measure/sound") is None
    sound = root.find(".//direction/sound")
    assert sound is not None and sound.get("tempo") == "90"
