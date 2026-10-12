"""Independently authored navigation records: placements, fonts and hostile bounds."""

import struct

import pytest

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.jumps import navigation_by_measure
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import MusOther


def _assignment(flags: int, *, target: int = 1, passes: int = 2) -> bytes:
    return struct.pack("<hhhhhh6h", -10, passes, target, 3, 80, flags, 0, 0, 0, 0, 0, 0)


def test_numeric_assignment_retains_signed_fields_and_independent_flags() -> None:
    records = _others_records((MusOther(243, 8, 0, _assignment(0x4424, target=-2)),), "cp1252")
    fields = records[0].fields
    assert fields["target"] == "-2"
    assert fields["actuate"] == "2"
    assert fields["repnum"] == "3"
    assert (fields["action"], fields["trigger"]) == ("jumpRelative", "onPass")
    assert "hidden" in fields and "clrOnChange" in fields


def test_font_definition_and_utf16_text_are_resolved_in_their_own_id_space() -> None:
    definitions = struct.pack("<6H", 0, 0, 7, 24, 0, 0)
    records = _others_records(
        (
            MusOther(244, 3, 0, definitions),
            MusOther(246, 3, 0, "D.C. 音𝄞".encode("utf-16-le") + b"\0\0"),
        ),
        "cp1252",
        year=2011,
    )
    assert records[0].fields["fontID"] == "7"
    assert records[1].fields["rptText"] == "D.C. 音𝄞"


@pytest.mark.parametrize(
    "tag, data", [(243, b"\0" * 23), (244, b"\0" * 11), (246, b"x"), (246, b"\0\xd8")]
)
def test_incomplete_records_and_hostile_unicode_fail_clearly(tag: int, data: bytes) -> None:
    with pytest.raises(CorruptScoreError):
        _others_records((MusOther(tag, 1, 0, data),), "cp1252")


def test_placed_music_font_segno_and_hidden_controls_survive_without_palette_leaks() -> None:
    doc = parse_enigma(b"""<finale><others>
      <fontName cmper="7"><name>Maestro</name></fontName>
      <textRepeatDef cmper="3"><fontID>7</fontID></textRepeatDef>
      <textRepeatText cmper="3"><rptText>%</rptText></textRepeatText>
      <textRepeatText cmper="8"><rptText>D.C.</rptText></textRepeatText>
      <textRepeatAssign cmper="2"><repnum>3</repnum><action>noJump</action></textRepeatAssign>
      <textRepeatAssign cmper="5"><repnum>8</repnum><action>jumpAbsolute</action>
        <target>1</target><actuate>1</actuate><trigger>onPass</trigger><hidden/></textRepeatAssign>
    </others></finale>""")
    marks = navigation_by_measure(doc)
    assert marks[2][0].kind == "segno"
    assert not marks[5][0].visible
    assert marks[5][0].playback is not None and marks[5][0].playback.target == 1


def test_an_ordinary_percent_sign_is_not_promoted_to_a_segno() -> None:
    doc = parse_enigma(b"""<finale><others>
      <fontName cmper="7"><name>Times New Roman</name></fontName>
      <textRepeatDef cmper="3"><fontID>7</fontID></textRepeatDef>
      <textRepeatText cmper="3"><rptText>%</rptText></textRepeatText>
      <textRepeatAssign cmper="2"><repnum>3</repnum></textRepeatAssign>
    </others></finale>""")
    assert navigation_by_measure(doc)[2][0].kind == "words"


def test_an_unsupported_music_font_glyph_is_retained_without_a_guessed_sign() -> None:
    doc = parse_enigma(b"""<finale><others>
      <fontName cmper="7"><name>Jazz</name></fontName>
      <textRepeatDef cmper="3"><fontID>7</fontID></textRepeatDef>
      <textRepeatText cmper="3"><rptText>%</rptText></textRepeatText>
      <textRepeatAssign cmper="2"><repnum>3</repnum></textRepeatAssign>
    </others></finale>""")
    assert navigation_by_measure(doc)[2][0].kind == "unknown-glyph"
