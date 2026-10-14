"""Original MIT endpoint drawings; no third-party score or shape fixture."""

from dataclasses import replace

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, OthersPool, Record, parse_enigma
from finale_file_parser.enigma.lines import lines_by_staff
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import (
    TAG_SHAPE_DATA,
    TAG_SHAPE_DEF,
    TAG_SHAPE_LIST,
    MusOther,
)
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _resources() -> tuple[Record, ...]:
    """An original open triangular endpoint, with deliberately different IDs."""
    commands = [
        (0x736F, [-8, 0, -10, 14, 10, -2, 1000, 1000, 0, 0, 0]),
        (0x6C77, [96]),
        (0x726D, [0, 0]),
        (0x7364, [8, 0]),
        (0x726C, [8, 12]),
        (0x726C, [8, -12]),
        (0x7374, []),
    ]
    header = (9).to_bytes(2, "little") + (11).to_bytes(2, "little") + bytes([7]) + bytes(7)
    instructions = b"".join(
        opcode.to_bytes(2, "little") + bytes([len(values), 2]) for opcode, values in commands
    ) + bytes(8)
    # Nonzero storage after the consumed prefix is not another instruction.
    values = [value for _, parameters in commands for value in parameters] + [42, -31]
    data = b"".join(value.to_bytes(4, "little", signed=True) for value in values)
    return tuple(
        _others_records(
            (
                MusOther(TAG_SHAPE_DEF, 37, 0, header),
                MusOther(TAG_SHAPE_LIST, 9, 0, instructions),
                MusOther(TAG_SHAPE_DATA, 11, 0, data),
                MusOther(TAG_SHAPE_DATA, 37, 0, bytes(4)),  # Must not use shape ID as data ID.
            ),
            "cp1252",
        )
    )


def _document(resources: tuple[Record, ...] | None = None, *, flags: str = "") -> EnigmaDocument:
    doc = parse_enigma(
        f"""<finale><others><staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      <smartShape cmper="7"><shapeType>29</shapeType><ssLineStyleID>5</ssLineStyleID>{flags}
        <startTermSeg><endPt><inst>1</inst><meas>1</meas><edu>0</edu></endPt></startTermSeg>
        <endTermSeg><endPt><inst>1</inst><meas>1</meas><edu>4096</edu></endPt>
          <endPtAdj><on/><x>-6</x><y>-120</y></endPtAdj></endTermSeg>
      </smartShape><smartShapeMeasMark cmper="1"><shapeNum>7</shapeNum></smartShapeMeasMark>
      <smartShapeCustomLine cmper="5"><lineStyle>solid</lineStyle>
        <lineCapEndType>arrowheadCustom</lineCapEndType><lineCapEndArrowID>37</lineCapEndArrowID>
      </smartShapeCustomLine></others>
      <details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
      <entries><entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
        <isNote/><note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
      </entry></entries></finale>""".encode()
    )
    doc.others = OthersPool(doc.others.records + (_resources() if resources is None else resources))
    return doc


def test_visible_endpoint_joins_separate_instruction_and_data_ids_without_changing_music() -> None:
    score = build_score(_document())
    line = score.parts[0].lines[0]
    graphic = line.end_graphic
    assert graphic is not None
    assert (graphic.source_ref, graphic.instruction_ref, graphic.data_ref, graphic.kind) == (
        "shapeDef:37",
        "shapeList:9",
        "shapeData:11",
        "arrowhead",
    )
    assert [(cmd.kind, cmd.parameters) for cmd in graphic.instructions] == [
        ("startObject", (-8, 0, -10, 14, 10, -2, 1000, 1000, 0, 0, 0)),
        ("lineWidth", (96,)),
        ("rMoveTo", (0, 0)),
        ("setDash", (8, 0)),
        ("rLineTo", (8, 12)),
        ("rLineTo", (8, -12)),
        ("stroke", ()),
    ]
    assert line.end_symbol == "shape:37" and line.end_cap == "none"
    # Standard bracket export retains exact attachment/geometry, but does not
    # turn an arbitrary endpoint path into a pedal controller or guessed glyph.
    unresolved = build_score(_document(()))
    assert to_musicxml(score) == to_musicxml(unresolved)
    assert any(d.code == "line-endpoint-graphic" for d in score.diagnostics)
    assert not any(d.code == "line-graphic-resource" for d in score.diagnostics)
    assert score.parts[0].measures == unresolved.parts[0].measures


def test_typed_xml_uses_the_same_graphic_resolution() -> None:
    resources = parse_enigma(b"""<finale><others>
      <shapeDef cmper="37"><instList>9</instList><dataList>11</dataList>
        <shapeType>arrowhead</shapeType></shapeDef>
      <shapeList cmper="9"><instruct><tag>rLineTo</tag><numData>2</numData></instruct></shapeList>
      <shapeData cmper="11"><data>-4</data><data>7</data></shapeData>
    </others></finale>""").others.records
    graphic = build_score(_document(resources)).parts[0].lines[0].end_graphic
    assert graphic is not None
    assert [(cmd.kind, cmd.parameters) for cmd in graphic.instructions] == [("rLineTo", (-4, 7))]


