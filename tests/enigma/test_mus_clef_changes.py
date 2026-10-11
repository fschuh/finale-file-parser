"""Authored binary and XML clef lists; no third-party score bytes."""

from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.clef import clef_changes_by_measure, clefs_by_measure
from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _clef_enums, _gfhold_clef, _rows_others
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.mus_rows import MusRowRecord, MusRows
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


@pytest.mark.parametrize("order", ["little", "big"])
def test_literal_alto_and_list_reference_are_distinguished(order: ByteOrder) -> None:
    literal = (1).to_bytes(2, order) + bytes(2)
    listed = (1).to_bytes(2, order) + (0x0400).to_bytes(2, order)
    assert _gfhold_clef(literal, order) == {"clefID": "1"}
    assert _gfhold_clef(listed, order) == {"clefListID": "1"}


@pytest.mark.parametrize("order", ["little", "big"])
def test_packed_and_dcl_lists_keep_positions_and_visibility(order: ByteOrder) -> None:
    payload = b"".join(
        n.to_bytes(2, order, signed=True)
        for n in (
            0,
            0,
            0,
            75,
            -2,
            0,
            1,
            768,
            0,
            75,
            -4,
            2,
        )
    )
    enums = _clef_enums(payload, {"cmper": "17"}, order)
    assert [r.fields["xEduPos"] for r in enums] == ["0", "768"]
    assert [r.fields["clefMode"] for r in enums] == ["whenNeeded", "hidden"]
    assert enums[1].fields["xEvpuOffset"] == "-4"
    rows = MusRows(
        others={("CE", 17): MusRowRecord("CE", 17, payload=payload, incidences=2)},
        details={},
        byte_order=order,
    )
    assert _rows_others(rows, {}) == enums


@pytest.mark.parametrize("payload", [b"", bytes(11), bytes(13), bytes(12 * 4097)])
def test_incomplete_or_oversized_clef_lists_are_rejected(payload: bytes) -> None:
    with pytest.raises(CorruptScoreError, match="clefEnum"):
        _clef_enums(payload, {"cmper": "1"})


def _xml(list_body: str, reference: str = "17") -> bytes:
    return f"""<finale><options><clefOptions>
      <clefDef><clefChar>38</clefChar><adjust>-10</adjust></clefDef>
      <clefDef><clefChar>63</clefChar><adjust>2</adjust></clefDef>
    </clefOptions></options><others>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>2</beats><divbeat>1024</divbeat></measSpec>
      <measSpec cmper="2"><beats>2</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="3"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      {list_body}</others><details>
      <gfhold cmper1="1" cmper2="1"><clefListID>{reference}</clefListID><frame1>3</frame1></gfhold>
    </details><entries><entry entnum="1" prev="0" next="0">
      <dura>2048</dura><numNotes>1</numNotes><isValid/><isNote/>
      <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>""".encode()


LIST = """<clefEnum cmper="17" inci="0"><clef>0</clef><xEduPos>0</xEduPos></clefEnum>
  <clefEnum cmper="17" inci="1"><clef>1</clef><xEduPos>768</xEduPos></clefEnum>"""


def test_a_timed_clef_changes_notation_and_carries_into_a_silent_measure() -> None:
    document = parse_enigma(_xml(LIST))
    assert clefs_by_measure(document)[1, 1] == 0
    assert clef_changes_by_measure(document)[1, 1][1].offset == Fraction(3, 16)
    score = build_score(document)
    first, second = score.parts[0].measures
    assert [(c.offset, c.sign, c.line) for c in first.clef_changes] == [
        (Fraction(0), "G", 2),
        (Fraction(3, 16), "F", 4),
    ]
    assert second.clef_sign is None  # already in bass; no redundant change
    root = ET.fromstring(to_musicxml(score))
    first_xml = root.find("part/measure")
    assert first_xml is not None
    cursor = 0
    timed = []
    notes = []
    for node in first_xml:
        if node.tag == "forward":
            cursor += int(node.findtext("duration", "0"))
        elif node.tag == "backup":
            cursor -= int(node.findtext("duration", "0"))
        elif node.tag == "attributes" and node.find("clef") is not None:
            timed.append((cursor, node.findtext("clef/sign")))
        elif node.tag == "note":
            notes.append((cursor, node.findtext("pitch/step")))
    assert timed == [(0, "G"), (3, "F")]
    assert notes == [(0, "C")]


@pytest.mark.parametrize(
    "body",
    ["", LIST.replace("768", "-1"), LIST.replace("768", "0"), LIST.replace("<clef>1", "<clef>7")],
)
def test_invalid_references_and_positions_fail_clearly(body: str) -> None:
    with pytest.raises(CorruptScoreError, match="clef"):
        build_score(parse_enigma(_xml(body)))


def test_multiple_clef_changes_leave_a_sustained_pitch_and_duration_unchanged() -> None:
    body = (
        LIST
        + """<clefEnum cmper="17" inci="2">
      <clef>0</clef><xEduPos>1536</xEduPos></clefEnum>"""
    )
    score = build_score(parse_enigma(_xml(body)))
    first = score.parts[0].measures[0]
    assert [c.offset for c in first.clef_changes] == [Fraction(0), Fraction(3, 16), Fraction(3, 8)]
    root = ET.fromstring(to_musicxml(score))
    note = root.find("part/measure/note")
    assert note is not None and note.findtext("pitch/step") == "C"
    assert note.findtext("duration") == "8"
    assert [c.findtext("sign") for c in root.findall("part/measure/attributes/clef")] == [
        "G",
        "F",
        "G",
    ]
