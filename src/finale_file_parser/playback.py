"""Bounded source-driven playback traversal over the canonical score."""

from finale_file_parser.errors import FinaleFileError
from finale_file_parser.ir import Part, RepeatPlayback, Score


class PlaybackError(FinaleFileError):
    """A source route is malformed, unsupported or cannot finish within its bound."""


def measure_route(score: Score, *, max_visits: int = 10_000) -> tuple[int, ...]:
    """Unfold source repeats, retaining each bar's consumed ending/repeat state.

    This returns measure numbers, not synthesized notes or MIDI performance.
    Explicit source jumps and partial-measure stops can be added independently.
    """
    if not score.parts:
        return ()
    if not 1 <= max_visits <= 1_000_000:
        raise ValueError("max_visits must be in 1..1000000")
    part = score.parts[0]
    positions = {m.number: i for i, m in enumerate(part.measures)}
    if len(positions) != len(part.measures):
        raise PlaybackError("playback requires unique measure numbers")
    targets = _targets(part, positions)
    endings = _endings(part)
    encounters: dict[int, int] = {}
    result: list[int] = []
    index = 0
    steps = 0
    while index < len(part.measures):
        steps += 1
        if steps > max_visits:
            raise PlaybackError("repeat traversal exceeds the configured visit bound")
        if index in endings:
            stop, passes, repeat = endings[index]
            pass_number = encounters.get(repeat, 0) + 1
            if passes and pass_number not in passes:
                index = stop + 1
                continue
        measure = part.measures[index]
        result.append(measure.number)
        if not measure.repeat_backward:
            index += 1
            continue
        rule = measure.repeat_playback or RepeatPlayback(passes=measure.repeat_passes)
        count = encounters.get(index, 0) + 1
        encounters[index] = count
        jump = (
            rule.trigger == "always"
            or (rule.trigger == "onPass" and count == rule.passes)
            or (rule.trigger == "untilPass" and count < rule.passes)
        )
        if not jump or rule.action == "noJump":
            index += 1
            continue
        if rule.action == "stop":
            break
        target = targets[index]
        # Only rules explicitly reset on another repeat action are reset. The
        # repeat performing this jump must keep its own pass counter.
        for other in range(target, index):
            other_rule = part.measures[other].repeat_playback
            if other_rule is not None and other_rule.reset_on_action:
                encounters.pop(other, None)
        index = target
    return tuple(result)


def _targets(part: Part, positions: dict[int, int]) -> dict[int, int]:
    targets = {}
    opening = 0
    for index, measure in enumerate(part.measures):
        if measure.repeat_forward:
            opening = index
        if not measure.repeat_backward:
            continue
        rule = measure.repeat_playback or RepeatPlayback(passes=measure.repeat_passes)
        if rule.action == "jumpAuto":
            target = opening
        elif rule.action in {"noJump", "stop"}:
            target = index
        elif rule.action in {"jumpAbsolute", "jumpRelative"}:
            number = rule.target + (measure.number if rule.action == "jumpRelative" else 0)
            target = positions.get(number, -1)
        else:
            raise PlaybackError(f"unsupported repeat action {rule.action!r}")
        if target < 0:
            raise PlaybackError("repeat target refers to a missing measure")
        if rule.trigger not in {"always", "onPass", "untilPass"} or not 1 <= rule.passes <= 32767:
            raise PlaybackError("invalid repeat trigger or pass count")
        targets[index] = target
    return targets


def _endings(part: Part) -> dict[int, tuple[int, tuple[int, ...], int]]:
    result = {}
    current: tuple[int, tuple[int, ...]] | None = None
    for index, measure in enumerate(part.measures):
        for ending in measure.endings:
            if ending.type == "start":
                current = index, ending.numbers
            elif current is not None:
                start, passes = current
                repeat = next(
                    (n for n in range(start, index + 1) if part.measures[n].repeat_backward),
                    max((n for n in range(start) if part.measures[n].repeat_backward), default=-1),
                )
                if repeat < 0:
                    raise PlaybackError("ending has no associated repeat")
                # A second ending tests the preceding repeat's consumed pass,
                # rather than a new repeat at the end of the whole piece.
                result[start] = index, passes, repeat
                current = None
    if current is not None:
        raise PlaybackError("ending has no stop")
    return result
