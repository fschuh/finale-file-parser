"""Authored fragments cover grace slashes from EnigmaXML through exported XML."""

from __future__ import annotations

from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Beam, Score


def _entry(
    number: int,
    duration: int,
    *,
    grace: bool = False,
    slash: bool = False,
    beam: bool = False,
    levels: tuple[int, ...] = (0,),
) -> str:
    flags = ("<graceNote/>" if grace else "") + ("<slashGrace/>" if slash else "")
    flags += "<beam/>" if beam else ""
    notes = "".join(
        f"<note><harmLev>{level}</harmLev><harmAlt>0</harmAlt></note>" for level in levels
    )
    return (
        f'<entry entnum="{number}" prev="{number - 1}" next="{number + 1}">'
        f"<dura>{duration}</dura><numNotes>{len(levels)}</numNotes>{flags}{notes}</entry>"
    )


def _score(*entries: str, always_slash: bool | None, option_attrs: str = "") -> Score:
    options = ""
    if always_slash is not None:
        flag = "<slashFlaggedGraceNotes/>" if always_slash else ""
        options = f"<options><graceNoteOptions{option_attrs}>{flag}</graceNoteOptions></options>"
    xml = f"""
    <finale>
      {options}
      <others>
        <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
        <frameSpec cmper="10">
          <startEntry>1</startEntry><endEntry>{len(entries)}</endEntry>
        </frameSpec>
      </others>
      <details><gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold></details>
      <entries>{"".join(entries)}</entries>
    </finale>
    """
    return build_score(parse_enigma(xml.encode()))


@pytest.mark.parametrize("always_slash", [None, False, True])
@pytest.mark.parametrize("individual_slash", [False, True])
def test_global_or_individual_slash_preserves_a_flagged_grace_chord(
    always_slash: bool | None, individual_slash: bool
) -> None:
    score = _score(
        _entry(1, 512, grace=True, slash=individual_slash, levels=(0, 2)),
        _entry(2, 1024),
        always_slash=always_slash,
    )
    grace, main = score.parts[0].measures[0].voices[0].events
    expected = True if individual_slash else always_slash
    assert grace.grace_slash is expected
    assert grace.duration == 0 and grace.written_duration == Fraction(1, 8)
    assert main.duration == main.written_duration == Fraction(1, 4)
    assert main.grace_slash is None
    notes = DET.fromstring(to_musicxml(score)).findall("./part/measure/note")
    attrs = {} if expected is None else {"slash": "yes" if expected else "no"}
    for note in notes[:2]:
        element = note.find("grace")
        assert element is not None and element.attrib == attrs
        assert note.find("duration") is None
        assert note.findtext("type") == "eighth"
    assert [element.tag for element in notes[1]][:3] == ["grace", "chord", "pitch"]
    assert notes[2].find("grace") is None


def test_beamed_graces_keep_their_beams_and_do_not_receive_automatic_slashes() -> None:
    score = _score(
        _entry(1, 512, grace=True, slash=True),
        _entry(2, 256, grace=True),
        _entry(3, 512),
        always_slash=True,
    )
    first, second, main = score.parts[0].measures[0].voices[0].events
    assert first.beams == (Beam(1, "begin"),)
    assert second.beams == (Beam(1, "end"), Beam(2, "backward hook"))
    assert first.grace_slash is second.grace_slash is False
    assert main.beams == ()
    root = DET.fromstring(to_musicxml(score))
    assert [item.get("slash") for item in root.findall(".//grace")] == ["no", "no"]
    assert [item.text for item in root.findall(".//beam")] == ["begin", "end", "backward hook"]


def test_the_beam_break_bit_makes_two_consecutive_graces_flagged() -> None:
    score = _score(
        _entry(1, 512, grace=True),
        _entry(2, 512, grace=True, beam=True),
        _entry(3, 1024),
        always_slash=True,
    )
    events = score.parts[0].measures[0].voices[0].events
    assert [event.beams for event in events] == [(), (), ()]
    assert [event.grace_slash for event in events] == [True, True, None]


def test_an_ordinary_beam_spans_a_separately_flagged_grace() -> None:
    score = _score(
        _entry(1, 512, beam=True),
        _entry(2, 512, grace=True),
        _entry(3, 512),
        always_slash=True,
    )
    first, grace, last = score.parts[0].measures[0].voices[0].events
    assert first.beams == (Beam(1, "begin"),)
    assert last.beams == (Beam(1, "end"),)
    assert grace.beams == () and grace.grace_slash is True
    assert sum(event.duration for event in (first, grace, last)) == Fraction(1, 4)


@pytest.mark.parametrize("duration", [32, 256, 512, 768])
def test_short_written_values_with_flags_can_receive_slashes(duration: int) -> None:
    score = _score(_entry(1, duration, grace=True), always_slash=True)
    assert score.parts[0].measures[0].voices[0].events[0].grace_slash is True


@pytest.mark.parametrize("duration", [1024, 1536, 2048, 4096])
def test_graces_without_flags_ignore_both_slash_settings(duration: int) -> None:
    score = _score(_entry(1, duration, grace=True, slash=True), always_slash=True)
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.grace_slash is False and event.duration == 0


def test_a_grace_rest_does_not_receive_a_slash() -> None:
    score = _score(_entry(1, 512, grace=True, slash=True, levels=()), always_slash=True)
    assert score.parts[0].measures[0].voices[0].events[0].grace_slash is False


def test_an_individual_flag_on_an_ordinary_note_does_not_make_it_a_grace() -> None:
    score = _score(_entry(1, 512, slash=True), always_slash=True)
    event = score.parts[0].measures[0].voices[0].events[0]
    assert not event.is_grace and event.grace_slash is None
    assert DET.fromstring(to_musicxml(score)).find(".//grace") is None


def test_a_part_only_option_does_not_change_the_score() -> None:
    score = _score(_entry(1, 512, grace=True), always_slash=True, option_attrs=' part="1"')
    assert score.parts[0].measures[0].voices[0].events[0].grace_slash is None
