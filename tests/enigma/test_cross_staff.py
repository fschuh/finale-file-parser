"""Original two-staff examples authored for this project; licensed MIT."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import MusDetailRecord
from finale_file_parser.enigma.mus_document import _details_records
from finale_file_parser.enigma.mus_entries import _note_record
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import CrossStaff


def _document(
    *,
    note_id: int = 7,
    staff: int = 1,
    flag: bool = True,
    mods: str | None = None,
    chord: bool = False,
) -> EnigmaDocument:
    if mods is None:
        mods = (
            f'<crossStaff entnum="3"><noteID>{note_id}</noteID><staff>{staff}</staff></crossStaff>'
        )
    extra_note = '<note id="2"><harmLev>-7</harmLev><harmAlt>0</harmAlt></note>' if chord else ""
    return parse_enigma(
        f"""<finale><others>
      <staffSpec cmper="1"/><staffSpec cmper="2"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>5</endEntry></frameSpec>
    </others><details>
      <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <gfhold cmper1="2" cmper2="1"><frame1>2</frame1></gfhold>{mods}
    </details><entries>
      <entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
        <note id="1"><harmLev>4</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="2" prev="0" next="3"><dura>512</dura><beam/><numNotes>1</numNotes>
        <note id="7"><harmLev>-7</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="3" prev="2" next="4"><dura>512</dura><numNotes>{2 if chord else 1}</numNotes>
        <note id="7"><harmLev>0</harmLev><harmAlt>0</harmAlt>{"<crossStaff/>" if flag else ""}
        </note>{extra_note}</entry>
      <entry entnum="4" prev="3" next="5"><dura>512</dura><numNotes>1</numNotes>
        <note id="7"><harmLev>2</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="5" prev="4" next="0"><dura>512</dura><numNotes>1</numNotes>
        <note id="7"><harmLev>-7</harmLev><harmAlt>0</harmAlt></note></entry>
    </entries></finale>""".encode()
    )


def test_moved_notes_keep_source_voice_time_pitch_and_connected_beams() -> None:
    score = build_score(_document())
    assert [p.id for p in score.parts] == ["P1", "P2"]
    event = score.parts[1].measures[0].voices[0].events[1]
    assert event.cross_staff == (CrossStaff(0, "P1"),)
    assert event.duration == Fraction(1, 8) and event.pitches[0].step == "C"
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall("part")) == 1 and root.findtext(".//attributes/staves") == "2"
    notes = root.findall(".//note")
    assert [n.findtext("staff") for n in notes] == ["1", "2", "1", "2", "2"]
    assert [n.findtext("voice") for n in notes] == ["1", "2", "2", "2", "2"]
    assert [n.findtext("beam") for n in notes[1:]] == ["begin", "continue", "continue", "end"]


def test_mixed_chord_moves_only_the_member_with_a_matching_stable_id() -> None:
    root = ET.fromstring(to_musicxml(build_score(_document(chord=True))))
    notes = root.findall(".//note")
    assert notes[2].findtext("staff") == "1" and notes[3].findtext("staff") == "2"
    assert notes[3].find("chord") is not None
    assert notes[2].findtext("voice") == notes[3].findtext("voice") == "2"
    assert notes[2].findtext("duration") == notes[3].findtext("duration") == "1"


def test_inactive_or_part_only_modification_does_not_move_the_score_note() -> None:
    score = build_score(_document(flag=False))
    assert not score.parts[1].measures[0].voices[0].events[1].cross_staff
    assert len(ET.fromstring(to_musicxml(score)).findall("part")) == 2
    doc = _document(
        flag=False,
        mods='<crossStaff entnum="3" part="1"><noteID>7</noteID><staff>1</staff></crossStaff>',
    )
    assert not build_score(doc).parts[1].measures[0].voices[0].events[1].cross_staff


@pytest.mark.parametrize("staff", [0, -1, 3, 32767])
def test_missing_or_reserved_destination_is_a_clear_error(staff: int) -> None:
    with pytest.raises(CorruptScoreError, match="staff"):
        build_score(_document(staff=staff))


@pytest.mark.parametrize("note_id", [0, 2, 99])
def test_missing_note_attachment_is_not_guessed_from_chord_index(note_id: int) -> None:
    with pytest.raises(CorruptScoreError, match="cross-staff"):
        build_score(_document(note_id=note_id))


def test_flagged_note_without_a_destination_stays_unresolved_on_its_source_staff() -> None:
    score = build_score(_document(mods=""))
    event = score.parts[1].measures[0].voices[0].events[1]
    assert event.cross_staff == (CrossStaff(0, None),)
    assert score.diagnostics[0].code == "cross-staff-destination"
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall("part")) == 2
    assert [n.findtext("pitch/step") for n in root.findall("part")[1].findall(".//note")] == [
        "C",
        "C",
        "E",
        "C",
    ]


def test_packed_cross_staff_records_keep_note_ids_destinations_and_scope() -> None:
    first = b"\x07\x00\x01\x00" + bytes(6)
    second = b"\x02\x00\x02\x00" + bytes(6)
    records = _details_records((MusDetailRecord(1036, 0, 3, 1, first + second),))
    assert [r.fields for r in records] == [
        {"noteID": "7", "staff": "1"},
        {"noteID": "2", "staff": "2"},
    ]
    assert [r.attrs for r in records] == [
        {"entnum": "3", "inci": "0", "part": "1"},
        {"entnum": "3", "inci": "1", "part": "1"},
    ]


@pytest.mark.parametrize("size", [0, 9, 11])
def test_partial_binary_cross_staff_record_is_rejected(size: int) -> None:
    with pytest.raises(CorruptScoreError, match="display detail"):
        _details_records((MusDetailRecord(1036, 0, 3, 0, bytes(size)),))


def test_binary_note_cross_flag_keeps_identity_separate_from_attachment() -> None:
    raw = b"\x00\x00" + (0x90070000).to_bytes(4, "little")
    note = _note_record(raw, 0, "little")
    assert note.attrs["id"] == "7" and "crossStaff" in note.fields


@pytest.mark.parametrize("mark", [CrossStaff(0, "P99"), CrossStaff(4, "P1")])
def test_invalid_ir_destination_or_chord_member_raises_before_export(mark: CrossStaff) -> None:
    score = build_score(_document())
    part = score.parts[1]
    measure = part.measures[0]
    voice = measure.voices[0]
    events = (voice.events[0], replace(voice.events[1], cross_staff=(mark,)), *voice.events[2:])
    part = replace(part, measures=(replace(measure, voices=(replace(voice, events=events),)),))
    with pytest.raises(ExportError, match="cross-staff"):
        to_musicxml(replace(score, parts=(score.parts[0], part)))
