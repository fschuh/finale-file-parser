"""Write a `Score` as MusicXML.

Consumes the IR only -- nothing from `enigma` or `container` -- so any reader that
produces a `Score` exports for free (`docs/DECISIONS.md`, 2026-07-20).

Output is `score-partwise`, the more widely supported of the two MusicXML
orderings, and is validated against the official W3C schema in the tests.
"""

from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from finale_file_parser.errors import FinaleFileError
from finale_file_parser.export.navigation import append_navigation
from finale_file_parser.ir import (
    Ending,
    Event,
    Expression,
    Hairpin,
    LineSpan,
    Lyric,
    Measure,
    NoteEndpoint,
    NoteTies,
    OctaveShift,
    Ornament,
    Part,
    PartGroup,
    Pitch,
    Score,
    Slur,
    SlurEndpoint,
    Tempo,
    TimeSignature,
    Voice,
)

__all__ = ["MUSICXML_VERSION", "ExportError", "prints_as_words", "to_musicxml"]

MUSICXML_VERSION = "4.0"

_DOCTYPE = (
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML '
    f'{MUSICXML_VERSION} Partwise//EN" '
    f'"http://www.musicxml.org/dtds/{MUSICXML_VERSION}/partwise.dtd">'
)

_BREVE = Fraction(2, 1)
"""A breve is two whole notes, so it is the one note value whose fraction is not
`1/n` -- see `_note_type`."""

_NOTE_TYPES = {
    1: "whole",
    2: "half",
    4: "quarter",
    8: "eighth",
    16: "16th",
    32: "32nd",
    64: "64th",
    128: "128th",
    256: "256th",
}
"""Denominator of the written value as a fraction of a whole note -> MusicXML type."""

_MAX_DIVISIONS = 1_000_000
"""Guard against a pathological duration forcing an absurd divisions value."""

_ArpeggioNumbers = dict[tuple[str, int, int, int], tuple[str, ...]]

_MAX_WEDGE_NUMBER = 16
"""MusicXML's number-level bound, not a limit on the number of score hairpins."""


@dataclass(frozen=True)
class _Wedge:
    offset: Fraction
    kind: str
    number: str
    x_offset: Fraction


_HairpinDirections = dict[tuple[str, int], tuple[_Wedge, ...]]


@dataclass(frozen=True)
class _OctaveDirection:
    offset: Fraction
    type: str
    size: str
    number: str
    placement: str


_OctaveDirections = dict[tuple[str, int], tuple[_OctaveDirection, ...]]

_MAX_SLUR_NUMBER = 16
"""MusicXML's number-level bound on overlapping slurs in document order."""


@dataclass(frozen=True)
class _SlurNotation:
    type: str
    number: str
    placement: str | None
    x_offset: Fraction = Fraction(0)
    y_offset: Fraction = Fraction(0)


@dataclass(frozen=True)
class _SlurPosition:
    order: tuple[int, int, int]
    """Measure index, voice index and event index in the part's XML order."""

    onset: Fraction
    pitched: bool


_SlurNotations = dict[tuple[str, int, int, int], tuple[_SlurNotation, ...]]
_TremoloNotations = dict[SlurEndpoint, tuple[str, int]]


@dataclass(frozen=True)
class _GlissandoNotation:
    type: str
    number: str
    line_type: str
    x_offset: Fraction
    y_offset: Fraction


_GlissandoNotations = dict[NoteEndpoint, tuple[_GlissandoNotation, ...]]


class ExportError(FinaleFileError):
    """The score cannot be represented as MusicXML."""


def to_musicxml(score: Score) -> bytes:
    """Render `score` as a MusicXML document.

    Raises:
        ExportError: a duration has no MusicXML note type, or the divisions
            needed to express the score's durations exceed the guard.
    """
    score = matched_ties(_pickup_display(score))
    root = ET.Element("score-partwise", version=MUSICXML_VERSION)
    _append_identification(root, score)
    cues = any(
        not (event.playback and voice.playback) and not event.is_rest
        for part in score.parts
        for measure in part.measures
        for voice in measure.voices
        for event in voice.events
    )
    credited = any(_credit_values(score).values())
    if cues or credited:
        defaults = ET.SubElement(root, "defaults")
        if credited:
            # Credits are placed on a page; MuseScore drops the whole header
            # when a credit has no coordinates or the page has no size.
            scaling = ET.SubElement(defaults, "scaling")
            ET.SubElement(scaling, "millimeters").text = str(_STAFF_MILLIMETERS)
            ET.SubElement(scaling, "tenths").text = "40"
            layout = ET.SubElement(defaults, "page-layout")
            ET.SubElement(layout, "page-height").text = str(_PAGE_HEIGHT)
            ET.SubElement(layout, "page-width").text = str(_PAGE_WIDTH)
        if cues:
            # Every silent cue emitted here retains ordinary source note size.
            # MuseScore ignores type size=full on cues, but honors this standard
            # default and therefore preserves full-size notation as well as silence.
            appearance = ET.SubElement(defaults, "appearance")
            ET.SubElement(appearance, "note-size", type="cue").text = "100"
    # Schema order: credits follow defaults and precede the part list.
    _append_credits(root, score)

    bundles = _staff_bundles(score)
    labels = {
        bundle[0].id: group
        for bundle in bundles
        if len(bundle) > 1 and (group := _bundle_group(bundle, score.groups)) is not None
    }
    _append_part_list(root, _part_list_layout(score, bundles), labels=labels)

    for bundle in bundles:
        if len(bundle) == 1:
            _append_part(root, bundle[0], arpeggio_numbers=_arpeggio_numbers(bundle))
        else:
            _append_multistaff_part(root, bundle, score.groups)

    _append_default_tempo(root, score)
    _append_default_swing(root, score)
    append_navigation(root, score)
    _append_measure_labels(root, bundles)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{_DOCTYPE}\n{body}\n'.encode()


def _append_measure_labels(root: ET.Element, bundles: tuple[tuple[Part, ...], ...]) -> None:
    for index, (xml_part, bundle) in enumerate(zip(root.findall("part"), bundles, strict=True)):
        for xml, measure in zip(xml_part.findall("measure"), bundle[0].measures, strict=True):
            if measure.leading_spacer:
                xml.set("implicit", "yes")
            if measure.display_number is not None:
                # IDs keep source measure identity independent of the printed
                # number (including repeated/unnumbered labels).
                xml.set("id", f"source-measure-{index}-{measure.number}")
                xml.set("number", measure.display_number or "0")
                if not measure.display_number:
                    xml.set("implicit", "yes")


def matched_ties(score: Score) -> Score:
    """Drop tie stops that no tie start reaches.

    Finale keeps a note's tie-end flag after the note it was tied from is changed
    or deleted -- Crash Man's F#3 still carries one behind an F3 -- and neither
    draws a tie for it nor holds it in playback. A stop is kept when a start on the
    same sounding pitch, in any voice of the part, ends exactly where it begins.
    """
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

    def key(pitch: Pitch) -> int:
        return 12 * pitch.octave + semitone[pitch.step] + pitch.alteration

    def flags(event: Event) -> tuple[NoteTies, ...]:
        # A length mismatch is left for `_append_event` to reject.
        if event.note_ties and len(event.note_ties) != len(event.pitches):
            return ()
        return event.note_ties or tuple(
            NoteTies(event.tie_start, event.tie_end) for _ in event.pitches
        )

    parts = []
    for part in score.parts:
        timed: list[tuple[int, int, int, Fraction]] = []
        starts: set[tuple[Fraction, int]] = set()
        origin = Fraction(0)
        for m_index, measure in enumerate(part.measures):
            extent = Fraction(0)
            for v_index, voice in enumerate(measure.voices):
                onset = origin + voice.start_offset
                for e_index, event in enumerate(voice.events):
                    end = onset if event.is_grace else onset + event.duration
                    for pitch, tie in zip(event.pitches, flags(event), strict=False):
                        if tie.start:
                            starts.add((end, key(pitch)))
                    timed.append((m_index, v_index, e_index, onset))
                    onset = end
                extent = max(extent, onset - origin)
            origin += extent
        changes: dict[tuple[int, int, int], Event] = {}
        for m_index, v_index, e_index, onset in timed:
            event = part.measures[m_index].voices[v_index].events[e_index]
            ties = flags(event)
            if not ties:
                continue
            kept = tuple(
                replace(tie, stop=tie.stop and (onset, key(pitch)) in starts)
                for pitch, tie in zip(event.pitches, ties, strict=True)
            )
            if kept != ties:
                changes[m_index, v_index, e_index] = replace(
                    event, note_ties=kept, tie_end=any(t.stop for t in kept)
                )
        if not changes:
            parts.append(part)
            continue
        measures = tuple(
            replace(
                measure,
                voices=tuple(
                    replace(
                        voice,
                        events=tuple(
                            changes.get((m_index, v_index, e_index), event)
                            for e_index, event in enumerate(voice.events)
                        ),
                    )
                    for v_index, voice in enumerate(measure.voices)
                ),
            )
            for m_index, measure in enumerate(part.measures)
        )
        parts.append(replace(part, measures=measures))
    return replace(score, parts=tuple(parts))


def _pickup_offset(value: Fraction, spacer: Fraction) -> Fraction:
    if value == 0:
        return value  # a measure-wide control still applies at the printed start
    if value < spacer:
        raise ExportError("a timed marking lies inside an omitted pickup spacer")
    return value - spacer


def _pickup_display(score: Score) -> Score:
    """Project independently established spacers; retain the original IR clock."""
    if not any(m.leading_spacer for p in score.parts for m in p.measures):
        return score
    offsets: dict[int, Fraction] = {}
    for part in score.parts:
        for measure in part.measures:
            if measure.leading_spacer < 0:
                raise ExportError("pickup spacer must not be negative")
            if measure.number in offsets and offsets[measure.number] != measure.leading_spacer:
                raise ExportError("score staves have conflicting pickup spacers")
            offsets[measure.number] = measure.leading_spacer
    parts = []
    for part in score.parts:
        measures = tuple(_pickup_measure(m) if m.leading_spacer else m for m in part.measures)
        hairpins = tuple(
            replace(
                s,
                start_offset=_pickup_offset(
                    s.start_offset, offsets.get(s.start_measure, Fraction())
                ),
                end_offset=_pickup_offset(s.end_offset, offsets.get(s.end_measure, Fraction())),
            )
            for s in part.hairpins
        )
        octaves = tuple(
            replace(
                s,
                start_offset=_pickup_offset(
                    s.start_offset, offsets.get(s.start_measure, Fraction())
                ),
                end_offset=_pickup_offset(s.end_offset, offsets.get(s.end_measure, Fraction())),
            )
            for s in part.octave_shifts
        )
        lines = tuple(
            replace(
                s,
                start_offset=_pickup_offset(
                    s.start_offset, offsets.get(s.start_measure, Fraction())
                ),
                end_offset=_pickup_offset(s.end_offset, offsets.get(s.end_measure, Fraction())),
            )
            for s in part.lines
        )
        parts.append(
            replace(part, measures=measures, hairpins=hairpins, octave_shifts=octaves, lines=lines)
        )
    return replace(score, parts=tuple(parts))


def _pickup_measure(measure: Measure) -> Measure:
    spacer = measure.leading_spacer
    voices = []
    for voice in measure.voices:
        if voice.start_offset >= spacer:
            voices.append(replace(voice, start_offset=voice.start_offset - spacer))
        elif voice.start_offset == 0 and len(voice.events) == 1 and voice.events[0].is_measure_rest:
            event = voice.events[0]
            if event.duration <= spacer:
                raise ExportError("pickup spacer consumes the whole resting measure")
            voices.append(
                replace(voice, events=(replace(event, duration=event.duration - spacer),))
            )
        else:
            raise ExportError("a source note or written rest precedes the pickup spacer")
    return replace(
        measure,
        voices=tuple(voices),
        expressions=tuple(
            replace(e, offset=_pickup_offset(e.offset, spacer)) for e in measure.expressions
        ),
        pedals=tuple(replace(e, offset=_pickup_offset(e.offset, spacer)) for e in measure.pedals),
        clef_changes=tuple(
            replace(e, offset=_pickup_offset(e.offset, spacer)) for e in measure.clef_changes
        ),
    )


