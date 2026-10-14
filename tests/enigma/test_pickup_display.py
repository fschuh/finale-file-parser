"""Original C/D pickup and numbering fixtures, authored here under MIT."""

from dataclasses import replace
from fractions import Fraction as Q

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.measure_numbers import measure_labels
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _meas_spec, _others_records
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Expression, Hairpin


def _document(numbering: str = "") -> bytes:
    return f"""<finale><others>
      <instUsed cmper="0" inci="0"><inst>1</inst></instUsed>
      <instUsed cmper="0" inci="1"><inst>2</inst></instUsed>
      <staffSpec cmper="1"/><staffSpec cmper="2"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <measSpec cmper="2"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1" inci="0"><startTime>3072</startTime></frameSpec>
      <frameSpec cmper="1" inci="1"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>
      {numbering}
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="2"><dura>512</dura><numNotes>1</numNotes>
      <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="2" prev="1" next="0"><dura>512</dura><numNotes>1</numNotes>
      <note><harmLev>1</harmLev><harmAlt>0</harmAlt></note></entry></entries></finale>""".encode()


def _region(fields: str = "", attrs: str = "") -> str:
    return f"""<measNumbRegion cmper="1" {attrs}><startMeas>2</startMeas><endMeas>1000</endMeas>
    <startChar>48</startChar><base>10</base><offset>0</offset><countFromOne/>{fields}</measNumbRegion>"""


def test_pickup_spacer_and_default_rest_keep_source_clock_but_print_short_bar() -> None:
    score = build_score(parse_enigma(_document(_region())))
    top, bass = score.parts
    assert top.measures[0].leading_spacer == bass.measures[0].leading_spacer == Q(3, 4)
    assert top.measures[0].voices[0].start_offset == Q(3, 4)
    assert bass.measures[0].voices[0].events[0].duration == 1
    assert [m.display_number for m in top.measures] == ["", "1"]
    root = ET.fromstring(to_musicxml(score))
    measures = root.findall("part/measure")
    assert [m.get("number") for m in measures] == ["0", "1", "0", "1"]
    assert [m.get("id") for m in measures] == [
        "source-measure-0-1",
        "source-measure-0-2",
        "source-measure-1-1",
        "source-measure-1-2",
    ]
    assert measures[0].get("implicit") == "yes"
    assert measures[0].find("forward") is None
    assert [n.findtext("duration") for n in measures[0].findall("note")] == ["1", "1"]
    assert measures[2].findtext("note/duration") == "1"
    assert measures[2].find("note/rest[@measure='yes']") is not None
    assert top.measures[0].voices[0].start_offset == Q(3, 4)  # immutable source


def test_pickup_controls_and_spans_use_the_same_clock_translation() -> None:
    score = build_score(parse_enigma(_document()))
    top = score.parts[0]
    measure = replace(
        top.measures[0],
        expressions=(
            Expression("initial", "", offset=Q(0)),
            Expression("later", "", offset=Q(7, 8)),
        ),
    )
    top = replace(
        top,
        measures=(measure, top.measures[1]),
        hairpins=(Hairpin("crescendo", 1, Q(3, 4), 1, Q(1)),),
    )
    root = ET.fromstring(to_musicxml(replace(score, parts=(top, score.parts[1]))))
    first = root.find("part/measure")
    assert first is not None
    assert [
        d.findtext("offset")
        for d in first.findall("direction")
        if d.find("direction-type/words") is not None
    ] == [None, "1"]
    assert [
        d.findtext("offset")
        for d in first.findall("direction")
        if d.find("direction-type/wedge") is not None
    ] == ["0", "2"]


def test_offset_inside_spacer_is_reported_instead_of_clamped() -> None:
    score = build_score(parse_enigma(_document()))
    top = score.parts[0]
    measure = replace(top.measures[0], expressions=(Expression("unsupported", "", offset=Q(1, 4)),))
    with pytest.raises(ExportError, match="inside.*spacer"):
        to_musicxml(replace(score, parts=(replace(top, measures=(measure,)), score.parts[1])))


def test_unproved_number_style_and_linked_parts_do_not_change_labels() -> None:
    doc = parse_enigma(_document(_region("<prefix>A</prefix>")))
    labels, diags = measure_labels(doc, [1, 2, 3])
    assert labels == {1: ""} and diags[0].code == "measure-numbering"
    assert measure_labels(parse_enigma(_document(_region(attrs='part="1"'))), [1, 2]) == ({}, ())


def test_excluded_measure_does_not_advance_a_source_region() -> None:
    doc = parse_enigma(
        _document(_region()).replace(b"<beats>4</beats>", b"<noMeasNum/><beats>4</beats>")
    )
    assert measure_labels(doc, [1, 2, 3])[0] == {1: "", 2: "", 3: "1"}


def test_numeric_unicode_region_and_include_numbering_bit() -> None:
    payload = bytearray(360)
    for at, value in ((140, 2), (142, 1000), (144, 48), (148, 10), (150, 0), (344, 0x82)):
        payload[at : at + 2] = value.to_bytes(2, "little")
    record = _others_records((MusOther(164, 1, 0, bytes(payload)),), "")[0]
    assert record.tag == "measNumbRegion" and record.fields["offset"] == "0"
    assert record.fields["startMeas"] == "2" and record.fields["numberFlags"] == "130"
    assert not any(
        r.tag == "measNumbRegion" for r in _others_records((MusOther(164, 1, 0, bytes(348)),), "")
    )
    raw = bytearray(12)
    raw[10:12] = (0x1000).to_bytes(2, "little")
    assert "noMeasNum" in _meas_spec(bytes(raw))


def test_malformed_number_region_is_a_clear_source_error() -> None:
    with pytest.raises(CorruptScoreError, match="range"):
        measure_labels(
            parse_enigma(_document(_region()).replace(b"<endMeas>1000", b"<endMeas>1")), [1, 2]
        )
