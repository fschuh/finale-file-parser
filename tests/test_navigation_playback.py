"""Source-driven traversal, independent of the displayed navigation words."""

from dataclasses import replace

import pytest

from finale_file_parser.ir import Ending, Measure, Navigation, Part, RepeatPlayback, Score
from finale_file_parser.playback import PlaybackError, measure_route


def _score(marks: dict[int, tuple[Navigation, ...]]) -> Score:
    return Score(
        parts=(
            Part(
                "P1",
                "Authored",
                tuple(Measure(n, navigation=marks.get(n, ())) for n in range(1, 6)),
            ),
        )
    )


def test_a_single_source_jump_replays_the_piece_once() -> None:
    score = _score(
        {
            5: (
                Navigation(
                    "Different printed words",
                    playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 1),
                ),
            )
        }
    )
    assert measure_route(score) == (1, 2, 3, 4, 5) * 2


def test_segno_destination_and_fine_on_second_pass() -> None:
    score = _score(
        {
            2: (Navigation("%", "segno", "repeat-4"),),
            4: (Navigation("Fine", playback=RepeatPlayback("stop", "onPass", passes=2)),),
            5: (Navigation("D.S.", playback=RepeatPlayback("jumpToMark", "onPass", 4, 1)),),
        }
    )
    assert measure_route(score) == (1, 2, 3, 4, 5, 2, 3, 4)


def test_relative_jump_and_inactive_optional_text() -> None:
    score = _score(
        {
            5: (
                Navigation("Optional D.C.", playback=RepeatPlayback("noJump")),
                Navigation("Repeat", playback=RepeatPlayback("jumpRelative", "onPass", -2, 1)),
            )
        }
    )
    assert measure_route(score) == (1, 2, 3, 4, 5, 3, 4, 5)


def test_navigation_remains_bounded_and_does_not_invent_a_missing_destination() -> None:
    score = _score({5: (Navigation("D.C.", playback=RepeatPlayback("jumpAbsolute", "always", 1)),)})
    with pytest.raises(PlaybackError, match="bound"):
        measure_route(score, max_visits=20)
    score = replace(
        score,
        parts=(
            replace(
                score.parts[0],
                measures=(
                    Measure(
                        1,
                        navigation=(
                            Navigation("Jump", playback=RepeatPlayback("jumpAbsolute", target=99)),
                        ),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(PlaybackError, match="missing measure"):
        measure_route(score)


def test_first_and_third_endings_replay_after_a_navigation_jump() -> None:
    first = (Ending((1, 3), "start"), Ending((1, 3), "stop"))
    second = (Ending((2, 4), "start"), Ending((2, 4), "discontinue"))
    score = Score(
        parts=(
            Part(
                "P1",
                "Authored",
                (
                    Measure(1),
                    Measure(
                        2,
                        endings=first,
                        repeat_backward=True,
                        repeat_playback=RepeatPlayback(trigger="always"),
                    ),
                    Measure(3, endings=second),
                    Measure(
                        4,
                        navigation=(
                            Navigation(
                                "D.C.", playback=RepeatPlayback("jumpAbsolute", "onPass", 1, 1)
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    assert measure_route(score) == (1, 2, 1, 3, 4, 1, 2, 1, 3, 4)
