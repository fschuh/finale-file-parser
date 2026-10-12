"""Authored single notes and chords pin safe parenthetical attachment handling."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.parentheses import parentheses_by_entry
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Event, Measure, Parenthesis, Part, Pitch, Score, Voice


def _document(
    *,
    chord: bool = False,
    font: str = "Maestro",
    right_x: int = 0,
    omit_right: bool = False,
    flags: str = "",
    definition_flags: str = "",
) -> EnigmaDocument:
    notes = "<note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>"
    if chord:
        notes += "<note><harmLev>2</harmLev><harmAlt>0</harmAlt></note>"
    right = (
        ""
        if omit_right
        else f"""
      <articAssign entnum="1" inci="1"><articDef>2</articDef>
        <horzOff>{right_x}</horzOff><vertOff>0</vertOff>{flags}</articAssign>"""
    )
    return parse_enigma(
        f"""<finale><others>
      <fontName cmper="0"><name>{font}</name></fontName>
      <articDef cmper="1"><charMain>40</charMain><fontMain>0</fontMain>
        <xOffsetMain>-26</xOffsetMain><yOffsetMain>-21</yOffsetMain>{definition_flags}</articDef>
      <articDef cmper="2"><charMain>41</charMain><fontMain>0</fontMain>
        <xOffsetMain>26</xOffsetMain><yOffsetMain>-21</yOffsetMain>{definition_flags}</articDef>
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <articAssign entnum="1"><articDef>1</articDef><horzOff>0</horzOff>
        <vertOff>0</vertOff>{flags}</articAssign>
      {right}</details><entries><entry entnum="1" prev="0" next="0"><dura>1024</dura>
        <numNotes>{2 if chord else 1}</numNotes>{notes}</entry></entries></finale>""".encode()
    )


def test_a_compact_pair_on_one_note_exports_as_notehead_parentheses() -> None:
    score = build_score(_document())
    event = score.parts[0].measures[0].voices[0].events[0]
    assert [m.pitch_index for m in event.parentheses] == [0, 0]
    assert event.pitches == (Pitch("C", 4, 0),) and event.duration == Fraction(1, 4)
    root = ET.fromstring(to_musicxml(score))
    assert root.findtext(".//notehead[@parentheses='yes']") == "normal"
    assert root.find(".//other-notation") is None
    assert score.diagnostics == ()


@pytest.mark.parametrize(
    ("chord", "right_x", "omit_right"), [(True, 0, False), (False, 118, False), (False, 0, True)]
)
def test_unestablished_note_or_span_attachment_retains_glyphs_and_reports_the_limit(
    chord: bool,
    right_x: int,
    omit_right: bool,
) -> None:
    score = build_score(_document(chord=chord, right_x=right_x, omit_right=omit_right))
    event = score.parts[0].measures[0].voices[0].events[0]
    assert all(m.pitch_index is None for m in event.parentheses)
    root = ET.fromstring(to_musicxml(score))
    assert root.find(".//notehead") is None
    marks = root.findall(".//other-notation")
    assert [m.text for m in marks] == ["(" if m.side == "left" else ")" for m in event.parentheses]
    assert marks[0].get("smufl") == "noteheadParenthesisLeft"
    assert float(marks[0].get("relative-x", "0")) == pytest.approx(-26 * 10 / 24)
    assert len(score.diagnostics) == 1
    assert score.diagnostics[0].code == "parenthesis-attachment"


@pytest.mark.parametrize("font", ["Times New Roman", "Unknown Music Font", "EngraverFontSet"])
def test_unsupported_font_letters_do_not_establish_music_parentheses(font: str) -> None:
    assert parentheses_by_entry(_document(font=font)) == {}


@pytest.mark.parametrize(
    ("flags", "definition_flags"),
    [("<hide/>", ""), ("", "<mainIsShape/>"), ("", "<noPrint/>")],
)
def test_hidden_or_shape_definitions_do_not_place_glyphs(flags: str, definition_flags: str) -> None:
    assert parentheses_by_entry(_document(flags=flags, definition_flags=definition_flags)) == {}


def test_duplicate_source_assignments_preserve_only_one_pair() -> None:
    doc = _document()
    doc.details = replace(
        doc.details,
        records=(
            *doc.details.records,
            *(
                replace(r, attrs={**r.attrs, "inci": "2"})
                for r in doc.details.of_tag("articAssign")
                if r.fields.get("articDef") == "1"
            ),
        ),
    )
    assert len(parentheses_by_entry(doc)[1]) == 2


def test_part_variants_do_not_add_source_score_parentheses() -> None:
    doc = _document()
    doc.details = replace(
        doc.details,
        records=tuple(
            replace(r, attrs={**r.attrs, "part": "1"}) if r.tag == "articAssign" else r
            for r in doc.details.records
        ),
    )
    assert parentheses_by_entry(doc) == {}


def test_malformed_drawing_offset_raises_a_clear_error() -> None:
    doc = _document()
    doc.details = replace(
        doc.details,
        records=tuple(
            replace(r, fields={**r.fields, "horzOff": "invalid"}) if r.tag == "articAssign" else r
            for r in doc.details.records
        ),
    )
    with pytest.raises(CorruptScoreError, match="invalid parenthesis horzOff"):
        parentheses_by_entry(doc)


@pytest.mark.parametrize(
    "mark",
    [Parenthesis("other"), Parenthesis("left", pitch_index=2), Parenthesis("left", pitch_index=0)],
)
def test_invalid_side_note_or_unpaired_notehead_enclosure_has_a_clear_error(
    mark: Parenthesis,
) -> None:
    event = Event(Fraction(1, 4), Fraction(1, 4), (Pitch("C", 4, 0),), parentheses=(mark,))
    score = Score(parts=(Part("P1", "Test", (Measure(1, (Voice(1, (event,)),)),)),))
    with pytest.raises(ExportError, match="parenthes"):
        to_musicxml(score)
