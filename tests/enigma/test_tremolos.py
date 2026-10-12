"""Authored display constructions distinguish two-note tremolos from tuplets."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import MusDetailRecord
from finale_file_parser.enigma.mus_document import _details_records
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Score, SlurEndpoint


def _score(
    *,
    heads: bool = False,
    chord: bool = False,
    number_style: int = 0,
    mask: int = 0xB80,
    symbolic: int = 256,
    second_beam: bool = False,
) -> Score:
    reference = 2048 if heads else 1024
    mods = (
        "".join(
            f'<noteheadMod entnum="{i}"><noteID>1</noteID>'
            "<customChar>250</customChar></noteheadMod>"
            for i in (1, 2)
        )
        if heads
        else '<beamExtUp entnum="1"><leftAdjust>20</leftAdjust><rightAdjust>-20</rightAdjust>'
        f"<beamMask>{mask}</beamMask></beamExtUp>"
    )
    notes = '<note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note>'
    if chord:
        notes += '<note id="2"><harmLev>2</harmLev><harmAlt>0</harmAlt></note>'
    raw = f"""<finale><others>
      <fontName cmper="0"><name>Maestro</name></fontName><staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
      <tupletDef entnum="1"><symbolicNum>1</symbolicNum><symbolicDur>{symbolic}</symbolicDur>
        <refNum>1</refNum><refDur>{reference}</refDur><numberStyle>{number_style}</numberStyle>
        <brackStyle>0</brackStyle></tupletDef>{mods}
    </details><entries>
      <entry entnum="1" prev="0" next="2"><dura>128</dura><beam/>
        <numNotes>{2 if chord else 1}</numNotes>{notes}</entry>
      <entry entnum="2" prev="1" next="0"><dura>128</dura>
        {"<beam/>" if second_beam else ""}<numNotes>{2 if chord else 1}</numNotes>{notes}</entry>
    </entries></finale>"""
    return build_score(parse_enigma(raw.encode()))


@pytest.mark.parametrize("heads,printed", [(False, "quarter"), (True, "half")])
def test_hidden_tuplet_with_source_display_mods_becomes_one_exact_tremolo_pair(
    heads: bool, printed: str
) -> None:
    score = _score(heads=heads)
    part = score.parts[0]
    assert len(part.tremolos) == 1
    span = part.tremolos[0]
    assert span.start == SlurEndpoint(1, 1, 0) and span.end == SlurEndpoint(1, 1, 1)
    events = part.measures[0].voices[0].events
    assert events[0].written_duration == events[0].duration * 2
    assert events[0].tuplet_ratio == Fraction(1, 2)
    root = DET.fromstring(to_musicxml(score))
    assert root.findall(".//tremolo")[0].get("type") == "start"
    assert root.findall(".//tremolo")[1].get("type") == "stop"
    assert [e.text for e in root.findall(".//note/type")] == [printed, printed]
    assert root.findtext(".//time-modification/actual-notes") == "2"
    assert root.findtext(".//time-modification/normal-notes") == "1"
    assert not root.findall(".//beam")


def test_chord_tremolo_marks_once_per_chord_without_losing_pitches() -> None:
    root = DET.fromstring(to_musicxml(_score(chord=True)))
    assert len(root.findall(".//pitch")) == 4 and len(root.findall(".//tremolo")) == 2


@pytest.mark.parametrize(
    "style,mask,symbolic,second_beam",
    [
        (1, 0xB80, 256, False),
        (0, 0, 256, False),
        (0, 0xB80, 384, False),
        (0, 0xB80, 256, True),
    ],
)
def test_ordinary_tuplets_and_beams_are_not_guessed_as_tremolos(
    style: int, mask: int, symbolic: int, second_beam: bool
) -> None:
    assert (
        not _score(number_style=style, mask=mask, symbolic=symbolic, second_beam=second_beam)
        .parts[0]
        .tremolos
    )


@pytest.mark.parametrize("tag,size", [(1021, 9), (1022, 11), (1058, 19)])
def test_partial_source_display_records_raise_a_clear_error(tag: int, size: int) -> None:
    with pytest.raises(CorruptScoreError, match="display detail"):
        _details_records((MusDetailRecord(tag, 0, 1, 0, bytes(size)),))


def test_invalid_tremolo_endpoint_does_not_silently_disappear_in_export() -> None:
    score = _score()
    part = score.parts[0]
    bad = replace(part.tremolos[0], end=SlurEndpoint(1, 1, 99))
    with pytest.raises(ExportError, match="tremolo endpoints"):
        to_musicxml(replace(score, parts=(replace(part, tremolos=(bad,)),)))


def test_normalizes_beam_mask_and_signed_extension_offsets() -> None:
    payload = b"\x14\x00\xec\xff" + bytes(4) + b"\x80\x0b"
    record = _details_records((MusDetailRecord(1021, 0, 1, 0, payload),))[0]
    assert record.fields == {"leftAdjust": "20", "rightAdjust": "-20", "beamMask": str(0xB80)}


def test_packed_notehead_mods_keep_note_ids_and_custom_font_flags_distinct() -> None:
    first = bytearray(20)
    first[:2], first[6:8] = b"\x01\x00", b"\xfa\x00"
    second = bytearray(first)
    second[:2], second[8] = b"\x02\x00", 1
    records = _details_records((MusDetailRecord(1058, 0, 1, 0, bytes(first + second)),), year=2011)
    assert [r.fields["noteID"] for r in records] == ["1", "2"]
    assert [r.fields["customChar"] for r in records] == ["250", "250"]
    assert "useCustomFont" not in records[0].fields and "useCustomFont" in records[1].fields
