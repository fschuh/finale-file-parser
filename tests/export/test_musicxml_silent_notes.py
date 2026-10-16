"""Silent pitches retain notation and timing with standard full-size cue notes."""

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Event, Measure, NoteTies, Part, Pitch, Score, Voice


def test_silent_chord_retains_full_size_visual_ties_and_exact_rhythm() -> None:
    chord = Event(
        Fraction(1, 4),
        Fraction(1, 4),
        (Pitch("C", 4, 0), Pitch("E", 4, 0)),
        note_ties=(NoteTies(start=True), NoteTies(stop=True)),
        playback=False,
    )
    score = Score(parts=(Part("P1", "Authored", (Measure(1, (Voice(1, (chord,)),)),)),))
    root = DET.fromstring(to_musicxml(score))
    assert root.findtext("defaults/appearance/note-size[@type='cue']") == "100"
    notes = root.findall(".//note")
    assert len(notes) == 2 and all(n.find("cue") is not None for n in notes)
    assert all(n.findtext("duration") == "1" for n in notes)
    assert all(n.findtext("type") == "quarter" for n in notes)
    for note in notes:
        note_type = note.find("type")
        assert note_type is not None and note_type.get("size") == "full"
    assert not root.findall(".//tie")
    # E's stop has no start reaching it, so only C's start is drawn.
    assert [t.get("type") for t in root.findall(".//tied")] == ["start"]
    assert all(n.find("pitch") is not None and n.find("rest") is None for n in notes)


def test_hidden_sounding_note_and_visible_rest_keep_their_separate_state() -> None:
    note = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 0),), visible=False)
    rest = Event(Fraction(1, 4), Fraction(1, 4), playback=False)
    score = Score(parts=(Part("P1", "Authored", (Measure(1, (Voice(1, (note, rest)),)),)),))
    root = DET.fromstring(to_musicxml(score))
    notes = root.findall(".//note")
    assert notes[0].get("print-object") == "no" and notes[0].find("cue") is None
    assert notes[1].get("print-object") is None and notes[1].find("rest") is not None
