"""Authored entry-attached dynamics are font-gated timed directions."""

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _xml(
    *, font: str = "Maestro", hidden: bool = False, shape: bool = False, variant: bool = False
) -> bytes:
    raw = f"""<finale><others><fontName cmper="7"><name>{font}</name></fontName>
      <articDef cmper="1"><charMain>80</charMain><fontMain>7</fontMain>
        {"<mainIsShape/>" if shape else ""}</articDef>
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry>
        <startTime>128</startTime></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <articAssign entnum="1" {'part="1"' if variant else ""}><articDef>1</articDef>
        {"<hide/>" if hidden else ""}</articAssign>
    </details><entries><entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
      <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
      <note><harmLev>2</harmLev><harmAlt>0</harmAlt></note></entry></entries></finale>"""
    return to_musicxml(build_score(parse_enigma(raw.encode())))


def test_music_font_mp_on_a_chord_is_one_dynamic_at_the_source_frame_offset() -> None:
    root = DET.fromstring(_xml())
    assert len(root.findall(".//dynamics/mp")) == 1 and len(root.findall(".//pitch")) == 2
    direction = next(d for d in root.findall(".//direction") if d.find(".//mp") is not None)
    assert direction.findtext("offset") == "1"
    assert direction.find("sound") is None
    assert root.find(".//articulations/mp") is None


@pytest.mark.parametrize(
    "font,hidden,shape,variant",
    [
        ("Times New Roman", False, False, False),
        ("Unestablished Music Font", False, False, False),
        ("Maestro", True, False, False),
        ("Maestro", False, True, False),
        ("Maestro", False, False, True),
    ],
)
def test_a_letter_shape_or_non_score_assignment_is_not_guessed_as_a_dynamic(
    font: str, hidden: bool, shape: bool, variant: bool
) -> None:
    assert (
        DET.fromstring(_xml(font=font, hidden=hidden, shape=shape, variant=variant)).find(".//mp")
        is None
    )
