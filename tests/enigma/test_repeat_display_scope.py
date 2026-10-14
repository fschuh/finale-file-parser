"""Original independent repeat-printing examples authored here, licensed MIT."""

from dataclasses import replace

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.mus_document import _staff_spec
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Score


def _score(*, hide_lower: bool = True, bundled: bool = False) -> Score:
    flag = "<hideRepeats/>" if hide_lower else ""
    xml = f"""<finale><others>
    <staffSpec cmper="1"/><staffSpec cmper="2">{flag}</staffSpec>
    <staffSpec cmper="1" part="1"><hideRepeats/></staffSpec>
    <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat>
      <barEnding/><forRepBar/><bacRepBar/></measSpec>
    <repeatEndingStart cmper="1"/>
    <repeatPassList cmper="1"><act>1</act><act>3</act></repeatPassList>
    <repeatEndingText cmper="1"><rptText>first</rptText></repeatEndingText>
    <textRepeatAssign cmper="1"><repnum>1</repnum><action>stop</action></textRepeatAssign>
    <textRepeatText cmper="1"><rptText>Fine</rptText></textRepeatText>
    <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>2</endEntry></frameSpec>
    </others><details>
    <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
    <gfhold cmper1="2" cmper2="1"><frame1>2</frame1></gfhold>
    </details><entries>
    <entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
      <isValid/><isNote/><note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>
    <entry entnum="2" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
      <isValid/><isNote/><note id="1"><harmLev>4</harmLev><harmAlt>0</harmAlt></note></entry>
    </entries></finale>""".encode()
    score = build_score(parse_enigma(xml))
    if bundled:
        score = replace(score, parts=tuple(replace(p, instrument_id="I23") for p in score.parts))
    return score


@pytest.mark.parametrize("order", ["little", "big"])
@pytest.mark.parametrize("length", [84, 96])
def test_numeric_inst_flag_is_independent_of_staff_hiding(order: ByteOrder, length: int) -> None:
    raw = bytearray(length)
    raw[22:24] = (0x0200).to_bytes(2, order)
    fields = _staff_spec(bytes(raw), order, decode_hide_mode=True)
    assert "hideRepeats" in fields and "hideMode" not in fields
    assert "hideRepeats" not in _staff_spec(bytes(raw), order)
    raw[22:24] = (0x0040).to_bytes(2, order)  # repeat bars have a separate policy
    assert "hideRepeats" not in _staff_spec(bytes(raw), order, decode_hide_mode=True)


def test_staff_print_policy_preserves_each_repeat_rule_and_navigation_control() -> None:
    score = _score()
    upper, lower = [p.measures[0] for p in score.parts]
    assert all(e.visible for e in upper.endings)
    assert all(not e.visible for e in lower.endings)
    assert upper.repeat_forward and lower.repeat_forward
    assert upper.repeat_backward and lower.repeat_backward
    assert (
        [e.numbers for e in upper.endings] == [e.numbers for e in lower.endings] == [(1, 3), (1, 3)]
    )
    assert upper.navigation[0].visible and not lower.navigation[0].visible
    assert upper.navigation[0].playback == lower.navigation[0].playback
    root = ET.fromstring(to_musicxml(score))
    parts = root.findall("part")
    assert [n.get("print-object") for n in parts[0].findall(".//ending")] == [None, None]
    assert [n.get("print-object") for n in parts[1].findall(".//ending")] == ["no", "no"]
    assert [len(p.findall(".//repeat")) for p in parts] == [2, 2]
    assert root.find(".//sound[@fine='yes']") is not None


def test_independent_parts_keep_intentionally_visible_brackets() -> None:
    root = ET.fromstring(to_musicxml(_score(hide_lower=False)))
    assert len(root.findall("part")) == 2
    assert len(root.findall(".//ending")) == 4
    assert all(e.get("print-object") is None for e in root.findall(".//ending"))


def test_shared_part_merges_only_visibility_preserving_ending_numbers() -> None:
    root = ET.fromstring(to_musicxml(_score(bundled=True)))
    assert len(root.findall("part")) == 1
    assert [e.get("number") for e in root.findall(".//ending")] == ["1,3", "1,3"]
    assert all(e.get("print-object") is None for e in root.findall(".//ending"))


def test_shared_part_still_rejects_conflicting_ending_semantics() -> None:
    score = _score(bundled=True)
    lower = score.parts[1]
    measure = lower.measures[0]
    altered = replace(
        lower,
        measures=(
            replace(measure, endings=tuple(replace(e, numbers=(2,)) for e in measure.endings)),
        ),
    )
    with pytest.raises(ExportError, match="conflicting barlines"):
        to_musicxml(replace(score, parts=(score.parts[0], altered)))