def _append_default_tempo(root: ET.Element, score: Score) -> None:
    if score.playback is None or not score.parts:
        return
    initial = score.parts[0].measures[0].number if score.parts[0].measures else None
    if any(
        expression.score_assignment
        and expression.tempo is not None
        and expression.offset == 0
        and (expression.playback is None or expression.playback.kind == "tempo")
        for part in score.parts
        for measure in part.measures
        if measure.number == initial
        for expression in measure.expressions
    ):
        return
    # A display-only first-beat metronome must carry the independent source
    # default alongside its printed rate. MuseScore otherwise infers playback
    # from the notation and overrides a separate measure-level sound element.
    attached = False
    for part in root.findall("part"):
        first = part.find("measure")
        if first is None:
            continue
        for direction in first.findall("direction"):
            if (
                direction.find("direction-type/metronome") is None
                or direction.findtext("offset", "0") != "0"
            ):
                continue
            sound = direction.find("sound")
            if sound is None:
                sound = ET.SubElement(direction, "sound")
            sound.set("tempo", _decimal_number(score.playback.quarter_bpm))
            attached = True
    if attached:
        return
    measure = root.find("part/measure")
    if measure is not None:
        position = next(
            (
                i
                for i, element in enumerate(measure)
                if element.tag not in {"barline", "attributes"}
            ),
            len(measure),
        )
        sound = ET.Element("sound", tempo=_decimal_number(score.playback.quarter_bpm))
        measure.insert(position, sound)


def _append_default_swing(root: ET.Element, score: Score) -> None:
    prefs = score.playback
    if prefs is None or not prefs.swing_amount or not score.parts or not score.parts[0].measures:
        return
    first = score.parts[0].measures[0]
    if any(
        e.score_assignment
        and e.playback is not None
        and e.playback.kind == "swing"
        and e.offset == 0
        for part in score.parts
        for measure in part.measures
        if measure.number == first.number
        for e in measure.expressions
    ):
        return
    if prefs.swing_amount not in {Fraction(0), Fraction(1)} or prefs.swing_unit is None:
        raise ExportError("default swing interpolation/unit is not established")
    measure = root.find("part/measure")
    if measure is None:
        return
    direction = next(
        (
            d
            for d in measure.findall("direction")
            if (d.findtext("direction-type/words") or "").lower().startswith("swing")
        ),
        None,
    )
    if direction is None:
        direction = ET.Element("direction", placement="above")
        ET.SubElement(ET.SubElement(direction, "direction-type"), "words").text = "Swing"
        at = next(
            (i for i, e in enumerate(measure) if e.tag not in {"barline", "attributes"}),
            len(measure),
        )
        measure.insert(at, direction)
    direction.set("system", "only-top")
    sound = direction.find("sound")
    if sound is None:
        sound = ET.SubElement(direction, "sound")
    _append_swing(sound, prefs.swing_amount, prefs.swing_unit)


def _append_part_list(
    root: ET.Element, score: Score, *, labels: dict[str, PartGroup] | None = None
) -> None:
    """The part list, with each group's brace or bracket wrapped around it.

    MusicXML expresses a group as a matched pair of `<part-group>` elements
    surrounding the `<score-part>`s it covers, identified by a `number` rather
    than by nesting. The number is reused once a group closes, which is what
    lets an arbitrarily deep score use few of them.
    """
    part_list = ET.SubElement(root, "part-list")
    starting, stopping = _group_edges(score)
    open_numbers: dict[int, str] = {}
    for index, part in enumerate(score.parts):
        for group_index in starting.get(index, ()):
            number = _lowest_free(open_numbers)
            open_numbers[group_index] = number
            _append_group(part_list, score.groups[group_index], number, "start")
        score_part = ET.SubElement(part_list, "score-part", id=part.id)
        label = (labels or {}).get(part.id)
        ET.SubElement(score_part, "part-name").text = (
            label.name if label is not None and label.name else part.name or part.id
        )
        abbreviation = label.abbreviation if label is not None else part.abbreviation
        if abbreviation:
            ET.SubElement(score_part, "part-abbreviation").text = abbreviation
        # Innermost first, so groups close in the reverse of the order they
        # opened even where several end on the same part.
        for group_index in reversed(stopping.get(index, ())):
            number = open_numbers.pop(group_index)
            ET.SubElement(part_list, "part-group", number=number, type="stop")


