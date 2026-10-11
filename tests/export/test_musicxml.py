"""Tests for the MusicXML exporter."""

from __future__ import annotations

from fractions import Fraction

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import ExportError, prints_as_words, to_musicxml
from finale_file_parser.formats.dynamics import DYNAMICS
from finale_file_parser.ir import (
    Beam,
    Ending,
    Event,
    Expression,
    Fermata,
    Lyric,
    Measure,
    NoteTies,
    Ornament,
    Part,
    PartGroup,
    Pitch,
    Score,
    Tempo,
    TimeSignature,
    Voice,
)

QUARTER = Fraction(1, 4)
EIGHTH = Fraction(1, 8)
TRIPLET_EIGHTH = Fraction(1, 12)


def _score(*events: Event, **measure_kwargs: object) -> Score:
    measure = Measure(number=1, voices=(Voice(number=1, events=events),), **measure_kwargs)  # type: ignore[arg-type]
    return Score(parts=(Part(id="P1", name="Flute", measures=(measure,)),))


def _tree(score: Score):  # type: ignore[no-untyped-def]
    return DET.fromstring(to_musicxml(score).decode())


def _note(**kwargs: object) -> Event:
    base: dict[str, object] = {
        "duration": QUARTER,
        "written_duration": QUARTER,
        "pitches": (Pitch("C", 4, 0),),
    }
    base.update(kwargs)
    return Event(**base)  # type: ignore[arg-type]


def test_emits_a_well_formed_document() -> None:
    root = _tree(_score(_note()))
    assert root.tag == "score-partwise"
    assert root.findtext("./part-list/score-part/part-name") == "Flute"
    assert root.findtext("./part/measure/note/pitch/step") == "C"


def test_caesura_and_fermata_on_a_chord_are_emitted_once() -> None:
    root = _tree(
        _score(
            _note(
                pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0)),
                articulations=("caesura",),
                fermatas=(Fermata(),),
            )
        )
    )
    assert len(root.findall(".//caesura")) == len(root.findall(".//fermata")) == 1
    assert root.find("./part/measure/note/notations/articulations/caesura") is not None


def test_divisions_accommodate_triplets() -> None:
    """A triplet eighth is 1/12 of a whole note.

    With divisions=1 its duration rounds to zero, so the count must clear the
    denominator -- here 3 per quarter.
    """
    root = _tree(
        _score(_note(duration=TRIPLET_EIGHTH, written_duration=EIGHTH, tuplet_ratio=Fraction(2, 3)))
    )
    assert root.findtext("./part/measure/attributes/divisions") == "3"
    assert root.findtext("./part/measure/note/duration") == "1"


def test_tuplet_emits_time_modification_the_right_way_round() -> None:
    """A triplet is 3 notes in the time of 2, while its sounded ratio is 2/3."""
    root = _tree(
        _score(_note(duration=TRIPLET_EIGHTH, written_duration=EIGHTH, tuplet_ratio=Fraction(2, 3)))
    )
    modification = root.find("./part/measure/note/time-modification")
    assert modification is not None
    assert modification.findtext("actual-notes") == "3"
    assert modification.findtext("normal-notes") == "2"


def test_grace_notes_omit_duration_entirely() -> None:
    """The schema requires duration > 0, and a grace note has none.

    Writing zero fails validation -- this is the bug the W3C schema caught on real
    corpus output, not a hypothetical.
    """
    root = _tree(_score(_note(duration=Fraction(0), is_grace=True), _note()))
    notes = root.findall("./part/measure/note")
    assert notes[0].find("grace") is not None
    assert notes[0].find("duration") is None
    assert notes[1].find("grace") is None
    assert notes[1].findtext("duration") == "1"


def test_grace_notes_do_not_affect_divisions() -> None:
    """A zero duration must not drag the divisions calculation."""
    root = _tree(_score(_note(duration=Fraction(0), is_grace=True), _note()))
    assert root.findtext("./part/measure/attributes/divisions") == "1"


