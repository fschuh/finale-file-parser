"""Authored silence, grace and independent voices verify exact cursor handling."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Arpeggio, Event, Measure, Part, PartGroup, Pitch, Score, Voice

NOTE = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 0),))
GRACE = Event(Fraction(0), Fraction(1, 8), (Pitch("D", 4, 0),), is_grace=True)


def test_leading_silence_is_exact_and_the_next_voice_rewinds_to_zero() -> None:
    measure = Measure(
        1,
        (
            Voice(1, (GRACE, NOTE), start_offset=Fraction(1, 8)),
            Voice(2, (NOTE,)),
        ),
    )
    root = DET.fromstring(to_musicxml(Score(parts=(Part("P1", "Authored", (measure,)),))))
    assert root.findtext("part/measure/attributes/divisions") == "2"
    assert root.findtext("part/measure/forward/duration") == "1"
    assert root.findtext("part/measure/forward/voice") == "1"
    assert root.findtext("part/measure/backup/duration") == "3"
    notes = root.findall("part/measure/note")
    assert [note.findtext("duration") for note in notes] == [None, "2", "2"]
    assert notes[0].find("grace") is not None
    assert root.findall("part/measure/note/rest") == []


def test_negative_voice_start_is_an_export_error() -> None:
    part = Part("P1", "Authored", (Measure(1, (Voice(1, (NOTE,), start_offset=Fraction(-1, 8)),)),))
    with pytest.raises(ExportError, match="start offset must not be negative"):
        to_musicxml(Score(parts=(part,)))


def test_delayed_voices_keep_staff_and_voice_mapping_when_combined() -> None:
    ids = ("P1", "P2")
    roll = Arpeggio("authored-roll", ids)
    parts = tuple(
        Part(
            part_id,
            "Authored",
            (
                Measure(
                    1, (Voice(1, (replace(NOTE, arpeggios=(roll,)),), start_offset=Fraction(1, 8)),)
                ),
            ),
        )
        for part_id in ids
    )
    root = DET.fromstring(to_musicxml(Score(parts=parts, groups=(PartGroup(ids, "brace"),))))
    forwards = root.findall("part/measure/forward")
    notes = root.findall("part/measure/note")
    assert len(root.findall("part")) == 1
    assert [forward.findtext("staff") for forward in forwards] == ["1", "2"]
    assert [forward.findtext("voice") for forward in forwards] == [
        note.findtext("voice") for note in notes
    ]
    assert [forward.findtext("duration") for forward in forwards] == ["1", "1"]
