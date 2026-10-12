"""Bounded source-driven playback traversal over the canonical score."""

from finale_file_parser.errors import FinaleFileError
from finale_file_parser.ir import Navigation, Part, RepeatPlayback, Score


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
    ending_limits: dict[int, int] = {}
    for _, passes, repeat in endings.values():
        ending_limits[repeat] = max(ending_limits.get(repeat, 1), max(passes, default=1))
    ending_finishes: dict[int, list[tuple[int, int]]] = {}
    encounters: dict[int, int] = {}
    mark_encounters: dict[tuple[int, int], int] = {}
    result: list[int] = []
    index = 0
    steps = 0
    while index < len(part.measures):
        steps += 1
        if steps > max_visits:
            raise PlaybackError("repeat traversal exceeds the configured visit bound")
        if index in endings:
            stop, passes, repeat = endings[index]
            pass_number = min(encounters.get(repeat, 0) + 1, ending_limits[repeat])
            if passes and pass_number not in passes:
                index = stop + 1
                continue
            if stop != repeat:
                ending_finishes.setdefault(stop, []).append((repeat, pass_number))
        measure = part.measures[index]
        result.append(measure.number)
        for repeat, pass_number in ending_finishes.pop(index, ()):
            encounters[repeat] = max(encounters.get(repeat, 0), pass_number)
        destination = None
        stop = False
        for mark_index, mark in enumerate(measure.navigation):
            rule = mark.playback
            if rule is None or rule.action == "noJump":
                continue
            key = index, mark_index
            count = mark_encounters.get(key, 0) + 1
            mark_encounters[key] = count
            if not _triggers(rule, count):
                continue
            if rule.action == "stop":
                stop = True
                break
            destination = positions[navigation_target(part, measure.number, mark)]
            break
        if stop:
            break
        if destination is not None:
            ending_finishes.clear()
            for other in range(len(part.measures)):
                other_rule = part.measures[other].repeat_playback
                if other_rule is not None and other_rule.reset_on_action:
                    encounters.pop(other, None)
                for mark_index, mark in enumerate(part.measures[other].navigation):
                    if mark.playback is not None and mark.playback.reset_on_action:
                        if (other, mark_index) != key:
                            mark_encounters.pop((other, mark_index), None)
            index = destination
            continue
        if not measure.repeat_backward:
            index += 1
            continue
        rule = measure.repeat_playback or RepeatPlayback(passes=measure.repeat_passes)
        count = encounters.get(index, 0) + 1
        encounters[index] = count
        jump = _triggers(rule, count)
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
        for other, other_measure in enumerate(part.measures):
            for mark_index, mark in enumerate(other_measure.navigation):
                if mark.playback is not None and mark.playback.reset_on_action:
                    mark_encounters.pop((other, mark_index), None)
        ending_finishes.clear()
        index = target
    return tuple(result)


def _triggers(rule: RepeatPlayback, count: int) -> bool:
    if rule.trigger not in {"always", "onPass", "untilPass"}:
        raise PlaybackError("unsupported navigation trigger")
    if rule.trigger != "always" and not 1 <= rule.passes <= 32767:
        raise PlaybackError("navigation needs a positive bounded pass count")
    return (
        rule.trigger == "always"
        or (rule.trigger == "onPass" and count == rule.passes)
        or (rule.trigger == "untilPass" and count < rule.passes)
    )


def navigation_target(part: Part, number: int, mark: Navigation) -> int:
    """Resolve a source destination without using the printed D.C./D.S. words."""
    rule = mark.playback
    if rule is None:
        raise PlaybackError("navigation has no playback destination")
    if rule.action == "jumpAuto":
        target = part.measures[0].number
    elif rule.action == "jumpAbsolute":
        target = rule.target
    elif rule.action == "jumpRelative":
        target = number + rule.target
    elif rule.action == "jumpToMark":
        candidates = {
            m.number
            for m in part.measures
            for n in m.navigation
            if n.mark_id == f"repeat-{rule.target}"
        }
        if len(candidates) != 1:
            raise PlaybackError("navigation target mark is missing or ambiguous")
        target = candidates.pop()
    else:
        raise PlaybackError(f"unsupported navigation action {rule.action!r}")
    if not any(m.number == target for m in part.measures):
        raise PlaybackError("navigation target refers to a missing measure")
    return target


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
