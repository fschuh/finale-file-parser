"""Independently authored binary definitions and packed entry assignments."""

from __future__ import annotations

from fractions import Fraction

import pytest

from finale_file_parser.enigma import mus_document as adapter
from finale_file_parser.enigma.document import EnigmaDocument, Record
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import TAG_SMART_SHAPE_ENTRY_MARK, MusDetailRecord
from finale_file_parser.enigma.mus_others import TAG_SMART_SHAPE, MusOther
from finale_file_parser.enigma.slurs import slurs_by_staff
from finale_file_parser.ir import Slur, SlurEndpoint


def _payload(*, kind: int = 15, note_id: int = 0) -> bytes:
    result = bytearray(96)
    result[:2] = kind.to_bytes(2, "little", signed=True)
    result[2:6] = (0x60008210).to_bytes(4, "little")
    for at, measure, entry in ((6, 1, 1), (36, 2, 5)):
        result[at : at + 2] = (1).to_bytes(2, "little", signed=True)
        result[at + 2 : at + 4] = measure.to_bytes(2, "little", signed=True)
        result[at + 4 : at + 8] = entry.to_bytes(4, "little", signed=True)
    result[76:78] = note_id.to_bytes(2, "little", signed=True)
    return bytes(result)


def _slot(shape: int) -> bytes:
    return shape.to_bytes(2, "little") + bytes(8)


def _read(
    monkeypatch: pytest.MonkeyPatch,
    others: tuple[MusOther, ...] = (),
    details: tuple[MusDetailRecord, ...] = (),
) -> EnigmaDocument:
    entries = tuple(
        Record("entry", {"entnum": str(entry), "prev": "0", "next": "0"}, "", {"numNotes": "1"})
        for entry in (1, 5)
    )
    monkeypatch.setattr(adapter, "read_mus_others", lambda _: others)
    monkeypatch.setattr(adapter, "read_mus_details", lambda _: details)
    monkeypatch.setattr(adapter, "read_mus_entry_records", lambda _: entries)
    monkeypatch.setattr(adapter, "_texts_records", lambda _: [])
    monkeypatch.setattr(adapter, "_banner_year", lambda _: 2012)
    monkeypatch.setattr(adapter, "_banner_platform", lambda _: "WIN")
    return adapter.read_mus_document("unused.mus")


_POSITIONS = {(1, 1, 1): (SlurEndpoint(1, 1, 0),), (1, 2, 5): (SlurEndpoint(2, 1, 1),)}


@pytest.mark.parametrize(("kind", "placement"), [(0, "below"), (1, "above"), (15, None)])
def test_binary_entry_slurs_reach_the_shared_resolver(
    monkeypatch: pytest.MonkeyPatch, kind: int, placement: str | None
) -> None:
    document = _read(
        monkeypatch,
        (MusOther(TAG_SMART_SHAPE, 7, 0, _payload(kind=kind)),),
        (MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 0, 1, 0, _slot(7)),),
    )
    assert slurs_by_staff(document, _POSITIONS) == {
        1: (Slur(SlurEndpoint(1, 1, 0), SlurEndpoint(2, 1, 1), placement),)
    }


def test_packed_marks_keep_every_incidence_and_the_full_entry_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _read(
        monkeypatch,
        details=(
            MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 1, 2, 0, _slot(7) + _slot(8)),
            MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 1, 2, 9, _slot(10)),
        ),
    )
    assert [
        (record.attrs, record.fields) for record in document.details.of_tag("smartShapeEntryMark")
    ] == [
        ({"entnum": "65538", "inci": "0", "sourceInci": "0"}, {"shapeNum": "7"}),
        ({"entnum": "65538", "inci": "1", "sourceInci": "0"}, {"shapeNum": "8"}),
        ({"entnum": "65538", "inci": "0", "sourceInci": "9", "part": "9"}, {"shapeNum": "10"}),
    ]


@pytest.mark.parametrize("size", [0, 1, 9, 11, 19, 21])
def test_partial_entry_assignment_slots_fail_clearly(
    monkeypatch: pytest.MonkeyPatch, size: int
) -> None:
    with pytest.raises(CorruptScoreError, match="expected complete 10-byte slots"):
        _read(
            monkeypatch,
            details=(MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 0, 1, 0, bytes(size)),),
        )


def test_chord_note_ids_survive_normalization_without_inventing_an_entry_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _read(
        monkeypatch,
        (MusOther(TAG_SMART_SHAPE, 7, 0, _payload(note_id=2)),),
        (MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 0, 1, 0, _slot(7)),),
    )
    shape = document.others.get("smartShape", 7)
    assert shape is not None and shape.fields["startNoteID"] == "2"
    assert slurs_by_staff(document, _POSITIONS) == {}


@pytest.mark.parametrize("active", [False, True])
def test_same_entry_graphical_curves_need_active_distinct_drawing_endpoints(
    monkeypatch: pytest.MonkeyPatch, active: bool
) -> None:
    payload = bytearray(_payload())
    payload[38:40] = (1).to_bytes(2, "little")
    payload[40:44] = (1).to_bytes(4, "little")
    for base, x, y in ((6, -96, 24), (36, 0, 12)):
        payload[base + 8 : base + 10] = x.to_bytes(2, "little", signed=True)
        payload[base + 10 : base + 12] = y.to_bytes(2, "little", signed=True)
        payload[base + 12 : base + 14] = (0x4000 if active else 0).to_bytes(2, "little")
    doc = _read(
        monkeypatch,
        (MusOther(TAG_SMART_SHAPE, 7, 0, bytes(payload)),),
        (MusDetailRecord(TAG_SMART_SHAPE_ENTRY_MARK, 0, 1, 0, _slot(7)),),
    )
    if not active:
        with pytest.raises(CorruptScoreError, match="end must follow"):
            slurs_by_staff(doc, _POSITIONS)
    else:
        endpoint = SlurEndpoint(1, 1, 0)
        assert slurs_by_staff(doc, _POSITIONS) == {
            1: (
                Slur(
                    endpoint,
                    endpoint,
                    None,
                    True,
                    Fraction(-4),
                    Fraction(1),
                    Fraction(0),
                    Fraction(1, 2),
                ),
            )
        }
