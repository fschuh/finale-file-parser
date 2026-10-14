"""Check written note multiplicity and timing across IR to MusicXML projection."""

import re
from collections import Counter
from fractions import Fraction
from xml.etree.ElementTree import Element

from finale_file_parser.ir import Pitch, Score

from .attacks import midi_pitch

_Note = tuple[int, Fraction, int | None, Fraction, bool, bool, tuple[str, ...]]


def check_projection(score: Score, xml: Element) -> dict[str, int]:
    expected: Counter[_Note] = Counter()
    actual: Counter[_Note] = Counter()
    for part in score.parts:
        for measure in part.measures:
            for voice in measure.voices:
                spacer = measure.leading_spacer * 4
                cursor = voice.start_offset * 4
                for event in voice.events:
                    pitches = tuple(
                        midi_pitch(p)
                        + 12
                        * sum(
                            s.octaves
                            for s in part.octave_shifts
                            if s.contains(measure.number, cursor / 4)
                        )
                        for p in event.pitches
                    )
                    for pi, pitch in enumerate(pitches or (None,)):
                        ties = event.note_ties[pi] if pitches and event.note_ties else None
                        start = ties.start if ties else event.tie_start
                        stop = ties.stop if ties else event.tie_end
                        flags = tuple(
                            sorted(
                                t for t, enabled in (("start", start), ("stop", stop)) if enabled
                            )
                        )
                        onset = max(Fraction(0), cursor - spacer)
                        duration = event.duration * 4
                        if event.is_measure_rest and cursor < spacer:
                            duration -= spacer - cursor
                        expected[
                            measure.number,
                            onset,
                            pitch,
                            duration,
                            event.is_grace,
                            bool(pitches) and not (event.playback and voice.playback),
                            flags,
                        ] += 1
                    if not event.is_grace:
                        cursor += event.duration * 4
    for xml_part in xml.findall("part"):
        divisions = 1
        for xml_measure in xml_part.findall("measure"):
            identity = re.fullmatch(r"source-measure-\d+-(\d+)", xml_measure.get("id", ""))
            number = int(identity[1] if identity else xml_measure.get("number", "0"))
            cursor = previous = Fraction(0)
            for element in xml_measure:
                if element.tag == "attributes":
                    value = element.findtext("divisions")
                    if value:
                        divisions = int(value)
                elif element.tag in {"forward", "backup"}:
                    duration = Fraction(element.findtext("duration", "0")) / divisions
                    cursor += duration if element.tag == "forward" else -duration
                elif element.tag == "note":
                    chord = element.find("chord") is not None
                    onset = previous if chord else cursor
                    grace = element.find("grace") is not None
                    duration = Fraction(element.findtext("duration", "0")) / divisions
                    pitch_element = element.find("pitch")
                    pitch = None
                    if pitch_element is not None:
                        step = pitch_element.findtext("step", "C")
                        pitch = midi_pitch(
                            Pitch(
                                step,
                                int(pitch_element.findtext("octave", "0")),
                                int(pitch_element.findtext("alter", "0")),
                            )
                        )
                    # Cue notes carry notation ties, while the MusicXML grammar
                    # excludes their sounding ties. They must remain silent.
                    tie_path = "notations/tied" if element.find("cue") is not None else "tie"
                    flags = tuple(sorted(t.get("type", "") for t in element.findall(tie_path)))
                    actual[
                        number,
                        onset,
                        pitch,
                        duration,
                        grace,
                        pitch is not None and element.find("cue") is not None,
                        flags,
                    ] += 1
                    previous = onset
                    if not chord and not grace:
                        cursor += duration
    if expected != actual:
        missing, extra = expected - actual, actual - expected
        raise ValueError(
            f"IR/MusicXML note projection differs: {sum(missing.values())} missing, "
            f"{sum(extra.values())} extra/mistimed; examples "
            f"{list(missing.items())[:2]} / {list(extra.items())[:2]}"
        )
    return {
        "source_written_notes_and_rests": sum(expected.values()),
        "xml_written_notes_and_rests": sum(actual.values()),
    }
