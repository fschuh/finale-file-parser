"""Authored source shapes distinguish stale references from malformed music."""

from dataclasses import replace

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, OthersPool, Record, parse_enigma
from finale_file_parser.enigma.hairpins import hairpins_by_staff
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.smart_shapes import stale_smart_shapes
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.ir import ScoreDiagnostic


def _document(
    start: int = 5, end: int = 6, *, part: bool = False, end_edu: int = 1024
) -> EnigmaDocument:
    attrs = ' part="9"' if part else ""
    raw = f'''<finale version="18.0" xmlns="http://www.makemusic.com/2012/finale">
      <others>
        <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
        <smartShape cmper="7"><shapeType>cresc</shapeType>
          <startTermSeg><endPt><inst>1</inst><meas>{start}</meas><edu>0</edu></endPt></startTermSeg>
          <endTermSeg><endPt><inst>1</inst><meas>{end}</meas><edu>{end_edu}</edu></endPt></endTermSeg>
        </smartShape>
        <smartShapeMeasMark cmper="{start}"{attrs}><shapeNum>7</shapeNum></smartShapeMeasMark>
      </others>
    </finale>'''
    return parse_enigma(raw.encode())


def test_wholly_out_of_score_shapes_have_structured_diagnostics_and_raw_records() -> None:
    doc = _document()
    before = doc.others.records
    ignored, diagnostics = stale_smart_shapes(doc, [1, 2])
    assert ignored == frozenset({7})
    assert diagnostics == (
        ScoreDiagnostic(
            "stale-shape",
            "Assigned shape 7 refers wholly beyond the score "
            "(bars 5–6; last bar 2). Its source record is retained.",
            "smartShape:7",
        ),
    )
    assert hairpins_by_staff(doc, ignored_shapes=ignored) == {}
    assert doc.others.records == before
    assert build_score(doc).diagnostics[0].code == "stale-shape"


@pytest.mark.parametrize("start,end", [(1, 2), (2, 5), (5, 2), (6, 5)])
def test_in_score_partial_and_reversed_spans_are_not_quarantined(start: int, end: int) -> None:
    assert stale_smart_shapes(_document(start, end), [1, 2]) == (frozenset(), ())


def test_linked_part_only_and_unassigned_shapes_are_not_visible_score_diagnostics() -> None:
    assert stale_smart_shapes(_document(part=True), [1]) == (frozenset(), ())
    doc = _document()
    doc.others = OthersPool(tuple(r for r in doc.others.records if r.tag != "smartShapeMeasMark"))
    assert stale_smart_shapes(doc, [1]) == (frozenset(), ())


def test_a_zero_length_hairpin_is_not_hidden_by_quarantine() -> None:
    doc = _document(5, 5, end_edu=0)
    assert stale_smart_shapes(doc, [1]) == (frozenset(), ())
    with pytest.raises(CorruptScoreError, match="end must follow"):
        hairpins_by_staff(doc)


def test_invalid_endpoint_data_is_not_hidden_by_out_of_score_quarantine() -> None:
    doc = _document()
    shape = doc.others.get("smartShape", 7)
    assert shape is not None
    segment = shape.fields["startTermSeg"]
    assert isinstance(segment, Record)
    point = segment.fields["endPt"]
    assert isinstance(point, Record)
    bad_point = replace(point, fields={**point.fields, "edu": "-1"})
    bad_segment = replace(segment, fields={**segment.fields, "endPt": bad_point})
    bad_shape = replace(shape, fields={**shape.fields, "startTermSeg": bad_segment})
    doc.others = OthersPool(tuple(bad_shape if r is shape else r for r in doc.others.records))
    assert stale_smart_shapes(doc, [1]) == (frozenset(), ())
    with pytest.raises(CorruptScoreError, match="invalid startTermSeg position"):
        hairpins_by_staff(doc)
