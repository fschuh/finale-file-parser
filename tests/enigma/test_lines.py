"""Authored lines pin source assignment, style, geometry and MusicXML timing."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.lines import lines_by_staff
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Event, LineSpan, Measure, Part, Pitch, Score, TimeSignature, Voice


def _document(
    kind: str = "10",
    *,
    assigned: bool = True,
    flags: str = "",
    font: str = "Maestro",
    caps: str = "<lineCapStartType>none</lineCapStartType><lineCapEndType>none</lineCapEndType>",
) -> EnigmaDocument:
    mark = (
        '<smartShapeMeasMark cmper="1"><shapeNum>7</shapeNum></smartShapeMeasMark>'
        if assigned
        else ""
    )
    return parse_enigma(
        f"""<finale><others><fontName cmper="0"><name>{font}</name></fontName>
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      <smartShape cmper="7"><shapeType>{kind}</shapeType><ssLineStyleID>9</ssLineStyleID>{flags}
        <startTermSeg><endPt><inst>1</inst><meas>1</meas><edu>512</edu></endPt>
          <endPtAdj><on/><x>-12</x><y>-120</y></endPtAdj></startTermSeg>
        <endTermSeg><endPt><inst>1</inst><meas>1</meas><edu>1536</edu></endPt>
          <endPtAdj><on/><x>24</x><y>-96</y></endPtAdj></endTermSeg></smartShape>{mark}
      <smartShapeCustomLine cmper="9"><lineStyle>char</lineStyle>
        <charParams><lineChar>126</lineChar><fontID>0</fontID><fontSize>24</fontSize></charParams>
        {caps}
        <leftStartRawTextID>17</leftStartRawTextID></smartShapeCustomLine>
      </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
      <entries><entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
        <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry></entries>
      <texts><smartShapeText number="17">gentle</smartShapeText></texts></finale>""".encode()
    )


@pytest.mark.parametrize(
    ("kind", "style", "cap"),
    [
        ("10", "dashed", "none"),
        ("11", "solid", "none"),
        ("32", "dashed", "up"),
        ("29", "wavy", "none"),
    ],
)
def test_assigned_lines_preserve_exact_offsets_geometry_and_styles(
    kind: str, style: str, cap: str
) -> None:
    score = build_score(_document(kind))
    (line,) = score.parts[0].lines
    assert line.start_offset == Fraction(1, 8) and line.end_offset == Fraction(3, 8)
    assert (line.start_x, line.start_y, line.end_x, line.end_y) == (
        Fraction(-1, 2),
        Fraction(-5),
        Fraction(1),
        Fraction(-4),
    )
    assert (line.line_type, line.start_cap) == (style, cap)
    xml = ET.fromstring(to_musicxml(score))
    directions = xml.findall("part/measure/direction")
    assert [d.findtext("offset") for d in directions] == ["1", "3"]
    offsets = xml.findall("part/measure/direction/offset")
    assert [offset.get("sound") for offset in offsets] == ["no", "no"]
    marks = xml.findall(".//bracket")
    assert [m.get("type") for m in marks] == ["start", "stop"]
    assert all(m.get("line-type") == style for m in marks)
    assert marks[0].get("line-end") == cap
    assert not xml.findall(".//sound")
    if kind == "29":
        assert line.start_text == "gentle" and xml.findtext(".//words") == "gentle"


@pytest.mark.parametrize("flags", ["<hidden/>", "<entryBased/>", "<lyricBased/>"])
def test_hidden_or_unestablished_attachment_never_creates_a_false_metric_span(flags: str) -> None:
    assert lines_by_staff(_document(flags=flags))[0] == {}


def test_unused_line_and_label_palettes_place_nothing() -> None:
    assert lines_by_staff(_document("29", assigned=False)) == ({}, ())


def test_stale_assigned_line_is_quarantined() -> None:
    assert lines_by_staff(_document("29"), ignored_shapes=(7,)) == ({}, ())


def test_unknown_music_font_retains_a_visible_line_diagnostic() -> None:
    lines, diagnostics = lines_by_staff(_document("29", font="Unknown Music Font"))
    assert lines == {} and diagnostics[0].code == "line-character"


def test_engraver_trill_extension_glyph_preserves_a_wavy_drawing_without_ornament_meaning() -> None:
    lines, diagnostics = lines_by_staff(_document("29", font="EngraverFontSet"))
    assert lines[1][0].line_type == "wavy" and diagnostics == ()


def _score(lines: tuple[LineSpan, ...]) -> Score:
    event = Event(Fraction(1), Fraction(1), (Pitch("C", 4, 0),))
    return Score(
        parts=(
            Part(
                "P1",
                "Test",
                (Measure(1, (Voice(1, (event,)),), time=TimeSignature(4, 4)),),
                lines=lines,
            ),
        )
    )


def test_graphical_zero_time_line_retains_distinct_positions() -> None:
    span = LineSpan(
        1,
        Fraction(0),
        1,
        Fraction(0),
        start_x=Fraction(-1),
        end_x=Fraction(1),
        start_y=Fraction(-5),
        end_y=Fraction(-6),
    )
    xml = ET.fromstring(to_musicxml(_score((span,))))
    marks = xml.findall(".//bracket")
    assert [m.get("relative-x") for m in marks] == ["-10", "10"]
    assert [m.get("relative-y") for m in marks] == ["-50", "-60"]
    assert xml.findtext(".//note/duration") == "4"


def test_more_than_sixteen_sequential_lines_reuse_musicxml_numbers() -> None:
    spans = tuple(LineSpan(1, Fraction(i, 100), 1, Fraction(i + 1, 100)) for i in range(20))
    marks = ET.fromstring(to_musicxml(_score(spans))).findall(".//bracket")
    assert len(marks) == 40 and all(m.get("number") == "1" for m in marks)


def test_seventeen_overlapping_lines_fail_without_reusing_an_active_number() -> None:
    span = LineSpan(1, Fraction(0), 1, Fraction(1))
    with pytest.raises(ExportError, match="more than 16 drawn lines"):
        to_musicxml(_score((span,) * 17))


@pytest.mark.parametrize(("length", "cap"), [(1536, "up"), (-768, "down"), (0, "none")])
def test_custom_hook_signed_efix_length_is_preserved(length: int, cap: str) -> None:
    document = _document(
        "29",
        caps=f"<lineCapStartType>hook</lineCapStartType>"
        f"<lineCapStartHookLength>{length}</lineCapStartHookLength>",
    )
    score = build_score(document)
    line = score.parts[0].lines[0]
    assert line.start_cap == cap and line.start_cap_length == Fraction(abs(length), 1536)
    bracket = ET.fromstring(to_musicxml(score)).find(".//bracket")
    assert bracket is not None and bracket.get("line-end") == cap
    assert bracket.get("end-length") == str(abs(length) * 10 // 1536)


def test_custom_endpoint_shape_remains_explicit_in_ir_and_diagnostics() -> None:
    document = _document(
        "29",
        caps="<lineCapEndType>arrowheadCustom</lineCapEndType><lineCapEndArrowID>107</lineCapEndArrowID>",
    )
    lines, diagnostics = lines_by_staff(document)
    assert lines[1][0].end_symbol == "shape:107"
    assert any(d.code == "line-endpoint-graphic" for d in diagnostics)


@pytest.mark.parametrize(
    "span",
    [
        LineSpan(1, Fraction(-1), 1, Fraction(0)),
        LineSpan(1, Fraction(0), 2, Fraction(0)),
        LineSpan(1, Fraction(1, 2), 1, Fraction(1, 4)),
        LineSpan(1, Fraction(0), 1, Fraction(1), line_type="other"),
    ],
)
def test_invalid_line_bounds_or_style_raise_clear_errors(span: LineSpan) -> None:
    with pytest.raises(ExportError, match="line"):
        to_musicxml(_score((span,)))


def test_explicit_cross_staff_line_pairs_numbers_and_preserves_staff_scope() -> None:
    score = _score((LineSpan(1, Fraction(0), 1, Fraction(1, 2), end_part_id="P2"),))
    lower = replace(score.parts[0], id="P2", lines=())
    xml = ET.fromstring(to_musicxml(replace(score, parts=(*score.parts, lower))))
    assert len(xml.findall("part")) == 1
    dirs = xml.findall(".//direction")
    assert [d.findtext("staff") for d in dirs] == ["1", "2"]
    brackets = xml.findall(".//direction/direction-type/bracket")
    assert [bracket.get("number") for bracket in brackets] == ["1", "1"]