@pytest.mark.parametrize(
    ("slash", "attrs"), [(None, {}), (False, {"slash": "no"}), (True, {"slash": "yes"})]
)
def test_grace_slash_preserves_known_style_and_leaves_unknown_style_unspecified(
    slash: bool | None, attrs: dict[str, str]
) -> None:
    root = _tree(_score(_note(duration=Fraction(0), is_grace=True, grace_slash=slash), _note()))
    element = root.find(".//grace")
    assert element is not None and element.attrib == attrs
    note = root.find("./part/measure/note")
    assert note is not None and note.find("duration") is None


def test_grace_slash_is_ignored_on_an_ordinary_authored_event() -> None:
    assert _tree(_score(_note(grace_slash=True))).find(".//grace") is None


def test_chord_marks_only_the_notes_after_the_first() -> None:
    root = _tree(_score(_note(pitches=(Pitch("C", 4, 0), Pitch("E", 4, 1), Pitch("G", 4, 0)))))
    notes = root.findall("./part/measure/note")
    assert [n.find("chord") is None for n in notes] == [True, False, False]
    assert notes[1].findtext("./pitch/alter") == "1"


def test_rest_has_no_pitch() -> None:
    root = _tree(_score(_note(pitches=())))
    note = root.find("./part/measure/note")
    assert note is not None
    assert note.find("rest") is not None
    assert note.find("pitch") is None


def test_ties_emit_both_sound_and_notation() -> None:
    """`<tie>` is the sounding instruction, `<tied>` the visual slur.

    Most applications need both for a tie to survive a round trip.
    """
    root = _tree(_score(_note(tie_start=True, tie_end=True)))
    note = root.find("./part/measure/note")
    assert note is not None
    assert {t.get("type") for t in note.findall("tie")} == {"start", "stop"}
    assert {t.get("type") for t in note.findall("./notations/tied")} == {"start", "stop"}


def test_a_chord_can_have_different_ties_on_each_pitch() -> None:
    root = _tree(
        _score(
            _note(
                pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0), Pitch("G", 4, 0)),
                tie_start=True,
                tie_end=True,
                note_ties=(NoteTies(), NoteTies(stop=True), NoteTies(start=True, stop=True)),
            )
        )
    )
    notes = root.findall("./part/measure/note")
    expected = [[], ["stop"], ["stop", "start"]]
    assert [[tie.get("type") for tie in note.findall("tie")] for note in notes] == expected
    assert [
        [tie.get("type") for tie in note.findall("./notations/tied")] for note in notes
    ] == expected


def test_explicit_false_note_ties_override_the_legacy_flags() -> None:
    root = _tree(_score(_note(tie_start=True, tie_end=True, note_ties=(NoteTies(),))))
    assert root.findall(".//tie") == []
    assert root.findall(".//tied") == []


def test_authored_chords_without_note_ties_keep_the_legacy_behavior() -> None:
    root = _tree(_score(_note(pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0)), tie_start=True)))
    assert len(root.findall(".//tie[@type='start']")) == 2
    assert len(root.findall(".//tied[@type='start']")) == 2


def test_per_note_tie_flags_must_match_the_pitches() -> None:
    with pytest.raises(ExportError, match="tie flags must match"):
        to_musicxml(_score(_note(note_ties=(NoteTies(), NoteTies()))))


@pytest.mark.parametrize(("distance", "step"), [(None, None), (1, "half"), (2, "whole")])
def test_upper_mordent_uses_the_unstruck_musicxml_symbol(
    distance: int | None, step: str | None
) -> None:
    root = _tree(_score(_note(ornaments=(Ornament("upper-mordent", distance),))))
    ornament = root.find(".//notations/ornaments/inverted-mordent")
    assert ornament is not None
    assert ornament.get("start-note") == "main"
    assert ornament.get("trill-step") == step
    assert root.findall(".//mordent") == []


def test_chord_ornaments_appear_once_alongside_other_notations() -> None:
    root = _tree(
        _score(
            _note(
                pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0)),
                note_ties=(NoteTies(start=True), NoteTies()),
                articulations=("staccato",),
                fingerings=("1",),
                ornaments=(Ornament("upper-mordent", 2),),
            )
        )
    )
    notes = root.findall("./part/measure/note")
    assert len(notes[0].findall("notations")) == 1
    assert notes[1].find("notations") is None
    assert len(root.findall(".//inverted-mordent")) == 1
    assert root.find(".//tied") is not None
    assert root.find(".//staccato") is not None
    assert root.findtext(".//fingering") == "1"


