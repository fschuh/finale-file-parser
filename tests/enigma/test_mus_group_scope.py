"""Authored detail headers test score/linked-part scope without score fixtures."""

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.articulations import articulations_by_entry
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
from finale_file_parser.enigma.mus_details import MusDetailRecord, _walk
from finale_file_parser.enigma.mus_document import _details_records
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _group(
    number: int,
    part: int = 0,
    *,
    start: int = 1,
    end: int = 2,
    bracket: int = 3,
    name: int = 0,
) -> MusDetailRecord:
    data = bytearray(40)
    for offset, value in (
        (0, start),
        (2, end),
        (4, name),
        (10, bracket),
        (20, 0x0400),
        (32, 1),
        (34, 32767),
    ):
        data[offset : offset + 2] = value.to_bytes(2, "little")
    return MusDetailRecord(1057, 0, number, part, bytes(data))


def _document(groups: tuple[MusDetailRecord, ...]) -> EnigmaDocument:
    others = [Record("measSpec", {"cmper": "1"}, "", {"beats": "1", "divbeat": "1024"})]
    details = _details_records(groups)
    entries = []
    for staff in range(1, 5):
        number = str(staff)
        others.extend(
            (
                Record("staffSpec", {"cmper": number}, "", {}),
                Record(
                    "frameSpec", {"cmper": number}, "", {"startEntry": number, "endEntry": number}
                ),
            )
        )
        details.append(Record("gfhold", {"cmper1": number, "cmper2": "1"}, "", {"frame1": number}))
        entries.append(
            Record(
                "entry",
                {
                    "entnum": number,
                    "prev": str(staff - 1),
                    "next": str(staff + 1 if staff < 4 else 0),
                },
                "",
                {
                    "dura": "1024",
                    "numNotes": "1",
                    "note": Record("note", {}, "", {"harmLev": "0", "harmAlt": "0"}),
                },
            )
        )
    others.extend(
        (
            Record("textBlock", {"cmper": "70"}, "", {"textID": "8"}),
            Record("textBlock", {"cmper": "71"}, "", {"textID": "9"}),
        )
    )
    return EnigmaDocument(
        "18.0",
        Pool(()),
        Pool(()),
        OptionsPool(()),
        OthersPool(tuple(others)),
        DetailsPool(tuple(details)),
        EntriesPool(tuple(entries)),
        TextsPool(
            (
                Record("blockText", {"number": "8"}, "Piano", {}),
                Record("blockText", {"number": "9"}, "Linked part name", {}),
            )
        ),
    )


def test_header_word_at_six_is_preserved_as_part_scope() -> None:
    records = (_group(10), _group(11, 3))
    stream = b"".join(
        b"".join(n.to_bytes(2, "little") for n in (r.tag, r.cmper1, r.cmper2, r.inci))
        + len(r.payload).to_bytes(4, "little")
        + r.payload
        + bytes(4)
        for r in records
    )
    parsed = _walk(stream)
    assert parsed is not None
    assert [r.part for r in parsed] == [0, 3]
    assert [r.inci for r in parsed] == [0, 3]  # compatibility attribute


@pytest.mark.parametrize("same_key", [False, True])
def test_linked_part_group_is_retained_but_does_not_brace_the_score(same_key: bool) -> None:
    document = _document((_group(10, name=70), _group(10 if same_key else 11, 3, name=71)))
    assert document.details.get("staffGroup", 0, 10) is not None
    variant = document.details.get("staffGroup", 0, 10 if same_key else 11, part=3)
    assert variant is not None and variant.fields["fullID"] == "71"
    score = build_score(document)
    assert [(g.part_ids, g.name) for g in score.groups] == [(("P1", "P2"), "Piano")]
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall("part-list/part-group[@type='start']")) == 1
    assert root.findtext("part-list/part-group/group-name") == "Piano"
    assert len(root.findall("part/measure/note")) == 4


def test_equal_score_spans_keep_legitimately_distinct_groups() -> None:
    score = build_score(_document((_group(10, name=70), _group(11, bracket=6, name=71))))
    assert [(g.symbol, g.name) for g in score.groups] == [
        ("brace", "Piano"),
        ("bracket", "Linked part name"),
    ]
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall("part-list/part-group[@type='start']")) == 2


def test_nested_score_groups_survive_part_filtering() -> None:
    score = build_score(
        _document(
            (
                _group(10, end=4, bracket=6),
                _group(11),
                _group(12, start=3, end=4),
                _group(13, 3, end=4, bracket=6),
            )
        )
    )
    assert [g.part_ids for g in score.groups] == [
        ("P1", "P2", "P3", "P4"),
        ("P1", "P2"),
        ("P3", "P4"),
    ]


def test_part_label_never_promotes_an_unnamed_score_group() -> None:
    score = build_score(_document((_group(10), _group(11, 3, name=70))))
    assert len(score.groups) == 1 and score.groups[0].name == ""


@pytest.mark.parametrize("start,end", [(99, 2), (3, 1)])
def test_invalid_group_spans_are_not_repaired_by_a_part_variant(start: int, end: int) -> None:
    score = build_score(_document((_group(10, start=start, end=end), _group(11, 3))))
    assert score.groups == ()


@pytest.mark.parametrize("part_first", [True, False])
def test_assignment_deduplication_does_not_swallow_a_score_mark(part_first: bool) -> None:
    data = bytearray(20)
    data[:2] = (7).to_bytes(2, "little")
    score_record = MusDetailRecord(1009, 0, 1, 0, bytes(data))
    part_record = MusDetailRecord(1009, 0, 1, 3, bytes(data))
    records = (part_record, score_record) if part_first else (score_record, part_record)
    assignments = _details_records(records)
    assert len(assignments) == 2
    document = EnigmaDocument(
        "18.0",
        Pool(()),
        Pool(()),
        OptionsPool(()),
        OthersPool((Record("articDef", {"cmper": "7"}, "", {"charMain": "62"}),)),
        DetailsPool(tuple(assignments)),
        EntriesPool(()),
        TextsPool(()),
    )
    assert articulations_by_entry(document) == {1: ("accent",)}


@pytest.mark.parametrize(
    "tag,payload",
    [
        (1044, bytes(20)),
        (1009, b"\x01\x00" + bytes(18)),
        (1108, b"\x01\x00" + bytes(18)),
        (1064, bytes(10)),
        (1072, bytes(8)),
    ],
)
def test_all_translated_details_retain_their_header_part(tag: int, payload: bytes) -> None:
    normalized = _details_records((MusDetailRecord(tag, 1, 2, 3, payload),))
    assert normalized and all(r.attrs.get("part") == "3" for r in normalized)
