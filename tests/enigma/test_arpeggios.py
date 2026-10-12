"""Authored notation exercises recognition and conservative span resolution."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.arpeggios import arpeggios_by_entry, connect_arpeggios
from finale_file_parser.enigma.document import EnigmaDocument, Record, parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Arpeggio, Event, Measure, Part, PartGroup, Pitch, Voice


def _document(
    *,
    character: str = "103",
    definition_attrs: str = "",
    assignment_attrs: str = "",
    definition_flags: str = "",
    assignment_flags: str = "",
    extension: str = "-240",
    distance: str = "-240",
    layout_attrs: str = "",
) -> EnigmaDocument:
    return parse_enigma(
        f"""
    <finale>
      <options><clefOptions>
        <clefDef index="0"><clefChar>38</clefChar><adjust>-10</adjust></clefDef>
        <clefDef index="1"><clefChar>63</clefChar><adjust>2</adjust></clefDef>
      </clefOptions></options>
      <others>
        <articDef cmper="1"{definition_attrs}>
          <charMain>{character}</charMain>{definition_flags}
        </articDef>
        <instUsed cmper="0" inci="0"{layout_attrs}>
          <inst>1</inst><distFromTop>0</distFromTop>
        </instUsed>
        <instUsed cmper="0" inci="1"{layout_attrs}>
          <inst>2</inst><distFromTop>{distance}</distFromTop>
        </instUsed>
        <staffSpec cmper="1"/><staffSpec cmper="2"><defaultClef>1</defaultClef></staffSpec>
        <measSpec cmper="1"><beats>1</beats><divbeat>1024</divbeat></measSpec>
        <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
        <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>2</endEntry></frameSpec>
      </others>
      <details>
        <articAssign entnum="1"{assignment_attrs}>
          <articDef>1</articDef><vertAdd>{extension}</vertAdd>{assignment_flags}
        </articAssign>
        <gfhold cmper1="1" cmper2="1"><frame1>1</frame1><clefID>0</clefID></gfhold>
        <gfhold cmper1="2" cmper2="1"><frame1>2</frame1><clefID>1</clefID></gfhold>
        <staffGroup cmper1="0" cmper2="1">
          <startInst>1</startInst><endInst>2</endInst><bracket><id>3</id></bracket>
        </staffGroup>
      </details>
      <entries>
        <entry entnum="1" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
          <note><harmLev>7</harmLev><harmAlt>0</harmAlt></note>
          <note><harmLev>9</harmLev><harmAlt>0</harmAlt></note>
        </entry>
        <entry entnum="2" prev="0" next="0"><dura>1024</dura><numNotes>2</numNotes>
          <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
          <note><harmLev>2</harmLev><harmAlt>0</harmAlt></note>
        </entry>
      </entries>
    </finale>
    """.encode()
    )


def test_an_assigned_plain_arpeggio_is_distinct_from_an_articulation() -> None:
    assert arpeggios_by_entry(_document()) == {1: (Arpeggio(),)}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"character": "109"},
        {"character": "85"},
        {"character": "nonsense"},
        {"definition_attrs": ' part="1"'},
        {"assignment_attrs": ' part="1"'},
        {"definition_flags": "<mainIsShape/>"},
        {"assignment_flags": "<hide/>"},
    ],
)
def test_other_symbols_and_part_or_hidden_variants_do_not_place_arpeggios(
    kwargs: dict[str, str],
) -> None:
    assert arpeggios_by_entry(_document(**kwargs)) == {}


def test_a_library_definition_without_an_assignment_does_not_place_a_sign() -> None:
    document = _document()
    document.details = replace(
        document.details,
        records=tuple(record for record in document.details.records if record.tag != "articAssign"),
    )
    assert arpeggios_by_entry(document) == {}


def _parts() -> tuple[Part, ...]:
    def staff(number: int, clef: str, line: int, pitches: tuple[Pitch, ...], marked: bool) -> Part:
        event = Event(
            Fraction(1, 4), Fraction(1, 4), pitches, arpeggios=(Arpeggio(),) if marked else ()
        )
        return Part(
            f"P{number}",
            "Keyboard",
            (
                Measure(
                    1,
                    (Voice(1, (event,)),),
                    clef_sign=clef,
                    clef_line=line,
                ),
            ),
        )

    return (
        staff(1, "G", 2, (Pitch("C", 5, 0), Pitch("E", 5, 0)), True),
        staff(2, "F", 4, (Pitch("C", 4, 0), Pitch("E", 4, 0)), False),
    )


_BRACE = (PartGroup(("P1", "P2"), "brace"),)
_ORIGIN = {("P1", 1, 1, 0): 1}


def test_the_clone_endpoint_connects_the_simultaneous_lower_chord() -> None:
    parts = _parts()
    connected = connect_arpeggios(_document(), parts, _BRACE, _ORIGIN)
    marks = [part.measures[0].voices[0].events[0].arpeggios for part in connected]
    assert marks[0] == marks[1] and marks[0][0].part_ids == ("P1", "P2")
    assert marks[0][0].group is not None
    for before, after in zip(parts, connected, strict=True):
        assert (
            replace(
                after.measures[0].voices[0].events[0],
                arpeggios=before.measures[0].voices[0].events[0].arpeggios,
            )
            == before.measures[0].voices[0].events[0]
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"extension": "-24"},
        {"extension": "0"},
        {"extension": "120"},
        {"extension": "invalid"},
        {"distance": "invalid"},
        {"layout_attrs": ' part="1"'},
    ],
)
def test_missing_geometry_or_an_endpoint_above_the_lower_chord_keeps_one_staff(
    kwargs: dict[str, str],
) -> None:
    parts = _parts()
    assert connect_arpeggios(_document(**kwargs), parts, _BRACE, _ORIGIN) == parts


def test_a_brace_without_a_source_extension_does_not_invent_a_roll() -> None:
    parts = _parts()
    assert connect_arpeggios(_document(), parts, (), _ORIGIN) == parts
    assert (
        connect_arpeggios(_document(), parts, (replace(_BRACE[0], symbol="bracket"),), _ORIGIN)
        == parts
    )


@pytest.mark.parametrize(
    "kind", ["rest", "grace", "already_marked", "percussion", "late", "ambiguous"]
)
def test_only_one_complete_unmarked_ordinary_chord_at_the_same_time_connects(kind: str) -> None:
    upper, lower = _parts()
    measure = lower.measures[0]
    event = measure.voices[0].events[0]
    if kind == "rest":
        event = replace(event, pitches=())
    elif kind == "grace":
        event = replace(event, is_grace=True, duration=Fraction(0))
    elif kind == "already_marked":
        event = replace(event, arpeggios=(Arpeggio(),))
    events: tuple[Event, ...] = (event,)
    if kind == "late":
        events = (
            replace(event, pitches=(), duration=Fraction(1, 8), written_duration=Fraction(1, 8)),
            event,
        )
    voices: tuple[Voice, ...] = (Voice(1, events),)
    if kind == "ambiguous":
        voices += (Voice(2, (event,)),)
    measure = replace(
        measure, voices=voices, clef_sign="percussion" if kind == "percussion" else "F"
    )
    parts = (upper, replace(lower, measures=(measure,)))
    assert connect_arpeggios(_document(), parts, _BRACE, _ORIGIN) == parts


def test_clefs_carry_into_a_later_measure_for_span_geometry() -> None:
    parts = tuple(
        replace(
            part,
            measures=(
                part.measures[0],
                replace(part.measures[0], number=2, clef_sign=None, clef_line=None),
            ),
        )
        for part in _parts()
    )
    connected = connect_arpeggios(_document(), parts, _BRACE, {("P1", 2, 1, 0): 1})
    assert connected[1].measures[1].voices[0].events[0].arpeggios[0].part_ids == ("P1", "P2")
    assert connected[1].measures[1].clef_sign is None


def test_an_assignment_on_an_excluded_staff_is_ignored_by_span_resolution() -> None:
    parts = _parts()
    assert connect_arpeggios(_document(), parts, _BRACE, {("P32767", 1, 1, 0): 1}) == parts


def test_enigmaxml_to_ir_to_musicxml_preserves_the_connected_sign() -> None:
    score = build_score(_document())
    assert len(score.parts) == 2
    assert score.parts[0].measures[0].voices[0].events[0].pitches == (
        Pitch("C", 5, 0),
        Pitch("E", 5, 0),
    )
    assert score.parts[1].measures[0].voices[0].events[0].pitches == (
        Pitch("C", 4, 0),
        Pitch("E", 4, 0),
    )
    root = DET.fromstring(to_musicxml(score))
    assert len(root.findall("part")) == 1
    assert root.findtext("part/measure/attributes/staves") == "2"
    assert [note.findtext("staff") for note in root.findall("part/measure/note")] == [
        "1",
        "1",
        "2",
        "2",
    ]
    marks = root.findall(".//arpeggiate")
    assert len(marks) == 4 and all(
        mark.attrib == {"number": "1", "unbroken": "yes"} for mark in marks
    )


def _with_arrow(
    *,
    font: str = "Maestro",
    x: str = "-67",
    y: str = "-46",
    arrow_flags: dict[str, str] | None = None,
    definition_flags: dict[str, str] | None = None,
    arrow_attrs: dict[str, str] | None = None,
    duplicate: bool = False,
) -> EnigmaDocument:
    doc = _document()
    doc.others = replace(
        doc.others,
        records=(
            *doc.others.records,
            Record("fontName", {"cmper": "7"}, "", {"name": font}),
            Record(
                "articDef",
                {"cmper": "7"},
                "",
                {"charMain": "224", "fontMain": "7", **(definition_flags or {})},
            ),
        ),
    )
    arrow = Record(
        "articAssign",
        {"entnum": "1", "inci": "1", **(arrow_attrs or {})},
        "",
        {"articDef": "7", "horzOff": x, "vertOff": y, **(arrow_flags or {})},
    )
    doc.details = replace(
        doc.details,
        records=(
            *(
                replace(r, fields={**r.fields, "horzOff": "-42", "vertOff": "-24"})
                if r.tag == "articAssign"
                else r
                for r in doc.details.records
            ),
            arrow,
            *((replace(arrow, attrs={**arrow.attrs, "inci": "2"}),) if duplicate else ()),
        ),
    )
    return doc


def test_a_maestro_triangle_at_the_bottom_of_one_roll_sets_downward_direction() -> None:
    assert arpeggios_by_entry(_with_arrow()) == {1: (Arpeggio(direction="down"),)}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"font": "Times New Roman"},
        {"font": "Unestablished Music Font"},
        {"x": "12"},
        {"x": "invalid"},
        {"y": "12"},
        {"y": "invalid"},
        {"arrow_flags": {"hide": ""}},
        {"definition_flags": {"mainIsShape": ""}},
        {"arrow_attrs": {"part": "1"}},
        {"arrow_attrs": {"entnum": "2"}},
        {"duplicate": True},
    ],
)
def test_a_triangle_without_unambiguous_source_context_does_not_add_an_arrow(
    kwargs: dict[str, object],
) -> None:
    doc = _with_arrow(**kwargs)  # type: ignore[arg-type]
    assert arpeggios_by_entry(doc) == {1: (Arpeggio(),)}


def test_a_standalone_triangle_does_not_create_a_roll() -> None:
    doc = _with_arrow()
    doc.details = replace(
        doc.details,
        records=tuple(
            r
            for r in doc.details.records
            if r.tag != "articAssign" or r.fields.get("articDef") == "7"
        ),
    )
    assert arpeggios_by_entry(doc) == {}


def test_downward_direction_survives_a_connected_staff_span_and_musicxml() -> None:
    score = build_score(_with_arrow())
    marks = [p.measures[0].voices[0].events[0].arpeggios[0] for p in score.parts]
    assert marks[0] == marks[1]
    assert marks[0].direction == "down" and marks[0].part_ids == ("P1", "P2")
    xml = DET.fromstring(to_musicxml(score))
    assert [m.get("direction") for m in xml.findall(".//arpeggiate")] == ["down"] * 4


def test_partial_chord_coverage_does_not_expand_to_another_staff() -> None:
    upper, lower = _parts()
    event = upper.measures[0].voices[0].events[0]
    event = replace(event, arpeggios=(Arpeggio(pitch_indices=(1,), direction="down"),))
    upper = replace(
        upper,
        measures=(replace(upper.measures[0], voices=(Voice(1, (event,)),)),),
    )
    assert connect_arpeggios(_document(), (upper, lower), _BRACE, _ORIGIN) == (upper, lower)