@pytest.mark.parametrize("ornament", [Ornament("unknown"), Ornament("upper-mordent", 3)])
def test_unsupported_ornaments_raise(ornament: Ornament) -> None:
    with pytest.raises(ExportError, match="ornament|auxiliary"):
        to_musicxml(_score(_note(ornaments=(ornament,))))


@pytest.mark.parametrize(
    ("unit", "dots", "rate", "expected_unit", "expected_rate", "expected_bpm"),
    [
        (QUARTER, 0, Fraction(120), "quarter", "120", "120"),
        (Fraction(1, 2), 0, Fraction(60), "half", "60", "120"),
        (EIGHTH, 1, Fraction(80), "eighth", "80", "60"),
        (QUARTER, 2, Fraction(40), "quarter", "40", "70"),
        (QUARTER, 0, Fraction(165, 2), "quarter", "82.5", "82.5"),
    ],
)
def test_metronome_marking_emits_quarter_note_playback_tempo(
    unit: Fraction,
    dots: int,
    rate: Fraction,
    expected_unit: str,
    expected_rate: str,
    expected_bpm: str,
) -> None:
    expression = Expression(
        text="source marking", category="tempoMarks", tempo=Tempo(unit, rate, dots)
    )
    root = _tree(_score(_note(), expressions=(expression,)))
    metronome = root.find(".//metronome")
    assert metronome is not None
    assert metronome.findtext("beat-unit") == expected_unit
    assert len(metronome.findall("beat-unit-dot")) == dots
    assert metronome.findtext("per-minute") == expected_rate
    sound = root.find(".//sound")
    assert sound is not None
    assert sound.get("tempo") == expected_bpm
    assert root.findall(".//words") == []
    assert not prints_as_words(expression)


def test_tempo_words_do_not_duplicate_the_metronome_marking() -> None:
    expression = Expression(
        text="Faster q = 112",
        category="tempoMarks",
        tempo=Tempo(QUARTER, Fraction(112), words="Faster"),
    )
    root = _tree(_score(_note(), expressions=(expression,)))
    assert [words.text for words in root.findall(".//words")] == ["Faster"]
    assert root.findtext(".//metronome/per-minute") == "112"
    assert prints_as_words(expression)


@pytest.mark.parametrize(
    "tempo",
    [
        Tempo(QUARTER, Fraction(0)),
        Tempo(QUARTER, Fraction(-1)),
        Tempo(QUARTER, Fraction(80), dots=-1),
        Tempo(QUARTER, Fraction(80), dots=4),
        Tempo(Fraction(3, 8), Fraction(80)),
    ],
)
def test_invalid_metronome_markings_raise(tempo: Tempo) -> None:
    with pytest.raises(ExportError, match="tempo"):
        to_musicxml(
            _score(_note(), expressions=(Expression(text="tempo", category="", tempo=tempo),))
        )


def test_dotted_note_type_is_the_undotted_base() -> None:
    """A dotted quarter is 3/8 of a whole, which is not a note value."""
    root = _tree(_score(_note(duration=Fraction(3, 8), written_duration=Fraction(3, 8), dots=1)))
    note = root.find("./part/measure/note")
    assert note is not None
    assert note.findtext("type") == "quarter"
    assert len(note.findall("dot")) == 1


def test_attributes_are_emitted_only_where_they_change() -> None:
    first = Measure(
        number=1,
        voices=(Voice(number=1, events=(_note(),)),),
        key_fifths=2,
        time=TimeSignature(4, 4),
        clef_sign="G",
        clef_line=2,
    )
    second = Measure(number=2, voices=(Voice(number=1, events=(_note(),)),))
    score = Score(parts=(Part(id="P1", name="P", measures=(first, second)),))
    measures = _tree(score).findall("./part/measure")
    assert measures[0].find("attributes") is not None
    assert measures[1].find("attributes") is None, "unchanged attributes must not repeat"


