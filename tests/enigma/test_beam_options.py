"""Original rest rhythms and scalar preference fixtures; authored here, MIT."""

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.beam_options import rest_beams
from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.mus_document import _beam_options, _options_records
from finale_file_parser.enigma.mus_others import OPTIONS_CMPER, TAG_BEAM_OPTIONS, MusOther
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


@pytest.mark.parametrize("order", ["little", "big"])
@pytest.mark.parametrize("size", [12, 36])
def test_evidenced_preference_word_keeps_separate_flags(order: ByteOrder, size: int) -> None:
    raw = bytearray(size)
    raw[2:4] = (0x143).to_bytes(2, order)
    record = _beam_options(bytes(raw), order)
    assert record is not None
    assert record.fields == {
        "incEdgeRestsInBeamGroups": "",
        "incRestsInClassicBeams": "",
        "doStemStubs": "",
        "extendSecBeamsOverRests": "",
    }
    disabled = _beam_options(bytes(size), order)
    assert disabled is not None and disabled.fields == {}


@pytest.mark.parametrize("size", [0, 2, 11, 13, 24, 37])
def test_unsupported_preference_layout_does_not_invent_rest_beam_settings(size: int) -> None:
    assert _beam_options(bytes(size)) is None


def test_linked_part_or_other_comparator_does_not_set_score_beaming() -> None:
    raw = b"\x00\x00\x01\x01" + bytes(8)
    assert not _options_records((MusOther(TAG_BEAM_OPTIONS, OPTIONS_CMPER, 1, raw),), None)
    assert not _options_records((MusOther(TAG_BEAM_OPTIONS, 1, 0, raw),), None)
    records = _options_records((MusOther(TAG_BEAM_OPTIONS, OPTIONS_CMPER, 0, raw),), None)
    assert len(records) == 1 and records[0].tag == "beamOptions"


@pytest.mark.parametrize(
    "options,connected", [("", False), ("<beamOptions/>", True), ('<beamOptions part="1"/>', False)]
)
def test_source_settings_and_boundaries_recover_beams_without_changing_rest_time(
    options: str, connected: bool
) -> None:
    doc = parse_enigma(
        f"""<finale><options>{options}</options><others>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>3</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="2"><dura>512</dura><beam/><numNotes>1</numNotes>
      <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="2" prev="1" next="3"><dura>512</dura><numNotes>0</numNotes></entry>
      <entry entnum="3" prev="2" next="0"><dura>512</dura><numNotes>1</numNotes>
      <note><harmLev>1</harmLev><harmAlt>0</harmAlt></note></entry></entries></finale>""".encode()
    )
    assert (rest_beams(doc) is not None) == connected
    root = ET.fromstring(to_musicxml(build_score(doc)))
    notes = root.findall(".//note")
    assert [n.findtext("duration") for n in notes] == ["1"] * 3
    assert notes[1].find("rest") is not None
    assert [n.findtext("beam") for n in notes] == (
        ["begin", "continue", "end"] if connected else [None] * 3
    )