def _group_edges(score: Score) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Which groups start and stop at each part index, in opening order."""
    at = {part.id: index for index, part in enumerate(score.parts)}
    starting: dict[int, list[int]] = {}
    stopping: dict[int, list[int]] = {}
    for group_index, group in enumerate(score.groups):
        positions = [at[part_id] for part_id in group.part_ids if part_id in at]
        if not positions:
            continue
        starting.setdefault(min(positions), []).append(group_index)
        stopping.setdefault(max(positions), []).append(group_index)
    return starting, stopping


def _lowest_free(open_numbers: dict[int, str]) -> str:
    taken = set(open_numbers.values())
    number = 1
    while str(number) in taken:
        number += 1
    return str(number)


def _append_group(part_list: ET.Element, group: PartGroup, number: str, kind: str) -> None:
    element = ET.SubElement(part_list, "part-group", number=number, type=kind)
    # Schema order: group-name, group-abbreviation, group-symbol, group-barline.
    if group.name:
        ET.SubElement(element, "group-name").text = group.name
    if group.abbreviation:
        ET.SubElement(element, "group-abbreviation").text = group.abbreviation
    if group.symbol:
        ET.SubElement(element, "group-symbol").text = group.symbol
    if group.barline:
        ET.SubElement(element, "group-barline").text = "yes"


def _append_identification(root: ET.Element, score: Score) -> None:
    if score.title:
        work = ET.SubElement(root, "work")
        ET.SubElement(work, "work-title").text = score.title
    creators = [("composer", score.composer), ("arranger", score.metadata.get("arranger", ""))]
    rights = score.metadata.get("copyright", "")
    if not any(text for _, text in creators) and not rights:
        return
    identification = ET.SubElement(root, "identification")
    # Schema order: creator*, then rights*.
    for kind, text in creators:
        if text:
            ET.SubElement(identification, "creator", type=kind).text = text
    if rights:
        ET.SubElement(identification, "rights").text = rights


_STAFF_MILLIMETERS = 7
_PAGE_WIDTH = 1234
_PAGE_HEIGHT = 1597
"""A US Letter page (215.9 x 279.4 mm) in tenths of a 7 mm staff, the paper
NinSheetMusic engraves on."""

_CREDITS = (
    # keys, credit-types, x, y, justify, valign, font size
    (("title",), ("title",), _PAGE_WIDTH // 2, _PAGE_HEIGHT - 100, "center", "top", 24),
    (("subtitle",), ("subtitle",), _PAGE_WIDTH // 2, _PAGE_HEIGHT - 170, "center", "top", 14),
    # One right-hand block, as printed: MuseScore stacks separate composer and
    # arranger credits on the same spot.
    (
        ("composer", "arranger"),
        ("composer", "arranger"),
        _PAGE_WIDTH - 100,
        _PAGE_HEIGHT - 220,
        "right",
        "top",
        12,
    ),
    (("copyright",), ("rights",), _PAGE_WIDTH // 2, 100, "center", "bottom", 10),
)


def _credit_values(score: Score) -> dict[str, str]:
    values = {"title": score.title, "composer": score.composer, **score.metadata}
    return {key: values.get(key, "") for keys, *_ in _CREDITS for key in keys}


def _append_credits(root: ET.Element, score: Score) -> None:
    """Page-one header text, typed and placed, so readers rebuild the title block."""
    values = _credit_values(score)
    for keys, kinds, x, y, justify, valign, size in _CREDITS:
        present = [(key, kind) for key, kind in zip(keys, kinds, strict=True) if values[key]]
        if not present:
            continue
        credit = ET.SubElement(root, "credit", page="1")
        for _, kind in present:
            ET.SubElement(credit, "credit-type").text = kind
        ET.SubElement(
            credit,
            "credit-words",
            {
                "default-x": str(x),
                "default-y": str(y),
                "font-size": str(size),
                "justify": justify,
                "valign": valign,
            },
        ).text = "\n".join(values[key] for key, _ in present)


def _divisions_for(part: Part) -> int:
    """Divisions per quarter making note durations and hairpin offsets exact.

    MusicXML durations are integers, so the denominators have to be cleared. A
    triplet eighth is 1/12 of a whole note, which needs divisions divisible by 3 --
    picking 1 (or any power of two) silently truncates it to zero.
    """
    denominator = 1
    for measure in part.measures:
        for expression in measure.expressions:
            denominator = math.lcm(denominator, (expression.offset * 4).denominator)
        for pedal in measure.pedals:
            denominator = math.lcm(denominator, (pedal.offset * 4).denominator)
        for change in measure.clef_changes:
            denominator = math.lcm(denominator, (change.offset * 4).denominator)
        for voice in measure.voices:
            if voice.start_offset < 0:
                raise ExportError("voice start offset must not be negative")
            denominator = math.lcm(denominator, (voice.start_offset * 4).denominator)
            for event in voice.events:
                if event.is_grace:
                    continue
                # duration is a fraction of a whole note; a quarter is 1/4, so
                # duration * 4 * divisions must be a whole number.
                denominator = math.lcm(denominator, (event.duration * 4).denominator)
    for hairpin in part.hairpins:
        for offset in (hairpin.start_offset, hairpin.end_offset):
            denominator = math.lcm(denominator, (offset * 4).denominator)
    for span in part.octave_shifts:
        for offset in (span.start_offset, span.end_offset):
            denominator = math.lcm(denominator, (offset * 4).denominator)
    for line in part.lines:
        for offset in (line.start_offset, line.end_offset):
            denominator = math.lcm(denominator, (offset * 4).denominator)
    if denominator > _MAX_DIVISIONS:
        raise ExportError(f"durations require {denominator} divisions per quarter; refusing")
    return denominator


def _duration_in_divisions(duration: Fraction, divisions: int) -> int:
    value = duration * 4 * divisions
    if value.denominator != 1:
        raise ExportError(f"duration {duration} is not expressible in {divisions} divisions")
    return int(value)


_ACCIDENTALS = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}

_TupletNotation = tuple[str, int, bool, str]
"""(start or stop, nesting level, bracket, show-number) for one `<tuplet>`."""


def _tuplet_notations(events: tuple[Event, ...]) -> dict[int, tuple[_TupletNotation, ...]]:
    """`<tuplet>` starts and stops by event index, for the tuplets the voice closes.

    Finale brackets a tuplet only where its notes are not beamed together: every
    corpus PDF shows beamed triplets with a bare number (Hikari bar 4, under either
    bracket style) and unbeamed ones bracketed (SMB Game Over bar 2).
    """
    result: dict[int, list[_TupletNotation]] = {}
    opened: dict[int, int] = {}
    for index, event in enumerate(events):
        for level, mark in enumerate(event.tuplets, start=1):
            if mark.start:
                opened[level] = index
            if mark.stop and level in opened:
                first = opened.pop(level)
                group = [e for e in events[first : index + 1] if not e.is_grace]
                bracket = not all(e.beams and not e.is_rest for e in group)
                show = events[first].tuplets[level - 1].show_number
                result.setdefault(first, []).append(("start", level, bracket, show))
                result.setdefault(index, []).append(("stop", level, bracket, show))
    return {index: tuple(marks) for index, marks in result.items()}


def _time_modification(event: Event) -> tuple[int, int, str | None]:
    """actual-notes, normal-notes and normal-type for an event in a tuplet.

    Source tuplets keep their own counts -- six in the time of four, not 3:2 --
    so a reader rebuilds a sextuplet rather than two triplets. Without them the
    sounded ratio is inverted: a triplet sounds 2/3, so 3 notes in the time of 2.
    """
    assert event.tuplet_ratio is not None
    if event.tuplets:
        actual = normal = 1
        for mark in event.tuplets:
            actual *= mark.actual
            normal *= mark.normal
        if Fraction(normal, actual) == event.tuplet_ratio:
            unit = event.tuplets[-1].unit
            base = event.written_duration / (2 - Fraction(1, 2**event.dots))
            name = _NOTE_TYPES.get(unit.denominator) if unit.numerator == 1 else None
            return actual, normal, name if name is not None and unit != base else None
    return event.tuplet_ratio.denominator, event.tuplet_ratio.numerator, None


def _note_type(event: Event) -> str:
    """MusicXML note type from the written duration, undotting first.

    `written_duration` includes the augmentation dots, so a dotted quarter is 3/8
    -- which is not a note value. Removing the dots recovers the base 1/4.
    """
    undotted = event.written_duration / (2 - Fraction(1, 2**event.dots))
    if undotted == _BREVE:
        # The table below is keyed by denominator, which assumes a note value is
        # a whole note or shorter. A breve is the exception.
        return "breve"
    if undotted.numerator != 1:
        raise ExportError(f"written duration {event.written_duration} is not a note value")
    name = _NOTE_TYPES.get(undotted.denominator)
    if name is None:
        raise ExportError(f"written duration {event.written_duration} has no MusicXML type")
    return name


def _append_part(
    root: ET.Element,
    part: Part,
    *,
    divisions: int | None = None,
    arpeggio_numbers: _ArpeggioNumbers | None = None,
    hairpin_directions: _HairpinDirections | None = None,
    slur_notations: _SlurNotations | None = None,
    octave_directions: _OctaveDirections | None = None,
    glissando_notations: _GlissandoNotations | None = None,
    line_directions: _LineDirections | None = None,
    display_staves: dict[str, int] | None = None,
) -> None:
    element = ET.SubElement(root, "part", id=part.id)
    divisions = _divisions_for(part) if divisions is None else divisions
    if hairpin_directions is None:
        hairpin_directions = _hairpin_directions((part,))
    if slur_notations is None:
        slur_notations = _slur_notations((part,))
    if octave_directions is None:
        octave_directions = _octave_directions((part,))
    if line_directions is None:
        line_directions = _line_directions((part,))
    first = True
    hidden = part.staff_hide_mode in {"score", "score-parts"}
    reaffirmed = False
    tremolos = _tremolo_notations(part)
    glissandi = (
        _glissando_notations((part,)) if glissando_notations is None else glissando_notations
    )
    printed = _printed_times(part)
    for index, measure in enumerate(part.measures):
        _append_measure(
            element,
            measure,
            divisions,
            emit_divisions=first,
            printed=printed[index] if printed is not None else None,
            part_id=part.id,
            arpeggio_numbers=arpeggio_numbers,
            wedges=hairpin_directions.get((part.id, measure.number), ()),
            slur_notations=slur_notations,
            octaves=octave_directions.get((part.id, measure.number), ()),
            octave_spans=part.octave_shifts,
            tremolo_notations=tremolos,
            glissando_notations=glissandi,
            lines=line_directions.get((part.id, measure.number), ()),
            display_staves=display_staves,
        )
        if first and hidden:
            attributes = _initial_attributes(element[-1])
            assert attributes is not None  # the first measure emits divisions
            _append_hidden_staff_details(attributes)
        if (
            hidden
            and not reaffirmed
            and any(not event.is_rest for voice in measure.voices for event in voice.events)
        ):
            # Reaffirm the persistent print policy after the first written
            # notes. MuseScore mistakes an initial hidden resting staff for
            # hide-empty-staves, but honors the same policy after voiced music.
            attributes = ET.Element("attributes")
            _append_hidden_staff_details(attributes)
            current = element[-1]
            right = current.find("barline[@location='right']")
            current.insert(
                list(current).index(right) if right is not None else len(current), attributes
            )
            reaffirmed = True
        first = False


def _printed_times(part: Part) -> list[tuple[TimeSignature | None, str | None]] | None:
    """The `<time>` each measure writes, where the part carries printed signatures.

    A printed signature is written where what the page shows changes, not where
    the time in force does: a pickup held as 1/4 but shown as 4/4 prints 4/4 once,
    and a hidden split of a final bar prints nothing. None for a part with no
    display signature or symbol, which keeps `measure.time` as the `<time>`.
    """
    if not any(m.display_time or m.time_symbol for m in part.measures):
        return None
    result: list[tuple[TimeSignature | None, str | None]] = []
    in_force: TimeSignature | None = None
    last: tuple[TimeSignature | None, str | None] | None = None
    for measure in part.measures:
        if measure.time is not None:
            in_force = measure.time
        shown = (measure.display_time or in_force, measure.time_symbol)
        result.append(shown if shown != last else (None, None))
        last = shown
    return result


def _append_hidden_staff_details(attributes: ET.Element) -> None:
    ET.SubElement(attributes, "staff-details", {"print-object": "no", "print-spacing": "no"})


def _staff_bundles(score: Score) -> tuple[tuple[Part, ...], ...]:
    """Explicit shared playback identities or arpeggios join staff-parts for MusicXML."""
    positions = {part.id: index for index, part in enumerate(score.parts)}
    joined = [False] * max(0, len(score.parts) - 1)
    for index, (first, second) in enumerate(zip(score.parts, score.parts[1:], strict=False)):
        if first.instrument_id is not None and first.instrument_id == second.instrument_id:
            joined[index] = True
    for part in score.parts:
        for line in part.lines:
            target = line.end_part_id or part.id
            if target not in positions:
                raise ExportError("line endpoint names a missing score part")
            first_index, last_index = sorted((positions[part.id], positions[target]))
            for index in range(first_index, last_index):
                joined[index] = True
        for span in part.glissandi:
            target = span.end.part_id or part.id
            if target == part.id:
                continue
            if target not in positions:
                raise ExportError("glissando endpoint names a missing score part")
            first_index, last_index = sorted((positions[part.id], positions[target]))
            for index in range(first_index, last_index):
                joined[index] = True
        for measure in part.measures:
            for voice in measure.voices:
                for event in voice.events:
                    if len({mark.pitch_index for mark in event.cross_staff}) != len(
                        event.cross_staff
                    ):
                        raise ExportError("duplicate cross-staff note attachment")
                    for placement in event.cross_staff:
                        if placement.part_id is None:
                            if not 0 <= placement.pitch_index < len(event.pitches):
                                raise ExportError("invalid cross-staff note attachment")
                            continue
                        if (
                            placement.part_id not in positions
                            or not 0 <= placement.pitch_index < len(event.pitches)
                        ):
                            raise ExportError("invalid cross-staff note or destination part")
                        first_index, last_index = sorted(
                            (positions[part.id], positions[placement.part_id])
                        )
                        for index in range(first_index, last_index):
                            joined[index] = True
                    for mark in event.arpeggios:
                        if not mark.part_ids:
                            continue
                        indices = [positions.get(part_id, -1) for part_id in mark.part_ids]
                        if (
                            not mark.group
                            or len(indices) < 2
                            or part.id not in mark.part_ids
                            or indices[0] < 0
                            or indices != list(range(indices[0], indices[0] + len(indices)))
                        ):
                            raise ExportError("an arpeggio span must name consecutive score parts")
                        for index in indices[:-1]:
                            joined[index] = True
    for group in score.groups:
        if not group.instrument or not all(p in positions for p in group.part_ids):
            continue
        indices = [positions[part_id] for part_id in group.part_ids]
        if len(indices) > 1 and indices == list(range(indices[0], indices[0] + len(indices))):
            for index in indices[:-1]:
                joined[index] = True
    bundles: list[tuple[Part, ...]] = []
    start = 0
    for index, connected in enumerate(joined):
        if not connected:
            bundles.append(score.parts[start : index + 1])
            start = index + 1
    if score.parts:
        bundles.append(score.parts[start:])
    return tuple(bundles)


def _part_list_layout(score: Score, bundles: tuple[tuple[Part, ...], ...]) -> Score:
    ids = {part.id: bundle[0].id for bundle in bundles for part in bundle}
    absorbed = {
        group
        for bundle in bundles
        if len(bundle) > 1 and (group := _bundle_group(bundle, score.groups)) is not None
    }
    groups = []
    for group in score.groups:
        members = tuple(dict.fromkeys(ids[part_id] for part_id in group.part_ids if part_id in ids))
        if group in absorbed:
            # This group's symbol now belongs to the multi-staff part itself.
            continue
        groups.append(replace(group, part_ids=members))
    parts = []
    for bundle in bundles:
        group = _bundle_group(bundle, score.groups) if len(bundle) > 1 else None
        if group is not None and group.instrument and group.name:
            # The instrument's name ("Piano") labels its multi-staff part.
            parts.append(
                replace(
                    bundle[0],
                    name=group.name,
                    abbreviation=group.abbreviation or bundle[0].abbreviation,
                )
            )
        else:
            parts.append(bundle[0])
    return replace(score, parts=tuple(parts), groups=tuple(groups))


def _bundle_group(parts: tuple[Part, ...], groups: tuple[PartGroup, ...]) -> PartGroup | None:
    ids = tuple(part.id for part in parts)
    candidates = [group for group in groups if group.part_ids == ids and group.symbol]
    return next(
        (group for group in reversed(candidates) if group.symbol == "brace"),
        candidates[-1] if candidates else None,
    )


def _arpeggio_numbers(parts: tuple[Part, ...]) -> _ArpeggioNumbers:
    """Independent simultaneous rolls get different numbers, connected rolls one."""
    result: _ArpeggioNumbers = {}
    used: dict[tuple[int, Fraction], dict[str | tuple[str, int, int, int], str]] = {}
    for part in parts:
        for measure in part.measures:
            for voice in measure.voices:
                onset = voice.start_offset
                for index, event in enumerate(voice.events):
                    assigned = []
                    for mark_index, mark in enumerate(event.arpeggios):
                        numbers = used.setdefault((measure.number, onset), {})
                        identity = mark.group or (part.id, voice.number, index, mark_index)
                        if identity not in numbers:
                            if len(numbers) == 16:
                                raise ExportError("more than 16 simultaneous arpeggios")
                            numbers[identity] = str(len(numbers) + 1)
                        assigned.append(numbers[identity])
                    if assigned:
                        result[part.id, measure.number, voice.number, index] = tuple(assigned)
                    if not event.is_grace:
                        onset += event.duration
    return result


def _append_multistaff_part(
    root: ET.Element, parts: tuple[Part, ...], groups: tuple[PartGroup, ...]
) -> None:
    """Project staff-parts onto one XML part, keeping notes and their attachments."""
    numbers = tuple(measure.number for measure in parts[0].measures)
    if any(tuple(measure.number for measure in part.measures) != numbers for part in parts):
        raise ExportError("connected staff parts must have the same measure sequence")
    divisions = math.lcm(*(_divisions_for(part) for part in parts))
    if divisions > _MAX_DIVISIONS:
        raise ExportError(f"durations require {divisions} divisions per quarter; refusing")
    temporary = ET.Element("parts")
    arpeggio_numbers = _arpeggio_numbers(parts)
    hairpin_directions = _hairpin_directions(parts)
    line_directions = _line_directions(parts)
    slur_notations = _slur_notations(parts)
    octave_directions = _octave_directions(parts)
    glissando_notations = _glissando_notations(parts)
    next_voice = 1
    display_staves = {part.id: staff for staff, part in enumerate(parts, start=1)}
    for staff, part in enumerate(parts, start=1):
        _append_part(
            temporary,
            part,
            divisions=divisions,
            arpeggio_numbers=arpeggio_numbers,
            hairpin_directions=hairpin_directions,
            line_directions=line_directions,
            slur_notations=slur_notations,
            octave_directions=octave_directions,
            glissando_notations=glissando_notations,
            display_staves=display_staves,
        )
        voices = sorted({voice.number for measure in part.measures for voice in measure.voices})
        voice_ids = {str(voice): str(next_voice + index) for index, voice in enumerate(voices)}
        next_voice += len(voices)
        _assign_staff(temporary[-1], staff, voice_ids)
    group = _bundle_group(parts, groups)
    symbol = group.symbol if group is not None else None
    result = ET.SubElement(root, "part", id=parts[0].id)
    for index, number in enumerate(numbers):
        measures = tuple(part[index] for part in temporary)
        _merge_staff_measures(result, number, measures, symbol, first=index == 0)


def _assign_staff(part: ET.Element, staff: int, voices: dict[str, str]) -> None:
    for measure in part:
        for element in measure:
            if element.tag in {"note", "forward"}:
                voice = element.find("voice")
                if voice is not None and voice.text is not None:
                    voice.text = voices[voice.text]
                at = next(
                    (
                        index
                        for index, child in enumerate(element)
                        if child.tag in {"beam", "notations", "lyric"}
                    ),
                    len(element),
                )
                if element.find("staff") is None:
                    staff_element = ET.Element("staff")
                    staff_element.text = str(staff)
                    element.insert(at, staff_element)
            elif element.tag == "direction":
                at = next(
                    (index for index, child in enumerate(element) if child.tag == "sound"),
                    len(element),
                )
                staff_element = ET.Element("staff")
                staff_element.text = str(staff)
                element.insert(at, staff_element)
            elif element.tag == "attributes":
                for clef in element.findall("clef"):
                    clef.set("number", str(staff))
                for details in element.findall("staff-details"):
                    details.set("number", str(staff))


def _merged_attributes(
    measures: tuple[ET.Element, ...], symbol: str | None, *, first: bool
) -> ET.Element | None:
    sources = [_initial_attributes(measure) for measure in measures]
    if not first and all(source is None for source in sources):
        return None
    result = ET.Element("attributes")
    for tag in ("divisions", "key", "time"):
        for staff, source in enumerate(sources, start=1):
            if source is None or (element := source.find(tag)) is None:
                continue
            if tag == "divisions":
                if result.find(tag) is None:
                    result.append(element)
            else:
                element.set("number", str(staff))
                result.append(element)
    if first:
        ET.SubElement(result, "staves").text = str(len(measures))
        if symbol:
            ET.SubElement(
                result, "part-symbol", {"top-staff": "1", "bottom-staff": str(len(measures))}
            ).text = symbol
    for staff, source in enumerate(sources, start=1):
        if source is not None and (clef := source.find("clef")) is not None:
            clef.set("number", str(staff))
            result.append(clef)
    for staff, source in enumerate(sources, start=1):
        if source is not None:
            for details in source.findall("staff-details"):
                details.set("number", str(staff))
                result.append(details)
    return result


def _initial_attributes(measure: ET.Element) -> ET.Element | None:
    for element in measure:
        if element.tag in {"forward", "backup", "note"}:
            break
        if element.tag == "attributes":
            return element
    return None


def _merge_staff_measures(
    parent: ET.Element,
    number: int,
    measures: tuple[ET.Element, ...],
    symbol: str | None,
    *,
    first: bool,
) -> None:
    result = ET.SubElement(parent, "measure", number=str(number))
    attributes = _merged_attributes(measures, symbol, first=first)
    if attributes is not None:
        result.append(attributes)
    barlines = {
        element.get("location", "right"): element for element in measures[0].findall("barline")
    }
    for measure in measures[1:]:
        other = {
            element.get("location", "right"): element for element in measure.findall("barline")
        }
        if {key: _barline_identity(value) for key, value in other.items()} != {
            key: _barline_identity(value) for key, value in barlines.items()
        }:
            raise ExportError("connected staff parts have conflicting barlines")
        # A shared part-level bracket prints when any source staff displays it.
        # Hidden copies still carry the identical pass selection and timing.
        for key, barline in other.items():
            for selected, candidate in zip(
                barlines[key].findall("ending"), barline.findall("ending"), strict=True
            ):
                if candidate.get("print-object") != "no":
                    selected.attrib.pop("print-object", None)
    cursor = 0
    for measure in measures:
        if cursor:
            ET.SubElement(ET.SubElement(result, "backup"), "duration").text = str(cursor)
            cursor = 0
        initial = _initial_attributes(measure)
        for element in measure:
            if element is initial:
                continue
            if element.tag == "barline":
                continue
            result.append(element)
            duration = int(element.findtext("duration", "0"))
            if element.tag == "backup":
                cursor -= duration
            elif element.tag == "forward" or (
                element.tag == "note" and element.find("chord") is None
            ):
                cursor += duration
    if "left" in barlines:
        result.insert(0, barlines["left"])
    if "right" in barlines:
        result.append(barlines["right"])


def _barline_identity(barline: ET.Element) -> bytes:
    """Shared barline semantics exclude only independent bracket print policy."""
    normalized = copy.deepcopy(barline)
    for ending in normalized.findall("ending"):
        ending.attrib.pop("print-object", None)
    return ET.tostring(normalized)


_DYNAMICS_PLACEMENT = "below"
"""Where dynamics are engraved, and where a reader expects them. Tempo and
technique words go above; dynamics do not."""


@dataclass(frozen=True)
class _LineDirection:
    offset: Fraction
    type: str
    number: str
    span: LineSpan


_LineDirections = dict[tuple[str, int], tuple[_LineDirection, ...]]


def _line_directions(parts: tuple[Part, ...]) -> _LineDirections:
    positions = {p.id: _hairpin_measure_positions(p) for p in parts}
    staff_order = {p.id: i for i, p in enumerate(parts)}
    intervals = []
    for part in parts:
        for span in part.lines:
            if span.line_type not in {"solid", "dashed", "dotted", "wavy"}:
                raise ExportError("unsupported drawn line type")
            if span.start_cap not in {
                "none",
                "up",
                "down",
                "both",
                "arrow",
            } or span.end_cap not in {"none", "up", "down", "both", "arrow"}:
                raise ExportError("unsupported drawn line cap")
            if any(
                length is not None and length < 0
                for length in (span.start_cap_length, span.end_cap_length)
            ):
                raise ExportError("drawn line cap length must not be negative")
            target = span.end_part_id or part.id
            keys = []
            for identity, measure, offset in (
                (part.id, span.start_measure, span.start_offset),
                (target, span.end_measure, span.end_offset),
            ):
                if identity not in positions or measure not in positions[identity]:
                    raise ExportError("drawn line refers to a missing part or measure")
                index, length = positions[identity][measure]
                if not 0 <= offset <= length:
                    raise ExportError("drawn line offset is outside its measure")
                keys.append((index, staff_order[identity], offset))
            if (keys[1][0], span.end_offset) < (keys[0][0], span.start_offset):
                raise ExportError("drawn line end precedes its start")
            intervals.append((min(keys), max(keys), part.id, target, span))
    result: dict[tuple[str, int], list[_LineDirection]] = {}
    active: list[tuple[tuple[int, int, Fraction], str]] = []
    for low, high, owner, target, span in sorted(intervals, key=lambda i: i[:2]):
        active = [(end, n) for end, n in active if end > low]
        used = {n for _, n in active}
        number = next((str(n) for n in range(1, 17) if str(n) not in used), None)
        if number is None:
            raise ExportError("more than 16 drawn lines overlap in MusicXML document order")
        active.append((high, number))
        for identity, measure, offset, kind in (
            (owner, span.start_measure, span.start_offset, "start"),
            (target, span.end_measure, span.end_offset, "stop"),
        ):
            result.setdefault((identity, measure), []).append(
                _LineDirection(offset, kind, number, span)
            )
    return {
        key: tuple(sorted(directions, key=lambda d: d.offset)) for key, directions in result.items()
    }


def _append_lines(element: ET.Element, lines: tuple[_LineDirection, ...], divisions: int) -> None:
    for item in lines:
        span = item.span
        start = item.type == "start"
        x, y = (span.start_x, span.start_y) if start else (span.end_x, span.end_y)
        text = span.start_text if start else span.end_text
        direction = ET.SubElement(element, "direction", placement="below" if y < 0 else "above")
        if text:
            ET.SubElement(ET.SubElement(direction, "direction-type"), "words").text = text
        attributes = {
            "type": item.type,
            "number": item.number,
            "line-type": span.line_type,
            "line-end": span.start_cap if start else span.end_cap,
            "relative-x": _decimal_number(x * 10),
            "relative-y": _decimal_number(y * 10),
        }
        length = span.start_cap_length if start else span.end_cap_length
        if length is not None:
            attributes["end-length"] = _decimal_number(length * 10)
        ET.SubElement(
            ET.SubElement(direction, "direction-type"),
            "bracket",
            attributes,
        )
        if item.offset:
            ET.SubElement(direction, "offset", sound="no").text = str(
                _duration_in_divisions(item.offset, divisions)
            )


def _hairpin_measure_positions(part: Part) -> dict[int, tuple[int, Fraction]]:
    """Existing measure indices and bounds, without expanding span-supplied ids."""
    result: dict[int, tuple[int, Fraction]] = {}
    signature_length = Fraction(1)
    for index, measure in enumerate(part.measures):
        if measure.number in result:
            raise ExportError("hairpins require unique measure numbers within a part")
        if measure.time is not None:
            signature_length = Fraction(measure.time.beats, measure.time.beat_type)
        written_length = max(
            (
                voice.start_offset
                + sum((event.duration for event in voice.events if not event.is_grace), Fraction(0))
                for voice in measure.voices
            ),
            default=Fraction(0),
        )
        result[measure.number] = (
            index,
            max(signature_length - measure.leading_spacer, written_length),
        )
    return result


def _hairpin_endpoints(
    span: Hairpin, positions: dict[int, tuple[int, Fraction]]
) -> tuple[int, int]:
    if span.kind not in {"crescendo", "diminuendo"}:
        raise ExportError(f"unsupported hairpin kind {span.kind!r}")
    indices = []
    for measure, offset in (
        (span.start_measure, span.start_offset),
        (span.end_measure, span.end_offset),
    ):
        position = positions.get(measure)
        if position is None:
            raise ExportError(f"hairpin refers to missing measure {measure}")
        index, length = position
        if not 0 <= offset <= length:
            raise ExportError(f"hairpin offset {offset} is outside measure {measure}")
        indices.append(index)
    start, end = indices
    if (end, span.end_offset) <= (start, span.start_offset):
        raise ExportError("hairpin end must follow its start")
    return start, end


def _octave_stop(part: Part, span: OctaveShift, length: Fraction) -> Fraction:
    """Finale includes an attack at the endpoint; XML stops before that attack.

    Extend an exact attack endpoint through its note, capped at the next onset.
    A point span thus covers its source note and associated grace notes, without
    shifting the next attack. The IR retains the unmodified source endpoint.
    """
    measure = next(m for m in part.measures if m.number == span.end_measure)
    durations: list[Fraction] = []
    following: list[Fraction] = []
    for voice in measure.voices:
        onset = voice.start_offset
        for event in voice.events:
            if event.pitches and onset == span.end_offset:
                durations.append(event.duration)
            if onset > span.end_offset:
                following.append(onset)
            if not event.is_grace:
                onset += event.duration
    if not durations:
        if (span.start_measure, span.start_offset) == (span.end_measure, span.end_offset):
            raise ExportError("point octave span must cover a pitched attack")
        return span.end_offset
    following.extend(
        other.start_offset
        for other in part.octave_shifts
        if other.start_measure == span.end_measure and other.start_offset > span.end_offset
    )
    stop = min(span.end_offset + max(durations), min(following, default=length))
    if stop <= span.end_offset:
        # A grace-only endpoint can extend to the next onset or the barline.
        stop = min(following, default=length)
    if stop <= span.end_offset:
        raise ExportError("octave endpoint has no following metric position")
    return stop


def _octave_directions(parts: tuple[Part, ...]) -> _OctaveDirections:
    endpoints: list[tuple[int, int, Fraction, int, int, OctaveShift]] = []
    for staff, part in enumerate(parts):
        if not part.octave_shifts:
            continue
        positions = _hairpin_measure_positions(part)
        intervals: list[tuple[tuple[int, Fraction], tuple[int, Fraction]]] = []
        for index, span in enumerate(part.octave_shifts):
            if span.octaves not in {-2, -1, 1, 2}:
                raise ExportError("octave displacement must be one or two octaves")
            for measure, offset in (
                (span.start_measure, span.start_offset),
                (span.end_measure, span.end_offset),
            ):
                if measure not in positions or not 0 <= offset <= positions[measure][1]:
                    raise ExportError("octave endpoint is outside the part's measures")
            start = positions[span.start_measure][0], span.start_offset
            end = positions[span.end_measure][0], span.end_offset
            if end < start:
                raise ExportError("octave end must not precede its start")
            intervals.append((start, end))
            stop = _octave_stop(part, span, positions[span.end_measure][1])
            endpoints.append((start[0], staff, start[1], 1, index, span))
            endpoints.append((end[0], staff, stop, 0, index, span))
        ordered = sorted(intervals)
        if any(right[0] <= left[1] for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ExportError("overlapping octave spans on one staff are ambiguous")
    active: dict[tuple[int, int], str] = {}
    result: dict[tuple[str, int], list[_OctaveDirection]] = {}
    for _, staff, offset, starting, index, span in sorted(endpoints, key=lambda item: item[:5]):
        key = staff, index
        if starting:
            number = next((str(n) for n in range(1, 17) if str(n) not in active.values()), None)
            if number is None:
                raise ExportError("more than 16 octave lines overlap in MusicXML document order")
            active[key] = number
        else:
            number = active.pop(key)
        kind = ("down" if span.octaves > 0 else "up") if starting else "stop"
        measure = span.start_measure if starting else span.end_measure
        result.setdefault((parts[staff].id, measure), []).append(
            _OctaveDirection(
                offset,
                kind,
                str(7 * abs(span.octaves) + 1),
                number,
                "above" if span.octaves > 0 else "below",
            )
        )
    return {key: tuple(value) for key, value in result.items()}


def _append_octaves(
    element: ET.Element, directions: tuple[_OctaveDirection, ...], divisions: int
) -> None:
    """Place shifts at their real cursor times, then rewind before note voices.

    This standard serialization also supports importers whose pitch pass
    ignores direction offsets. It adds no notes, rests or elapsed score time.
    """
    cursor = 0
    for mark in directions:
        target = _duration_in_divisions(mark.offset, divisions)
        if target < cursor:
            raise ExportError("octave directions must follow their musical positions")
        if target > cursor:
            ET.SubElement(ET.SubElement(element, "forward"), "duration").text = str(target - cursor)
            cursor = target
        direction = ET.SubElement(element, "direction", placement=mark.placement)
        ET.SubElement(
            ET.SubElement(direction, "direction-type"),
            "octave-shift",
            type=mark.type,
            size=mark.size,
            number=mark.number,
        )
        ET.SubElement(direction, "offset", sound="yes").text = "0"
    if cursor:
        ET.SubElement(ET.SubElement(element, "backup"), "duration").text = str(cursor)


def _hairpin_directions(parts: tuple[Part, ...]) -> _HairpinDirections:
    """Pair spans with numbers in the order their endpoints enter the XML.

    Staff projection writes each measure staff by staff. Musical-time-only
    numbering can reuse a still-open number in that document order, so staff
    index precedes offset here. The offsets themselves preserve musical time.
    """
    endpoints: list[tuple[int, int, Fraction, int, int, Hairpin]] = []
    for staff, part in enumerate(parts):
        if not part.hairpins:
            continue
        positions = _hairpin_measure_positions(part)
        for index, span in enumerate(part.hairpins):
            start, end = _hairpin_endpoints(span, positions)
            endpoints.append((start, staff, span.start_offset, 1, index, span))
            endpoints.append((end, staff, span.end_offset, 0, index, span))
    active: dict[tuple[int, int], str] = {}
    result: dict[tuple[str, int], list[_Wedge]] = {}
    for _, staff, offset, starting, index, span in sorted(endpoints, key=lambda item: item[:5]):
        key = staff, index
        if starting:
            number = next(
                (
                    str(value)
                    for value in range(1, _MAX_WEDGE_NUMBER + 1)
                    if str(value) not in active.values()
                ),
                None,
            )
            if number is None:
                raise ExportError("more than 16 hairpins overlap in MusicXML document order")
            active[key] = number
        else:
            number = active.pop(key)
        measure = span.start_measure if starting else span.end_measure
        result.setdefault((parts[staff].id, measure), []).append(
            _Wedge(
                offset,
                span.kind if starting else "stop",
                number,
                span.start_x_offset if starting else span.end_x_offset,
            )
        )
    return {key: tuple(directions) for key, directions in result.items()}


def _append_wedges(element: ET.Element, wedges: tuple[_Wedge, ...], divisions: int) -> None:
    """Directions are emitted at cursor zero; offsets never advance the notes."""
    # Leave the optional spread to the reader's style. MuseScore treats the
    # crescendo start's spread as overall height (despite MusicXML ignoring it
    # at the closed tip), so an explicit zero collapses the whole hairpin.
    # Source opening widths are not decoded; see ARCHITECTURE for importer evidence.
    for wedge in wedges:
        direction = ET.SubElement(element, "direction", placement=_DYNAMICS_PLACEMENT)
        attrs = {"type": wedge.kind, "number": wedge.number}
        if wedge.x_offset:
            attrs["relative-x"] = _decimal_number(wedge.x_offset * 10)
        ET.SubElement(
            ET.SubElement(direction, "direction-type"),
            "wedge",
            attrs,
        )
        ET.SubElement(direction, "offset", sound="yes").text = str(
            _duration_in_divisions(wedge.offset, divisions)
        )


def _slur_positions(part: Part) -> dict[SlurEndpoint, _SlurPosition]:
    """Resolve authored endpoint references without expanding supplied indices."""
    result = {}
    measures: set[int] = set()
    for measure_index, measure in enumerate(part.measures):
        if measure.number in measures:
            raise ExportError("slurs require unique measure numbers within a part")
        measures.add(measure.number)
        voices: set[int] = set()
        for voice_index, voice in enumerate(measure.voices):
            if voice.number in voices:
                raise ExportError("slurs require unique voice numbers within a measure")
            voices.add(voice.number)
            onset = voice.start_offset
            for event_index, event in enumerate(voice.events):
                result[SlurEndpoint(measure.number, voice.number, event_index)] = _SlurPosition(
                    (measure_index, voice_index, event_index), onset, not event.is_rest
                )
                if not event.is_grace:
                    onset += event.duration
    return result


def _slur_endpoints(
    span: Slur, positions: dict[SlurEndpoint, _SlurPosition]
) -> tuple[_SlurPosition, _SlurPosition]:
    if span.placement not in {None, "above", "below"}:
        raise ExportError(f"unsupported slur placement {span.placement!r}")
    start = positions.get(span.start)
    end = positions.get(span.end)
    if start is None or end is None:
        raise ExportError("slur refers to a missing measure, voice or event")
    if not start.pitched or not end.pitched:
        raise ExportError("slur endpoints must be pitched events")
    if span.graphical:
        if span.start != span.end or span.start_x_offset == span.end_x_offset:
            raise ExportError("a graphical slur needs distinct drawing endpoints on one event")
        return start, end
    start_time, end_time = (start.order[0], start.onset), (end.order[0], end.onset)
    if end_time < start_time or (
        end_time == start_time
        and (start.order[1] != end.order[1] or end.order[2] <= start.order[2])
    ):
        raise ExportError("slur end must follow its start")
    return start, end


def _slur_notations(parts: tuple[Part, ...]) -> _SlurNotations:
    """Pair complete spans in actual measure/staff/voice/event XML order.

    A cross-voice stop can precede its start in XML. Whichever endpoint is
    serialized first reserves the number; the second releases it. Musical
    endpoints still retain their start/stop types and exact event references.
    """
    endpoints: list[tuple[int, int, int, int, bool, int, Slur]] = []
    for staff, part in enumerate(parts):
        if not part.slurs:
            continue
        positions = _slur_positions(part)
        for index, span in enumerate(part.slurs):
            start, end = _slur_endpoints(span, positions)
            for position, starting in ((start, True), (end, False)):
                measure, voice, event = position.order
                endpoints.append((measure, staff, voice, event, starting, index, span))
    active: dict[tuple[int, int], str] = {}
    result: dict[tuple[str, int, int, int], list[_SlurNotation]] = {}
    for _, staff, _, _, starting, index, span in sorted(
        endpoints,
        key=lambda item: (
            *item[:4],
            2 if item[6].graphical and not item[4] else int(item[4]),
            item[5],
        ),
    ):
        identity = staff, index
        number = active.pop(identity, None)
        if number is None:
            number = next(
                (
                    str(value)
                    for value in range(1, _MAX_SLUR_NUMBER + 1)
                    if str(value) not in active.values()
                ),
                None,
            )
            if number is None:
                raise ExportError("more than 16 slurs overlap in MusicXML document order")
            active[identity] = number
        point = span.start if starting else span.end
        result.setdefault(
            (parts[staff].id, point.measure, point.voice, point.event_index), []
        ).append(
            _SlurNotation(
                "start" if starting else "stop",
                number,
                span.placement,
                span.start_x_offset if starting else span.end_x_offset,
                span.start_y_offset if starting else span.end_y_offset,
            )
        )
    return {key: tuple(marks) for key, marks in result.items()}


_MAX_GLYPH = 2
"""Text this short with no letters or digits is a music-font character rather
than words. Printing it literally puts an A-umlaut in the score where a
fortissimo belongs -- the same guard `enigma.jumps` applies to the segno."""

_MUSICXML_DYNAMICS = frozenset(
    """p pp ppp pppp ppppp pppppp f ff fff ffff fffff ffffff mp mf
       sf sfp sfpp fp rf rfz sfz sffz fz n pf sfzp""".split()
)
"""The element names MusicXML's `<dynamics>` accepts.

