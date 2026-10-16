"""Source-fixed accidentals; fixtures authored for this project."""

import struct
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.mus_entries import _note_record
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import AccidentalMark, Event, Measure, Part, Pitch, Score, Voice


def _xml(flags: str) -> list[tuple[str | None, str | None]]:
    # Bb4, D5 (natural) and F5 in Bb major's neighbour C major.
    doc = parse_enigma(
        f"""<finale><others>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
      <note id="1"><harmLev>6</harmLev><harmAlt>-1</harmAlt>{flags}</note>
      <note id="2"><harmLev>8</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>""".encode()
    )
    root = ET.fromstring(to_musicxml(build_score(doc)))
    found = [(n.findtext("accidental"), n.find("accidental")) for n in root.iter("note")]
    return [(text, None if mark is None else mark.get("parentheses")) for text, mark in found]


def test_computed_accidentals_are_left_to_the_reader() -> None:
    assert _xml("<showAcci/>") == [(None, None), (None, None)]


def test_a_frozen_shown_accidental_is_written() -> None:
    assert _xml("<showAcci/><freezeAcci/>") == [("flat", None), (None, None)]


def test_a_parenthesized_accidental_keeps_its_parentheses() -> None:
    assert _xml("<showAcci/><freezeAcci/><parenAcci/>") == [("flat", "yes"), (None, None)]


def test_a_frozen_hidden_accidental_has_no_musicxml_form() -> None:
    assert _xml("<freezeAcci/>") == [(None, None), (None, None)]


@pytest.mark.parametrize(
    "flag,field",
    [(0x01000000, "showAcci"), (0x00800000, "parenAcci"), (0x00000002, "freezeAcci")],
)
def test_mus_note_flags_surface_the_accidental_state(flag: int, field: str) -> None:
    record = _note_record(struct.pack("<HI", 0x0010, 0x80000000 | flag), 0, "little")
    assert field in record.fields


def test_an_accidental_on_a_missing_pitch_is_rejected() -> None:
    event = Event(
        duration=Fraction(1, 4),
        written_duration=Fraction(1, 4),
        pitches=(Pitch("C", 4, 0),),
        accidentals=(AccidentalMark(3),),
    )
    with pytest.raises(ExportError, match="accidental"):
        to_musicxml(Score(parts=(Part("P1", "P", (Measure(1, (Voice(1, (event,)),)),)),)))
