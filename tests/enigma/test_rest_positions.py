"""Original positioned-rest fixtures authored here, licensed MIT."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import ExportError, to_musicxml
from finale_file_parser.ir import Pitch


def _document(flags: str = "", note_id: int = 31, *, key: int = 0) -> bytes:
    return f'''<finale><others><staffSpec cmper="1"/>
    <measSpec cmper="1"><keySig><key>{key}</key></keySig>
    <beats>4</beats><divbeat>1024</divbeat></measSpec>
    <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="2"><dura>1024</dura><numNotes>1</numNotes>
      <isValid/>{flags}<note id="{note_id}"><harmLev>-5</harmLev><harmAlt>0</harmAlt></note></entry>
    <entry entnum="2" prev="1" next="0"><dura>1024</dura><numNotes>1</numNotes>
      <isValid/><isNote/><note id="1"><harmLev>-5</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>'''.encode()


@pytest.mark.parametrize("key,step,octave", [(0, "E", 3), (1, "B", 3), (257, "G", 3)])
def test_manual_rest_uses_the_stored_note_position_without_becoming_a_pitch(
    key: int, step: str, octave: int
) -> None:
    score = build_score(parse_enigma(_document(key=key)))
    rest, note = score.parts[0].measures[0].voices[0].events
    assert rest.is_rest and not rest.pitches
    assert rest.rest_display_pitch == Pitch(step, octave, 0)
    assert (note.pitches[0].step, note.pitches[0].octave) == (step, octave)
    assert rest.duration == Fraction(1, 4) and note.duration == Fraction(1, 4)
    root = ET.fromstring(to_musicxml(score))
    assert len(root.findall(".//pitch")) == 1
    assert root.findtext(".//rest/display-step") == step
    assert root.findtext(".//rest/display-octave") == str(octave)
    assert [n.findtext("duration") for n in root.findall(".//note")] == ["1", "1"]


@pytest.mark.parametrize("flags,identity", [("<floatRest/>", 31), ("", 7)])
def test_floating_or_unestablished_rest_records_do_not_claim_a_manual_position(
    flags: str, identity: int
) -> None:
    score = build_score(parse_enigma(_document(flags, identity)))
    assert score.parts[0].measures[0].voices[0].events[0].rest_display_pitch is None
    assert ET.fromstring(to_musicxml(score)).find(".//rest/display-step") is None


def test_hidden_manual_rest_keeps_geometry_and_time_independently() -> None:
    score = build_score(parse_enigma(_document("<ignore/>")))
    root = ET.fromstring(to_musicxml(score))
    first = root.find(".//note")
    assert first is not None and first.get("print-object") == "no"
    assert first.findtext("rest/display-step") == "E" and first.findtext("duration") == "1"


def test_rest_position_cannot_turn_into_a_pitched_note_or_invalid_xml_octave() -> None:
    score = build_score(parse_enigma(_document()))
    part = score.parts[0]
    measure = part.measures[0]
    voice = measure.voices[0]
    for event in (
        replace(voice.events[0], rest_display_pitch=Pitch("C", 10, 0)),
        replace(voice.events[1], rest_display_pitch=Pitch("C", 4, 0)),
    ):
        altered = replace(
            score,
            parts=(
                replace(
                    part, measures=(replace(measure, voices=(replace(voice, events=(event,)),)),)
                ),
            ),
        )
        with pytest.raises(ExportError, match="rest.*position"):
            to_musicxml(altered)