A marking outside this set is not an element -- `subito p` is a real library
entry whose name has a space in it, and emitting `<subito p/>` would produce a
document no parser can read. Those go to `<other-dynamics>`, which is what it
is for.
"""


def _append_pedals(element: ET.Element, measure: Measure, divisions: int) -> None:
    extent = max(
        (
            v.start_offset + sum((e.duration for e in v.events if not e.is_grace), Fraction(0))
            for v in measure.voices
        ),
        default=Fraction(0),
    )
    if measure.time is not None:
        extent = max(extent, Fraction(measure.time.beats, measure.time.beat_type))
    for pedal in sorted(measure.pedals, key=lambda p: p.offset):
        if pedal.kind not in {"start", "stop", "change"} or not 0 <= pedal.offset <= extent:
            raise ExportError("pedal requires a supported change at a position within its measure")
        direction = ET.SubElement(element, "direction", placement="below")
        ET.SubElement(
            ET.SubElement(direction, "direction-type"),
            "pedal",
            type=pedal.kind,
            sign="yes" if pedal.sign else "no",
            line="yes" if pedal.line else "no",
        )
        if pedal.offset:
            ET.SubElement(direction, "offset").text = str(
                _duration_in_divisions(pedal.offset, divisions)
            )
        ET.SubElement(direction, "sound", {"damper-pedal": "no" if pedal.kind == "stop" else "yes"})


def _append_expressions(element: ET.Element, measure: Measure, divisions: int) -> None:
    """Emit this staff's markings.

    Structured markings keep their notation and playback meaning:

    * a dynamic this project has named becomes a real `<dynamics>` element, so a
      consumer gets `<ff/>` rather than a character it would have to recognise;
    * an explicit metronome marking becomes `<metronome>` and quarter-note
      `<sound tempo="...">`, with any surrounding text emitted once;
    * other readable text, including tempo words without an explicit rate, is
      emitted as `<words>`;
    * an unidentified music-font glyph is **dropped**, because printing it
      literally is worse than omitting it. The IR keeps it either way.

    The legacy untyped `velocity` is not emitted. A separately decoded key-
    velocity instruction uses MusicXML's percentage of MIDI forte 90; a typed
    tempo can differ from its printed metronome. Nonabsolute source values are
    retained with diagnostics rather than converted into impossible controls.
    """
    seen_swing = set()
    for expression in measure.expressions:
        if not expression.score_assignment:
            continue
        if expression.playback is not None and expression.playback.kind == "swing":
            identity = (
                expression.offset,
                expression.playback,
                expression.score_wide,
                expression.layer,
                expression.visible,
            )
            if identity in seen_swing:
                continue
            seen_swing.add(identity)
        if not expression.visible:
            direction = (
                _append_tempo(element, expression.tempo)
                if expression.tempo is not None
                else ET.SubElement(element, "direction")
            )
            for kind in direction.findall("direction-type"):
                direction.remove(kind)
            kind = ET.Element("direction-type")
            ET.SubElement(kind, "other-direction", {"print-object": "no"}).text = expression.text
            direction.insert(0, kind)
        elif expression.tempo is not None:
            direction = _append_tempo(element, expression.tempo)
        elif expression.playback is not None and expression.playback.kind == "swing":
            direction = ET.SubElement(element, "direction", placement="above")
            ET.SubElement(ET.SubElement(direction, "direction-type"), "words").text = (
                "Straight" if not expression.playback.value else "Swing"
            )
        elif expression.is_rehearsal:
            # `<rehearsal>`, not `<words>`: the two are different elements and a
            # consumer treats them differently -- a rehearsal mark is a
            # navigation target, and players jump to it.
            direction = ET.SubElement(element, "direction", placement="above")
            mark = ET.SubElement(ET.SubElement(direction, "direction-type"), "rehearsal")
            mark.text = expression.text
        elif expression.marking:
            direction = ET.SubElement(element, "direction", placement=_DYNAMICS_PLACEMENT)
            dynamics = ET.SubElement(ET.SubElement(direction, "direction-type"), "dynamics")
            if expression.marking in _MUSICXML_DYNAMICS:
                ET.SubElement(dynamics, expression.marking)
            else:
                ET.SubElement(dynamics, "other-dynamics").text = expression.marking
        elif prints_as_words(expression):
            direction = ET.SubElement(element, "direction", placement="above")
            words = ET.SubElement(ET.SubElement(direction, "direction-type"), "words")
            words.text = expression.text
        else:
            continue
        _append_expression_playback(direction, expression)
        if expression.score_wide and expression.playback and expression.playback.kind == "swing":
            direction.set("system", "only-top")
        if expression.offset:
            offset = ET.Element("offset", sound="yes")
            offset.text = str(_duration_in_divisions(expression.offset, divisions))
            # MusicXML places offset before voice/staff/sound. Directions are
            # emitted at cursor zero, so neither this nor backups move notes.
            at = next(
                (i for i, child in enumerate(direction) if child.tag == "sound"), len(direction)
            )
            direction.insert(at, offset)


def _append_expression_playback(direction: ET.Element, expression: Expression) -> None:
    playback = expression.playback
    if playback is None:
        return
    if playback.kind != "tempo" or playback.value <= 0:
        for existing_sound in direction.findall("sound"):
            existing_sound.attrib.pop("tempo", None)
            if not existing_sound.attrib and not len(existing_sound):
                direction.remove(existing_sound)
    if playback.kind == "none":
        return
    if playback.kind == "swing":
        sound = direction.find("sound")
        if sound is None:
            sound = ET.SubElement(direction, "sound")
        _append_swing(sound, Fraction(playback.value, 1024), playback.beat_unit)
        if playback.pass_number:
            sound.set("time-only", str(playback.pass_number))
        return
    attrs = {}
    if playback.kind == "tempo" and playback.beat_unit is not None:
        rate = playback.value * playback.beat_unit * 4
        if rate <= 0:
            return
        attrs["tempo"] = _decimal_number(rate)
    elif playback.kind == "amplitude":
        if not 0 <= playback.value <= 127:
            return
        attrs["dynamics"] = _decimal_number(Fraction(playback.value * 100, 90))
    if not attrs:
        return
    sound = direction.find("sound")
    if sound is None:
        sound = ET.SubElement(direction, "sound")
    sound.attrib.update(attrs)
    if playback.pass_number:
        sound.set("time-only", str(playback.pass_number))


def _append_swing(sound: ET.Element, amount: Fraction, unit: Fraction | None) -> None:
    swing = ET.SubElement(sound, "swing")
    if amount == 0:
        ET.SubElement(swing, "straight")
        return
    if amount != 1 or unit not in {Fraction(1, 8), Fraction(1, 16)}:
        raise ExportError("swing needs an established triplet amount and eighth/16th unit")
    ET.SubElement(swing, "first").text = "2"
    ET.SubElement(swing, "second").text = "1"
    ET.SubElement(swing, "swing-type").text = "eighth" if unit == Fraction(1, 8) else "16th"


def _decimal_number(value: Fraction) -> str:
    text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _append_tempo(element: ET.Element, tempo: Tempo) -> ET.Element:
    if tempo.per_minute <= 0 or not 0 <= tempo.dots <= 3:
        raise ExportError("tempo must have a positive rate and zero to three dots")
    unit = _NOTE_TYPES.get(tempo.beat_unit.denominator)
    if tempo.beat_unit.numerator != 1 or unit is None:
        raise ExportError(f"tempo beat unit {tempo.beat_unit} has no MusicXML type")
    direction = ET.SubElement(element, "direction", placement="above")
    if tempo.words:
        ET.SubElement(ET.SubElement(direction, "direction-type"), "words").text = tempo.words
    for value in (tempo, *tempo.equivalents):
        unit = _NOTE_TYPES.get(value.beat_unit.denominator)
        if value.beat_unit.numerator != 1 or unit is None:
            raise ExportError("unsupported equivalent tempo unit")
        if value.quarter_bpm != tempo.quarter_bpm or (value is not tempo and value.equivalents):
            raise ExportError("equivalent tempos must have the same rate and not be nested")
        metronome = ET.SubElement(ET.SubElement(direction, "direction-type"), "metronome")
        ET.SubElement(metronome, "beat-unit").text = unit
        for _ in range(value.dots):
            ET.SubElement(metronome, "beat-unit-dot")
        per_minute = _decimal_number(value.per_minute)
        if value.upper_per_minute is not None:
            if value.upper_per_minute < value.per_minute:
                raise ExportError("tempo range must have an ordered upper limit")
            per_minute += "–" + _decimal_number(value.upper_per_minute)
        ET.SubElement(metronome, "per-minute").text = per_minute
    if tempo.upper_per_minute is None:
        ET.SubElement(direction, "sound", tempo=_decimal_number(tempo.quarter_bpm))
    return direction


def prints_as_words(expression: Expression) -> bool:
    """Whether this expression is emitted as `<words>`.

    False for a rehearsal mark, which gets `<rehearsal>` instead.

    Public because the export audit counts against it: the completeness sweep
    asserts that everything this predicate calls printable *is* printed, and one
    rule stated once is what makes that check mean anything. Whether the rule
    itself is right is pinned by the unit tests, not here.
    """
    if expression.tempo is not None:
        return bool(expression.tempo.words)
    return not expression.is_rehearsal and not expression.marking and not _is_glyph(expression.text)


def _is_glyph(text: str) -> bool:
    return len(text) <= _MAX_GLYPH and not any(character.isalnum() for character in text)


def _glissando_notations(parts: tuple[Part, ...]) -> _GlissandoNotations:
    positions = {part.id: _slur_positions(part) for part in parts}
    events = {
        NoteEndpoint(SlurEndpoint(m.number, v.number, i), j, p.id): event
        for p in parts
        for m in p.measures
        for v in m.voices
        for i, event in enumerate(v.events)
        for j in range(len(event.pitches))
    }
    staff_order = {p.id: i for i, p in enumerate(parts)}
    endpoints = []
    for owner in parts:
        for index, span in enumerate(owner.glissandi):
            if span.start.part_id not in {None, owner.id}:
                raise ExportError("a glissando must be owned by its starting part")
            points = tuple(
                replace(point, part_id=point.part_id or owner.id)
                for point in (span.start, span.end)
            )
            resolved = [positions.get(point.part_id or "", {}).get(point.event) for point in points]
            if any(point not in events for point in points) or any(p is None for p in resolved):
                raise ExportError(
                    "glissando endpoint does not identify a pitched note in this instrument"
                )
            start, end = resolved
            assert start is not None and end is not None
            if points[0] == points[1] or (end.order[0], end.onset) < (start.order[0], start.onset):
                raise ExportError("glissando end must follow its start")
            if span.line_type not in {"wavy", "solid"}:
                raise ExportError("unsupported glissando line type")
            for point, position, starting in zip(points, (start, end), (True, False), strict=True):
                rank = (
                    position.order[0],
                    staff_order[point.part_id or ""],
                    *position.order[1:],
                    point.pitch_index,
                )
                mark = _GlissandoNotation(
                    "start" if starting else "stop",
                    "",
                    span.line_type,
                    span.start_x_offset if starting else span.end_x_offset,
                    span.start_y_offset if starting else span.end_y_offset,
                )
                endpoints.append((rank, owner.id, index, point, mark))
    result: dict[NoteEndpoint, list[_GlissandoNotation]] = {}
    active: dict[tuple[str, int], str] = {}
    for _, owner_id, index, point, mark in sorted(
        endpoints, key=lambda row: (row[0], row[1], row[2])
    ):
        identity = owner_id, index
        number = active.pop(identity, None)
        if number is None:
            number = next((str(i) for i in range(1, 17) if str(i) not in active.values()), None)
            if number is None:
                raise ExportError("more than 16 overlapping glissandi")
            active[identity] = number
        result.setdefault(point, []).append(replace(mark, number=number))
    return {point: tuple(items) for point, items in result.items()}


def _tremolo_notations(part: Part) -> _TremoloNotations:
    events = {
        SlurEndpoint(measure.number, voice.number, index): event
        for measure in part.measures
        for voice in measure.voices
        for index, event in enumerate(voice.events)
    }
    result: _TremoloNotations = {}
    for span in part.tremolos:
        a, b = events.get(span.start), events.get(span.end)
        adjacent = span.end == SlurEndpoint(
            span.start.measure, span.start.voice, span.start.event_index + 1
        )
        if (
            not adjacent
            or a is None
            or b is None
            or a.is_rest
            or b.is_rest
            or a.is_grace
            or b.is_grace
        ):
            raise ExportError("tremolo endpoints must be adjacent pitched events in the same voice")
        if (
            not 1 <= span.marks <= 8
            or a.duration != b.duration
            or a.written_duration != b.written_duration
        ):
            raise ExportError("tremolo requires matching rhythmic values and 1..8 strokes")
        if span.start in result or span.end in result:
            raise ExportError("overlapping tremolo pairs")
        result[span.start], result[span.end] = ("start", span.marks), ("stop", span.marks)
    return result


def _append_measure(
    parent: ET.Element,
    measure: Measure,
    divisions: int,
    *,
    emit_divisions: bool,
    part_id: str = "",
    arpeggio_numbers: _ArpeggioNumbers | None = None,
    wedges: tuple[_Wedge, ...] = (),
    slur_notations: _SlurNotations | None = None,
    octaves: tuple[_OctaveDirection, ...] = (),
    octave_spans: tuple[OctaveShift, ...] = (),
    tremolo_notations: _TremoloNotations | None = None,
    glissando_notations: _GlissandoNotations | None = None,
    lines: tuple[_LineDirection, ...] = (),
    display_staves: dict[str, int] | None = None,
    printed: tuple[TimeSignature | None, str | None] | None = None,
) -> None:
    element = ET.SubElement(parent, "measure", number=str(measure.number))
    _append_barline(element, measure, "left")
    _append_attributes(element, measure, divisions, emit_divisions=emit_divisions, printed=printed)
    for words in measure.directions:
        if any(mark.text == words for mark in measure.navigation):
            continue
        # Before the notes: the marking applies to the measure, and a direction
        # placed after them would read as belonging to the next bar.
        direction = ET.SubElement(element, "direction", placement="above")
        ET.SubElement(ET.SubElement(direction, "direction-type"), "words").text = words
    _append_expressions(element, measure, divisions)
    _append_pedals(element, measure, divisions)
    _append_lines(element, lines, divisions)
    _append_wedges(element, wedges, divisions)
    _append_octaves(element, octaves, divisions)
    _append_clef_changes(element, measure, divisions)

    order = _voice_order(measure)
    for index, voice in enumerate(measure.voices):
        if index:
            # Voices are written in sequence, so the cursor must be rewound to the
            # start of the measure before each one after the first.
            previous_voice = measure.voices[index - 1]
            spent = _duration_in_divisions(previous_voice.start_offset, divisions) + sum(
                (
                    _duration_in_divisions(e.duration, divisions)
                    for e in measure.voices[index - 1].events
                ),
                0,
            )
            if spent:
                backup = ET.SubElement(element, "backup")
                ET.SubElement(backup, "duration").text = str(spent)
        if voice.start_offset:
            forward = ET.SubElement(element, "forward")
            ET.SubElement(forward, "duration").text = str(
                _duration_in_divisions(voice.start_offset, divisions)
            )
            ET.SubElement(forward, "voice").text = str(order.get(voice.number, voice.number))
        onset = voice.start_offset
        written = replace(voice, number=order[voice.number]) if voice.number in order else voice
        tuplet_marks = _tuplet_notations(voice.events)
        for event_index, event in enumerate(voice.events):
            numbers = (
                ()
                if arpeggio_numbers is None
                else arpeggio_numbers.get((part_id, measure.number, voice.number, event_index), ())
            )
            slurs = (
                ()
                if slur_notations is None
                else slur_notations.get((part_id, measure.number, voice.number, event_index), ())
            )
            displacement = sum(
                span.octaves for span in octave_spans if span.contains(measure.number, onset)
            )
            _append_event(
                element,
                event,
                written,
                divisions,
                arpeggio_numbers=numbers,
                slurs=slurs,
                tuplets=tuplet_marks.get(event_index, ()),
                octave_displacement=displacement,
                display_staves=display_staves,
                tremolo=(tremolo_notations or {}).get(
                    SlurEndpoint(measure.number, voice.number, event_index)
                ),
                glissandi=tuple(
                    (glissando_notations or {}).get(
                        NoteEndpoint(
                            SlurEndpoint(measure.number, voice.number, event_index), i, part_id
                        ),
                        (),
                    )
                    for i in range(len(event.pitches))
                ),
            )
            if not event.is_grace:
                onset += event.duration

    _append_barline(element, measure, "right")


def _voice_order(measure: Measure) -> dict[int, int]:
    """Renumber a staff's sounding layers so the highest-pitched one is voice 1.

    MusicXML readers treat voice 1 as the upper voice -- MuseScore places its rests
    high and voice 2's low, measuring an explicit rest position from there -- but a
    Finale layer number says nothing about register: an upper melody often sits in
    layer 2. The numbers are only permuted among the layers that hold notes. A
    measure whose renumbered layer carries a tie across either barline keeps its
    numbers, since a tie must stay in one voice.
    """
    semitone = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    heights: list[tuple[Fraction, int]] = []
    for voice in measure.voices:
        pitches = [
            12 * p.octave + semitone[p.step] + p.alteration
            for e in voice.events
            if not e.is_grace
            for p in e.pitches
        ]
        if pitches:
            heights.append((Fraction(sum(pitches), len(pitches)), voice.number))
    if len(heights) < 2:
        return {}
    numbers = sorted(number for _, number in heights)
    ranked = sorted(heights, key=lambda item: (-item[0], item[1]))
    order = {voice: numbers[rank] for rank, (_, voice) in enumerate(ranked)}
    if all(voice == number for voice, number in order.items()):
        return {}
    for voice in measure.voices:
        if order.get(voice.number, voice.number) == voice.number:
            continue
        sounding = [e for e in voice.events if not e.is_grace and e.pitches]
        if sounding and (
            any(t.stop for t in sounding[0].note_ties)
            or sounding[0].tie_end
            or any(t.start for t in sounding[-1].note_ties)
            or sounding[-1].tie_start
        ):
            return {}
    return order


def _append_clef_changes(element: ET.Element, measure: Measure, divisions: int) -> None:
    cursor = Fraction(0)
    extent = max(
        (
            v.start_offset + sum((e.duration for e in v.events if not e.is_grace), Fraction(0))
            for v in measure.voices
        ),
        default=Fraction(0),
    )
    if measure.time is not None:
        extent = max(extent, Fraction(measure.time.beats, measure.time.beat_type))
    for index, change in enumerate(measure.clef_changes):
        if not 0 <= change.offset <= extent or (index and change.offset <= cursor):
            raise ExportError("clef changes require ordered positions within the measure")
        if change.sign not in {"G", "F", "C", "percussion", "TAB", "none", "jianpu"}:
            raise ExportError(f"unsupported clef sign {change.sign!r}")
        if change.line is not None and not 1 <= change.line <= 5:
            raise ExportError("clef line must be in 1..5")
        if change.offset > cursor:
            ET.SubElement(ET.SubElement(element, "forward"), "duration").text = str(
                _duration_in_divisions(change.offset - cursor, divisions)
            )
        clef = ET.SubElement(ET.SubElement(element, "attributes"), "clef")
        if not change.visible:
            clef.set("print-object", "no")
        ET.SubElement(clef, "sign").text = change.sign
        if change.line is not None:
            ET.SubElement(clef, "line").text = str(change.line)
        cursor = change.offset
    if cursor:
        ET.SubElement(ET.SubElement(element, "backup"), "duration").text = str(
            _duration_in_divisions(cursor, divisions)
        )


def _append_barline(element: ET.Element, measure: Measure, location: str) -> None:
    """The barline: its style, a repeat, and any ending bracket that meets it.

    Left and right are separate elements at opposite ends of the measure, so a
    forward repeat opens the measure and a backward one closes it -- and a
    one-measure ending, which both opens and closes here, writes one of each.
    """
    left = location == "left"
    endings = [e for e in measure.endings if (e.type == "start") == left]
    repeat = measure.repeat_forward if left else measure.repeat_backward
    # A double or final bar belongs to the right barline only. Where a repeat
    # meets one -- four corpus measures do -- the repeat's own heavy line is
    # what gets drawn, which the `elif` below enforces: two `<bar-style>`
    # elements in one barline is invalid.
    style = None if left else measure.barline_style
    if not endings and not repeat and style is None:
        return

    barline = ET.SubElement(element, "barline", location=location)
    # Schema order within a barline: bar-style, then ending, then repeat.
    if repeat:
        ET.SubElement(barline, "bar-style").text = "heavy-light" if left else "light-heavy"
    elif style is not None:
        ET.SubElement(barline, "bar-style").text = style
    for ending in endings:
        attrs = {"number": ",".join(str(n) for n in ending.numbers), "type": ending.type}
        if not ending.visible:
            attrs["print-object"] = "no"
        ET.SubElement(barline, "ending", attrs).text = _ending_text(ending)
    if repeat:
        attrs = {"direction": "forward" if left else "backward"}
        # `times` defaults to 2, so it is written only where Finale says
        # otherwise -- a section played three times, say.
        if not left and measure.repeat_passes != 2:
            attrs["times"] = str(measure.repeat_passes)
        if not left and not endings and measure.repeat_playback is not None:
            attrs["after-jump"] = "yes" if measure.repeat_playback.reset_on_action else "no"
        ET.SubElement(barline, "repeat", attrs)


def _ending_text(ending: Ending) -> str:
    """The source label is independent of MusicXML's playback numbers."""
    return (
        ending.text
        if ending.text is not None
        else ", ".join(f"{number}." for number in ending.numbers)
    )


