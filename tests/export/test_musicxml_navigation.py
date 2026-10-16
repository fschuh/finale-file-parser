"""Navigation labels, controls and hidden notation are independently authored."""

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import (
    Event,
    Measure,
    Navigation,
    Part,
    Pitch,
    RepeatPlayback,
    Score,
    TimeSignature,
    Voice,
)
from finale_file_parser.playback import measure_route


def _score(*measures: Measure) -> Score:
    return Score(parts=(Part("P1", "Authored", measures),))


NOTE = Event(Fraction(1), Fraction(1), (Pitch("C", 4, 0),))


def test_source_jump_plays_on_its_pass_at_the_end_of_its_bar() -> None:
    jump = Navigation(
        "D.C. after two passes", playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 2)
    )
    root = DET.fromstring(to_musicxml(_score(Measure(1, (Voice(1, (NOTE,)),), navigation=(jump,)))))
    sound = root.find(".//sound")
    assert sound is not None and sound.attrib == {"dacapo": "yes", "time-only": "2"}
    assert root.findtext(".//direction/offset") == "4"


def test_ds_al_fine_keeps_standard_destination_independent_of_printed_words() -> None:
    mark = Navigation("%", "segno", "authored-segno")
    jump = Navigation("D.S. al Fine", playback=RepeatPlayback("jumpAbsolute", "onPass", 2, 1))
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1, (Voice(1, (NOTE,)),)),
                Measure(2, (Voice(1, (NOTE,)),), navigation=(mark,)),
                Measure(3, (Voice(1, (NOTE,)),), navigation=(jump,)),
            )
        )
    )
    assert root.find(".//segno") is not None
    sound = root.find("part/measure[@number='3']/sound")
    assert sound is not None and sound.get("dalsegno") == "authored-segno"
    assert (
        root.findtext("part/measure[@number='3']/direction/direction-type/words") == "D.S. al Fine"
    )


def test_inactive_optional_text_does_not_invent_a_jump() -> None:
    mark = Navigation("Optional repeat", playback=RepeatPlayback("noJump", target=1))
    root = DET.fromstring(to_musicxml(_score(Measure(1, navigation=(mark,)))))
    assert root.find(".//sound") is None
    assert root.findtext(".//words") == "Optional repeat"


def test_hidden_control_uses_a_schema_supported_hidden_direction() -> None:
    mark = Navigation(
        "D.C.", playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 1), visible=False
    )
    root = DET.fromstring(to_musicxml(_score(Measure(1, navigation=(mark,)))))
    hidden = root.find(".//other-direction")
    assert hidden is not None and hidden.get("print-object") == "no"
    assert root.find(".//sound") is not None


def test_positioned_marker_keeps_graphical_coordinates_separate_from_jump_time() -> None:
    """Original positions and navigation authored here; MIT."""
    marker = Navigation(
        "%", "segno", "source", x_offset=Fraction(5, 2), y_offset=Fraction(4), justification="left"
    )
    jump = Navigation(
        "Repeat from",
        playback=RepeatPlayback("jumpAbsolute", target=2),
        x_offset=Fraction(20),
        y_offset=Fraction(5),
        justification="left",
    )
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1, (Voice(1, (NOTE,)),)),
                Measure(2, (Voice(1, (NOTE,)),), navigation=(marker,)),
                Measure(3, (Voice(1, (NOTE,)),), navigation=(jump,)),
            )
        )
    )
    sign = root.find(".//segno")
    assert (
        sign is not None
        and sign.get("default-x") == "25.00000"
        and sign.get("default-y") == "40.00000"
    )
    direction = root.find("part/measure[@number='3']/direction")
    assert direction is not None and direction.findtext("offset") == "4"
    sound = direction.find("sound")
    assert sound is not None and sound.get("dalsegno") == "source"
    words = direction.find("direction-type/words")
    assert words is not None and words.get("default-y") == "50.00000"
    assert words.get("default-x") is None  # source-left origin needs independent layout


def test_reused_reference_sign_does_not_create_a_second_playback_destination() -> None:
    marker = Navigation("%", "segno", "shared")
    cue = Navigation("%", "segno", "shared", RepeatPlayback("noJump"), x_offset=Fraction(26))
    jump = Navigation("Repeat from", playback=RepeatPlayback("jumpAbsolute", target=2))
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1, (Voice(1, (NOTE,)),)),
                Measure(2, (Voice(1, (NOTE,)),), navigation=(marker,)),
                Measure(3, (Voice(1, (NOTE,)),), navigation=(jump, cue)),
            )
        )
    )
    assert len(root.findall(".//segno")) == 1 and root.findtext(".//symbol") == "segno"
    assert [s.get("segno") for s in root.findall(".//sound") if s.get("segno")] == [
        "shared-measure-2"
    ]
    sound = root.find("part/measure[@number='3']/direction/sound")
    assert sound is not None and sound.get("dalsegno") == "shared-measure-2"


