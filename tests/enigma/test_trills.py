"""Authored font-gated trills retain chord structure and altered-key neighbors."""

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _score(
    *,
    key: int = 0,
    level: int = 0,
    second: int | None = None,
    font: str = "Maestro",
    assignment: str = "",
    hidden: bool = False,
) -> bytes:
    notes = f"<note><harmLev>{level}</harmLev><harmAlt>0</harmAlt></note>"
    if second is not None:
        notes += f"<note><harmLev>{second}</harmLev><harmAlt>0</harmAlt></note>"
    raw = f"""<finale><others>
      <fontName cmper="7"><name>{font}</name></fontName>
      <articDef cmper="1"><charMain>217</charMain><fontMain>7</fontMain></articDef>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat>
        <keySig><key>{key}</key></keySig></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details>
      <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <articAssign entnum="1" {assignment}>{"<hide/>" if hidden else ""}
        <articDef>1</articDef></articAssign>
    </details><entries>
      <entry entnum="1" prev="0" next="0"><dura>4096</dura>
        <numNotes>{1 if second is None else 2}</numNotes>{notes}</entry>
    </entries></finale>"""
    return to_musicxml(build_score(parse_enigma(raw.encode())))


@pytest.mark.parametrize("key,level,step", [(0, 0, "whole"), (0, 6, "half"), (257, 1, "half")])
def test_trills_preserve_the_main_pitch_and_resolve_the_written_key_neighbor(
    key: int, level: int, step: str
) -> None:
    root = DET.fromstring(_score(key=key, level=level))
    mark = root.find(".//trill-mark")
    assert mark is not None and mark.get("trill-step") == step and mark.get("start-note") == "main"
    assert len(root.findall(".//note")) == 1 and root.findtext(".//note/duration") == "4"


@pytest.mark.parametrize("first,second,index,step", [(0, 6, 1, "half"), (6, 0, 0, "half")])
def test_a_chord_trills_only_the_upper_pitch_independently_of_chord_order(
    first: int, second: int, index: int, step: str
) -> None:
    root = DET.fromstring(_score(level=first, second=second))
    assert len(root.findall(".//trill-mark")) == 1 and len(root.findall(".//pitch")) == 2
    assert root.find(".//note/chord") is not None
    mark = root.findall(".//note")[index].find("notations/ornaments/trill-mark")
    assert mark is not None and mark.get("trill-step") == step


def test_unknown_or_text_font_character_is_not_guessed_as_a_trill() -> None:
    assert DET.fromstring(_score(font="Times New Roman")).find(".//trill-mark") is None
    assert DET.fromstring(_score(font="Unestablished Music Font")).find(".//trill-mark") is None


def test_linked_part_assignment_does_not_add_an_extra_score_trill() -> None:
    assert DET.fromstring(_score(assignment='part="1"')).find(".//trill-mark") is None


def test_hidden_assignment_does_not_add_a_trill() -> None:
    assert DET.fromstring(_score(hidden=True)).find(".//trill-mark") is None