def _append_attributes(
    element: ET.Element,
    measure: Measure,
    divisions: int,
    *,
    emit_divisions: bool,
    printed: tuple[TimeSignature | None, str | None] | None = None,
) -> None:
    """`printed`, where given, replaces `measure.time` as the `<time>` to write."""
    time = measure.time if printed is None else printed[0]
    symbol = None if printed is None else printed[1]
    needed = (
        emit_divisions
        or measure.key_fifths is not None
        or time is not None
        or measure.clef_sign is not None
    )
    if not needed:
        return
    attributes = ET.SubElement(element, "attributes")
    # Order is fixed by the schema: divisions, key, time, ... clef.
    if emit_divisions:
        ET.SubElement(attributes, "divisions").text = str(divisions)
    if measure.key_fifths is not None:
        key = ET.SubElement(attributes, "key")
        ET.SubElement(key, "fifths").text = str(measure.key_fifths)
        ET.SubElement(key, "mode").text = "minor" if measure.is_minor else "major"
    if time is not None:
        element_time = ET.SubElement(attributes, "time", {"symbol": symbol} if symbol else {})
        ET.SubElement(element_time, "beats").text = str(time.beats)
        ET.SubElement(element_time, "beat-type").text = str(time.beat_type)
    if measure.clef_sign is not None:
        clef = ET.SubElement(attributes, "clef")
        ET.SubElement(clef, "sign").text = measure.clef_sign
        if measure.clef_line is not None:
            ET.SubElement(clef, "line").text = str(measure.clef_line)


