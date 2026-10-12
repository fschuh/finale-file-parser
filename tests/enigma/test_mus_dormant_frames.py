"""Authored frame databases exercise scope without third-party score fixtures."""

from dataclasses import replace

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, EntriesPool, OthersPool, parse_enigma
from finale_file_parser.enigma.location import MalformedScoreError, locate_entries
from finale_file_parser.enigma.mus_document import _frame_assignment_scope
from finale_file_parser.enigma.to_ir import build_score


def _document(
    *,
    shared: bool = False,
    higher_layer: bool = False,
    linked_part: bool = False,
    orphan: bool = False,
) -> EnigmaDocument:
    start = 1 if shared else 2
    primary = '<gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold>'
    if higher_layer:
        primary = '<gfhold cmper1="1" cmper2="1"><frame1>10</frame1><frame3>20</frame3></gfhold>'
    if linked_part:
        primary += '<gfhold cmper1="1" cmper2="1" part="9"><frame4>20</frame4></gfhold>'
    entries = "".join(
        f'<entry entnum="{n}" prev="0" next="0"><dura>1024</dura><numNotes>1</numNotes>'
        "<note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>"
        for n in range(1, 4 if orphan else 3)
    )
    raw = f"""<finale version="18.0" xmlns="http://www.makemusic.com/2012/finale">
      <entries>{entries}</entries>
      <others>
        <frameSpec cmper="10"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
        <frameSpec cmper="20"><startEntry>{start}</startEntry><endEntry>2</endEntry></frameSpec>
        <measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
      </others><details>{primary}</details>
    </finale>"""
    # A shared frame continues the ordinary entry into an unused one.
    if shared:
        raw = raw.replace('entnum="1" prev="0" next="0"', 'entnum="1" prev="0" next="2"')
    doc = parse_enigma(raw.encode())
    scoped = _frame_assignment_scope(
        list(doc.others.records), list(doc.details.records), doc.entries.records
    )
    doc.others = OthersPool(tuple(scoped))
    return doc


@pytest.mark.parametrize("shared", [False, True])
def test_unused_frame_entries_remain_raw_and_do_not_become_music(shared: bool) -> None:
    doc = _document(shared=shared)
    assert len(doc.entries.records) == 2
    frame = doc.others.get("frameSpec", 20)
    assert frame is not None and "unassignedFrame" in frame.fields
    with pytest.raises(MalformedScoreError, match="orphan"):
        locate_entries(doc)
    locations = locate_entries(doc, include_reserved_staff=False)
    assert set(locations) == {1}
    score = build_score(doc)
    assert len(score.parts[0].measures[0].voices[0].events) == 1


def test_higher_layer_frames_are_assigned_music() -> None:
    doc = _document(higher_layer=True)
    frame = doc.others.get("frameSpec", 20)
    assert frame is not None and "unassignedFrame" not in frame.fields
    assert set(locate_entries(doc, include_reserved_staff=False)) == {1, 2}
    assert [v.number for v in build_score(doc).parts[0].measures[0].voices] == [1, 3]


def test_entries_without_any_frame_remain_genuine_orphans() -> None:
    with pytest.raises(MalformedScoreError, match=r"1 orphan.*\[3\]"):
        locate_entries(_document(orphan=True), include_reserved_staff=False)


def test_a_linked_part_reference_prevents_a_dormant_frame_claim() -> None:
    doc = _document(linked_part=True)
    frame = doc.others.get("frameSpec", 20)
    assert frame is not None and "unassignedFrame" not in frame.fields
    with pytest.raises(MalformedScoreError, match="orphan"):
        locate_entries(doc, include_reserved_staff=False)


def test_unused_frame_chain_links_are_still_validated() -> None:
    doc = _document(shared=True)
    entries = tuple(
        replace(record, attrs={**record.attrs, "next": "99"})
        if record.attrs["entnum"] == "1"
        else record
        for record in doc.entries.records
    )
    doc.entries = EntriesPool(entries)
    with pytest.raises(MalformedScoreError, match="missing entry 99"):
        locate_entries(doc, include_reserved_staff=False)