def test_second_voice_is_preceded_by_a_backup() -> None:
    measure = Measure(
        number=1,
        voices=(
            Voice(number=1, events=(_note(), _note())),
            Voice(number=2, events=(_note(),)),
        ),
    )
    root = _tree(Score(parts=(Part(id="P1", name="P", measures=(measure,)),)))
    backup = root.find("./part/measure/backup")
    assert backup is not None
    assert backup.findtext("duration") == "2", "must rewind by the first voice's full length"


def test_unrepresentable_duration_raises() -> None:
    with pytest.raises(ExportError, match="note value"):
        to_musicxml(_score(_note(written_duration=Fraction(5, 16))))


def test_a_lyric_is_emitted_with_its_syllabic_and_text() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            lyrics=(Lyric(number=1, text="ho", syllabic="begin"),),
        )
    )
    xml = to_musicxml(score).decode()
    assert '<lyric number="1">' in xml
    assert "<syllabic>begin</syllabic>" in xml
    assert "<text>ho</text>" in xml


def test_a_word_extension_emits_extend() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            lyrics=(Lyric(number=1, text="ah", syllabic="single", extend=True),),
        )
    )
    assert "<extend />" in to_musicxml(score).decode()


def test_a_chord_sings_its_syllable_once() -> None:
    """The syllable belongs to the event, not to each pitch: repeating it per
    note of a chord would make the part sing it three times."""
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(
                Pitch(step="C", alteration=0, octave=4),
                Pitch(step="E", alteration=0, octave=4),
            ),
            lyrics=(Lyric(number=1, text="ah", syllabic="single"),),
        )
    )
    assert to_musicxml(score).decode().count("<lyric ") == 1


def test_lyric_comes_after_notations_as_the_schema_requires() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            tie_start=True,
            lyrics=(Lyric(number=1, text="ah", syllabic="single"),),
        )
    )
    xml = to_musicxml(score).decode()
    assert xml.index("<notations>") < xml.index("<lyric ")


def test_articulations_are_emitted_inside_notations() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            articulations=("staccato", "accent"),
        )
    )
    xml = to_musicxml(score).decode()
    assert "<articulations>" in xml
    assert xml.index("<staccato />") < xml.index("<accent />")


def test_ties_and_articulations_share_one_notations_element() -> None:
    """The schema allows one <notations> per note, with <tied> before
    <articulations>."""
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            tie_start=True,
            articulations=("staccato",),
        )
    )
    xml = to_musicxml(score).decode()
    assert xml.count("<notations>") == 1
    assert xml.index("<tied ") < xml.index("<articulations>")


def test_a_chord_carries_its_articulation_once() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 4),
            written_duration=Fraction(1, 4),
            pitches=(
                Pitch(step="C", alteration=0, octave=4),
                Pitch(step="E", alteration=0, octave=4),
            ),
            articulations=("staccato",),
        )
    )
    assert to_musicxml(score).decode().count("<staccato />") == 1


def test_a_fermata_shares_notations_with_ties_and_other_chord_attachments() -> None:
    root = _tree(
        _score(
            _note(
                pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0)),
                note_ties=(NoteTies(start=True), NoteTies()),
                fermatas=(Fermata(),),
                articulations=("accent",),
                ornaments=(Ornament("upper-mordent"),),
                fingerings=("1", "3"),
                lyrics=(Lyric(1, "ah"),),
            )
        )
    )
    notes = root.findall(".//note")
    assert len(notes[0].findall("notations")) == 1
    notations = notes[0].find("notations")
    assert notations is not None
    assert [child.tag for child in notations] == [
        "tied",
        "fermata",
        "articulations",
        "ornaments",
        "technical",
    ]
    assert len(root.findall(".//fermata")) == 1
    fermata = notations.find("fermata")
    assert fermata is not None
    assert fermata.get("type") == "upright"
    assert notes[1].find("notations") is None
    assert [child.tag for child in notes[0]][-2:] == ["notations", "lyric"]


def test_a_measure_rest_can_carry_an_inverted_fermata() -> None:
    root = _tree(
        _score(_note(pitches=(), is_measure_rest=True, fermatas=(Fermata(inverted=True),)))
    )
    note = root.find(".//note")
    assert note is not None
    assert note.find("rest[@measure='yes']") is not None
    assert note.find("notations/fermata[@type='inverted']") is not None
    assert note.findtext("duration") == "1"
    assert note.find("type") is None


