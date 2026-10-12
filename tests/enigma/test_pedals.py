"""Authored explicit pedal signs retain exact frame-aware time and font context."""

from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Score


def _score(
    *,
    font: str = "Maestro",
    repedal: bool = False,
    hidden: bool = False,
    part_variant: bool = False,
) -> Score:
    extra = (
        '<articAssign entnum="2" inci="1"><articDef>1</articDef></articAssign>' if repedal else ""
    )
    raw = f"""<finale><others><fontName cmper="7"><name>{font}</name></fontName>
      <articDef cmper="1"><charMain>161</charMain><fontMain>7</fontMain></articDef>
      <articDef cmper="2"><charMain>42</charMain><fontMain>7</fontMain></articDef>
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>2</endEntry>
        <startTime>128</startTime></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <articAssign entnum="1" {'part="1"' if part_variant else ""}>
        <articDef>1</articDef>{"<hide/>" if hidden else ""}</articAssign>
      <articAssign entnum="2"><articDef>2</articDef></articAssign>{extra}
    </details><entries>
      <entry entnum="1" prev="0" next="2"><dura>1024</dura><numNotes>2</numNotes>
        <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
        <note><harmLev>2</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="2" prev="1" next="0"><dura>1024</dura><numNotes>1</numNotes>
        <note><harmLev>1</harmLev><harmAlt>0</harmAlt></note></entry>
    </entries></finale>"""
    return build_score(parse_enigma(raw.encode()))


def test_pedal_signs_are_timed_directions_not_duplicate_chord_articulations() -> None:
    score = _score()
    marks = score.parts[0].measures[0].pedals
    assert [(m.kind, m.offset) for m in marks] == [
        ("start", Fraction(1, 32)),
        ("stop", Fraction(9, 32)),
    ]
    root = DET.fromstring(to_musicxml(score))
    directions = [
        d for d in root.findall(".//direction") if d.find("direction-type/pedal") is not None
    ]
    assert [d.findtext("offset") for d in directions] == ["1", "9"]
    sounds = [d.find("sound") for d in directions]
    assert all(s is not None for s in sounds)
    assert [s.get("damper-pedal") for s in sounds if s is not None] == ["yes", "no"]
    assert len(root.findall(".//pedal")) == 2 and len(root.findall(".//pitch")) == 3
    assert all(p.get("sign") == "yes" and p.get("line") == "no" for p in root.findall(".//pedal"))


def test_release_and_reapply_at_one_offset_is_an_explicit_pedal_change() -> None:
    score = _score(repedal=True)
    assert score.parts[0].measures[0].pedals[1].kind == "change"
    assert [m.get("type") for m in DET.fromstring(to_musicxml(score)).findall(".//pedal")] == [
        "start",
        "change",
    ]


@pytest.mark.parametrize("font", ["Times New Roman", "Unestablished Music Font"])
def test_an_ordinary_asterisk_does_not_become_a_pedal_release(font: str) -> None:
    assert not _score(font=font).parts[0].measures[0].pedals


@pytest.mark.parametrize("hidden,variant", [(True, False), (False, True)])
def test_hidden_or_linked_part_start_does_not_become_a_visible_score_sign(
    hidden: bool, variant: bool
) -> None:
    assert [
        m.kind for m in _score(hidden=hidden, part_variant=variant).parts[0].measures[0].pedals
    ] == ["stop"]