def _append_event(
    element: ET.Element,
    event: Event,
    voice: Voice,
    divisions: int,
    *,
    arpeggio_numbers: tuple[str, ...] = (),
    slurs: tuple[_SlurNotation, ...] = (),
    octave_displacement: int = 0,
    tremolo: tuple[str, int] | None = None,
    glissandi: tuple[tuple[_GlissandoNotation, ...], ...] = (),
    display_staves: dict[str, int] | None = None,
    tuplets: tuple[_TupletNotation, ...] = (),
) -> None:
    if not voice.playback:
        event = replace(event, playback=False)
    if event.rest_display_pitch is not None and not event.is_rest:
        raise ExportError("rest drawing position cannot be assigned to pitched notes")
    if event.note_ties and len(event.note_ties) != len(event.pitches):
        raise ExportError("per-note tie flags must match the number of pitches")
    if any(
        not 0 <= head.pitch_index < len(event.pitches) or head.shape not in {None, "normal", "x"}
        for head in event.noteheads
    ) or len({head.pitch_index for head in event.noteheads}) != len(event.noteheads):
        raise ExportError("invalid or duplicate notehead override")
    if any(
        i < 0 or i >= len(event.pitches) for mark in event.arpeggios for i in mark.pitch_indices
    ):
        raise ExportError("arpeggio coverage contains an invalid chord pitch")
    if any(not 0 <= mark.pitch_index < len(event.pitches) for mark in event.ornaments):
        raise ExportError("ornament principal note is outside the event's pitches")
    if any(not 0 <= mark.pitch_index < len(event.pitches) for mark in event.accidentals):
        raise ExportError("accidental note is outside the event's pitches")
    if any(
        m.side not in {"left", "right"}
        or (m.pitch_index is not None and not 0 <= m.pitch_index < len(event.pitches))
        for m in event.parentheses
    ):
        raise ExportError("invalid parenthesis side or note attachment")
    for index in {m.pitch_index for m in event.parentheses if m.pitch_index is not None}:
        if {m.side for m in event.parentheses if m.pitch_index == index} != {"left", "right"}:
            raise ExportError("a notehead enclosure requires both parentheses")
    legacy_ties = NoteTies(event.tie_start, event.tie_end)
    if event.is_rest:
        _append_note(
            element,
            event,
            voice,
            divisions,
            pitch=None,
            chord=False,
            ties=legacy_ties,
            tuplets=tuplets,
        )
        return
    for index, pitch in enumerate(event.pitches):
        pitch = replace(pitch, octave=pitch.octave + octave_displacement)
        if not 0 <= pitch.octave <= 9:
            raise ExportError("sounding pitch octave is outside MusicXML's 0..9 range")
        ties = event.note_ties[index] if event.note_ties else legacy_ties
        _append_note(
            element,
            event,
            voice,
            divisions,
            pitch=pitch,
            pitch_index=index,
            chord=bool(index),
            ties=ties,
            arpeggio_numbers=arpeggio_numbers,
            slurs=slurs if not index else (),
            tuplets=tuplets if not index else (),
            ornaments=tuple(mark for mark in event.ornaments if mark.pitch_index == index),
            tremolo=tremolo if not index else None,
            glissandi=glissandi[index] if glissandi else (),
            display_staff=next(
                (
                    (display_staves or {}).get(mark.part_id)
                    for mark in event.cross_staff
                    if mark.pitch_index == index and mark.part_id is not None
                ),
                None,
            ),
        )