def test_beams_are_emitted_with_their_level() -> None:
    score = _score(
        Event(
            duration=Fraction(1, 16),
            written_duration=Fraction(1, 16),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            beams=(Beam(number=1, type="begin"), Beam(number=2, type="begin")),
        )
    )
    xml = to_musicxml(score).decode()
    assert '<beam number="1">begin</beam>' in xml
    assert '<beam number="2">begin</beam>' in xml


def test_a_beam_comes_before_notations() -> None:
    """Schema order: <beam> after <time-modification>, before <notations>."""
    score = _score(
        Event(
            duration=Fraction(1, 8),
            written_duration=Fraction(1, 8),
            pitches=(Pitch(step="C", alteration=0, octave=4),),
            beams=(Beam(number=1, type="begin"),),
            articulations=("staccato",),
        )
    )
    xml = to_musicxml(score).decode()
    assert xml.index("<beam ") < xml.index("<notations>")


def test_a_chord_beams_once() -> None:
    """The beam belongs to the stem, not to each pitch."""
    score = _score(
        Event(
            duration=Fraction(1, 8),
            written_duration=Fraction(1, 8),
            pitches=(
                Pitch(step="C", alteration=0, octave=4),
                Pitch(step="E", alteration=0, octave=4),
            ),
            beams=(Beam(number=1, type="begin"),),
        )
    )
    assert to_musicxml(score).decode().count("<beam ") == 1


def _barline(score: Score, location: str):  # type: ignore[no-untyped-def]
    measure = _tree(score).find("./part/measure")
    assert measure is not None
    return measure.find(f'./barline[@location="{location}"]')


def test_a_forward_repeat_opens_the_measure() -> None:
    barline = _barline(_score(_note(), repeat_forward=True), "left")
    assert barline is not None
    assert barline.findtext("bar-style") == "heavy-light"
    repeat = barline.find("repeat")
    assert repeat is not None and repeat.get("direction") == "forward"


def test_a_backward_repeat_closes_the_measure() -> None:
    barline = _barline(_score(_note(), repeat_backward=True), "right")
    assert barline is not None
    assert barline.findtext("bar-style") == "light-heavy"
    repeat = barline.find("repeat")
    assert repeat is not None and repeat.get("direction") == "backward"


def test_the_repeat_barline_goes_at_the_right_end_of_the_measure() -> None:
    """A left barline before the notes and a right one after them -- swapping
    them turns a repeat into one that sends the player somewhere else."""
    score = _score(_note(), repeat_forward=True, repeat_backward=True)
    xml = to_musicxml(score).decode()
    assert xml.index('location="left"') < xml.index("<note>") < xml.index('location="right"')


def test_total_passes_are_written_only_when_they_are_not_the_default() -> None:
    """MusicXML already defaults to two, so writing `times="2"` says nothing."""
    assert 'times="2"' not in to_musicxml(_score(_note(), repeat_backward=True)).decode()
    assert (
        'times="4"' in to_musicxml(_score(_note(), repeat_backward=True, repeat_passes=4)).decode()
    )


def test_an_ending_bracket_carries_its_number_and_its_text() -> None:
    score = _score(_note(), endings=(Ending(numbers=(1, 2), type="start"),))
    xml = to_musicxml(score).decode()
    assert 'number="1,2"' in xml
    assert 'type="start"' in xml
    assert ">1., 2.<" in xml


def test_an_ending_is_written_before_the_repeat_it_meets() -> None:
    """Schema order inside a barline is bar-style, ending, repeat; the other
    order is rejected outright."""
    score = _score(_note(), repeat_backward=True, endings=(Ending(numbers=(1,), type="stop"),))
    xml = to_musicxml(score).decode()
    assert xml.index("<bar-style>") < xml.index("<ending ") < xml.index("<repeat ")


def test_a_measure_without_repeats_writes_no_barline() -> None:
    assert "<barline" not in to_musicxml(_score(_note())).decode()


def _grouped(*groups: PartGroup, parts: int = 3) -> Score:
    return Score(
        parts=tuple(
            Part(id=f"P{n}", name=f"Staff {n}", measures=(Measure(number=1),))
            for n in range(1, parts + 1)
        ),
        groups=groups,
    )


