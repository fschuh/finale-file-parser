"""Source-derived attacks and contextual comparison; never fit a route to MIDI."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction

from finale_file_parser.ir import Event, Part, Pitch, Score
from finale_file_parser.playback import measure_route

from .midi import MidiNote

_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAX_ATTACKS = 100_000
MAX_MATCH_CELLS = 4_000_000
MAX_TOTAL_MATCH_CELLS = 8_000_000


@dataclass(frozen=True)
class Attack:
    part: str
    instrument: str | None
    measure: int
    visit: int
    voice: int
    event: int
    pitch_index: int
    pitch: int
    onset: Fraction
    metric_onset: Fraction
    duration: Fraction
    event_duration: Fraction
    grace: bool = False
    grace_context: bool = False
    arpeggio: bool = False
    arpeggio_context: bool = False
    ornament: str = ""
    auxiliary_pitch: int | None = None


@dataclass(frozen=True)
class PerformanceWindow:
    kind: str
    start: Fraction
    end: Fraction
    pitches: tuple[int, ...]


@dataclass(frozen=True)
class SourceAttacks:
    route: tuple[int, ...]
    length: Fraction
    attacks: tuple[Attack, ...]
    windows: tuple[PerformanceWindow, ...]
    swing_shifted: int


@dataclass(frozen=True)
class Match:
    source: Attack
    midi: MidiNote
    delta: float


@dataclass(frozen=True)
class Comparison:
    matched: tuple[Match, ...]
    missing: tuple[Attack, ...]
    extra: tuple[MidiNote, ...]


def midi_pitch(pitch: Pitch) -> int:
    return 12 * (pitch.octave + 1) + _STEPS[pitch.step] + pitch.alteration


def _lengths(score: Score) -> dict[int, Fraction]:
    lengths: dict[int, Fraction] = {}
    for part in score.parts:
        signature = Fraction(4)
        for measure in part.measures:
            if measure.time:
                signature = Fraction(measure.time.beats * 4, measure.time.beat_type)
            extent = max(
                (
                    v.start_offset * 4
                    + sum((e.duration * 4 for e in v.events if not e.is_grace), Fraction(0))
                    for v in measure.voices
                ),
                default=Fraction(0),
            )
            lengths[measure.number] = max(
                lengths.get(measure.number, Fraction(0)), signature, extent
            )
    return lengths


def _swing_offset(
    offset: Fraction, duration: Fraction, written: Fraction, amount: Fraction, unit: Fraction | None
) -> Fraction:
    # Only an established triplet setting shifts an exact offbeat. Neither
    # tuplets nor arbitrary fractional swing amounts are approximated here.
    if amount == 1 and unit and duration == written and offset % (unit * 8) == unit * 4:
        return offset + unit * Fraction(4, 3)
    return offset


def source_attacks(score: Score, *, linear_probe: bool = False) -> SourceAttacks:
    route = (
        tuple(m.number for m in score.parts[0].measures)
        if linear_probe and score.parts
        else measure_route(score)
    )
    lengths = _lengths(score)
    parts = {p.id: {m.number: m for m in p.measures} for p in score.parts}
    prefs = score.playback
    swing = (prefs.swing_amount, prefs.swing_unit) if prefs else (Fraction(0), None)
    states = {p.id: swing for p in score.parts}
    pending: dict[tuple[str, int, int], tuple[Fraction, int]] = {}
    attacks: list[Attack] = []
    swing_delays: list[Fraction] = []
    windows: list[PerformanceWindow] = []
    start = Fraction(0)
    shifted = 0
    visits: Counter[int] = Counter()
    for visit, number in enumerate(route, 1):
        visits[number] += 1
        changes = []
        for part in score.parts:
            for expression in parts[part.id][number].expressions:
                control = expression.playback
                if (
                    control is not None
                    and control.kind == "swing"
                    and (not control.pass_number or control.pass_number == visits[number])
                ):
                    changes.append(
                        (
                            expression.offset * 4,
                            part.id,
                            expression.score_wide,
                            Fraction(control.value, 1024),
                            control.beat_unit,
                        )
                    )
        initial_states = states.copy()
        for part in score.parts:
            measure = parts[part.id][number]
            for voice in measure.voices:
                cursor = voice.start_offset * 4
                grace_offsets: set[Fraction] = set()
                for index, event in enumerate(voice.events):
                    if event.is_grace:
                        grace_offsets.add(cursor)
                    amount, unit = initial_states[part.id]
                    for offset, owner, global_scope, value, beat in sorted(changes):
                        if offset <= cursor and (global_scope or owner == part.id):
                            amount, unit = value, beat
                    sounding = _swing_offset(
                        cursor, event.duration * 4, event.written_duration * 4, amount, unit
                    )
                    for pi, pitch in enumerate(event.pitches):
                        if not event.playback or not voice.playback:
                            continue
                        attack = _attack(
                            part,
                            event,
                            voice.number,
                            voice.instrument_id,
                            index,
                            pi,
                            midi_pitch(pitch),
                            number,
                            visit,
                            cursor,
                            start + cursor,
                            cursor in grace_offsets,
                        )
                        key = part.id, voice.number, attack.pitch
                        previous = pending.pop(key, None)
                        ties = event.note_ties[pi] if event.note_ties else None
                        stop_tie = ties.stop if ties else event.tie_end
                        start_tie = ties.start if ties else event.tie_start
                        if stop_tie and previous is not None and previous[0] == start + cursor:
                            attack_index = previous[1]
                            held = attacks[attack_index]
                            attacks[attack_index] = replace(
                                held,
                                duration=held.duration + event.duration * 4,
                            )
                        else:
                            attack_index = len(attacks)
                            attacks.append(attack)
                            swing_delays.append(sounding - cursor)
                            if len(attacks) > MAX_ATTACKS:
                                raise ValueError("source exceeds the audit attack limit")
                        if start_tie and not event.is_grace:
                            pending[key] = start + cursor + event.duration * 4, attack_index
                    if not event.is_grace:
                        cursor += event.duration * 4
        for _, owner, global_scope, value, unit in sorted(changes):
            for identity in states:
                if global_scope or owner == identity:
                    states[identity] = value, unit
        start += lengths[number]
        if len(attacks) > MAX_ATTACKS:
            raise ValueError("source exceeds the audit attack limit")
    # Preserve source tie sustains independently of the explicit backbeat
    # timing model. Human Playback can vary its realization; do not disable
    # swing just because a note has a longer tied sustain.
    for index, (attack, delay) in enumerate(zip(attacks, swing_delays, strict=True)):
        if delay:
            attacks[index] = replace(attack, onset=attack.onset + delay)
            shifted += 1
    windows = _windows(score, route, lengths, attacks)
    return SourceAttacks(route, start, tuple(attacks), tuple(windows), shifted)


def _attack(
    part: Part,
    event: Event,
    voice: int,
    instrument: str | None,
    index: int,
    pi: int,
    pitch: int,
    measure: int,
    visit: int,
    offset: Fraction,
    onset: Fraction,
    grace_context: bool,
) -> Attack:
    pitch += 12 * sum(s.octaves for s in part.octave_shifts if s.contains(measure, offset / 4))
    ornament = next((o for o in event.ornaments if o.pitch_index == pi), None)
    auxiliary = (
        pitch + ornament.auxiliary_semitones
        if ornament and ornament.auxiliary_semitones is not None
        else None
    )
    return Attack(
        part.id,
        part.instrument_id or instrument,
        measure,
        visit,
        voice,
        index,
        pi,
        pitch,
        onset,
        onset,
        event.duration * 4,
        event.duration * 4,
        event.is_grace,
        grace_context,
        any(not a.pitch_indices or pi in a.pitch_indices for a in event.arpeggios),
        bool(event.arpeggios),
        ornament.kind if ornament else "",
        auxiliary,
    )


def _windows(
    score: Score, route: tuple[int, ...], lengths: dict[int, Fraction], attacks: list[Attack]
) -> list[PerformanceWindow]:
    if len(route) * sum(len(p.tremolos) + len(p.glissandi) for p in score.parts) > 1_000_000:
        raise ValueError("source performance-window lookup exceeds the audit work limit")
    result: list[PerformanceWindow] = []
    for attack in attacks:
        if attack.ornament and attack.auxiliary_pitch is not None:
            result.append(
                PerformanceWindow(
                    attack.ornament,
                    attack.onset,
                    attack.onset + attack.duration,
                    (attack.pitch, attack.auxiliary_pitch),
                )
            )
    points: dict[tuple[str, int, int, int, int], tuple[Fraction, int]] = {}
    for part in score.parts:
        for measure in part.measures:
            for voice in measure.voices:
                cursor = voice.start_offset * 4
                for index, event in enumerate(voice.events):
                    for pi, pitch in enumerate(event.pitches):
                        displacement = 12 * sum(
                            s.octaves
                            for s in part.octave_shifts
                            if s.contains(measure.number, cursor / 4)
                        )
                        points[part.id, measure.number, voice.number, index, pi] = (
                            cursor,
                            midi_pitch(pitch) + displacement,
                        )
                    if not event.is_grace:
                        cursor += event.duration * 4
    if len(route) * sum(len(p.tremolos) for p in score.parts) * len(points) > 8_000_000:
        raise ValueError("source tremolo pitch lookup exceeds the audit work limit")
    starts: list[Fraction] = []
    elapsed = Fraction(0)
    for number in route:
        starts.append(elapsed)
        elapsed += lengths[number]
    for visit, number in enumerate(route):
        for part in score.parts:
            result.extend(_span_windows(part, visit, number, route, starts, points))
    return result


def _span_windows(
    part: Part,
    visit: int,
    number: int,
    route: tuple[int, ...],
    starts: list[Fraction],
    points: dict[tuple[str, int, int, int, int], tuple[Fraction, int]],
) -> list[PerformanceWindow]:
    result = []
    for span in part.tremolos:
        if span.start.measure == number == span.end.measure:
            first = points.get((part.id, number, span.start.voice, span.start.event_index, 0))
            last = points.get((part.id, number, span.end.voice, span.end.event_index, 0))
            if first and last:
                events = next(m for m in part.measures if m.number == number).voices
                ending = next(v for v in events if v.number == span.end.voice).events[
                    span.end.event_index
                ]
                pitches = tuple(
                    p
                    for (owner, bar, voice, event, _), (_, p) in points.items()
                    if owner == part.id
                    and bar == number
                    and voice == span.start.voice
                    and event in {span.start.event_index, span.end.event_index}
                )
                result.append(
                    PerformanceWindow(
                        "two-note-tremolo",
                        starts[visit] + first[0],
                        starts[visit] + last[0] + ending.duration * 4,
                        pitches,
                    )
                )
    for gliss in part.glissandi:
        if gliss.start.event.measure != number:
            continue
        end_visit = next(
            (i for i in range(visit, len(route)) if route[i] == gliss.end.event.measure), None
        )
        if end_visit is None:
            continue
        first = points.get(
            (
                part.id,
                number,
                gliss.start.event.voice,
                gliss.start.event.event_index,
                gliss.start.pitch_index,
            )
        )
        last = points.get(
            (
                gliss.end.part_id or part.id,
                gliss.end.event.measure,
                gliss.end.event.voice,
                gliss.end.event.event_index,
                gliss.end.pitch_index,
            )
        )
        if first and last:
            low, high = sorted((first[1], last[1]))
            result.append(
                PerformanceWindow(
                    "glissando",
                    starts[visit] + first[0],
                    starts[end_visit] + last[0],
                    tuple(range(low, high + 1)),
                )
            )
    return result


def compare(attacks: tuple[Attack, ...], notes: tuple[MidiNote, ...]) -> Comparison:
    source_by_pitch: dict[int, list[Attack]] = defaultdict(list)
    midi_by_pitch: dict[int, list[MidiNote]] = defaultdict(list)
    for attack in attacks:
        source_by_pitch[attack.pitch].append(attack)
    for note in notes:
        midi_by_pitch[note.pitch].append(note)
    matched: list[Match] = []
    missing: list[Attack] = []
    extra: list[MidiNote] = []
    work = 0
    for pitch in sorted(source_by_pitch.keys() | midi_by_pitch.keys()):
        a = sorted(source_by_pitch[pitch], key=lambda n: n.onset)
        b = sorted(midi_by_pitch[pitch], key=lambda n: n.onset)
        work += (len(a) + 1) * (len(b) + 1)
        if work > MAX_TOTAL_MATCH_CELLS:
            raise ValueError("total alignment exceeds the audit work limit")
        pairs, lost, added = _match_pitch(a, b)
        matched.extend(pairs)
        missing.extend(lost)
        extra.extend(added)
    return Comparison(tuple(matched), tuple(missing), tuple(extra))


def _match_pitch(
    a: list[Attack], b: list[MidiNote]
) -> tuple[list[Match], list[Attack], list[MidiNote]]:
    rows, cols = len(a), len(b)
    if (rows + 1) * (cols + 1) > MAX_MATCH_CELLS:
        raise ValueError("per-pitch alignment exceeds the audit allocation/work limit")
    paths = [bytearray(cols + 1) for _ in range(rows + 1)]
    last = [float(n) for n in range(cols + 1)]
    for j in range(1, cols + 1):
        paths[0][j] = 2
    midi_onsets = [float(note.onset) for note in b]
    for i, attack in enumerate(a, 1):
        current = [float(i)] + [0.0] * cols
        paths[i][0] = 1
        tolerance = (
            0.4
            if attack.grace or attack.grace_context
            else 0.75
            if attack.arpeggio_context
            else 0.16
        )
        source_onset = float(attack.onset)
        for j in range(1, cols + 1):
            delta = abs(midi_onsets[j - 1] - source_onset)
            value, code = (last[j - 1] + delta if delta <= tolerance else math.inf), 3
            if last[j] + 1 < value:
                value, code = last[j] + 1, 1
            if current[j - 1] + 1 < value:
                value, code = current[j - 1] + 1, 2
            current[j], paths[i][j] = value, code
        last = current
    i, j = rows, cols
    matched: list[Match] = []
    missing: list[Attack] = []
    extra: list[MidiNote] = []
    while i or j:
        code = paths[i][j]
        if code == 3:
            matched.append(Match(a[i - 1], b[j - 1], float(b[j - 1].onset - a[i - 1].onset)))
            i, j = i - 1, j - 1
        elif code == 1:
            missing.append(a[i - 1])
            i -= 1
        elif code == 2:
            extra.append(b[j - 1])
            j -= 1
        else:
            raise ValueError("invalid audit alignment path")
    return matched, missing, extra
