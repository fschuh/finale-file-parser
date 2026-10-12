"""Authored headers distinguish assigned metronomes from unused text palettes."""

from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.expressions import first_page_tempos
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import ExpressionPlayback, Tempo


def _document(
    *,
    page: int = 1,
    flags: str = "",
    attrs: str = "",
    font: str = "Maestro",
    text: str = "^fontMus(0,0)h = 130",
    assigned: bool = True,
) -> EnigmaDocument:
    placement = (
        f'<pageTextAssign cmper="{page}"{attrs}><block>9</block>{flags}</pageTextAssign>'
        if assigned
        else ""
    )
    return parse_enigma(
        f"""<finale><others>
      <fontName cmper="0"><name>{font}</name></fontName>
      <textBlock cmper="9"><textID>42</textID></textBlock>{placement}
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
      <entries><entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>1</numNotes>
      <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry></entries>
      <texts><blockText number="42">{text}</blockText></texts></finale>""".encode()
    )


def test_a_visible_assigned_first_page_metronome_has_display_only_scope() -> None:
    (header,) = first_page_tempos(_document())
    assert header.tempo == Tempo(Fraction(1, 2), Fraction(130))
    assert header.page == 1 and header.score_wide
    assert header.playback == ExpressionPlayback("none", 0)
    score = build_score(_document())
    assert score.parts[0].measures[0].expressions == (header,)
    xml = ET.fromstring(to_musicxml(score))
    assert xml.findtext(".//metronome/beat-unit") == "half"
    assert xml.findtext(".//metronome/per-minute") == "130"
    assert xml.find(".//direction/sound") is None


@pytest.mark.parametrize(
    ("page", "flags", "attrs", "assigned"),
    [
        (2, "", "", True),
        (0, "", "", True),
        (1, "<postIt/>", "", True),
        (1, "", ' part="1"', True),
        (1, "", "", False),
    ],
)
def test_unused_hidden_other_page_or_part_text_does_not_place_a_tempo(
    page: int,
    flags: str,
    attrs: str,
    assigned: bool,
) -> None:
    assert (
        first_page_tempos(_document(page=page, flags=flags, attrs=attrs, assigned=assigned)) == ()
    )


@pytest.mark.parametrize("text", ["Arranged by Musician", "h = 0", "h = 1001", "copyright 130"])
def test_non_metronome_or_invalid_rate_headers_are_not_promoted(text: str) -> None:
    assert first_page_tempos(_document(text=text)) == ()


@pytest.mark.parametrize("font", ["Times New Roman", "Unknown Music Font"])
def test_an_ordinary_header_letter_h_is_not_a_half_note(font: str) -> None:
    assert first_page_tempos(_document(font=font)) == ()


def test_explicit_written_unit_words_establish_a_header_without_a_music_font() -> None:
    assert first_page_tempos(_document(font="Times New Roman", text="quarter = 120"))[
        0
    ].tempo == Tempo(Fraction(1, 4), Fraction(120))
