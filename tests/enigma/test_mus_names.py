"""Independently authored name references and ETF text; no score fixtures."""

from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma import mus_document as adapter
from finale_file_parser.enigma.document import (
    DetailsPool,
    EnigmaDocument,
    EntriesPool,
    OptionsPool,
    OthersPool,
    Pool,
    Record,
    TextsPool,
)
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.mus_rows import MusRowRecord, MusRows
from finale_file_parser.enigma.text import StaffNames, staff_names, text_block
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _staff(full: int, abbreviated: int = 0, order: ByteOrder = "little") -> bytes:
    data = bytearray(36)
    data[30:32] = full.to_bytes(2, order)
    data[32:34] = abbreviated.to_bytes(2, order)
    return bytes(data)


def _block(text: int, tag: int = 2004, order: ByteOrder = "little") -> bytes:
    data = bytearray(36)
    data[0:2] = text.to_bytes(2, order)
    data[8:10] = (100).to_bytes(2, order)
    data[14:16] = (0x1A08).to_bytes(2, order)
    data[24:26] = tag.to_bytes(2, order)
    return bytes(data)


def _document(
    others: list[Record],
    texts: list[Record],
    details: tuple[Record, ...] = (),
    entries: tuple[Record, ...] = (),
) -> EnigmaDocument:
    return EnigmaDocument(
        "18.0",
        Pool(()),
        Pool(()),
        OptionsPool(()),
        OthersPool(tuple(others)),
        DetailsPool(details),
        EntriesPool(entries),
        TextsPool(tuple(texts)),
    )


def _text(number: int, text: str, tag: str = "blockText") -> Record:
    return Record(tag, {"number": str(number)}, text, {})


def test_binary_staff_references_follow_the_document_text_blocks() -> None:
    records = (
        MusOther(231, 1, 0, _staff(41, 42)),
        MusOther(183, 41, 0, _block(7)),
        MusOther(183, 42, 0, _block(9)),
        MusOther(183, 41, 1, _block(8)),
        MusOther(231, 1, 1, _staff(43)),
    )
    document = _document(
        adapter._others_records(records, "cp1252"),
        [
            _text(7, "^size(12)Clarinet in B♭"),
            _text(9, "Cl."),
            _text(8, "WRONG linked part"),
            _text(41, "WRONG direct ID"),
        ],
    )
    assert staff_names(document) == {1: StaffNames("Clarinet in B♭", "Cl.")}
    assert document.others.get("textBlock", 41, part=1) is not None


@pytest.mark.parametrize("order", ["little", "big"])
def test_dcl_staff_and_text_blocks_use_the_file_byte_order(order: ByteOrder) -> None:
    rows = MusRows(
        others={
            ("IS", 1): MusRowRecord("IS", 1, payload=_staff(51, 52, order)),
            ("TX", 51): MusRowRecord("TX", 51, payload=_block(4, order=order)),
            ("TX", 52): MusRowRecord("TX", 52, payload=_block(6, order=order)),
        },
        byte_order=order,
    )
    document = _document(adapter._rows_others(rows, {}), [_text(4, "Violin"), _text(6, "Vln.")])
    assert staff_names(document) == {1: StaffNames("Violin", "Vln.")}


def test_pre_2004_tx_uses_the_documented_default_block_text_tag() -> None:
    rows = MusRows(
        others={
            ("TX", 37): MusRowRecord("TX", 37, payload=_block(8, tag=0) + bytes(12)),
        }
    )
    document = _document(adapter._rows_others(rows, {}), [_text(8, "Oboe")])
    assert text_block(document, 37) == "Oboe"


@pytest.mark.parametrize("raw_tag,text_tag", [(2004, "blockText"), (2006, "expression")])
def test_text_block_selects_its_own_text_pool(raw_tag: int, text_tag: str) -> None:
    others = adapter._others_records((MusOther(183, 41, 0, _block(7, raw_tag)),), "cp1252")
    document = _document(
        others, [_text(7, "Block text"), _text(7, "Expression text", "expression")]
    )
    assert text_block(document, 41) == (
        "Block text" if text_tag == "blockText" else "Expression text"
    )


