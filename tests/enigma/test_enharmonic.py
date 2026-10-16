"""Original chord fixtures authored for this project; licensed MIT."""

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.enharmonic import flip_enharmonic
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import MusDetailRecord
from finale_file_parser.enigma.mus_document import _details_records
from finale_file_parser.enigma.pitch import SpelledPitch
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _document(mods: str) -> EnigmaDocument:
    # C#4, Eb4, G4 in C major.
    return parse_enigma(
        f"""<finale><others>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>{mods}
    </details><entries><entry entnum="1" prev="0" next="0"><dura>1024</dura>
      <numNotes>3</numNotes>
      <note id="7"><harmLev>0</harmLev><harmAlt>1</harmAlt></note>
      <note id="2"><harmLev>2</harmLev><harmAlt>-1</harmAlt></note>
      <note id="11"><harmLev>4</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>""".encode()
    )


def _flip(note: int, attrs: str = "") -> str:
    return (
        f'<noteheadMod entnum="1" {attrs}><noteID>{note}</noteID>'
        "<customChar>0</customChar><enharmonic/></noteheadMod>"
    )


@pytest.mark.parametrize(
    "before,after",
    [
        (("C", 1, 4), ("D", -1, 4)),
        (("B", -1, 3), ("A", 1, 3)),
        (("E", 0, 4), ("F", -1, 4)),
        (("F", 0, 4), ("E", 1, 4)),
        (("B", 0, 3), ("C", -1, 4)),
        (("C", 0, 4), ("B", 1, 3)),
        (("B", 1, 3), ("C", 0, 4)),
        (("C", -1, 4), ("B", 0, 3)),
        (("D", 0, 4), ("E", -2, 4)),
    ],
)
def test_flip_keeps_the_sounding_pitch_under_the_neighbouring_letter(
    before: tuple[str, int, int], after: tuple[str, int, int]
) -> None:
    assert flip_enharmonic(SpelledPitch(*before)) == SpelledPitch(*after)


def test_flagged_notes_are_respelled_and_others_keep_their_spelling() -> None:
    score = build_score(_document(_flip(7) + _flip(2, 'inci="1"')))
    notes = ET.fromstring(to_musicxml(score)).findall(".//pitch")
    spelled = [(n.findtext("step"), n.findtext("alter")) for n in notes]
    assert spelled == [("D", "-1"), ("D", "1"), ("G", None)]
    assert not score.diagnostics


def test_linked_part_flips_do_not_change_the_score() -> None:
    score = build_score(_document(_flip(7, 'part="1"')))
    assert ET.fromstring(to_musicxml(score)).findtext(".//pitch/step") == "C"


def test_a_flip_naming_a_missing_note_is_rejected() -> None:
    with pytest.raises(CorruptScoreError, match="note ID"):
        build_score(_document(_flip(99)))


@pytest.mark.parametrize("year", [2011, 2012])
def test_mus_flag_byte_is_read_in_both_layouts_without_corrupting_the_character(
    year: int,
) -> None:
    group = bytearray(20)
    group[:2], group[2:4], group[8] = b"\x07\x00", b"\x64\x00", 0x04
    plain = bytearray(group)
    plain[:2], plain[6:8], plain[8] = b"\x02\x00", b"\xc0\x00", 0
    payload = bytes(group + plain)
    records = _details_records((MusDetailRecord(1058, 0, 1, 0, payload),), year=year)
    assert [r.fields["customChar"] for r in records] == ["0", "192"]
    assert ["enharmonic" in r.fields for r in records] == [True, False]