def _part_list(score: Score):  # type: ignore[no-untyped-def]
    element = _tree(score).find("part-list")
    assert element is not None
    return [
        (child.tag, child.get("type"), child.get("number") or child.get("id")) for child in element
    ]


def test_a_group_wraps_the_parts_it_covers() -> None:
    score = _grouped(PartGroup(part_ids=("P1", "P2"), symbol="brace"))
    assert _part_list(score) == [
        ("part-group", "start", "1"),
        ("score-part", None, "P1"),
        ("score-part", None, "P2"),
        ("part-group", "stop", "1"),
        ("score-part", None, "P3"),
    ]


def test_a_group_carries_its_symbol_barline_and_name() -> None:
    score = _grouped(PartGroup(part_ids=("P1", "P2"), symbol="bracket", barline=True, name="Winds"))
    start = _tree(score).find("./part-list/part-group")
    assert start is not None
    assert start.findtext("group-name") == "Winds"
    assert start.findtext("group-symbol") == "bracket"
    assert start.findtext("group-barline") == "yes"


def test_an_unmapped_symbol_writes_no_group_symbol() -> None:
    score = _grouped(PartGroup(part_ids=("P1", "P2"), symbol=None, barline=True))
    start = _tree(score).find("./part-list/part-group")
    assert start is not None
    assert start.find("group-symbol") is None
    assert start.findtext("group-barline") == "yes"


def test_nested_groups_get_distinct_numbers_and_close_innermost_first() -> None:
    """Two groups open at the same part; the inner one must close first or the
    brackets interleave, which the schema permits and no reader draws."""
    score = _grouped(
        PartGroup(part_ids=("P1", "P2", "P3"), symbol="bracket"),
        PartGroup(part_ids=("P1", "P2"), symbol="brace"),
    )
    assert _part_list(score) == [
        ("part-group", "start", "1"),
        ("part-group", "start", "2"),
        ("score-part", None, "P1"),
        ("score-part", None, "P2"),
        ("part-group", "stop", "2"),
        ("score-part", None, "P3"),
        ("part-group", "stop", "1"),
    ]


def test_groups_ending_together_close_innermost_first() -> None:
    """Both end on the same part, so the closing order is decided here rather
    than by where they start. Closing the outer one first interleaves the
    brackets."""
    score = _grouped(
        PartGroup(part_ids=("P1", "P2", "P3"), symbol="bracket"),
        PartGroup(part_ids=("P2", "P3"), symbol="brace"),
    )
    closes = [n for tag, kind, n in _part_list(score) if tag == "part-group" and kind == "stop"]
    assert closes == ["2", "1"]


def test_a_group_number_is_reused_once_it_closes() -> None:
    score = _grouped(
        PartGroup(part_ids=("P1",), symbol="brace"),
        PartGroup(part_ids=("P2", "P3"), symbol="brace"),
    )
    numbers = [n for tag, kind, n in _part_list(score) if tag == "part-group" and kind == "start"]
    assert numbers == ["1", "1"]


def test_a_score_with_no_groups_writes_a_plain_part_list() -> None:
    assert all(tag == "score-part" for tag, _, _ in _part_list(_grouped()))


def test_a_measure_rest_is_marked_and_carries_no_type() -> None:
    """`measure="yes"` is what centres one symbol in the bar. The `<type>` has
    to go with it: a 3/4 measure rest has no note value, and asking for one
    raises."""
    score = _score(
        Event(duration=Fraction(3, 4), written_duration=Fraction(3, 4), is_measure_rest=True)
    )
    note = _tree(score).find("./part/measure/note")
    assert note is not None
    rest = note.find("rest")
    assert rest is not None and rest.get("measure") == "yes"
    assert note.find("type") is None
    assert note.findtext("duration") == "3"


def test_an_ordinary_rest_is_not_marked_as_a_measure_rest() -> None:
    note = _tree(_score(_note(pitches=()))).find("./part/measure/note")
    assert note is not None
    rest = note.find("rest")
    assert rest is not None and rest.get("measure") is None
    assert note.findtext("type") == "quarter"