def _append_note(
    element: ET.Element,
    event: Event,
    voice: Voice,
    divisions: int,
    *,
    pitch: Pitch | None,
    pitch_index: int = 0,
    chord: bool,
    ties: NoteTies,
    arpeggio_numbers: tuple[str, ...] = (),
    slurs: tuple[_SlurNotation, ...] = (),
    ornaments: tuple[Ornament, ...] = (),
    tremolo: tuple[str, int] | None = None,
    glissandi: tuple[_GlissandoNotation, ...] = (),
    display_staff: int | None = None,
    tuplets: tuple[_TupletNotation, ...] = (),
) -> None:
    note = ET.SubElement(element, "note")
    if not event.visible:
        note.set("print-object", "no")
    silent = not event.playback and pitch is not None
    # Schema order: grace, chord, pitch or rest, duration, tie, voice, type...
    # A grace note takes no metric time, and the schema requires duration > 0, so
    # it is expressed by omitting duration rather than by writing zero.
    if event.is_grace:
        grace = ET.SubElement(note, "grace")
        if event.grace_slash is not None:
            grace.set("slash", "yes" if event.grace_slash else "no")
    if silent:
        ET.SubElement(note, "cue")
    if chord:
        ET.SubElement(note, "chord")
    if pitch is None:
        # `measure="yes"` is what makes a reader centre one symbol in the bar
        # rather than draw a rest of some particular value -- and it is why the
        # note carries no <type>, since the length is the bar's, not a note's.
        rest = ET.SubElement(note, "rest")
        if event.is_measure_rest:
            rest.set("measure", "yes")
        if event.rest_display_pitch is not None:
            position = event.rest_display_pitch
            if (
                position.step not in "CDEFGAB"
                or len(position.step) != 1
                or not 0 <= position.octave <= 9
            ):
                raise ExportError("rest drawing position is outside MusicXML pitch bounds")
            ET.SubElement(rest, "display-step").text = position.step
            ET.SubElement(rest, "display-octave").text = str(position.octave)
    else:
        element_pitch = ET.SubElement(note, "pitch")
        ET.SubElement(element_pitch, "step").text = pitch.step
        if pitch.alteration:
            ET.SubElement(element_pitch, "alter").text = str(pitch.alteration)
        ET.SubElement(element_pitch, "octave").text = str(pitch.octave)
    if not event.is_grace:
        ET.SubElement(note, "duration").text = str(
            _duration_in_divisions(event.duration, divisions)
        )
    # <tie> is the sounding instruction; <tied> inside <notations> is the visual
    # tie. Both are required for a tie to survive a round trip through most
    # applications.
    if ties.stop and not silent:
        ET.SubElement(note, "tie", type="stop")
    if ties.start and not silent:
        ET.SubElement(note, "tie", type="start")
    ET.SubElement(note, "voice").text = str(voice.number)
    if not event.is_measure_rest:
        type_element = ET.SubElement(note, "type")
        type_element.text = _note_type(event)
        if silent:
            type_element.set("size", "full")
    for _ in range(event.dots):
        ET.SubElement(note, "dot")
    fixed = next((m for m in event.accidentals if m.pitch_index == pitch_index), None)
    # A hidden accidental has no MusicXML form (<accidental> takes no
    # print-object), so only drawn ones are written. Schema order: <accidental>
    # after <dot>, before <time-modification>.
    if pitch is not None and fixed is not None and fixed.shown and pitch.alteration in _ACCIDENTALS:
        attributes = {"parentheses": "yes"} if fixed.parentheses else {}
        ET.SubElement(note, "accidental", attributes).text = _ACCIDENTALS[pitch.alteration]
    if event.tuplet_ratio is not None:
        modification = ET.SubElement(note, "time-modification")
        actual, normal, normal_type = _time_modification(event)
        ET.SubElement(modification, "actual-notes").text = str(actual)
        ET.SubElement(modification, "normal-notes").text = str(normal)
        if normal_type is not None:
            ET.SubElement(modification, "normal-type").text = normal_type
    if pitch is not None and event.stem is not None:
        # Schema order: <stem> after <time-modification>, before <notehead>.
        ET.SubElement(note, "stem").text = event.stem
    if pitch is not None:
        enclosed = any(m.pitch_index == pitch_index for m in event.parentheses)
        head = next((h for h in event.noteheads if h.pitch_index == pitch_index), None)
        if enclosed or (head is not None and head.shape is not None):
            attributes = {"parentheses": "yes"} if enclosed else {}
            if head is not None and head.filled is not None:
                attributes["filled"] = "yes" if head.filled else "no"
            ET.SubElement(note, "notehead", attributes).text = (
                head.shape if head is not None and head.shape is not None else "normal"
            )
    if display_staff is not None:
        ET.SubElement(note, "staff").text = str(display_staff)
    # Schema order puts <beam> after <time-modification> and before
    # <notations>. Only on a chord's principal note: the beam belongs to the
    # stem, and the schema allows at most eight per note.
    if not chord:
        for beam in event.beams:
            ET.SubElement(note, "beam", number=str(beam.number)).text = beam.type
    # One <notations> holds the note's ties and the event's attachments.
    # A chord's marks belong to the event, so only its principal note carries
    # them -- repeating per pitch would print the staccato three times.
    marks = () if chord else event.articulations
    digits = () if chord else event.fingerings
    fermatas = () if chord else event.fermatas
    drawn_parentheses = (
        () if chord else tuple(m for m in event.parentheses if m.pitch_index is None)
    )
    arpeggios = (
        tuple(
            (i, mark)
            for i, mark in enumerate(event.arpeggios)
            if not mark.pitch_indices or pitch_index in mark.pitch_indices
        )
        if pitch is not None
        else ()
    )
    if (
        ties.start
        or ties.stop
        or marks
        or digits
        or ornaments
        or fermatas
        or arpeggios
        or slurs
        or tremolo
        or glissandi
        or drawn_parentheses
        or tuplets
    ):
        notations = ET.SubElement(note, "notations")
        if ties.stop:
            ET.SubElement(notations, "tied", type="stop")
        if ties.start:
            ET.SubElement(notations, "tied", type="start")
        for slur in slurs:
            attrs = {"type": slur.type, "number": slur.number}
            if slur.placement is not None:
                attrs["placement"] = slur.placement
                attrs["orientation"] = "over" if slur.placement == "above" else "under"
            if slur.x_offset:
                attrs["relative-x"] = _decimal_number(slur.x_offset * 10)
            if slur.y_offset:
                attrs["relative-y"] = _decimal_number(slur.y_offset * 10)
            ET.SubElement(notations, "slur", attrs)
        for kind, number, bracket, show in tuplets:
            ET.SubElement(
                notations,
                "tuplet",
                {
                    "type": kind,
                    "number": str(number),
                    "bracket": "yes" if bracket else "no",
                    "show-number": show,
                },
            )
        for glissando in glissandi:
            attrs = {
                "type": glissando.type,
                "number": glissando.number,
                "line-type": glissando.line_type,
            }
            if glissando.x_offset:
                attrs["relative-x"] = _decimal_number(glissando.x_offset * 10)
            if glissando.y_offset:
                attrs["relative-y"] = _decimal_number(glissando.y_offset * 10)
            ET.SubElement(notations, "glissando", attrs)
        for fermata in fermatas:
            ET.SubElement(notations, "fermata", type="inverted" if fermata.inverted else "upright")
        if marks:
            articulations = ET.SubElement(notations, "articulations")
            for name in marks:
                if name == "strong-accent-down":
                    ET.SubElement(articulations, "strong-accent", type="down")
                else:
                    ET.SubElement(articulations, name)
        if ornaments or tremolo:
            ornament_group = ET.SubElement(notations, "ornaments")
            if tremolo is not None:
                ET.SubElement(ornament_group, "tremolo", type=tremolo[0]).text = str(tremolo[1])
            for ornament in ornaments:
                if ornament.kind not in {"upper-mordent", "trill"}:
                    raise ExportError(f"unsupported ornament {ornament.kind!r}")
                attributes = {"placement": "above", "start-note": "main"}
                if ornament.auxiliary_semitones is not None:
                    step = {1: "half", 2: "whole"}.get(ornament.auxiliary_semitones)
                    if step is None:
                        raise ExportError("ornament auxiliary note must be one or two semitones")
                    attributes["trill-step"] = step
                ET.SubElement(
                    ornament_group,
                    "trill-mark" if ornament.kind == "trill" else "inverted-mordent",
                    attributes,
                )
                if ornament.auxiliary_alteration is not None:
                    accidental = {-1: "flat", 0: "natural", 1: "sharp"}.get(
                        ornament.auxiliary_alteration
                    )
                    if accidental is None:
                        raise ExportError("unsupported ornament auxiliary accidental")
                    ET.SubElement(
                        ornament_group, "accidental-mark", placement="above"
                    ).text = accidental
        if digits:
            # All of a chord's fingerings sit on its principal note rather than
            # one per pitch. Enigma attaches them to the entry, not to a note,
            # so which finger goes with which pitch is not stored -- and
            # MusicXML allows several <fingering> in one <technical> for exactly
            # this case.
            technical = ET.SubElement(notations, "technical")
            for digit in digits:
                ET.SubElement(technical, "fingering").text = digit
        # Unlike an accent, an arpeggio names every participating chord pitch.
        for index, arpeggio in arpeggios:
            attrs = {"number": arpeggio_numbers[index] if arpeggio_numbers else str(index + 1)}
            if arpeggio.part_ids:
                attrs["unbroken"] = "yes"
            if arpeggio.direction is not None:
                if arpeggio.direction not in {"up", "down"}:
                    raise ExportError(f"unsupported arpeggio direction {arpeggio.direction!r}")
                attrs["direction"] = arpeggio.direction
            ET.SubElement(notations, "arpeggiate", attrs)
        for mark in drawn_parentheses:
            if mark.side not in {"left", "right"}:
                raise ExportError(f"unsupported parenthesis side {mark.side!r}")
            attrs = {
                "type": "single",
                "smufl": "noteheadParenthesisLeft"
                if mark.side == "left"
                else "noteheadParenthesisRight",
                "relative-x": _decimal_number(mark.x_offset * 10),
                "relative-y": _decimal_number(mark.y_offset * 10),
            }
            ET.SubElement(notations, "other-notation", attrs).text = (
                "(" if mark.side == "left" else ")"
            )
    # Schema order puts <lyric> last, after <notations>. Only on a chord's
    # principal note: the syllable is sung once, not once per pitch.
    if not chord:
        for lyric in event.lyrics:
            _append_lyric(note, lyric)


def _append_lyric(note: ET.Element, lyric: Lyric) -> None:
    element = ET.SubElement(note, "lyric", number=str(lyric.number))
    ET.SubElement(element, "syllabic").text = lyric.syllabic
    ET.SubElement(element, "text").text = lyric.text
    if lyric.extend:
        ET.SubElement(element, "extend")
