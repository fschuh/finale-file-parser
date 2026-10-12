"""Authored glissandi use stable note IDs, independent of chord order and voice."""

from dataclasses import replace

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_entries import _note_record
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import NoteEndpoint, Score, SlurEndpoint


def _score(*, note_id: int = 4, hidden: bool = False, assigned: bool = True) -> Score:
    assignment = (
        '<smartShapeEntryMark entnum="1"><shapeNum>1</shapeNum></smartShapeEntryMark>'
        if assigned
        else ""
    )
    raw = f"""<finale><others><staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
      <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>2</endEntry>
        <startTime>1024</startTime></frameSpec>
      <smartShape cmper="1"><shapeType>glissando</shapeType><entryBased/>
        {"<hidden/>" if hidden else ""}<startNoteID>7</startNoteID><endNoteID>{note_id}</endNoteID>
        <startTermSeg><endPt><inst>1</inst><meas>1</meas><entryNum>1</entryNum></endPt></startTermSeg>
        <endTermSeg><endPt><inst>1</inst><meas>1</meas><entryNum>2</entryNum></endPt></endTermSeg>
      </smartShape>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1><frame2>2</frame2></gfhold>
      {assignment}
    </details><entries>
      <entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
        <note id="3"><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
        <note id="7"><harmLev>4</harmLev><harmAlt>0</harmAlt></note></entry>
      <entry entnum="2" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
        <noPlayback/><ignore/>
        <note id="4"><harmLev>-3</harmLev><harmAlt>0</harmAlt></note>
        <note id="8"><harmLev>2</harmLev><harmAlt>0</harmAlt></note></entry>
    </entries></finale>"""
    return build_score(parse_enigma(raw.encode()))


def test_exact_chord_notes_and_cross_voice_endpoints_survive_export() -> None:
    score = _score()
    span = score.parts[0].glissandi[0]
    assert span.start == NoteEndpoint(SlurEndpoint(1, 1, 0), 1)
    assert span.end == NoteEndpoint(SlurEndpoint(1, 2, 0), 0)
    root = DET.fromstring(to_musicxml(score))
    notes = root.findall(".//note")
    assert notes[0].find(".//glissando") is None
    start, end = notes[1].find(".//glissando"), notes[2].find(".//glissando")
    assert start is not None and start.get("type") == "start"
    assert end is not None and end.get("type") == "stop"
    assert notes[2].get("print-object") == "no" and notes[2].find("cue") is not None
    assert notes[3].find(".//glissando") is None
    assert len(root.findall(".//pitch")) == 4


@pytest.mark.parametrize("hidden,assigned", [(True, True), (False, False)])
def test_hidden_or_unassigned_palette_shapes_do_not_place_a_glissando(
    hidden: bool, assigned: bool
) -> None:
    assert not _score(hidden=hidden, assigned=assigned).parts[0].glissandi


def test_missing_note_id_is_not_guessed_from_pitch_or_chord_order() -> None:
    with pytest.raises(CorruptScoreError, match="note ID 5 has 0 matches"):
        _score(note_id=5)


def test_documented_note_id_bits_do_not_overlap_tie_flags() -> None:
    record = _note_record(bytes(2) + (0xC0070000).to_bytes(4, "little"), 0, "little")
    assert record.attrs == {"id": "7"} and "tieStart" in record.fields


def test_invalid_export_pitch_index_raises_before_creating_a_dangling_line() -> None:
    score = _score()
    part = score.parts[0]
    span = replace(part.glissandi[0], end=NoteEndpoint(SlurEndpoint(1, 2, 0), 1000000))
    with pytest.raises(ExportError, match="glissando endpoint"):
        to_musicxml(replace(score, parts=(replace(part, glissandi=(span,)),)))


def test_cross_bar_glissando_does_not_compare_reset_measure_offsets_as_absolute_time() -> None:
    score = _score()
    part = score.parts[0]
    measure = part.measures[0]
    first = replace(measure, voices=(measure.voices[0],))
    last = replace(
        measure,
        number=2,
        voices=(replace(measure.voices[1], start_offset=measure.voices[0].start_offset),),
    )
    span = replace(part.glissandi[0], end=NoteEndpoint(SlurEndpoint(2, 2, 0), 0))
    result = replace(score, parts=(replace(part, measures=(first, last), glissandi=(span,)),))
    assert len(DET.fromstring(to_musicxml(result)).findall(".//glissando")) == 2
