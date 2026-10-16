"""Printed time signatures, abbreviations and split bars; fixtures authored for this project."""

from __future__ import annotations

import struct

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.mus_document import _meas_spec, _options_records, _others_records
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _document(specs: str, options: str = "") -> EnigmaDocument:
    entries = "".join(
        f'<entry entnum="{n}" prev="{n - 1}" next="{n + 1 if n < 3 else 0}"><dura>1024</dura>'
        '<numNotes>1</numNotes><note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>'
        for n in (1, 2, 3)
    )
    return parse_enigma(
        f"""<finale><options>{options}</options><others>
      <staffSpec cmper="1"/>{specs}
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>3</endEntry></frameSpec>
    </others><details>
      <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <gfhold cmper1="1" cmper2="2"><frame1>2</frame1></gfhold>
    </details><entries>{entries}</entries></finale>""".encode()
    )


def _times(document: EnigmaDocument) -> list[tuple[str, str | None, str | None, str | None]]:
    root = ET.fromstring(to_musicxml(build_score(document)))
    return [
        (m.get("number", ""), t.get("symbol"), t.findtext("beats"), t.findtext("beat-type"))
        for m in root.iter("measure")
        for t in m.iter("time")
    ]


def _spec(cmper: int, beats: int, divbeat: int, extra: str = "") -> str:
    return (
        f'<measSpec cmper="{cmper}"><beats>{beats}</beats><divbeat>{divbeat}</divbeat>'
        f"{extra}</measSpec>"
    )


def test_a_pickup_held_as_one_beat_prints_its_display_signature_once() -> None:
    shown = "<dispBeats>4</dispBeats><dispDivbeat>1024</dispDivbeat><useDisplayTimesig/>"
    doc = _document(_spec(1, 1, 1024, shown) + _spec(2, 2, 1024, shown))
    # Measure 2 holds 2/4 but shows 4/4, the same as measure 1: nothing new prints.
    assert _times(doc) == [("1", None, "4", "4")]


def test_a_display_signature_abbreviates_by_its_own_flag() -> None:
    shown = "<dispBeats>2</dispBeats><dispDivbeat>2048</dispDivbeat><useDisplayTimesig/>"
    doc = _document(_spec(1, 4, 1024, shown + "<abbrvTime/>") + _spec(2, 4, 1024, shown))
    assert _times(doc) == [("1", "cut", "2", "2"), ("2", None, "2", "2")]


@pytest.mark.parametrize(
    "options,expected",
    [
        ("<timeSigDoAbrvCommon/>", "common"),
        ("<timeSigDoAbrvCut/>", None),
        ("", None),
    ],
)
def test_document_options_abbreviate_plain_common_time(options: str, expected: str) -> None:
    doc = _document(
        _spec(1, 4, 1024) + _spec(2, 4, 1024),
        f"<timeSignatureOptions>{options}</timeSignatureOptions>",
    )
    assert _times(doc) == [("1", expected, "4", "4")]


def test_a_display_signature_ignores_the_document_abbreviation() -> None:
    shown = "<dispBeats>2</dispBeats><dispDivbeat>2048</dispDivbeat><useDisplayTimesig/>"
    doc = _document(
        _spec(1, 2, 2048, shown) + _spec(2, 2, 2048, shown),
        "<timeSignatureOptions><timeSigDoAbrvCut/></timeSignatureOptions>",
    )
    assert _times(doc) == [("1", None, "2", "2")]


def test_mus_meas_spec_decodes_the_display_signature_and_its_flags() -> None:
    payload = struct.pack("<9H", 400, 0, 1, 1024, 6, 0x5010, 4, 1024, 0xF6) + bytes(8)
    fields = _meas_spec(payload)
    assert fields["beats"] == "1" and fields["dispBeats"] == "4"
    assert fields["dispDivbeat"] == "1024"
    assert "useDisplayTimesig" in fields and "abbrvTime" in fields
    plain = _meas_spec(struct.pack("<9H", 400, 0, 4, 1024, 6, 0x1000, 4, 1024, 0xF0) + bytes(8))
    assert "useDisplayTimesig" not in plain and "abbrvTime" not in plain


def test_mus_barline_nibble_zero_is_an_invisible_barline() -> None:
    fields = _meas_spec(struct.pack("<9H", 300, 0, 3, 1024, 6, 0x0100, 4, 1024, 0xF0) + bytes(8))
    assert fields["barline"] == "none"


def test_mus_time_signature_options_read_both_abbreviations() -> None:
    record = MusOther(33, 65534, 0, bytes.fromhex("180000000100000063004300"))
    (option,) = [r for r in _options_records((record,), 2012) if r.tag == "timeSignatureOptions"]
    assert option.fields == {"timeSigDoAbrvCommon": ""}


def test_mus_legacy_number_region_reads_its_scalars() -> None:
    payload = bytearray(204)
    struct.pack_into("<HHHHh", payload, 132, 2, 1000, 0x30, 10, 0)
    (record,) = _others_records((MusOther(164, 1, 0, bytes(payload)),), "cp1252")
    assert record.tag == "measNumbRegion"
    assert (record.fields["startMeas"], record.fields["endMeas"]) == ("2", "1000")
    assert (record.fields["base"], record.fields["offset"]) == ("10", "0")
