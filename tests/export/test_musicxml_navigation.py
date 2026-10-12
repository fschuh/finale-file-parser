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
    Voice,
)


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
