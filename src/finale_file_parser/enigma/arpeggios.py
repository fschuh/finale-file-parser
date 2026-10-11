"""Resolve assigned rolled-chord signs and evidenced cross-staff connections.

Legacy glyph 103 (``g``) is the plain arpeggio in Finale's Maestro, Engraver
and Broadway Copyist charts. An assignment's ``vertAdd`` is its cloning endpoint
relative to the lowest note, in EVPUs. Geometry, rather than a long-line
threshold or a brace alone, determines which simultaneous chords it covers.
See ARCHITECTURE.md for the byte fields and scope of span resolution.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.ir import Arpeggio, Event, Measure, Part, PartGroup, Pitch

__all__ = ["arpeggios_by_entry", "connect_arpeggios"]

_ARPEGGIO_CHARACTER = 103
_EVPU_PER_STEP = 12
_STEPS = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
_CLEF_ANCHOR = {"G": 7 * 4 + 4, "F": 7 * 3 + 3, "C": 7 * 4}

EventPosition = tuple[str, int, int, int]
"""Staff-part id, measure number, voice number, event index."""


def _assignments(document: EnigmaDocument) -> dict[int, tuple[int | None, ...]]:
    definitions = {
        field_int(record.attrs.get("cmper"))
        for record in document.others.of_tag("articDef")
        if "part" not in record.attrs
        and "mainIsShape" not in record.fields
        and field_int(record.fields.get("charMain")) == _ARPEGGIO_CHARACTER
    }
    definitions.discard(None)
    out: dict[int, list[int | None]] = {}
    for record in document.details.of_tag("articAssign"):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entry = field_int(record.attrs.get("entnum"))
        definition = field_int(record.fields.get("articDef"))
        if entry is not None and definition is not None and definition in definitions:
            out.setdefault(entry, []).append(field_int(record.fields.get("vertAdd")))
    return {entry: tuple(offsets) for entry, offsets in out.items()}


def arpeggios_by_entry(document: EnigmaDocument) -> dict[int, tuple[Arpeggio, ...]]:
    """Only visible, assigned score glyphs place a sign; library entries do not."""
    return {
        entry: tuple(Arpeggio() for _ in offsets)
        for entry, offsets in _assignments(document).items()
    }


def _staff_distances(document: EnigmaDocument) -> dict[str, int]:
    return {
        f"P{staff}": distance
        for record in document.others.of_tag("instUsed")
        if "part" not in record.attrs and record.attrs.get("cmper") == "0"
        if (staff := field_int(record.fields.get("inst"))) is not None
        if (distance := field_int(record.fields.get("distFromTop"))) is not None
    }


def _pitch_y(pitch: Pitch, measure: Measure) -> int | None:
    anchor = _CLEF_ANCHOR.get(measure.clef_sign or "")
    if anchor is None or measure.clef_line is None:
        return None
    step = _STEPS.get(pitch.step)
    if step is None:
        return None
    # The clef's named pitch sits on its numbered line, counted from the
    # bottom. The staff's top (line 5) is the origin; a space is 24 EVPUs.
    return _EVPU_PER_STEP * (7 * pitch.octave + step - anchor + 2 * (measure.clef_line - 5))


def _bounds(event: Event, measure: Measure, distance: int) -> tuple[int, int] | None:
    if event.is_rest or event.is_grace:
        return None
    positions = [_pitch_y(pitch, measure) for pitch in event.pitches]
    if any(position is None for position in positions):
        return None
    ys = [position + distance for position in positions if position is not None]
    return min(ys), max(ys)


def _events_at(parts: tuple[Part, ...]) -> dict[EventPosition, tuple[Event, Measure, Fraction]]:
    out = {}
    for part in parts:
        clef_sign = None
        clef_line = None
        for measure in part.measures:
            if measure.clef_sign is not None:
                clef_sign, clef_line = measure.clef_sign, measure.clef_line
            geometry = replace(measure, clef_sign=clef_sign, clef_line=clef_line)
            for voice in measure.voices:
                onset = Fraction(0)
                for index, event in enumerate(voice.events):
                    out[part.id, measure.number, voice.number, index] = (event, geometry, onset)
                    if not event.is_grace:
                        onset += event.duration
    return out


def connect_arpeggios(
    document: EnigmaDocument,
    parts: tuple[Part, ...],
    groups: tuple[PartGroup, ...],
    assigned_entries: dict[EventPosition, int],
) -> tuple[Part, ...]:
    """Connect a sign covering simultaneous chords of a two-staff brace.

    Missing geometry, other clefs, ambiguous voices, graces and partial chord
    coverage leave the ordinary assigned sign intact. This does not infer an
    arpeggio from a brace or from simultaneous notes alone.
    """
    if not assigned_entries:
        return parts
    distances = _staff_distances(document)
    if not distances:
        return parts
    offsets = _assignments(document)
    events = _events_at(parts)
    by_onset: dict[tuple[str, int, Fraction], list[EventPosition]] = defaultdict(list)
    for position, (_, _, onset) in events.items():
        by_onset[position[0], position[1], onset].append(position)
    replacements: dict[EventPosition, Event] = {}
    braces = {
        group.part_ids for group in groups if group.symbol == "brace" and len(group.part_ids) == 2
    }
    for position, entry in assigned_entries.items():
        placed = events.get(position)
        if placed is None:
            continue
        event, measure, onset = placed
        distance = distances.get(position[0])
        if distance is None or len(event.arpeggios) != 1:
            continue
        extension = offsets[entry][0]
        bounds = _bounds(event, measure, distance)
        if extension is None or extension >= 0 or bounds is None:
            continue
        bottom = bounds[0] + extension
        for ids in braces:
            if position[0] != ids[0] or ids[1] not in distances:
                continue
            candidates = []
            for other in by_onset.get((ids[1], measure.number, onset), ()):
                target, target_measure, _ = events[other]
                target_bounds = _bounds(target, target_measure, distances[ids[1]])
                if (
                    target_bounds is not None
                    and bottom <= target_bounds[0]
                    and target_bounds[1] < bounds[0]
                    and not target.arpeggios
                ):
                    candidates.append(other)
            if len(candidates) != 1:
                continue
            other = candidates[0]
            if other in replacements:
                continue
            mark = Arpeggio(group=f"{position[0]}:{measure.number}:{entry}", part_ids=ids)
            replacements[position] = replace(event, arpeggios=(mark,))
            replacements[other] = replace(events[other][0], arpeggios=(mark,))
    return (
        tuple(
            replace(
                part,
                measures=tuple(
                    replace(
                        measure,
                        voices=tuple(
                            replace(
                                voice,
                                events=tuple(
                                    replacements.get(
                                        (part.id, measure.number, voice.number, index), event
                                    )
                                    for index, event in enumerate(voice.events)
                                ),
                            )
                            for voice in measure.voices
                        ),
                    )
                    for measure in part.measures
                ),
            )
            for part in parts
        )
        if replacements
        else parts
    )