def test_omitted_zero_count_and_blank_definition_are_valid_typed_defaults() -> None:
    resources = parse_enigma(b"""<finale><others>
      <shapeDef cmper="37"><instList>9</instList><dataList>11</dataList></shapeDef>
      <shapeList cmper="9"><instruct><tag>stroke</tag></instruct></shapeList>
      <shapeData cmper="11"/>
    </others></finale>""").others.records
    graphic = build_score(_document(resources)).parts[0].lines[0].end_graphic
    assert graphic is not None
    assert [(cmd.kind, cmd.parameters) for cmd in graphic.instructions] == [("stroke", ())]
    blank = Record("shapeDef", {"cmper": "37"}, "", {})
    score = build_score(_document((blank,)))
    graphic = score.parts[0].lines[0].end_graphic
    assert graphic is not None and not graphic.instructions
    assert not any(d.code == "line-graphic-resource" for d in score.diagnostics)


@pytest.mark.parametrize("flags", ["<hidden/>", "<entryBased/>"])
def test_ineligible_drawing_does_not_resolve_an_invalid_palette(flags: str) -> None:
    bad = Record("shapeDef", {"cmper": "37"}, "", {"instList": "-1"})
    lines, _ = lines_by_staff(_document((bad,), flags=flags))
    assert not lines


def test_linked_part_resources_do_not_replace_the_score_endpoint() -> None:
    resources = tuple(replace(r, attrs={**r.attrs, "part": "1"}) for r in _resources())
    score = build_score(_document(resources))
    assert score.parts[0].lines[0].end_graphic is None
    assert any(d.code == "line-graphic-resource" for d in score.diagnostics)


def test_unknown_opcode_retains_inert_parameters_with_a_diagnostic() -> None:
    resources = _resources()
    custom = _others_records((MusOther(TAG_SHAPE_LIST, 9, 0, b"\xff\x7f\x02\x02"),), "cp1252")[0]
    resources = tuple(custom if r.tag == "shapeList" else r for r in resources)
    score = build_score(_document(resources))
    graphic = score.parts[0].lines[0].end_graphic
    assert graphic is not None
    command = graphic.instructions[0]
    assert (command.kind, command.parameters, command.source_tag) == ("opcode:7fff", (-8, 0), 32767)
    assert any(d.code == "line-graphic-resource" for d in score.diagnostics)


def test_unestablished_binary_instruction_format_is_not_interpreted() -> None:
    custom = _others_records((MusOther(TAG_SHAPE_LIST, 9, 0, b"\x6c\x72\x02\x01"),), "cp1252")[0]
    resources = tuple(custom if r.tag == "shapeList" else r for r in _resources())
    score = build_score(_document(resources))
    assert score.parts[0].lines[0].end_graphic is None
    assert any("format is unestablished" in d.message for d in score.diagnostics)


@pytest.mark.parametrize("count", ["-1", "999999999999", "1", "<unexpected/>"])
def test_assigned_instructions_validate_counts_before_slicing(count: str) -> None:
    instructions = parse_enigma(
        f"""<finale><others><shapeList cmper="9">
      <instruct><tag>rLineTo</tag><numData>{count}</numData></instruct>
    </shapeList></others></finale>""".encode()
    ).others.records[0]
    resources = tuple(instructions if r.tag == "shapeList" else r for r in _resources())
    with pytest.raises(CorruptScoreError, match="shapeDef:37"):
        build_score(_document(resources))


@pytest.mark.parametrize(
    ("tag", "payload"),
    [
        (TAG_SHAPE_DEF, bytes(4)),
        (TAG_SHAPE_DEF, bytes(24)),
        (TAG_SHAPE_LIST, bytes(3)),
        (TAG_SHAPE_DATA, bytes(3)),
        (TAG_SHAPE_LIST, bytes(4 * 8193)),
        (TAG_SHAPE_DATA, bytes(4 * 65537)),
    ],
)
def test_binary_graphic_arrays_are_bounded_before_expansion(tag: int, payload: bytes) -> None:
    with pytest.raises(CorruptScoreError, match="shape(Def|List|Data)"):
        _others_records((MusOther(tag, 37, 0, payload),), "cp1252")


def test_typed_data_and_instruction_limits_are_also_enforced() -> None:
    resources = _resources()
    for custom in (
        Record("shapeData", {"cmper": "11"}, "", {"data": ("0",) * 65537}),
        Record("shapeData", {"cmper": "11"}, "", {"data": str(2**31)}),
        Record(
            "shapeList",
            {"cmper": "9"},
            "",
            {"instruct": (Record("instruct", {}, "", {"tag": "stroke", "numData": "0"}),) * 8193},
        ),
    ):
        changed = tuple(
            custom if (r.tag, r.attrs) == (custom.tag, custom.attrs) else r for r in resources
        )
        with pytest.raises(CorruptScoreError, match="shape(Data|List|Def)"):
            build_score(_document(changed))
