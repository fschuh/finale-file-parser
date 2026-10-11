"""Independently authored binary records exercise the smart-shape adapter."""

from __future__ import annotations

from fractions import Fraction

import pytest

from finale_file_parser.enigma import mus_document as adapter
from finale_file_parser.enigma.document import EnigmaDocument, Record
from finale_file_parser.enigma.hairpins import hairpins_by_staff
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_others import (
    TAG_SMART_SHAPE,
    TAG_SMART_SHAPE_MEAS_MARK,
    MusOther,
)
from finale_file_parser.ir import Hairpin


def _payload(*, kind: int = 3, flags: int = 0x8600, flag2: int = 0) -> bytes:
    result = bytearray(96)
    result[0:2] = kind.to_bytes(2, "little", signed=True)
    result[2:6] = flags.to_bytes(4, "little")
    for offset, measure, edu in ((6, 1, 512), (36, 2, 3584)):
        result[offset : offset + 2] = (1).to_bytes(2, "little", signed=True)
        result[offset + 2 : offset + 4] = measure.to_bytes(2, "little", signed=True)
        result[offset + 4 : offset + 8] = edu.to_bytes(4, "little", signed=True)
    result[82:84] = flag2.to_bytes(2, "little")
    return bytes(result)


def _slot(shape: int, center: int = 0) -> bytes:
    return shape.to_bytes(2, "little") + center.to_bytes(2, "little") + bytes(8)


def _read(monkeypatch: pytest.MonkeyPatch, *records: MusOther) -> EnigmaDocument:
    monkeypatch.setattr(adapter, "read_mus_others", lambda _: records)
    monkeypatch.setattr(adapter, "read_mus_details", lambda _: ())
    monkeypatch.setattr(adapter, "read_mus_entry_records", lambda _: ())
    monkeypatch.setattr(adapter, "_texts_records", lambda _: [])
    monkeypatch.setattr(adapter, "_banner_year", lambda _: 2012)
    monkeypatch.setattr(adapter, "_banner_platform", lambda _: "WIN")
    return adapter.read_mus_document("unused.mus")


@pytest.mark.parametrize(("source", "kind"), [(2, "diminuendo"), (3, "crescendo")])
def test_binary_hairpins_reach_the_shared_resolver(
    monkeypatch: pytest.MonkeyPatch, source: int, kind: str
) -> None:
    document = _read(
        monkeypatch,
        MusOther(TAG_SMART_SHAPE, 7, 0, _payload(kind=source)),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, _slot(7)),
    )
    assert hairpins_by_staff(document) == {
        1: (Hairpin(kind, 1, Fraction(1, 8), 2, Fraction(7, 8)),)
    }


def test_packed_marks_preserve_incidence_center_and_linked_part_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _read(
        monkeypatch,
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, _slot(7, 9) + _slot(8)),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 1, _slot(7)),
    )
    marks = document.others.of_tag("smartShapeMeasMark")
    assert [(mark.attrs, mark.fields) for mark in marks] == [
        ({"cmper": "1", "inci": "0"}, {"shapeNum": "7", "centerShapeNum": "9"}),
        ({"cmper": "1", "inci": "1"}, {"shapeNum": "8", "centerShapeNum": "0"}),
        ({"cmper": "1", "inci": "0", "part": "1"}, {"shapeNum": "7", "centerShapeNum": "0"}),
    ]


@pytest.mark.parametrize(
    ("flags", "flag2", "field"),
    [
        (0x8600, 1, "hidden"),
        (0x0600, 0, "noPresetShape"),
        (0x40008600, 0, "entryBased"),
        (0x10008600, 0, "lyricBased"),
    ],
)
def test_binary_visibility_and_attachment_modes_are_preserved_and_filtered(
    monkeypatch: pytest.MonkeyPatch, flags: int, flag2: int, field: str
) -> None:
    document = _read(
        monkeypatch,
        MusOther(TAG_SMART_SHAPE, 7, 0, _payload(flags=flags, flag2=flag2)),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, _slot(7)),
    )
    record = document.others.get("smartShape", 7)
    assert record is not None and field in record.fields
    assert hairpins_by_staff(document) == {}
    if field == "entryBased":
        segment = record.fields["startTermSeg"]
        assert isinstance(segment, Record)
        point = segment.fields["endPt"]
        assert isinstance(point, Record)
        assert point.fields["entryNum"] == "512" and "edu" not in point.fields


def test_linked_shapes_do_not_duplicate_and_other_visibility_bits_do_not_hide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _read(
        monkeypatch,
        MusOther(TAG_SMART_SHAPE, 7, 0, _payload(flag2=2)),
        MusOther(TAG_SMART_SHAPE, 7, 1, _payload()),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, _slot(7)),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 2, 0, _slot(7)),
    )
    assert len(document.others.of_tag("smartShape")) == 2
    assert len(hairpins_by_staff(document)[1]) == 1


@pytest.mark.parametrize("size", [0, 1, 6, 83, 92, 95, 97, 192])
def test_truncated_or_unrecognized_shape_layouts_fail_clearly(
    monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    with pytest.raises(CorruptScoreError, match="smartShape 7: expected 96 bytes"):
        _read(monkeypatch, MusOther(TAG_SMART_SHAPE, 7, 0, bytes(size)))


@pytest.mark.parametrize("size", [0, 1, 11, 13, 23, 25])
def test_partial_assignment_slots_are_rejected(monkeypatch: pytest.MonkeyPatch, size: int) -> None:
    with pytest.raises(CorruptScoreError, match="expected complete 12-byte slots"):
        _read(monkeypatch, MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, bytes(size)))


def test_signed_invalid_edu_is_not_reinterpreted_as_a_large_positive_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = bytearray(_payload())
    payload[10:14] = (-1).to_bytes(4, "little", signed=True)
    document = _read(
        monkeypatch,
        MusOther(TAG_SMART_SHAPE, 7, 0, bytes(payload)),
        MusOther(TAG_SMART_SHAPE_MEAS_MARK, 1, 0, _slot(7)),
    )
    with pytest.raises(CorruptScoreError, match="invalid startTermSeg position"):
        hairpins_by_staff(document)
