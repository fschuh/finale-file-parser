"""Authored auxiliary signs attach to ornaments, without changing written notes."""

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _score(
    *,
    char: int = 105,
    key: int = 0,
    level: int = 4,
    font: str = "Maestro",
    vertical: int = 75,
    chord: bool = False,
    competing: bool = False,
    hidden: bool = False,
) -> bytes:
    second = "<note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>" if chord else ""
    extra = (
        '<articAssign entnum="1" inci="2"><articDef>1</articDef></articAssign>' if competing else ""
    )
    raw = f"""<finale><others>
      <fontName cmper="7"><name>{font}</name></fontName>
      <articDef cmper="1"><charMain>109</charMain><fontMain>7</fontMain></articDef>
      <articDef cmper="2"><charMain>{char}</charMain><fontMain>7</fontMain></articDef>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat>
        <keySig><key>{key}</key></keySig></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details>
      <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <articAssign entnum="1"><articDef>1</articDef><vertOff>0</vertOff></articAssign>
      <articAssign entnum="1" inci="1"><articDef>2</articDef><vertOff>{vertical}</vertOff>
        {"<hide/>" if hidden else ""}</articAssign>{extra}
    </details><entries><entry entnum="1" prev="0" next="0"><dura>4096</dura>
      <numNotes>{2 if chord else 1}</numNotes>{second}
      <note><harmLev>{level}</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>"""
    return to_musicxml(build_score(parse_enigma(raw.encode())))


@pytest.mark.parametrize(
    "char,key,level,sign,step",
    [
        (105, 0, 4, "flat", "half"),
        (73, 0, 2, "sharp", "whole"),
        (233, 255, 2, "natural", "whole"),
    ],
)
def test_explicit_auxiliary_accidental_overrides_the_key_without_altering_the_main_pitch(
    char: int, key: int, level: int, sign: str, step: str
) -> None:
    root = DET.fromstring(_score(char=char, key=key, level=level))
    assert root.findtext(".//ornaments/accidental-mark") == sign
    mordent = root.find(".//inverted-mordent")
    assert mordent is not None and mordent.get("trill-step") == step
    assert root.find(".//pitch/alter") is None


def test_auxiliary_on_a_chord_uses_the_upper_note_and_does_not_duplicate_the_mark() -> None:
    root = DET.fromstring(_score(chord=True))
    assert len(root.findall(".//accidental-mark")) == 1
    assert root.findall(".//note")[1].find("notations/ornaments/accidental-mark") is not None


@pytest.mark.parametrize(
    "font,vertical,competing,hidden",
    [
        ("Times New Roman", 75, False, False),
        ("Maestro", -12, False, False),
        ("Maestro", 75, True, False),
        ("Maestro", 75, False, True),
    ],
)
def test_ordinary_or_ambiguous_signs_are_not_taken_as_auxiliary_accidentals(
    font: str,
    vertical: int,
    competing: bool,
    hidden: bool,
) -> None:
    root = DET.fromstring(_score(font=font, vertical=vertical, competing=competing, hidden=hidden))
    assert root.find(".//accidental-mark") is None
