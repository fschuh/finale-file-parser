"""Authored independent repeat triggers and retained ending state."""

from dataclasses import replace

import pytest

from finale_file_parser.ir import Ending, Measure, Part, RepeatPlayback, Score
from finale_file_parser.playback import PlaybackError, measure_route


def _score(*measures: Measure) -> Score:
    return Score(parts=(Part("P1", "Authored", measures),))


def test_a_later_repeat_reuses_its_opening_without_replaying_a_consumed_first_ending() -> None:
    first = (Ending((1,), "start"), Ending((1,), "stop"))
    second = (Ending((2,), "start"), Ending((2,), "discontinue"))
    score = _score(
        Measure(1),
        Measure(2, repeat_forward=True),
        Measure(
            3, repeat_backward=True, endings=first, repeat_playback=RepeatPlayback(trigger="always")
        ),
        Measure(4, endings=second),
        Measure(5),
        Measure(6, repeat_backward=True, repeat_playback=RepeatPlayback()),
    )
    assert measure_route(score) == (1, 2, 3, 2, 4, 5, 6, 2, 4, 5, 6)


def test_ordinary_repeat_counts_are_bounded_and_can_use_an_absolute_destination() -> None:
    score = _score(
        Measure(1),
        Measure(2),
        Measure(
            3,
            repeat_backward=True,
            repeat_playback=RepeatPlayback("jumpAbsolute", "untilPass", 2, 3),
        ),
    )
    assert measure_route(score) == (1, 2, 3, 2, 3, 2, 3)


def test_relative_destinations_and_jump_on_a_specific_pass_are_source_driven() -> None:
    score = _score(
        Measure(1),
        Measure(2),
        Measure(
            3, repeat_backward=True, repeat_playback=RepeatPlayback("jumpRelative", "onPass", -1, 1)
        ),
    )
    assert measure_route(score) == (1, 2, 3, 2, 3)


def test_stop_and_disabled_jump_rules_keep_notation_separate_from_playback() -> None:
    stop = Measure(2, repeat_backward=True, repeat_playback=RepeatPlayback("stop", "always"))
    assert measure_route(_score(Measure(1), stop, Measure(3))) == (1, 2)
    disabled = replace(stop, repeat_playback=RepeatPlayback("noJump", "always"))
    assert measure_route(_score(Measure(1), disabled, Measure(3))) == (1, 2, 3)


def test_genuine_unbounded_source_repeats_raise_instead_of_hanging() -> None:
    score = _score(
        Measure(1, repeat_backward=True, repeat_playback=RepeatPlayback(trigger="always"))
    )
    with pytest.raises(PlaybackError, match="visit bound"):
        measure_route(score, max_visits=10)


def test_a_missing_target_is_not_replaced_with_the_first_bar() -> None:
    score = _score(
        Measure(1, repeat_backward=True, repeat_playback=RepeatPlayback("jumpAbsolute", target=99))
    )
    with pytest.raises(PlaybackError, match="missing measure"):
        measure_route(score)
