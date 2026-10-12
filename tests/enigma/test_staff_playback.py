"""Authored staff routes identify instruments independently of braces or names."""

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Score


def _score(*, second_route: int = 0, first_play: bool = True, second_solo: bool = False) -> Score:
    raw = '<finale><others><measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>'
    for i, route in ((1, 0), (2, second_route)):
        play = i == 2 or first_play
        raw += f'''<staffSpec cmper="{i}"/><frameSpec cmper="{i}">
          <startEntry>{i}</startEntry><endEntry>{i}</endEntry></frameSpec>
          <staffPlayData cmper="{i}"><layer1><playbackRouteNum>{route}</playbackRouteNum>
            {"<play/>" if play else ""}{"<solo/>" if i == 2 and second_solo else ""}
          </layer1></staffPlayData>'''
    raw += "</others><details>"
    raw += "".join(f'<gfhold cmper1="{i}" cmper2="1"><frame1>{i}</frame1></gfhold>' for i in (1, 2))
    raw += "</details><entries>"
    raw += "".join(
        f'''<entry entnum="{i}" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
      <note><harmLev>{i}</harmLev><harmAlt>0</harmAlt></note></entry>'''
        for i in (1, 2)
    )
    return build_score(parse_enigma((raw + "</entries></finale>").encode()))


def test_same_explicit_route_forms_one_musicxml_instrument_with_two_staves() -> None:
    score = _score()
    assert [p.instrument_id for p in score.parts] == ["source-instrument:1"] * 2
    root = DET.fromstring(to_musicxml(score))
    assert len(root.findall("part")) == 1 and root.findtext(".//attributes/staves") == "2"
    assert len(root.findall(".//pitch")) == 2


def test_different_source_instruments_are_not_joined_by_similar_staff_names() -> None:
    assert len(DET.fromstring(to_musicxml(_score(second_route=1))).findall("part")) == 2


@pytest.mark.parametrize("first_play,second_solo", [(False, False), (True, True)])
def test_disabled_or_non_solo_layers_remain_written_and_export_silently(
    first_play: bool, second_solo: bool
) -> None:
    score = _score(first_play=first_play, second_solo=second_solo)
    assert not score.parts[0].measures[0].voices[0].playback
    root = DET.fromstring(to_musicxml(score))
    assert root.findall(".//note")[0].find("cue") is not None
    assert root.findtext(".//defaults/appearance/note-size") == "100"
    assert root.findall(".//note")[1].find("cue") is None


def test_exact_source_slots_keep_route_ids_play_flags_and_velocity_controls_separate() -> None:
    payload = b"".join(value.to_bytes(2, "little") for _ in range(6) for value in (2, 101, 33, 3))
    record = _others_records((MusOther(230, 1, 0, payload),), "cp1252")[0]
    control = record.fields["layer4"]
    assert not isinstance(control, (str, tuple))
    assert control.fields == {
        "playbackRouteNum": "2",
        "velControlLevel": "101",
        "velControlSaveFlags": "33",
        "play": "",
        "solo": "",
    }


def test_partial_staff_playback_data_raises_a_bounded_error() -> None:
    with pytest.raises(CorruptScoreError, match="eight-byte controls"):
        _others_records((MusOther(230, 1, 0, bytes(47)),), "cp1252")
