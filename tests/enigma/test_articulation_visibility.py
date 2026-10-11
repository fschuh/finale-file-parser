"""Authored music verifies visibility across the articulation-derived symbols."""

from __future__ import annotations

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


@pytest.mark.parametrize(
    ("character", "symbol"),
    [
        (46, "staccato"),
        (62, "accent"),
        (49, "fingering"),
        (85, "fermata"),
        (117, "fermata"),
        (109, "inverted-mordent"),
        (103, "arpeggiate"),
    ],
)
@pytest.mark.parametrize("visibility", ["visible", "hidden", "linked-part"])
def test_only_visible_score_assignments_print_their_symbols(
    character: int, symbol: str, visibility: str
) -> None:
    """Each symbol is assigned to one C quarter; no external score is a fixture."""
    attributes = ' part="1"' if visibility == "linked-part" else ""
    flags = "<hide/>" if visibility == "hidden" else ""
    document = parse_enigma(
        f"""<finale>
          <others>
            <articDef cmper="1"><charMain>{character}</charMain></articDef>
            <staffSpec cmper="1"/>
            <measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
            <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
          </others>
          <details>
            <articAssign entnum="1"{attributes}><articDef>1</articDef>{flags}</articAssign>
            <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
          </details>
          <entries>
            <entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>1</numNotes>
              <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
            </entry>
          </entries>
        </finale>""".encode()
    )
    root = DET.fromstring(to_musicxml(build_score(document)))
    assert len(root.findall(f".//{symbol}")) == (1 if visibility == "visible" else 0)
    (note,) = root.findall(".//note")
    assert (note.findtext("pitch/step"), note.findtext("duration")) == ("C", "1")