def test_two_real_targets_reusing_a_definition_keep_distinct_musicxml_labels() -> None:
    marker = Navigation("%", "segno", "shared")
    first = Navigation("Jump one", playback=RepeatPlayback("jumpAbsolute", target=2))
    second = Navigation("Jump two", playback=RepeatPlayback("jumpAbsolute", target=3))
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1),
                Measure(2, navigation=(marker,)),
                Measure(3, navigation=(marker,)),
                Measure(4, navigation=(first,)),
                Measure(5, navigation=(second,)),
            )
        )
    )
    assert root.find(".//symbol") is None
    labels = [s.get("segno") for s in root.findall(".//sound") if s.get("segno")]
    assert labels == ["shared-measure-2", "shared-measure-3"]
    jumps = [s.get("dalsegno") for s in root.findall(".//sound") if s.get("dalsegno")]
    assert jumps == labels


def _to_coda_score() -> Score:
    """Four original MIT bars: D.C., then To Coda on its second encounter."""
    measures = []
    for number, step in enumerate(("C", "D", "E", "F"), 1):
        navigation: tuple[Navigation, ...] = ()
        if number == 2:
            navigation = (
                Navigation("To Coda", playback=RepeatPlayback("jumpAbsolute", "onPass", 4, 2)),
            )
        elif number == 3:
            navigation = (
                Navigation("D.C. al Coda", playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 1)),
            )
        elif number == 4:
            navigation = (Navigation("", "coda", "authored-coda"),)
        event = Event(Fraction(1), Fraction(1), (Pitch(step, 4, 0),))
        measures.append(
            Measure(
                number,
                (Voice(1, (event,)),),
                navigation=navigation,
                time=TimeSignature(4, 4) if number == 1 else None,
                clef_sign="G" if number == 1 else None,
                clef_line=2 if number == 1 else None,
            )
        )
    return _score(*measures)


def test_to_coda_keeps_words_only_pass_condition_and_real_destination() -> None:
    score = _to_coda_score()
    assert measure_route(score) == (1, 2, 3, 1, 2, 4)
    root = DET.fromstring(to_musicxml(score))
    measure = root.find("part/measure[@number='2']")
    assert measure is not None
    assert measure.findtext("direction/direction-type/words") == "To Coda"
    assert measure.find(".//coda") is None
    direction = measure.find("direction")
    assert direction is not None
    assert direction.findtext("offset") == "4"
    sound = direction.find("sound")
    assert sound is not None and sound.attrib == {"tocoda": "authored-coda", "time-only": "2"}
    marker = root.find("part/measure[@number='4']/direction")
    assert marker is not None and marker.find("direction-type/coda") is not None
    marker_sound = marker.find("sound")
    assert marker_sound is not None and marker_sound.attrib == {"coda": "authored-coda"}


def test_jump_to_an_unmarked_bar_gets_a_hidden_segno_instead_of_being_dropped() -> None:
    # Finale's D.C. may return to the bar after a pickup; a plain da capo would
    # replay the pickup, so the destination gets its own hidden marker.
    jump = Navigation("D.C.", playback=RepeatPlayback("jumpAbsolute", "onPass", 2, 1))
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1, (Voice(1, (NOTE,)),)),
                Measure(2, (Voice(1, (NOTE,)),)),
                Measure(3, (Voice(1, (NOTE,)),), navigation=(jump,)),
            )
        )
    )
    target = root.find("part/measure[@number='2']/direction")
    assert target is not None
    hidden = target.find("direction-type/other-direction")
    assert hidden is not None and hidden.get("print-object") == "no"
    marker = target.find("sound")
    assert marker is not None and marker.attrib == {"segno": "jump-target-2"}
    sound = root.find("part/measure[@number='3']/direction/sound")
    assert sound is not None and sound.attrib == {"dalsegno": "jump-target-2", "time-only": "1"}
    assert root.findtext("part/measure[@number='3']/direction/direction-type/words") == "D.C."
    assert root.find(".//segno") is None


def test_forward_jump_to_an_unmarked_bar_gets_a_hidden_coda() -> None:
    jump = Navigation("To bar 3", playback=RepeatPlayback("jumpAbsolute", "onPass", 3, 1))
    root = DET.fromstring(
        to_musicxml(
            _score(
                Measure(1, (Voice(1, (NOTE,)),), navigation=(jump,)),
                Measure(2, (Voice(1, (NOTE,)),)),
                Measure(3, (Voice(1, (NOTE,)),)),
            )
        )
    )
    marker = root.find("part/measure[@number='3']/direction/sound")
    assert marker is not None and marker.attrib == {"coda": "jump-target-3"}
    sound = root.find("part/measure[@number='1']//sound[@tocoda]")
    assert sound is not None and sound.get("tocoda") == "jump-target-3"


def test_right_justified_words_without_a_jump_start_at_their_bar() -> None:
    words = Navigation(
        "(Optional) Go To Measure 1",
        playback=RepeatPlayback("noJump", target=1),
        justification="right",
    )
    root = DET.fromstring(
        to_musicxml(_score(Measure(1, (Voice(1, (NOTE,)),), navigation=(words,))))
    )
    offset = root.find(".//direction/offset")
    assert offset is not None and offset.text == "0" and offset.get("sound") is None


def test_right_justified_jumps_stay_at_the_barline() -> None:
    jump = Navigation(
        "D.C. after 2nd repeat",
        playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 2),
        justification="right",
    )
    root = DET.fromstring(to_musicxml(_score(Measure(1, (Voice(1, (NOTE,)),), navigation=(jump,)))))
    assert root.findtext(".//direction/offset") == "4"
    sound = root.find(".//direction/sound")
    assert sound is not None and sound.get("dacapo") == "yes"