def test_a_measure_direction_is_written_above_before_the_notes() -> None:
    """A direction placed after the notes reads as belonging to the next bar."""
    measure = Measure(
        number=1, voices=(Voice(number=1, events=(_note(),)),), directions=("D.C. al Fine",)
    )
    score = Score(parts=(Part(id="P1", name="Flute", measures=(measure,)),))
    element = _tree(score).find("./part/measure")
    assert element is not None
    assert [child.tag for child in element] == ["attributes", "direction", "note"]
    direction = element.find("direction")
    assert direction is not None
    assert direction.get("placement") == "above"
    assert direction.findtext("./direction-type/words") == "D.C. al Fine"


def test_a_measure_with_no_direction_writes_none() -> None:
    assert "<direction" not in to_musicxml(_score(_note())).decode()


def test_a_double_bar_is_written_on_the_right_barline() -> None:
    barline = _barline(_score(_note(), barline_style="light-light"), "right")
    assert barline is not None
    assert barline.findtext("bar-style") == "light-light"
    assert _barline(_score(_note(), barline_style="light-light"), "left") is None


def test_a_repeat_overrides_the_barline_style() -> None:
    """The repeat's own heavy line is what gets drawn. Four corpus measures ask
    for both, and emitting two bar-styles in one barline is invalid."""
    score = _score(_note(), barline_style="light-light", repeat_backward=True)
    barline = _barline(score, "right")
    assert barline is not None
    assert [child.tag for child in barline] == ["bar-style", "repeat"]
    assert barline.findtext("bar-style") == "light-heavy"


def test_an_ordinary_barline_writes_no_element() -> None:
    assert "<barline" not in to_musicxml(_score(_note())).decode()


def test_a_fingering_is_written_in_technical() -> None:
    score = _score(_note(fingerings=("3",)))
    note = _tree(score).find("./part/measure/note")
    assert note is not None
    assert note.findtext("./notations/technical/fingering") == "3"


def test_a_chords_fingerings_sit_on_its_principal_note() -> None:
    """Enigma attaches them to the entry, not to a note, so which finger goes
    with which pitch is not stored -- and repeating them per pitch would print
    each one once per chord tone."""
    score = _score(
        Event(
            duration=QUARTER,
            written_duration=QUARTER,
            pitches=(
                Pitch(step="C", alteration=0, octave=4),
                Pitch(step="E", alteration=0, octave=4),
            ),
            fingerings=("1", "3"),
        )
    )
    xml = to_musicxml(score).decode()
    assert xml.count("<technical>") == 1
    assert xml.count("<fingering>") == 2


def test_a_note_without_fingerings_writes_no_technical() -> None:
    assert "<technical>" not in to_musicxml(_score(_note())).decode()


BREVE = Fraction(2, 1)
DOTTED_WHOLE = Fraction(3, 2)


def test_a_breve_exports_as_a_breve() -> None:
    """The note-type table is keyed by denominator, which assumes a note value is
    a whole note or shorter. A breve is the one that is not, and one corpus
    document -- a Renaissance motet -- uses it."""
    root = _tree(_score(_note(duration=BREVE, written_duration=BREVE)))
    assert [e.text for e in root.iter("type")] == ["breve"]


def test_a_dotted_whole_exports_as_a_dotted_whole() -> None:
    """It was refused at the reader for exceeding a whole note; the limit belongs
    on the base value, since every dotted note exceeds its own base."""
    root = _tree(_score(_note(duration=DOTTED_WHOLE, written_duration=DOTTED_WHOLE, dots=1)))
    assert [e.text for e in root.iter("type")] == ["whole"]
    assert len(list(root.iter("dot"))) == 1


def _expr(**kwargs: object) -> Expression:
    base: dict[str, object] = {"text": "f", "category": "dynamics", "marking": "f"}
    base.update(kwargs)
    return Expression(**base)  # type: ignore[arg-type]


def test_a_named_dynamic_becomes_a_dynamics_element() -> None:
    """Not `<words>f</words>`: a consumer should get the marking as MusicXML
    models it, so it can transpose, play back, or re-engrave it."""
    root = _tree(_score(_note(), expressions=(_expr(marking="ff", text="Ä"),)))
    direction = root.find("./part/measure/direction")
    assert direction is not None
    assert direction.get("placement") == "below"
    assert direction.find("./direction-type/dynamics/ff") is not None


