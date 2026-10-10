"""Synthetic, authored score fragments exercise the reader -> IR -> XML path.

No music from the local Scars of Time investigation is used as a fixture here.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Fermata, NoteTies, Ornament, Score


def _score(
    *notes: str,
    others: str = "",
    details: str = "",
    key: int = 0,
    transposition: str = "",
) -> Score:
    """One linked, synthetic entry; optional definitions are not placed implicitly."""
    xml = f"""
    <finale version="18.0" xmlns="http://www.makemusic.com/2012/finale">
      <others>
        <frameSpec cmper="10" inci="0"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
        <measSpec cmper="1">
          <keySig><key>{key}</key></keySig><beats>1</beats><divbeat>1024</divbeat>
        </measSpec>
        <staffSpec cmper="1">{transposition}</staffSpec>
        {others}
      </others>
      <details>
        <gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold>
        {details}
      </details>
      <entries>
        <entry entnum="1" prev="0" next="0">
          <dura>1024</dura><numNotes>{len(notes)}</numNotes>{"".join(notes)}
        </entry>
      </entries>
    </finale>
    """
    return build_score(parse_enigma(xml.encode()))


def _note(level: int, flags: str = "", alteration: int = 0) -> str:
    return f"<note><harmLev>{level}</harmLev><harmAlt>{alteration}</harmAlt>{flags}</note>"


@pytest.mark.parametrize(
    ("flag", "ties", "xml_type"),
    [("tieStart", NoteTies(start=True), "start"), ("tieEnd", NoteTies(stop=True), "stop")],
)
def test_a_tie_on_one_chord_pitch_does_not_spread_to_the_others(
    flag: str, ties: NoteTies, xml_type: str
) -> None:
    """Also preserve an unmatched stop: repairing source ties is not the reader's job."""
    score = _score(_note(0), _note(2), _note(4, f"<{flag}/>"))
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.note_ties == (NoteTies(), NoteTies(), ties)
    assert event.tie_start == ties.start
    assert event.tie_end == ties.stop
    notes = DET.fromstring(to_musicxml(score)).findall("./part/measure/note")
    assert [note.findtext("pitch/step") for note in notes] == ["C", "E", "G"]
    for path in ("tie", "notations/tied"):
        assert [[tie.get("type") for tie in note.findall(path)] for note in notes] == [
            [],
            [],
            [xml_type],
        ]


_MORDENT_DEF = '<articDef cmper="1"><charMain>109</charMain></articDef>'
_MORDENT_ASSIGN = '<articAssign entnum="1" inci="0"><articDef>1</articDef></articAssign>'
_BB_TRANSPOSITION = """
    <transposition><keysig><interval>1</interval><adjust>2</adjust></keysig></transposition>
"""


@pytest.mark.parametrize(
    ("key", "level", "alteration", "transposition", "pitch", "distance"),
    [
        (0, 0, 0, "", "C", 2),
        (0, 6, 0, "", "B", 1),  # B4 -> C5 crosses the octave boundary.
        (257, 1, 0, "", "F", 1),  # E minor: F# -> G, not F -> G.
        (257, 0, 0, "", "E", 2),  # E minor: E -> F#.
        (0, 0, 1, "", "C", 1),  # A chromatic main note: C# -> D.
        (0, 0, -1, "", "C", None),  # Cb -> D exceeds the supported ornament steps.
        (0, 2, 0, _BB_TRANSPOSITION, "F", 1),  # Written key is D major.
    ],
)
def test_assigned_upper_mordents_reach_xml_with_the_key_neighbor(
    key: int,
    level: int,
    alteration: int,
    transposition: str,
    pitch: str,
    distance: int | None,
) -> None:
    score = _score(
        _note(level, alteration=alteration),
        others=_MORDENT_DEF,
        details=_MORDENT_ASSIGN,
        key=key,
        transposition=transposition,
    )
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.ornaments == (Ornament("upper-mordent", distance),)
    root = DET.fromstring(to_musicxml(score))
    assert root.findtext(".//note/pitch/step") == pitch
    ornament = root.find(".//inverted-mordent")
    assert ornament is not None
    assert ornament.get("trill-step") == {None: None, 1: "half", 2: "whole"}[distance]


@pytest.mark.parametrize(
    ("definition", "assignment"),
    [
        (_MORDENT_DEF, ""),  # A library is not usage.
        ("", _MORDENT_ASSIGN),  # Missing definition.
        (_MORDENT_DEF.replace("109", "217"), _MORDENT_ASSIGN),  # Unknown glyph.
        (_MORDENT_DEF.replace('cmper="1"', 'cmper="1" part="1"'), _MORDENT_ASSIGN),
        (_MORDENT_DEF, _MORDENT_ASSIGN.replace('entnum="1"', 'entnum="1" part="1"')),
    ],
)
def test_unsupported_or_unassigned_ornaments_do_not_reach_the_score(
    definition: str, assignment: str
) -> None:
    score = _score(_note(0), others=definition, details=assignment)
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.ornaments == ()
    assert DET.fromstring(to_musicxml(score)).find(".//ornaments") is None


_FERMATA_DEF = '<articDef cmper="1"><charMain>85</charMain><charAlt>117</charAlt></articDef>'
_FERMATA_ASSIGN = '<articAssign entnum="1" inci="0"><articDef>1</articDef></articAssign>'


@pytest.mark.parametrize(
    ("character", "inverted", "xml_type"), [(85, False, "upright"), (117, True, "inverted")]
)
@pytest.mark.parametrize("levels", [(0,), (0, 2, 4), ()])
def test_assigned_fermatas_reach_notes_chords_and_rests_without_changing_rhythm(
    character: int, inverted: bool, xml_type: str, levels: tuple[int, ...]
) -> None:
    score = _score(
        *(_note(level) for level in levels),
        others=_FERMATA_DEF.replace("<charMain>85", f"<charMain>{character}"),
        details=_FERMATA_ASSIGN,
    )
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.fermatas == (Fermata(inverted=inverted),)
    assert event.duration == event.written_duration == Fraction(1, 4)
    root = DET.fromstring(to_musicxml(score))
    notes = root.findall("./part/measure/note")
    assert len(notes) == max(1, len(levels))
    fermatas = root.findall(".//fermata")
    assert len(fermatas) == 1
    assert notes[0].find("notations/fermata") is fermatas[0]
    assert fermatas[0].get("type") == xml_type
    assert not fermatas[0].text  # Empty content is the normal rounded shape.
    assert [note.findtext("duration") for note in notes] == ["1"] * len(notes)
    assert root.find(".//sound") is None


@pytest.mark.parametrize(
    ("definition", "assignment"),
    [
        (_FERMATA_DEF, ""),
        ("", _FERMATA_ASSIGN),
        (_FERMATA_DEF.replace("<charMain>85", "<charMain>217"), _FERMATA_ASSIGN),
        (_FERMATA_DEF.replace('cmper="1"', 'cmper="1" part="1"'), _FERMATA_ASSIGN),
        (_FERMATA_DEF, _FERMATA_ASSIGN.replace('entnum="1"', 'entnum="1" part="1"')),
        (_FERMATA_DEF, _FERMATA_ASSIGN.replace("<articDef>1", "<articDef>invalid")),
    ],
)
def test_unsupported_or_unassigned_fermatas_do_not_reach_the_score(
    definition: str, assignment: str
) -> None:
    score = _score(_note(0), others=definition, details=assignment)
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.fermatas == ()
    assert DET.fromstring(to_musicxml(score)).find(".//fermata") is None
