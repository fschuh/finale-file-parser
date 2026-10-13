"""Authored controls pin unit flags independently of display and performance."""

import struct

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.articulation_playback import articulation_playback_by_entry
from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _artic_def
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import PlaybackAdjustment


@pytest.mark.parametrize("size", [48, 60])
@pytest.mark.parametrize("units", [0, 8, 0x10, 0x20, 0x38])
def test_binary_units_values_and_on_screen_flag_use_their_own_slots(size: int, units: int) -> None:
    data = bytearray(size)
    struct.pack_into("<H", data, 10, 0x100)
    struct.pack_into("<H", data, 24 if size == 60 else 22, units | 0x40)
    struct.pack_into("<6h", data, 38 if size == 60 else 36, -32, 64, 75, 85, 90, 110)
    fields = _artic_def(bytes(data))
    assert "noPrint" in fields and "playArtic" in fields
    for name, mask, values in (
        ("start", 0x10, (-32, 64)),
        ("dur", 0x20, (75, 85)),
        ("amp", 8, (90, 110)),
    ):
        unit = "Percent" if units & mask else "Delta"
        assert (fields[f"{name}TopNote{unit}"], fields[f"{name}BotNote{unit}"]) == tuple(
            map(str, values)
        )
        assert f"{name}TopNote{'Delta' if units & mask else 'Percent'}" not in fields


def _document(control: str, *, char: int = 8, assignment: str = "", definition: str = "") -> bytes:
    return f"""<finale><others>
      <fontName cmper="0"><name>Maestro</name></fontName>
      <articDef cmper="1"><charMain>{char}</charMain><fontMain>0</fontMain>
        {definition}{control}</articDef>
      <staffSpec cmper="1"/><measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details>
      <articAssign entnum="1"><articDef>1</articDef>{assignment}</articAssign>
      <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
    </details><entries><entry entnum="1" prev="0" next="0">
      <dura>1024</dura><numNotes>1</numNotes><note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>""".encode()


@pytest.mark.parametrize("char", [0, 8])
@pytest.mark.parametrize("hidden", ["", "<hide/>"])
def test_nonprinting_character_controls_survive_without_invented_notation(
    char: int, hidden: str
) -> None:
    doc = parse_enigma(
        _document(
            "<playArtic/><durTopNotePercent>75</durTopNotePercent><durBotNotePercent>75</durBotNotePercent>",
            char=char,
            assignment=hidden,
        )
    )
    score = build_score(doc)
    event = score.parts[0].measures[0].voices[0].events[0]
    (control,) = event.articulation_playback
    assert control.duration == PlaybackAdjustment(75, 75, "percent")
    assert event.articulations == () and event.playback
    assert {d.code for d in score.diagnostics} >= {
        "nonprinting-articulation",
        "articulation-playback",
    }
    note = ET.fromstring(to_musicxml(score)).find(".//note")
    assert note is not None and note.findtext("duration") == "1"
    assert note.get("release") is None and note.find("notations") is None


def test_velocity_percent_is_separate_from_duration_delta() -> None:
    doc = parse_enigma(
        _document(
            "<playArtic/><ampTopNotePercent>85</ampTopNotePercent><ampBotNotePercent>85</ampBotNotePercent>"
            "<durTopNoteDelta>-96</durTopNoteDelta><durBotNoteDelta>-96</durBotNoteDelta>",
        )
    )
    controls, _ = articulation_playback_by_entry(doc)
    assert controls[1][0].velocity == PlaybackAdjustment(85, 85, "percent")
    assert controls[1][0].duration == PlaybackAdjustment(-96, -96, "edu")


def test_no_print_definition_keeps_playback_but_omits_its_visible_accent() -> None:
    doc = parse_enigma(_document("<playArtic/>", char=62, definition="<noPrint/>"))
    event = build_score(doc).parts[0].measures[0].voices[0].events[0]
    assert not event.articulations and len(event.articulation_playback) == 1


def test_inactive_definition_and_unused_palette_do_not_attach_controls() -> None:
    doc = parse_enigma(_document("<durTopNotePercent>75</durTopNotePercent>"))
    assert articulation_playback_by_entry(doc)[0] == {}
    raw = _document("<playArtic/>").replace(b"<articDef>1</articDef>", b"<articDef>2</articDef>")
    assert articulation_playback_by_entry(parse_enigma(raw)) == ({}, ())


def test_invalid_source_control_fails_clearly() -> None:
    doc = parse_enigma(_document("<playArtic/><durTopNotePercent>oops</durTopNotePercent>"))
    with pytest.raises(CorruptScoreError, match="playback adjustment"):
        articulation_playback_by_entry(doc)