def test_every_named_dynamic_is_a_legal_musicxml_element() -> None:
    """The guard that matters: `subito p` is a real library entry whose marking
    has a space in it, and `<subito p/>` is a document no parser can read.
    Serialising every marking the table knows proves none of them can.
    """
    for entry in DYNAMICS:
        if not entry.marking:
            continue
        score = _score(_note(), expressions=(_expr(text=entry.glyph, marking=entry.marking),))
        # Round-trips through a real parser, so an illegal name fails here.
        root = DET.fromstring(to_musicxml(score).decode())
        dynamics = root.find("./part/measure/direction/direction-type/dynamics")
        assert dynamics is not None, entry
        assert len(dynamics) == 1, entry


def test_a_marking_musicxml_has_no_element_for_uses_other_dynamics() -> None:
    root = _tree(_score(_note(), expressions=(_expr(text="subito p", marking="subito p"),)))
    assert (
        root.findtext("./part/measure/direction/direction-type/dynamics/other-dynamics")
        == "subito p"
    )


def test_a_tempo_word_is_emitted_as_words_above() -> None:
    root = _tree(
        _score(_note(), expressions=(_expr(text="Adagio", category="tempoMarks", marking=None),))
    )
    direction = root.find("./part/measure/direction")
    assert direction is not None
    assert direction.get("placement") == "above"
    assert direction.findtext("./direction-type/words") == "Adagio"


def test_an_unidentified_glyph_is_not_printed_as_text() -> None:
    """`§` is a music-font character. Emitting it as words puts a section sign
    in the score; the IR still carries it, the exporter declines to print it."""
    root = _tree(_score(_note(), expressions=(_expr(text="§", marking=None),)))
    assert root.find("./part/measure/direction") is None


@pytest.mark.parametrize("offset", [Fraction(3, 8), Fraction(1, 20), Fraction(-1, 16)])
@pytest.mark.parametrize("kind", ["dynamic", "tempo", "words", "rehearsal"])
def test_expression_offsets_are_exact_without_moving_notes(offset: Fraction, kind: str) -> None:
    expression = Expression(
        text="Andante",
        category="",
        offset=offset,
        marking="mf" if kind == "dynamic" else None,
        tempo=Tempo(QUARTER, Fraction(96)) if kind == "tempo" else None,
        is_rehearsal=kind == "rehearsal",
    )
    root = _tree(_score(_note(), expressions=(expression,)))
    divisions = int(root.findtext("./part/measure/attributes/divisions") or "0")
    direction = root.find("./part/measure/direction")
    assert direction is not None
    assert direction.findtext("offset") == str(offset * 4 * divisions)
    assert direction.find("offset").get("sound") == "yes"
    assert int(root.findtext("./part/measure/note/duration") or "0") == divisions
    assert root.find("./part/measure/forward") is None
    if kind == "tempo":
        assert [child.tag for child in direction] == ["direction-type", "offset", "sound"]


def test_expressions_are_emitted_before_the_notes() -> None:
    """A direction placed after the notes reads as belonging to the next bar."""
    root = _tree(_score(_note(), expressions=(_expr(),)))
    measure = root.find("./part/measure")
    assert measure is not None
    tags = [child.tag for child in measure]
    assert tags.index("direction") < tags.index("note")


def test_velocity_is_not_exported() -> None:
    """The IR keeps the playback level; MusicXML's `<sound dynamics>` is a
    percentage of MIDI velocity 90, and that conversion is unverified here."""
    root = _tree(_score(_note(), expressions=(_expr(velocity=88),)))
    assert root.find(".//sound") is None


def test_a_rehearsal_mark_is_not_words() -> None:
    """`<rehearsal>` and `<words>` are different elements and consumers treat
    them differently -- a rehearsal mark is a navigation target."""
    mark = Expression(text="A", category="rehearsalMarks", is_rehearsal=True)
    root = _tree(_score(_note(), expressions=(mark,)))
    direction = root.find("./part/measure/direction")
    assert direction is not None
    assert direction.findtext("./direction-type/rehearsal") == "A"
    assert direction.find("./direction-type/words") is None
    assert prints_as_words(mark) is False
