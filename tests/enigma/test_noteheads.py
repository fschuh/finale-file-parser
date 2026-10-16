"""Original three-note chord fixtures authored for this project; licensed MIT."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import MusDetailRecord
from finale_file_parser.enigma.mus_document import _details_records
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Notehead, Parenthesis


def _document(mods: str = "", font: str = "Maestro") -> EnigmaDocument:
    return parse_enigma(
        f"""<finale><others>
      <fontName cmper="0"><name>{font}</name></fontName>
      <fontName cmper="2"><name>Times New Roman</name></fontName>
      <fontName cmper="3"><name>EngraverFontSet</name></fontName>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>{mods}
    </details><entries><entry entnum="1" prev="0" next="0"><dura>1536</dura>
      <numNotes>3</numNotes>
      <note id="7"><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
      <note id="2"><harmLev>2</harmLev><harmAlt>0</harmAlt></note>
      <note id="11"><harmLev>4</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>""".encode()
    )


def _mod(note: int = 2, character: int = 192, *, extra: str = "", attrs: str = "") -> str:
    return (
        f'<noteheadMod entnum="1" {attrs}><noteID>{note}</noteID>'
        f"<customChar>{character}</customChar>{extra}</noteheadMod>"
    )


@pytest.mark.parametrize("font", ["Maestro", "EngraverFontSet", "Engraver Font Set"])
def test_cross_head_joins_stable_note_id_and_keeps_chord_rhythm_pitch_and_ties(font: str) -> None:
    doc = _document(_mod(11, attrs='inci="0"') + _mod(7, attrs='inci="1"'), font)
    score = build_score(doc)
    event = score.parts[0].measures[0].voices[0].events[0]
    assert [(h.pitch_index, h.shape) for h in event.noteheads] == [(2, "x"), (0, "x")]
    assert event.duration == event.written_duration == Fraction(3, 8)
    assert event.dots == 1
    notes = ET.fromstring(to_musicxml(score)).findall(".//note")
    assert [n.findtext("pitch/step") for n in notes] == ["C", "E", "G"]
    assert [n.findtext("notehead") for n in notes] == ["x", None, "x"]
    assert [n.findtext("type") for n in notes] == ["quarter"] * 3
    assert all(n.find("dot") is not None for n in notes)
    assert not score.diagnostics


@pytest.mark.parametrize("font_id,shape", [(2, None), (3, "x")])
def test_custom_font_selects_its_own_character_mapping(font_id: int, shape: str | None) -> None:
    score = build_score(_document(_mod(extra=f"<useCustomFont/><fontID>{font_id}</fontID>")))
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.noteheads[0].shape == shape
    assert len(score.diagnostics) == (1 if shape is None else 0)
    assert ET.fromstring(to_musicxml(score)).findtext(".//notehead") == shape


@pytest.mark.parametrize("character,font", [(193, "Maestro"), (192, "Unknown"), (251, "Maestro")])
def test_unestablished_glyphs_retain_source_data_and_report_the_limit(
    character: int, font: str
) -> None:
    score = build_score(_document(_mod(character=character), font))
    head = score.parts[0].measures[0].voices[0].events[0].noteheads[0]
    assert (head.shape, head.source_character, head.source_font) == (None, character, font)
    assert score.diagnostics[0].code == "notehead-glyph"
    assert ET.fromstring(to_musicxml(score)).find(".//notehead") is None


def test_ordinary_cleared_and_linked_part_heads_do_not_place_score_modifications() -> None:
    score = build_score(_document(_mod(character=0) + _mod(attrs='part="1"')))
    assert not score.parts[0].measures[0].voices[0].events[0].noteheads
    assert not score.diagnostics


@pytest.mark.parametrize("font", ["Maestro", "EngraverFontSet", "Engraver Font Set"])
def test_half_head_override_keeps_dotted_quarter_rhythm_and_other_chord_heads(font: str) -> None:
    score = build_score(_document(_mod(character=250), font))
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.noteheads[0].shape == "normal" and event.noteheads[0].filled is False
    assert event.duration == event.written_duration == Fraction(3, 8) and event.dots == 1
    notes = ET.fromstring(to_musicxml(score)).findall(".//note")
    assert [n.findtext("type") for n in notes] == ["quarter"] * 3
    assert [n.findtext("duration") for n in notes] == ["3"] * 3
    assert all(n.find("dot") is not None for n in notes)
    head = notes[1].find("notehead")
    assert head is not None and head.text == "normal" and head.get("filled") == "no"
    assert notes[0].find("notehead") is None and notes[2].find("notehead") is None
    assert not score.diagnostics


def test_unknown_font_half_head_has_no_inferred_fill() -> None:
    score = build_score(_document(_mod(character=250), "Unknown"))
    head = score.parts[0].measures[0].voices[0].events[0].noteheads[0]
    assert head.shape is None and head.filled is None
    assert ET.fromstring(to_musicxml(score)).find(".//notehead") is None


def test_identical_packed_assignments_are_idempotent_while_conflicting_heads_raise() -> None:
    score = build_score(_document(_mod(attrs='inci="0"') + _mod(attrs='inci="1"')))
    assert len(score.parts[0].measures[0].voices[0].events[0].noteheads) == 1
    with pytest.raises(CorruptScoreError, match="conflicting notehead"):
        build_score(_document(_mod(attrs='inci="0"') + _mod(character=193, attrs='inci="1"')))


@pytest.mark.parametrize("note", [0, 1, 99])
def test_invalid_stable_note_ids_do_not_attach_to_a_chord_index(note: int) -> None:
    with pytest.raises(CorruptScoreError, match="note ID"):
        build_score(_document(_mod(note)))


def test_malformed_character_and_custom_font_are_clear_errors() -> None:
    for extra in ("<customChar>invalid</customChar>", "<useCustomFont/>"):
        with pytest.raises(CorruptScoreError, match="notehead"):
            build_score(_document(_mod(extra=extra)))


@pytest.mark.parametrize("year,font_at,flag_at", [(2011, 10, 8), (2012, 12, 10)])
def test_packed_source_font_ids_stay_attached_to_their_own_notes(
    year: int, font_at: int, flag_at: int
) -> None:
    first = bytearray(20)
    first[:2], first[6:8] = b"\x07\x00", b"\xc0\x00"
    second = bytearray(first)
    second[:2], second[flag_at] = b"\x0b\x00", 1
    second[font_at : font_at + 2] = b"\x03\x00"
    mods = _details_records((MusDetailRecord(1058, 0, 1, 0, bytes(first + second)),), year=year)
    assert "fontID" not in mods[0].fields and mods[1].fields["fontID"] == "3"
    doc = _document()
    doc.details = replace(doc.details, records=(*doc.details.records, *mods))
    heads = build_score(doc).parts[0].measures[0].voices[0].events[0].noteheads
    assert [(h.pitch_index, h.source_font) for h in heads] == [
        (0, "Maestro"),
        (2, "EngraverFontSet"),
    ]


def test_parentheses_and_shape_share_one_musicxml_notehead() -> None:
    score = build_score(_document(_mod()))
    part = score.parts[0]
    measure = part.measures[0]
    voice = measure.voices[0]
    event = replace(
        voice.events[0],
        parentheses=(Parenthesis("left", pitch_index=1), Parenthesis("right", pitch_index=1)),
    )
    part = replace(part, measures=(replace(measure, voices=(replace(voice, events=(event,)),)),))
    head = ET.fromstring(to_musicxml(replace(score, parts=(part,)))).find(".//notehead")
    assert head is not None and head.text == "x" and head.get("parentheses") == "yes"


@pytest.mark.parametrize(
    "heads", [(Notehead(99, "x"),), (Notehead(0, "other"),), (Notehead(0, "x"),) * 2]
)
def test_invalid_ir_heads_raise_export_errors(heads: tuple[Notehead, ...]) -> None:
    score = build_score(_document())
    part = score.parts[0]
    measure = part.measures[0]
    voice = measure.voices[0]
    event = replace(voice.events[0], noteheads=heads)
    part = replace(part, measures=(replace(measure, voices=(replace(voice, events=(event,)),)),))
    with pytest.raises(ExportError, match="notehead"):
        to_musicxml(replace(score, parts=(part,)))


@pytest.mark.parametrize("font", ["Maestro", "EngraverFontSet"])
def test_character_209_is_the_filled_triangle_head(font: str) -> None:
    score = build_score(_document(_mod(character=209), font))
    head = score.parts[0].measures[0].voices[0].events[0].noteheads[0]
    assert head.shape == "triangle"
    assert ET.fromstring(to_musicxml(score)).findtext(".//notehead") == "triangle"
    assert not score.diagnostics