def test_unknown_text_tags_and_unresolved_references_do_not_invent_names() -> None:
    others = adapter._others_records(
        (
            MusOther(231, 1, 0, _staff(41)),
            MusOther(231, 2, 0, _staff(42)),
            MusOther(231, 3, 0, _staff(0)),
            MusOther(183, 41, 0, _block(7, tag=65535)),
        ),
        "cp1252",
    )
    document = _document(others, [_text(7, "WRONG unknown tag")])
    assert staff_names(document) == {}
    assert text_block(document, 41) is None
    assert text_block(document, 42) is None


@pytest.mark.parametrize("payload", [b"", bytes(1), bytes(24), bytes(25)])
def test_truncated_numeric_text_block_fails_clearly(payload: bytes) -> None:
    with pytest.raises(CorruptScoreError, match="textBlock"):
        adapter._others_records((MusOther(183, 1, 0, payload),), "cp1252")


@pytest.mark.parametrize(
    "platform,encoding", [("WIN", "utf-8"), ("WIN", "cp1252"), ("MAC", "mac_roman")]
)
def test_block_sections_preserve_unicode_and_font_markup(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    encoding: str,
) -> None:
    # Binary font arguments are byte-sized even when literal content is UTF-8.
    markup = b"^\x85\x01\x01\x01\x0a^\x86\x01\x01\x01\x0f"
    text = b"^block(7)" + markup + "Célesta".encode(encoding) + b"^end"
    monkeypatch.setattr(
        adapter, "read_mus_streams", lambda _: [b"", b"", b"^block(7)WRONG stale copy^end", text]
    )
    monkeypatch.setattr(adapter, "_banner_platform", lambda _: platform)
    records = adapter._texts_records(Path("not-opened.mus"))
    others = adapter._others_records(
        (MusOther(231, 1, 0, _staff(41)), MusOther(183, 41, 0, _block(7))), "cp1252"
    )
    assert staff_names(_document(others, records)) == {1: StaffNames("Célesta")}
    assert records[0].text.startswith("^")  # markup retained in the normalized document


def test_staff_and_group_labels_keep_their_distinct_roles_in_musicxml() -> None:
    others = adapter._others_records(
        (
            MusOther(231, 1, 0, _staff(41, 42)),
            MusOther(231, 2, 0, _staff(0)),
            MusOther(231, 3, 0, _staff(43)),
            MusOther(183, 41, 0, _block(7)),
            MusOther(183, 42, 0, _block(9)),
            MusOther(183, 43, 0, _block(11)),
            MusOther(183, 44, 0, _block(12)),
            MusOther(183, 45, 0, _block(13)),
            MusOther(176, 1, 0, b"\x00\x00\x00\x00\x04\x00\x00\x04"),
        ),
        "cp1252",
    )
    others.extend(
        Record("frameSpec", {"cmper": str(i)}, "", {"startEntry": str(i), "endEntry": str(i)})
        for i in (1, 2, 3)
    )
    document = _document(
        others,
        [
            _text(7, "Right hand"),
            _text(9, "RH"),
            _text(11, "Flute"),
            _text(12, "Grand piano"),
            _text(13, "Pno."),
        ],
        (
            Record(
                "staffGroup",
                {"cmper1": "0", "cmper2": "1"},
                "",
                {
                    "startInst": "1",
                    "endInst": "2",
                    "fullID": "44",
                    "abbrvID": "45",
                    "bracket": Record("bracket", {}, "", {"id": "3"}),
                },
            ),
            *(
                Record("gfhold", {"cmper1": str(i), "cmper2": "1"}, "", {"frame1": str(i)})
                for i in (1, 2, 3)
            ),
        ),
        tuple(
            Record(
                "entry",
                {"entnum": str(i), "prev": str(i - 1), "next": str(i + 1 if i < 3 else 0)},
                "",
                {
                    "dura": "1024",
                    "numNotes": "1",
                    "note": Record("note", {}, "", {"harmLev": "0", "harmAlt": "0"}),
                },
            )
            for i in (1, 2, 3)
        ),
    )
    score = build_score(document)
    assert [p.name for p in score.parts] == ["Right hand", "Staff 2", "Flute"]
    assert score.groups[0].name == "Grand piano"
    root = ET.fromstring(to_musicxml(score))
    assert root.findtext("part-list/part-group/group-name") == "Grand piano"
    assert root.findtext("part-list/part-group/group-abbreviation") == "Pno."
    assert root.findtext("part-list/score-part/part-name") == "Right hand"
    assert root.findtext("part-list/score-part/part-abbreviation") == "RH"
