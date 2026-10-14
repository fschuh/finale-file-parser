"""Original C/D layouts and scalar binary records authored here, licensed MIT."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records, _staff_spec
from finale_file_parser.enigma.mus_others import TAG_STAFF_SPEC, MusOther
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import CrossStaff, Score


@pytest.mark.parametrize("order", ["little", "big"])
@pytest.mark.parametrize("size", [84, 96])
@pytest.mark.parametrize(
    "bits,mode", [(0, None), (0x4000, "score"), (0x8000, "scoreParts"), (0xC000, "cutaway")]
)
def test_stored_hide_mode_is_separate_from_other_flags(
    order: ByteOrder, size: int, bits: int, mode: str | None
) -> None:
    raw = bytearray(size)
    raw[44:46] = (bits | 0x241F).to_bytes(2, order)
    assert _staff_spec(bytes(raw), order, decode_hide_mode=True).get("hideMode") == mode
    assert "hideMode" not in _staff_spec(bytes(raw), order)


@pytest.mark.parametrize("size", [34, 46, 72, 85, 100])
def test_unproved_staff_layout_does_not_hide_music(size: int) -> None:
    raw = bytearray(size)
    if size >= 46:
        raw[44:46] = (0xC000).to_bytes(2, "little")
    assert "hideMode" not in _staff_spec(bytes(raw), decode_hide_mode=True)


def test_numeric_record_normalizes_print_mode() -> None:
    raw = bytearray(96)
    raw[44:46] = (0x641F).to_bytes(2, "little")
    records = _others_records((MusOther(TAG_STAFF_SPEC, 2, 0, bytes(raw)),), "")
    assert records[0].fields["hideMode"] == "score"


def _score(mode: str = "score") -> Score:
    return build_score(
        parse_enigma(
            f"""<finale><others>
      <instUsed cmper="0" inci="0"><inst>1</inst></instUsed>
      <instUsed cmper="0" inci="1"><inst>2</inst></instUsed>
      <staffSpec cmper="1"/><staffSpec cmper="2"><hideMode>{mode}</hideMode></staffSpec>
      <staffSpec cmper="1" part="1"><hideMode>scoreParts</hideMode></staffSpec>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details><gfhold cmper1="2" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
    <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry></entries></finale>""".encode()
        )
    )


@pytest.mark.parametrize("mode", ["score", "scoreParts"])
def test_hidden_music_and_visible_empty_staff_remain_in_canonical_score(mode: str) -> None:
    score = _score(mode)
    assert [p.staff_hide_mode for p in score.parts] == [
        None,
        "score" if mode == "score" else "score-parts",
    ]
    assert score.parts[0].measures[0].voices[0].events[0].is_measure_rest
    event = score.parts[1].measures[0].voices[0].events[0]
    assert event.playback and event.visible and event.duration == Fraction(1)
    for bundled in (False, True):
        hidden = score.parts[1]
        measure = hidden.measures[0]
        voice = measure.voices[0]
        bridged = replace(event, cross_staff=(CrossStaff(0, "P1"),))
        exported = (
            replace(
                score,
                parts=(
                    score.parts[0],
                    replace(
                        hidden,
                        measures=(replace(measure, voices=(replace(voice, events=(bridged,)),)),),
                    ),
                ),
            )
            if bundled
            else score
        )
        root = ET.fromstring(to_musicxml(exported))
        details = root.findall(".//staff-details")
        assert len(details) == 2
        assert all(
            d.attrib
            == {"print-object": "no", "print-spacing": "no", **({"number": "2"} if bundled else {})}
            for d in details
        )
        assert root.findtext(".//pitch/step") == "C"


def test_cutaway_policy_is_retained_without_globally_hiding_a_staff() -> None:
    score = _score("cutaway")
    assert score.parts[1].staff_hide_mode == "cutaway"
    assert score.diagnostics[0].code == "staff-cutaway-geometry"
    assert ET.fromstring(to_musicxml(score)).find(".//staff-details") is None


def test_unknown_policy_is_a_clear_source_error() -> None:
    with pytest.raises(CorruptScoreError, match="hideMode"):
        _score("unknown")
