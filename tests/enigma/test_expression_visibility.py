"""Original C/D score and expression fixtures, authored here and licensed MIT."""

from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _meas_expr_assign, _others_records
from finale_file_parser.enigma.mus_others import TAG_MEAS_EXPR_ASSIGN, MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _document(
    flags: str = "",
    *,
    refs: str = "",
    text: str = "quarter = 120",
    definition: str = "<playType>tempo</playType><value>120</value><auxdata1>1024</auxdata1>",
    extra: str = "",
) -> bytes:
    return f"""<finale><others><staffSpec cmper="1"/>
    <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
    <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    <textExprDef cmper="1">{definition}</textExprDef>{refs}
    <measExprAssign cmper="1" inci="0"><staffAssign>1</staffAssign>
    <textExprID>1</textExprID>{flags}</measExprAssign>{extra}
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
    <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry></entries>
    <texts><expression number="1">{text}</expression></texts></finale>""".encode()


@pytest.mark.parametrize(
    "bits,hidden,score,part",
    [
        (0, False, True, True),
        (0x4000, True, True, True),
        (0x0800, False, True, False),
        (0x1000, False, False, True),
        (0x1800, False, False, False),
    ],
)
def test_assignment_scope_and_visibility_are_independent_bits(
    bits: int, hidden: bool, score: bool, part: bool
) -> None:
    payload = bytearray(24)
    payload[0:2] = (1).to_bytes(2, "little")
    payload[8:10] = (1).to_bytes(2, "little")
    payload[10:12] = (bits | 0x0200).to_bytes(2, "little")
    fields = _meas_expr_assign(bytes(payload))
    assert ("hidden" in fields) == hidden
    assert ("noScoreAssignment" not in fields) == score
    assert ("noPartAssignment" not in fields) == part
    records = _others_records((MusOther(TAG_MEAS_EXPR_ASSIGN, 1, 0, bytes(payload) * 2),), "")
    assert len(records) == 2 and records[0].fields == records[1].fields == fields


def test_hidden_tempo_keeps_sound_and_source_text_without_a_printed_metronome() -> None:
    score = build_score(parse_enigma(_document("<hidden/>")))
    expression = score.parts[0].measures[0].expressions[0]
    assert not expression.visible and expression.score_assignment and expression.part_assignment
    assert expression.tempo is not None and expression.tempo.per_minute == 120
    assert expression.playback is not None and expression.playback.beat_unit == Fraction(1, 4)
    root = ET.fromstring(to_musicxml(score))
    assert root.find(".//metronome") is None and root.find(".//words") is None
    assert root.findtext(".//other-direction[@print-object='no']") == "quarter = 120"
    sound = root.find(".//sound")
    assert sound is not None and sound.attrib == {"tempo": "120"}


def test_untyped_explicit_hidden_metronome_keeps_existing_sound_projection() -> None:
    score = build_score(parse_enigma(_document("<hidden/>", definition="")))
    root = ET.fromstring(to_musicxml(score))
    assert root.find(".//metronome") is None
    sound = root.find(".//sound")
    assert sound is not None and sound.get("tempo") == "120"


@pytest.mark.parametrize(
    "mode,score_scope,part_scope", [("scoreOnly", True, False), ("partOnly", False, True)]
)
def test_part_print_scope_keeps_source_control_but_applies_only_score_assignments(
    mode: str, score_scope: bool, part_scope: bool
) -> None:
    score = build_score(parse_enigma(_document(f"<showStaffList>{mode}</showStaffList>")))
    expression = score.parts[0].measures[0].expressions[0]
    assert expression.score_assignment == score_scope and expression.part_assignment == part_scope
    assert expression.playback is not None and expression.playback.value == 120
    root = ET.fromstring(to_musicxml(score))
    assert (root.find(".//metronome") is not None) == score_scope
    assert (root.find(".//sound") is not None) == score_scope


def test_cleared_text_does_not_print_description_or_an_unrelated_same_number_glyph() -> None:
    raw = _document(
        refs='<textBlock cmper="2"><textID>0</textID><textTag>expression</textTag></textBlock>',
        text="unrelated",
        definition="<textBlockID>2</textBlockID>"
        "<descStr>pianissississimo (velocity = 0) (Copy)</descStr>"
        "<playType>amplitude</playType><value>0</value>",
    )
    score = build_score(parse_enigma(raw))
    expression = score.parts[0].measures[0].expressions[0]
    assert not expression.visible and expression.marking == "pppp"
    assert expression.playback is not None and expression.playback.value == 0
    root = ET.fromstring(to_musicxml(score))
    assert root.find(".//dynamics") is None and root.find(".//words") is None
    sound = root.find(".//sound")
    assert sound is not None and sound.attrib == {"dynamics": "0"}


def test_missing_text_remains_distinct_from_an_explicit_clear() -> None:
    score = build_score(
        parse_enigma(
            _document(
                definition="<textBlockID>99</textBlockID>"
                "<descStr>mezzo piano (velocity = 62)</descStr>"
                "<playType>amplitude</playType><value>62</value>"
            )
        )
    )
    assert score.parts[0].measures[0].expressions[0].visible
    assert ET.fromstring(to_musicxml(score)).find(".//dynamics/mp") is not None


def test_hidden_real_staff_copy_does_not_swallow_a_visible_list_assignment() -> None:
    extra = (
        '<measExprAssign cmper="1" inci="1"><staffAssign>-1</staffAssign>'
        "<textExprID>1</textExprID></measExprAssign>"
    )
    score = build_score(parse_enigma(_document("<hidden/>", extra=extra)))
    assert len(score.parts[0].measures[0].expressions) == 2
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall(".//metronome")) == 1 and len(root.findall(".//other-direction")) == 1


@pytest.mark.parametrize("scope", ["future-mode", "<bad/>"])
def test_unknown_print_scope_is_a_clear_source_error(scope: str) -> None:
    with pytest.raises(CorruptScoreError, match="showStaffList"):
        build_score(parse_enigma(_document(f"<showStaffList>{scope}</showStaffList>")))
