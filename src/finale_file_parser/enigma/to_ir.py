"""Build the format-neutral IR from a parsed EnigmaXML document.

The `.musx` side of the hub-and-spoke shape in `docs/DECISIONS.md`: this module
knows Enigma, the IR does not know this module, and no exporter knows either. A
`.mus` reader added later produces the same `Score` and every exporter keeps
working.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from fractions import Fraction

from finale_file_parser.enigma.arpeggios import EventPosition, arpeggios_by_entry, connect_arpeggios
from finale_file_parser.enigma.articulation_playback import articulation_playback_by_entry
from finale_file_parser.enigma.articulations import articulations_by_entry
from finale_file_parser.enigma.barlines import barline_styles
from finale_file_parser.enigma.beam_options import rest_beams
from finale_file_parser.enigma.beams import BeamedNote, RestBeams, beams_for
from finale_file_parser.enigma.clef import (
    Clef,
    ClefPosition,
    ClefSign,
    clef_changes_by_measure,
    clef_definitions,
    clefs_by_measure,
    default_clefs,
)
from finale_file_parser.enigma.cross_staff import cross_staff_by_entry
from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.enharmonic import enharmonic_notes_by_entry, flip_enharmonic
from finale_file_parser.enigma.expressions import (
    SCORE_WIDE_STAFF,
    expressions_by_measure,
    first_page_tempos,
)
from finale_file_parser.enigma.fermatas import fermatas_by_entry
from finale_file_parser.enigma.fingerings import fingerings_by_entry
from finale_file_parser.enigma.glissandi import glissandi_by_staff
from finale_file_parser.enigma.graces import grace_slash, slash_flagged_grace_notes
from finale_file_parser.enigma.groups import staff_groups, staff_order
from finale_file_parser.enigma.hairpins import hairpins_by_staff
from finale_file_parser.enigma.header import page_header, page_notes
from finale_file_parser.enigma.jumps import jumps_by_measure, navigation_by_measure
from finale_file_parser.enigma.key import KeySignature, Mode, decode_key
from finale_file_parser.enigma.lines import lines_by_staff
from finale_file_parser.enigma.location import effective_keys, locate_entries
from finale_file_parser.enigma.lyrics import Lyric as EnigmaLyric
from finale_file_parser.enigma.lyrics import lyrics_by_entry
from finale_file_parser.enigma.measure_numbers import measure_labels
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import Note, read_entry
from finale_file_parser.enigma.note_dynamics import dynamics_by_entry
from finale_file_parser.enigma.noteheads import noteheads_by_entry
from finale_file_parser.enigma.octaves import octaves_by_staff
from finale_file_parser.enigma.ornaments import ornaments_by_entry
from finale_file_parser.enigma.parentheses import parentheses_by_entry
from finale_file_parser.enigma.pedals import pedals_by_entry
from finale_file_parser.enigma.pitch import StaffTransposition, read_transposition, spell_note
from finale_file_parser.enigma.playback_preferences import playback_preferences
from finale_file_parser.enigma.repeats import Repeats, repeats_for
from finale_file_parser.enigma.slurs import slurs_by_staff
from finale_file_parser.enigma.smart_shapes import stale_smart_shapes
from finale_file_parser.enigma.staff_playback import with_playback_scopes
from finale_file_parser.enigma.staff_visibility import staff_hide_modes, staves_hiding_text_repeats
from finale_file_parser.enigma.stems import assign_stems, frozen_stem, layer_stems
from finale_file_parser.enigma.text import file_info, staff_names
from finale_file_parser.enigma.timesig import (
    PrintedTimeSignature,
    printed_time_signatures,
    time_signatures,
)
from finale_file_parser.enigma.timesig import TimeSignature as EnigmaTimeSignature
from finale_file_parser.enigma.tremolos import recover_tremolos
from finale_file_parser.enigma.tuplet import (
    Tuplet,
    entry_chain,
    sounded_durations,
    tuplet_positions,
    tuplets_by_entry,
)
from finale_file_parser.ir import (
    AccidentalMark,
    Arpeggio,
    ArticulationPlayback,
    ClefChange,
    CrossStaff,
    Event,
    Expression,
    Fermata,
    Lyric,
    Measure,
    Navigation,
    Notehead,
    NoteTies,
    Ornament,
    Parenthesis,
    Part,
    PartGroup,
    Pedal,
    Pitch,
    Score,
    ScoreDiagnostic,
    SlurEndpoint,
    TimeSignature,
    TupletMark,
    Voice,
)
from finale_file_parser.playback import PlaybackError, navigation_target

__all__ = ["build_score"]

_WHOLE_EDU = 4096
_NO_TRANSPOSITION = StaffTransposition(interval=0, adjust=0)
_MAX_SCORE_STAVES = 1024
_MAX_SCORE_MEASURE_CELLS = 1_000_000
"""Cap expansion of active but empty layout staves into complete measures."""

_CLEF_ANCHORS = {
    ClefSign.G: (-10, 2),
    ClefSign.F: (2, 4),
    ClefSign.C: (-4, 3),
}
"""(adjust, staff line) for each sign's standard clef.

Two `adjust` units move the clef one staff line. Applying that to the corpus clef
table reproduces exactly the nine historically used clefs -- treble, alto, tenor,
bass, both baritones, French violin, mezzo-soprano and soprano. That is why the
rule is trusted rather than merely fitted to the three clefs the corpus selects:
a wrong step would not land on the complete set.
"""

_ADJUST_PER_LINE = 2

_MUSICXML_SIGNS = {
    ClefSign.G: "G",
    ClefSign.F: "F",
    ClefSign.C: "C",
    ClefSign.SHAPE: "percussion",
}


def _clef_line(clef: Clef) -> int | None:
    anchor = _CLEF_ANCHORS.get(clef.sign)
    if anchor is None:
        return None
    anchor_adjust, anchor_line = anchor
    return anchor_line + (clef.adjust - anchor_adjust) // _ADJUST_PER_LINE


@dataclass
class _Cell:
    """What one (staff, measure) holds, gathered in a single pass."""

    events_by_layer: dict[int, list[Event]]
    key_raw: int
    starts_beam: dict[int, list[bool]] = field(default_factory=lambda: defaultdict(list))
    """Enigma's beam bit per event, parallel to `events_by_layer`. Kept beside
    the events rather than on them: it is an Enigma detail the IR has no need
    of once the beams themselves are worked out."""
    start_times: dict[int, int] = field(default_factory=dict)


def build_score(document: EnigmaDocument) -> Score:
    """Convert a parsed EnigmaXML document into the IR.

    One part per staff, measures in order, one IR voice per Finale layer.
    """
    location = locate_entries(document, include_reserved_staff=False)
    chain = entry_chain(document)
    tuplet_defs = tuplets_by_entry(document)
    sounded = sounded_durations(chain, tuplet_defs)
    positions = tuplet_positions(chain, tuplet_defs)
    records = {int(r.attrs["entnum"]): r for r in document.entries.of_tag("entry")}
    transpositions = _transpositions(document)
    lyrics = lyrics_by_entry(document)
    articulations = articulations_by_entry(document)
    articulation_playback, articulation_diagnostics = articulation_playback_by_entry(document)
    fingerings = fingerings_by_entry(document)
    ornaments = ornaments_by_entry(document)
    fermatas = fermatas_by_entry(document)
    arpeggios = arpeggios_by_entry(document)
    parentheses = parentheses_by_entry(document)
    noteheads = noteheads_by_entry(document)
    enharmonic = enharmonic_notes_by_entry(document)
    cross_staff = cross_staff_by_entry(document)
    assigned_entries: dict[EventPosition, int] = {}
    slur_positions: dict[tuple[int, int, int], list[SlurEndpoint]] = defaultdict(list)
    always_slash = slash_flagged_grace_notes(document)

    # One pass, in chain order, so a measure's notes come out in playing order
    # rather than document order.
    cells: dict[tuple[int, int], _Cell] = {}
    for entnum in chain.order:
        record = records.get(entnum)
        if record is None:
            continue
        # An entry can sound in more than one place -- a mirror. Each placement
        # builds its own event, because the staff decides the transposition and
        # so the spelling: a mirror onto a transposing staff is not the same
        # written note.
        for here in location.get(entnum, ()):
            cell = cells.setdefault(
                (here.staff, here.measure),
                _Cell(events_by_layer=defaultdict(list), key_raw=here.key_signature),
            )
            cell.starts_beam[here.layer].append("beam" in record.fields)
            if here.layer in cell.start_times and cell.start_times[here.layer] != here.start_time:
                raise CorruptScoreError("one layer has conflicting frame start times")
            cell.start_times[here.layer] = here.start_time
            slur_positions[here.staff, here.measure, entnum].append(
                SlurEndpoint(here.measure, here.layer, len(cell.events_by_layer[here.layer]))
            )
            if entnum in arpeggios:
                assigned_entries[
                    f"P{here.staff}",
                    here.measure,
                    here.layer,
                    len(cell.events_by_layer[here.layer]),
                ] = entnum
            cell.events_by_layer[here.layer].append(
                _event(
                    record=record,
                    key_raw=here.key_signature,
                    transposition=transpositions.get(here.staff, _NO_TRANSPOSITION),
                    written_edu=chain.written_edu[entnum],
                    sounded_edu=sounded[entnum],
                    lyrics=lyrics.get(entnum, ()),
                    articulations=articulations.get(entnum, ()),
                    fingerings=fingerings.get(entnum, ()),
                    ornaments=ornaments.get(entnum, ()),
                    fermatas=fermatas.get(entnum, ()),
                    arpeggios=arpeggios.get(entnum, ()),
                    parentheses=parentheses.get(entnum, ()),
                    articulation_playback=articulation_playback.get(entnum, ()),
                    noteheads=noteheads.get(entnum, ()),
                    cross_staff=cross_staff.get(entnum, ()),
                    enharmonic=enharmonic.get(entnum, frozenset()),
                    tuplets=_tuplet_marks(positions.get(entnum, ())),
                )
            )

    tremolo_written, tremolos = recover_tremolos(document, slur_positions)
    for (staff, measure, entry), endpoints in slur_positions.items():
        if entry not in tremolo_written:
            continue
        written = Fraction(tremolo_written[entry], _WHOLE_EDU)
        for endpoint in endpoints:
            events = cells[staff, measure].events_by_layer[endpoint.voice]
            event = events[endpoint.event_index]
            events[endpoint.event_index] = replace(
                event,
                written_duration=written,
                tuplet_ratio=event.duration / written,
                beams=(),
                tuplets=(),
            )
    rest_options = rest_beams(document)
    fixed_layers = layer_stems(document)
    for cell in cells.values():
        _apply_beams(cell, rest_options)
        cell.events_by_layer.update(assign_stems(cell.events_by_layer, fixed_layers))
        for layer, events in cell.events_by_layer.items():
            cell.events_by_layer[layer] = [
                replace(event, grace_slash=grace_slash(event, always_slash))
                if event.is_grace
                else event
                for event in events
            ]

    signatures = time_signatures(document)
    printed = printed_time_signatures(document)
    clef_table = clef_definitions(document)
    clef_at = clefs_by_measure(document)
    clef_changes = clef_changes_by_measure(document)
    names = staff_names(document)
    info = file_info(document)
    header = page_header(document)
    repeats = repeats_for(document)
    directions = jumps_by_measure(document)
    navigation = navigation_by_measure(document)
    barlines = barline_styles(document)
    expressions = expressions_by_measure(document)
    note_dynamics = dynamics_by_entry(document)
    for staff, measure, entry, offset in _entry_attachment_offsets(
        cells, slur_positions, set(note_dynamics)
    ):
        note_marks = tuple(replace(mark, offset=offset) for mark in note_dynamics[entry])
        expressions[staff, measure] = expressions.get((staff, measure), ()) + note_marks
    display_staves = {
        int(mark.part_id[1:])
        for marks in cross_staff.values()
        for mark in marks
        if mark.part_id is not None
    }
    staves = _ordered_staves(document, {staff for staff, _ in cells} | display_staves)
    keys = effective_keys(document)
    numbers = _measure_numbers(keys, cells)
    if numbers and numbers[-1] not in barlines and not repeats.get(numbers[-1]).backward:
        # Finale's "Final Barline at End of Piece" (Document Options > Barlines) is
        # on by default and in every corpus PDF; its option bit is not decoded, and
        # a .mus never stores a final barline on the measure itself.
        barlines = {**barlines, numbers[-1]: "light-heavy"}
    if len(staves) * len(numbers) > _MAX_SCORE_MEASURE_CELLS:
        raise CorruptScoreError("score staff/measure expansion exceeds the cell limit")
    headers = first_page_tempos(document)
    if headers and numbers:
        where = SCORE_WIDE_STAFF, numbers[0]
        expressions[where] = headers + expressions.get(where, ())
    notes = page_notes(document)
    last_page = max(
        (
            page
            for r in document.others.of_tag("pageTextAssign")
            if (page := field_int(r.attrs.get("cmper")))
        ),
        default=0,
    )
    for page, note in notes:
        # Page coordinates cannot be mapped to a bar without page layout, but a
        # note on the first page heads the piece and one on the last page ends it
        # (Memories of Green's echo hint and "octave lower on repeat").
        if not numbers or page not in {1, last_page}:
            continue
        where = SCORE_WIDE_STAFF, numbers[0] if page == 1 else numbers[-1]
        expressions[where] = expressions.get(where, ()) + (Expression(note, ""),)
    ignored_shapes, diagnostics = stale_smart_shapes(document, numbers)
    lines, line_diagnostics = lines_by_staff(document, ignored_shapes=ignored_shapes)
    diagnostics += line_diagnostics
    diagnostics += articulation_diagnostics
    diagnostics += tuple(
        ScoreDiagnostic(
            "navigation-word-position",
            f"Text repeat in measure {number} retains its source measure-origin X "
            "in the IR. Its bar-boundary export anchor stays exact; a layout-aware "
            "horizontal transform is not established for this word alignment.",
            f"textRepeatAssign:{number}:{index}",
        )
        for number, marks in navigation.items()
        for index, mark in enumerate(marks)
        if mark.kind == "words"
        and mark.x_offset not in {None, Fraction(0)}
        and mark.justification != "right"
    )
    placed_entries = {entry for _, _, entry in slur_positions}
    diagnostics += tuple(
        ScoreDiagnostic(
            "cross-staff-destination",
            f"Entry {entry} note {mark.pitch_index} has an active cross-staff flag "
            "without a destination detail; its source staff placement is retained.",
            f"crossStaff:{entry}",
        )
        for entry, marks in cross_staff.items()
        if entry in placed_entries
        for mark in marks
        if mark.part_id is None
    )
    diagnostics += tuple(
        ScoreDiagnostic(
            "notehead-glyph",
            f"Entry {entry} note {head.pitch_index} retains custom character "
            f"{head.source_character} in font {head.source_font!r}; "
            "its notehead meaning is not established for MusicXML.",
            f"noteheadMod:{entry}",
        )
        for entry, heads in noteheads.items()
        if entry in placed_entries
        for head in heads
        if head.shape is None
    )
    diagnostics += tuple(
        ScoreDiagnostic(
            "parenthesis-attachment",
            f"Parentheses on entry {entry} retain their glyph positions; their exact "
            "chord-note or span attachment requires Finale drawing layout. "
            "MusicXML other-notation preserves them, but MuseScore may not render them.",
            f"articAssign:{entry}",
        )
        for entry, marks in parentheses.items()
        if entry in placed_entries and any(mark.pitch_index is None for mark in marks)
    )
    hairpins = hairpins_by_staff(document, ignored_shapes=ignored_shapes)
    slurs = slurs_by_staff(document, slur_positions, ignored_shapes=ignored_shapes)
    octaves = octaves_by_staff(document, ignored_shapes=ignored_shapes)
    pedals = _pedal_directions(document, cells, slur_positions)
    glissandi, shaped_arpeggios = glissandi_by_staff(
        document, slur_positions, ignored_shapes=ignored_shapes
    )
    for (staff, endpoint), marks in shaped_arpeggios.items():
        events = cells[staff, endpoint.measure].events_by_layer[endpoint.voice]
        event = events[endpoint.event_index]
        events[endpoint.event_index] = replace(event, arpeggios=event.arpeggios + marks)
    clef_at = _carried_clefs(document, staves, numbers, clef_at, clef_changes)
    expressions = _place_score_wide(expressions, staves)
    hide_modes = staff_hide_modes(document)
    hide_text_repeats = staves_hiding_text_repeats(document)
    labels, label_diagnostics = measure_labels(document, numbers)
    diagnostics += label_diagnostics
    spacer = _initial_pickup_spacer(document, cells, staves, numbers[0]) if numbers else Fraction(0)
    diagnostics += tuple(
        ScoreDiagnostic(
            "staff-cutaway-geometry",
            f"Staff {staff} retains its cutaway print policy; its system geometry "
            "has not been resolved and is not interpreted as global hiding.",
            f"staffSpec:{staff}",
        )
        for staff in staves
        if hide_modes.get(staff) == "cutaway"
    )
    parts = [
        Part(
            id=f"P{staff}",
            # Fall back to a positional label only where the document names no
            # staff, which is most of them: 24 of 84 in the sampled corpus.
            name=names[staff].full or names[staff].abbreviated
            if staff in names
            else f"Staff {staff}",
            measures=tuple(
                replace(
                    _measure(
                        staff=staff,
                        number=number,
                        previous=numbers[index - 1] if index else None,
                        cells=cells,
                        keys=keys,
                        signatures=signatures,
                        printed=printed,
                        clef_table=clef_table,
                        clef_at=clef_at,
                        clef_changes=clef_changes,
                        show_text_repeats=staff not in hide_text_repeats,
                        repeats=repeats,
                        directions=directions,
                        barlines=barlines,
                        expressions=expressions,
                        navigation=navigation,
                        pedals=pedals,
                    ),
                    leading_spacer=spacer if index == 0 else Fraction(0),
                    display_number=labels.get(number),
                )
                for index, number in enumerate(numbers)
            ),
            hairpins=hairpins.get(staff, ()),
            slurs=slurs.get(staff, ()),
            abbreviation=names[staff].abbreviated if staff in names else "",
            octave_shifts=octaves.get(staff, ()),
            tremolos=tremolos.get(staff, ()),
            glissandi=glissandi.get(staff, ()),
            lines=lines.get(staff, ()),
            staff_hide_mode=hide_modes.get(staff),
        )
        for staff in staves
    ]
    parts = [_with_falls(part) for part in parts]
    groups = _groups(document, [part.id for part in parts])
    scoped_parts = with_playback_scopes(document, tuple(parts))
    return Score(
        parts=connect_arpeggios(document, scoped_parts, groups, assigned_entries),
        groups=groups,
        title=header.get("title", ""),
        composer=header.get("composer", ""),
        metadata={
            **{k: v for k, v in info.items() if k not in {"title", "composer"}},
            **{k: header[k] for k in ("subtitle", "arranger", "copyright") if k in header},
        },
        diagnostics=diagnostics
        + _playback_diagnostics(tuple(parts))
        + _navigation_diagnostics(tuple(parts)),
        playback=playback_preferences(document),
    )


def _initial_pickup_spacer(
    document: EnigmaDocument, cells: dict[tuple[int, int], _Cell], staves: list[int], number: int
) -> Fraction:
    frames = {
        int(r.attrs["cmper"])
        for r in document.others.of_tag("frameSpec")
        if r.attrs.get("part", "0") == "0"
        and "startTime" in r.fields
        and ("legacySpacer" in r.fields or not {"startEntry", "endEntry"}.intersection(r.fields))
    }
    refs = {
        (int(r.attrs["cmper1"]), layer): field_int(r.fields.get(f"frame{layer}"))
        for r in document.details.of_tag("gfhold")
        if r.attrs.get("part", "0") == "0" and int(r.attrs["cmper2"]) == number
        for layer in range(1, 5)
    }
    starts = [
        cell.start_times.get(layer, 0) if refs.get((staff, layer)) in frames else 0
        for (staff, measure), cell in cells.items()
        if staff in staves and measure == number
        for layer in cell.events_by_layer
    ]
    return Fraction(min(starts, default=0), _WHOLE_EDU)


def _entry_attachment_offsets(
    cells: dict[tuple[int, int], _Cell],
    positions: dict[tuple[int, int, int], list[SlurEndpoint]],
    wanted: set[int],
) -> Iterator[tuple[int, int, int, Fraction]]:
    """One linear voice scan for attached directions, including frame starts and graces."""
    selected: dict[tuple[int, int, int], dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (staff, measure, entry), endpoints in positions.items():
        if entry in wanted:
            for point in endpoints:
                selected[staff, measure, point.voice][point.event_index].append(entry)
    for (staff, measure, voice), indices in selected.items():
        cell = cells[staff, measure]
        offset = Fraction(cell.start_times.get(voice, 0), _WHOLE_EDU)
        for index, event in enumerate(cell.events_by_layer[voice]):
            for entry in indices.get(index, ()):
                yield staff, measure, entry, offset
            if not event.is_grace:
                offset += event.duration


def _pedal_directions(
    document: EnigmaDocument,
    cells: dict[tuple[int, int], _Cell],
    positions: dict[tuple[int, int, int], list[SlurEndpoint]],
) -> dict[tuple[int, int], tuple[Pedal, ...]]:
    assignments = pedals_by_entry(document)
    kinds: dict[tuple[int, int], dict[Fraction, set[str]]] = defaultdict(lambda: defaultdict(set))
    for staff, measure, entry, offset in _entry_attachment_offsets(
        cells, positions, set(assignments)
    ):
        kinds[staff, measure][offset].update(assignments[entry])
    return {
        key: tuple(
            Pedal(offset, "change" if values == {"start", "stop"} else next(iter(values)))
            for offset, values in sorted(offsets.items())
        )
        for key, offsets in kinds.items()
    }


def _navigation_diagnostics(parts: tuple[Part, ...]) -> tuple[ScoreDiagnostic, ...]:
    if not parts:
        return ()
    result = []
    part = parts[0]
    for measure in part.measures:
        for mark in measure.navigation:
            if mark.kind == "unknown-glyph":
                result.append(
                    ScoreDiagnostic(
                        "unsupported-navigation-glyph",
                        "Navigation glyph has no established font mapping",
                        f"{mark.mark_id}, measure {measure.number}",
                    )
                )
            if mark.playback is None or mark.playback.action in {"noJump", "stop"}:
                continue
            try:
                navigation_target(part, measure.number, mark)
            except PlaybackError as exc:
                result.append(
                    ScoreDiagnostic(
                        "unresolved-navigation-target",
                        str(exc),
                        f"{mark.mark_id}, measure {measure.number}, target {mark.playback.target}",
                    )
                )
    return tuple(result)


def _playback_diagnostics(parts: tuple[Part, ...]) -> tuple[ScoreDiagnostic, ...]:
    result = []
    for part in parts:
        for measure in part.measures:
            for index, expression in enumerate(measure.expressions):
                playback = expression.playback
                if playback is None:
                    continue
                if (playback.kind == "tempo" and playback.value <= 0) or (
                    playback.kind == "amplitude" and not 0 <= playback.value <= 127
                ):
                    result.append(
                        ScoreDiagnostic(
                            "nonabsolute-expression-playback",
                            f"Source {playback.kind} value {playback.value} is retained; "
                            "it cannot establish an absolute MusicXML rate/velocity.",
                            f"{part.id}/measure[{measure.number}]/expression[{index}]",
                        )
                    )
    return tuple(result)


RESERVED_STAFF = 0x7FFF
"""A staff id Finale reserves rather than lays out: 32767, the same sentinel the
format uses for "to the end" in `staffGroup.endMeas`.

Every one of the 401 corpus documents declares it, and no document treats it as
part of the score:

* it is **never** in the score's instrument list (0 of 401), which is what
  `instUsed` is -- the layout of the staves the score shows;
* it is **never** named by a staff group (0 of 401);
* its `staffSpec` is a template rather than a description of a part -- 401
  documents hold just two distinct bodies, all with the same fixed `instUuid`,
  a one-line `customStaff`, and clefs, key signatures, measure numbers, repeats
  and repeat barlines all hidden;
* in the 398 buildable documents measured when this rule was established, 376
  gave it a single repeated pitch, always in layer 1, and none carried a lyric;
  the final three documents became buildable later and were not part of that
  content count.

It is also the **only** staff in the corpus absent from the instrument list, so
excluding it excludes nothing else. What Finale actually uses it for is not
known and this does not guess; what is established is that it is not a part of
the score, and exporting it put a spurious "Staff 32767" into every file this
project produced. Its entries are still placed by `locate_entries`, so nothing
below the IR is lost.
"""


def _measure_numbers(keys: dict[int, int], cells: dict[tuple[int, int], _Cell]) -> list[int]:
    """Every measure of the score, in order.

    The list comes from `measSpec` -- which `effective_keys` already walks, one
    entry per measure -- and **not** from where the music happens to be. It runs
    1..N with no gaps in all 401 buildable corpus documents and nothing sounds
    outside it, whereas the measures that hold entries omit every bar in which
    the whole ensemble rests: 1,375 of them across 162 documents.

    A document with no `measSpec` at all falls back to the measures that hold
    entries, so a malformed file still exports what it has.
    """
    return sorted(keys) or sorted({measure for _, measure in cells})


def _measure_rest(signature: EnigmaTimeSignature | None) -> Event:
    """One rest filling the bar.

    A part silent through a measure still has that measure -- MusicXML gives
    every part every measure, and a reader that meets a gap in the numbering has
    no way to tell a silent bar from a missing one. Its length is the time
    signature's, which is why this is not just a whole-note rest: a 3/4 measure
    rest lasts 3/4 and has no note value.
    """
    length = (
        Fraction(signature.numerator, signature.denominator)
        if signature is not None
        else Fraction(1)
    )
    return Event(
        duration=length,
        written_duration=length,
        pitches=(),
        is_measure_rest=True,
    )


_FALL_DROP = Fraction(1)
"""Staff spaces a wavy line must descend to read as a fall rather than a trill line."""


def _with_falls(part: Part) -> Part:
    """Turn a short descending wavy line after a note into that note's fall.

    Dreadful Fight bar 48 draws a fall from its last bass note as a wavy smart
    shape running down to the barline. A line attached to no note is not drawn by
    readers that ignore line positions, so the gesture is given to the note it
    leaves: the last sounding event that starts at or before the line.
    """
    falls: dict[tuple[int, int, int], None] = {}
    kept = []
    for line in part.lines:
        descends = line.start_y - line.end_y >= _FALL_DROP
        if line.line_type != "wavy" or line.start_measure != line.end_measure or not descends:
            kept.append(line)
            continue
        target = _event_before(part, line.start_measure, line.start_offset)
        if target is None:
            kept.append(line)
            continue
        falls[target] = None
    if not falls:
        return part
    measures = []
    for measure in part.measures:
        voices = []
        for voice in measure.voices:
            events = tuple(
                replace(event, articulations=event.articulations + ("falloff",))
                if (measure.number, voice.number, index) in falls
                else event
                for index, event in enumerate(voice.events)
            )
            voices.append(replace(voice, events=events))
        measures.append(replace(measure, voices=tuple(voices)))
    return replace(part, measures=tuple(measures), lines=tuple(kept))


def _event_before(part: Part, number: int, offset: Fraction) -> tuple[int, int, int] | None:
    best: tuple[Fraction, tuple[int, int, int]] | None = None
    for measure in part.measures:
        if measure.number != number:
            continue
        for voice in measure.voices:
            onset = voice.start_offset
            for index, event in enumerate(voice.events):
                if event.pitches and not event.is_grace and onset <= offset:
                    if best is None or onset >= best[0]:
                        best = (onset, (number, voice.number, index))
                if not event.is_grace:
                    onset += event.duration
    return best[1] if best is not None else None


def _drawn_clef_changes(
    positions: tuple[ClefPosition, ...], in_force: int | None
) -> tuple[ClefPosition, ...]:
    """The clef changes Finale draws: those that change the clef in force.

    A measure's clef list opens with an entry at offset 0 restating its clef, and
    a list that changes back and forth restates the clef the previous bar ended
    in. Finale draws neither; exported, each printed a redundant clef (The Moon
    bar 23, Steel Samurai bar 10).
    """
    drawn = []
    for position in positions:
        if position.index != in_force:
            drawn.append(position)
        in_force = position.index
    return tuple(drawn)


def _carried_clefs(
    document: EnigmaDocument,
    staves: list[int],
    numbers: list[int],
    clef_at: dict[tuple[int, int], int],
    changes: dict[tuple[int, int], tuple[ClefPosition, ...]] | None = None,
) -> dict[tuple[int, int], int]:
    """The clef in force at every (staff, measure), not only where notes are.

    `clefs_by_measure` reads `gfhold`, and a measure a staff rests through has
    no `gfhold` at all -- so without carrying the last one forward a part would
    lose its clef the moment it fell silent, and re-announce it on returning.
    Before the first `gfhold` the staff's own `defaultClef` applies.
    """
    defaults = default_clefs(document)
    out = dict(clef_at)
    for staff in staves:
        current = defaults.get(staff, 0)
        for number in numbers:
            current = clef_at.get((staff, number), current)
            out[(staff, number)] = current
            if positions := (changes or {}).get((staff, number)):
                current = positions[-1].index
    return out


def _ordered_staves(document: EnigmaDocument, present: set[int]) -> list[int]:
    """Musical and explicitly laid-out staves, in the source score's order.

    `instUsed` gives that order, including active staves resting throughout
    the score. It is not always ascending: 10 corpus
    documents list their staves in an order the staff numbers do not follow, and
    sorting instead puts those parts down the page in the wrong places. Where
    the document has no such list, `staff_order` falls back to numeric order;
    those stored definitions alone do not establish active resting parts.

    A staff with music but no slot in the list keeps a place, after the listed
    ones, rather than being dropped: it has notes, and losing a part is worse
    than putting it last. The one exception is `RESERVED_STAFF`, which every
    document declares and none lays out.
    """
    order = staff_order(document)
    if len(set(order)) != len(order):
        raise CorruptScoreError("score layout names the same staff twice")
    has_layout = any(
        "part" not in record.attrs
        and field_int(record.attrs.get("inci")) is not None
        and field_int(record.fields.get("inst")) is not None
        for record in document.others.all_with("instUsed", 0)
    )
    # Numeric fallback order lists stored definitions, not active layout.
    # Only an explicit score list establishes a resting staff's membership.
    wanted = (present | (set(order) if has_layout else set())) - {RESERVED_STAFF}
    if len(wanted) > _MAX_SCORE_STAVES:
        raise CorruptScoreError("score exceeds the staff limit")
    listed = [staff for staff in order if staff in wanted]
    return listed + sorted(wanted - set(order))


def _groups(document: EnigmaDocument, part_ids: list[str]) -> tuple[PartGroup, ...]:
    """Staff groups whose staves form a contiguous run of the score's parts.

    A group is **dropped** where its staves are not contiguous here, which
    happens when the document lays its staves out in an order their numbers do
    not follow: 14 of 230 corpus groups. `build_score` orders parts by staff
    number, so for those documents a `<part-group>` would brace a run of parts
    the score does not group -- worse than no bracket at all. Fixing it properly
    means ordering parts by `staff_order`, which is a change to every part's
    position and belongs in its own slice.
    """
    at = {part_id: index for index, part_id in enumerate(part_ids)}
    out: list[PartGroup] = []
    for group in staff_groups(document):
        ids = [f"P{staff}" for staff in group.staves]
        positions = [at[part_id] for part_id in ids if part_id in at]
        if not positions or sorted(positions) != list(range(min(positions), max(positions) + 1)):
            continue
        out.append(
            PartGroup(
                part_ids=tuple(part_ids[index] for index in sorted(positions)),
                symbol=group.symbol,
                barline=group.barline,
                name=group.name,
                abbreviation=group.abbreviation,
                instrument=group.instrument,
            )
        )
    return tuple(out)


def _apply_beams(cell: _Cell, rest_options: RestBeams | None = None) -> None:
    """Replace each layer's events with the same events carrying their beams.

    Beaming is a property of a run of notes, not of one note, so it can only be
    worked out once a layer's events are all in playing order -- which is why
    this is a second pass rather than part of `_event`.
    """
    for layer, events in cell.events_by_layer.items():
        flags = cell.starts_beam[layer]
        notes = [
            BeamedNote(
                written_duration=event.written_duration,
                dots=event.dots,
                is_rest=event.is_rest,
                starts_group=starts,
                is_grace=event.is_grace,
            )
            for event, starts in zip(events, flags, strict=True)
        ]
        cell.events_by_layer[layer] = [
            replace(event, beams=tuple(beams)) if beams else event
            for event, beams in zip(
                events, beams_for(notes, rest_options=rest_options), strict=True
            )
        ]


def _transpositions(document: EnigmaDocument) -> dict[int, StaffTransposition]:
    out: dict[int, StaffTransposition] = {}
    for record in document.others.of_tag("staffSpec"):
        if "part" in record.attrs:
            continue
        transposition = read_transposition(record)
        if transposition is not None:
            out[int(record.attrs["cmper"])] = transposition
    return out


def _event(
    *,
    record: Record,
    key_raw: int,
    transposition: StaffTransposition,
    written_edu: int,
    sounded_edu: Fraction,
    lyrics: tuple[EnigmaLyric, ...] = (),
    articulations: tuple[str, ...] = (),
    fingerings: tuple[str, ...] = (),
    ornaments: tuple[Ornament, ...] = (),
    fermatas: tuple[Fermata, ...] = (),
    arpeggios: tuple[Arpeggio, ...] = (),
    parentheses: tuple[Parenthesis, ...] = (),
    articulation_playback: tuple[ArticulationPlayback, ...] = (),
    noteheads: tuple[Notehead, ...] = (),
    cross_staff: tuple[CrossStaff, ...] = (),
    enharmonic: frozenset[int] = frozenset(),
    tuplets: tuple[TupletMark, ...] = (),
) -> Event:
    entry = read_entry(record)
    key = decode_key(key_raw)
    written_pitches = [spell_note(note, key, transposition).written for note in entry.notes]
    pitches = tuple(
        Pitch(step=spelled.letter, octave=spelled.octave, alteration=spelled.alteration)
        for spelled in (
            flip_enharmonic(written) if index in enharmonic else written
            for index, written in enumerate(written_pitches)
        )
    )
    written = Fraction(written_edu, _WHOLE_EDU)
    duration = Fraction(sounded_edu) / _WHOLE_EDU
    # A ratio of 1 means no tuplet; recording it anyway would make every note
    # carry a pointless <time-modification>.
    # A grace note sounds for no time, which is not a tuplet ratio of zero.
    ratio = duration / written if written and duration and duration != written else None
    if ornaments and entry.notes:
        ornaments = tuple(
            _resolve_ornament(ornament, entry.notes, key, transposition) for ornament in ornaments
        )
    rest_position = (
        spell_note(entry.rest_position, key, transposition).written
        if entry.rest_position is not None
        else None
    )
    return Event(
        duration=duration,
        written_duration=written,
        pitches=pitches,
        dots=entry.duration.dots,
        tie_start=any(note.tie_start for note in entry.notes),
        tie_end=any(note.tie_end for note in entry.notes),
        note_ties=tuple(NoteTies(note.tie_start, note.tie_end) for note in entry.notes),
        tuplet_ratio=ratio,
        tuplets=tuplets if ratio is not None and _ratio_of(tuplets) == ratio else (),
        accidentals=tuple(
            AccidentalMark(index, note.show_accidental, note.paren_accidental)
            for index, note in enumerate(entry.notes)
            if note.freeze_accidental or note.paren_accidental
        ),
        is_grace="graceNote" in record.fields,
        playback=entry.playback,
        visible=entry.visible,
        rest_display_pitch=Pitch(rest_position.letter, rest_position.octave, 0)
        if rest_position is not None
        else None,
        grace_slash=True
        if "graceNote" in record.fields and "slashGrace" in record.fields
        else None,
        # Verse order, so a multi-verse note emits its lyrics top to bottom.
        lyrics=tuple(
            Lyric(
                number=lyric.number,
                text=lyric.text,
                syllabic=lyric.syllabic.value,
                extend=lyric.extend,
            )
            for lyric in sorted(lyrics, key=lambda item: item.number)
        ),
        articulations=articulations,
        fingerings=fingerings,
        ornaments=ornaments,
        fermatas=fermatas,
        arpeggios=arpeggios if pitches else (),
        parentheses=parentheses,
        articulation_playback=articulation_playback,
        noteheads=noteheads,
        cross_staff=cross_staff,
        stem=frozen_stem(record) if pitches else None,
    )


def _tuplet_marks(positions: tuple[tuple[Tuplet, bool, bool], ...]) -> tuple[TupletMark, ...]:
    """Unreduced tuplet counts, or none where a count is not a whole number of units."""
    marks = []
    for tuplet, first, last in positions:
        normal, remainder = divmod(
            tuplet.reference_number * tuplet.reference_duration, tuplet.symbolic_duration
        )
        if remainder or not normal:
            return ()
        marks.append(
            TupletMark(
                actual=tuplet.symbolic_number,
                normal=normal,
                unit=Fraction(tuplet.symbolic_duration, _WHOLE_EDU),
                start=first,
                stop=last,
                show_number="actual"
                if tuplet.number_style is None
                else {0: "none", 2: "both"}.get(tuplet.number_style, "actual"),
            )
        )
    return tuple(marks)


def _ratio_of(marks: tuple[TupletMark, ...]) -> Fraction | None:
    if not marks:
        return None
    ratio = Fraction(1)
    for mark in marks:
        ratio *= Fraction(mark.normal, mark.actual)
    return ratio


def _resolve_ornament(
    ornament: Ornament,
    notes: tuple[Note, ...],
    key: KeySignature,
    transposition: StaffTransposition,
) -> Ornament:
    # An above-chord trill acts on the upper note (Finale Human Playback's
    # documented rule), irrespective of serialized chord order. Drawing's
    # useTopNote flag is a separate positioning option, not a playback selector.
    index = (
        max(range(len(notes)), key=lambda i: notes[i].harm_lev)
        if ornament.kind in {"trill", "upper-mordent"}
        else ornament.pitch_index
    )
    main = spell_note(notes[index], key, transposition).written
    upper = spell_note(
        replace(notes[index], harm_lev=notes[index].harm_lev + 1, harm_alt=0), key, transposition
    ).written
    if ornament.auxiliary_alteration is not None:
        upper = replace(upper, alteration=ornament.auxiliary_alteration)
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    distance = (
        12 * (upper.octave - main.octave)
        + semitones[upper.letter]
        - semitones[main.letter]
        + upper.alteration
        - main.alteration
    )
    return replace(
        ornament, pitch_index=index, auxiliary_semitones=distance if distance in (1, 2) else None
    )


def _place_score_wide(
    expressions: dict[tuple[int, int], tuple[Expression, ...]], staves: list[int]
) -> dict[tuple[int, int], tuple[Expression, ...]]:
    """Move a score expression onto the topmost staff.

    `staffAssign = -1` means the marking belongs to a **staff list** rather than
    to a staff -- 596 markings across 267 corpus documents, which were dropped
    entirely until this existed, because no `Part` is built for staff -1.

    Where it goes is a **convention, not a decode.** What the list selects is
    still unknown: the record is a six-slot `uint16` array (`others` 306 for the
    score, 304 for the parts), zero fills an unused slot, and the first slot is
    `-1` in 1,486 of 1,584 corpus records -- so `-1` is a value and not an
    end-of-list marker, but which staves it stands for is not established. The
    key is `staffList` on the assignment and **not** `categoryID`: those differ
    in all 746 cases, and `categoryID` reaches values (25, 26, 29) for which no
    list record exists at all.

    So rather than guess the list, this places the marking where a score
    expression is *engraved* -- once, above the top staff. MusicXML has no
    score-wide direction, so it has to be attached to some part, and attaching it
    to every part would turn 596 markings into 2,481 and print a dynamic on
    staves the list may exclude. One part is recoverable information; eighteen
    copies would be an invention.

    The redundant ones are already gone: `expressions_by_measure` drops a
    score-wide copy of an expression the same measure assigns to a real staff.
    """
    score_wide = {key: items for key, items in expressions.items() if key[0] == SCORE_WIDE_STAFF}
    if not score_wide or not staves:
        return expressions
    top = staves[0]
    out = {key: items for key, items in expressions.items() if key[0] != SCORE_WIDE_STAFF}
    for (_staff, measure), items in score_wide.items():
        out[(top, measure)] = out.get((top, measure), ()) + items
    return out


def _measure(
    *,
    staff: int,
    number: int,
    previous: int | None,
    cells: dict[tuple[int, int], _Cell],
    keys: dict[int, int],
    signatures: dict[int, EnigmaTimeSignature],
    clef_table: dict[int, Clef],
    clef_at: dict[tuple[int, int], int],
    repeats: Repeats,
    directions: dict[int, tuple[str, ...]] | None = None,
    barlines: dict[int, str] | None = None,
    expressions: dict[tuple[int, int], tuple[Expression, ...]] | None = None,
    navigation: dict[int, tuple[Navigation, ...]] | None = None,
    pedals: dict[tuple[int, int], tuple[Pedal, ...]] | None = None,
    clef_changes: dict[tuple[int, int], tuple[ClefPosition, ...]] | None = None,
    show_text_repeats: bool = True,
    printed: dict[int, PrintedTimeSignature] | None = None,
) -> Measure:
    cell = cells.get((staff, number))
    shown = (printed or {}).get(number)

    signature = signatures.get(number)
    previous_signature = signatures.get(previous) if previous is not None else None
    clef_index = clef_at.get((staff, number))
    previous_clef_index = clef_at.get((staff, previous)) if previous is not None else None
    if positions := (clef_changes or {}).get((staff, previous)) if previous is not None else None:
        previous_clef_index = positions[-1].index
    clef = clef_table.get(clef_index) if clef_index is not None else None
    clef_changed = clef is not None and clef_index != previous_clef_index

    # The key comes from the measure, not from the staff's notes, so a measure
    # in which this part is silent still knows what key it is in.
    key_raw = keys.get(number, cell.key_raw if cell is not None else 0)
    key = decode_key(key_raw)
    key_changed = previous is None or keys.get(previous) != key_raw
    here = repeats.get(number)

    return Measure(
        number=number,
        pedals=(pedals or {}).get((staff, number), ()),
        voices=(
            tuple(
                Voice(
                    number=layer,
                    events=tuple(events),
                    start_offset=Fraction(cell.start_times.get(layer, 0), _WHOLE_EDU),
                )
                for layer, events in sorted(cell.events_by_layer.items())
            )
            if cell is not None
            else (Voice(number=1, events=(_measure_rest(signature),)),)
        ),
        # Emit an attribute only where it changes: that is what MusicXML expects,
        # and it keeps the output readable.
        key_fifths=key.fifths if key_changed else None,
        is_minor=key.mode is Mode.MINOR,
        time=(
            TimeSignature(beats=signature.numerator, beat_type=signature.denominator)
            if signature is not None and signature != previous_signature
            else None
        ),
        display_time=TimeSignature(
            beats=shown.signature.numerator, beat_type=shown.signature.denominator
        )
        if shown is not None and shown.display and shown.signature != signature
        else None,
        time_symbol=shown.symbol if shown is not None else None,
        clef_sign=_MUSICXML_SIGNS.get(clef.sign)
        if clef_changed and clef and not (clef_changes or {}).get((staff, number))
        else None,
        clef_line=_clef_line(clef)
        if clef_changed and clef and not (clef_changes or {}).get((staff, number))
        else None,
        clef_changes=_timed_clefs(
            _drawn_clef_changes((clef_changes or {}).get((staff, number), ()), previous_clef_index),
            clef_table,
        ),
        # Repeats belong to the measure, not the staff: every part carries the
        # same barline, which is what a reader of one part expects to see.
        # A marking belongs to the measure, so every part shows it -- which is
        # what a player reading one part needs.
        directions=(directions or {}).get(number, ()),
        # An expression, unlike a text repeat, belongs to one staff -- so it is
        # keyed by (staff, measure) and the parts can legitimately differ.
        expressions=(expressions or {}).get((staff, number), ()),
        barline_style=(barlines or {}).get(number),
        repeat_forward=here.forward,
        repeat_backward=here.backward,
        repeat_passes=here.passes,
        endings=tuple(
            replace(ending, visible=ending.visible and show_text_repeats) for ending in here.endings
        ),
        repeat_playback=here.playback,
        navigation=tuple(
            replace(mark, visible=mark.visible and show_text_repeats)
            for mark in (navigation or {}).get(number, ())
        ),
    )


def _timed_clefs(
    positions: tuple[ClefPosition, ...], table: dict[int, Clef]
) -> tuple[ClefChange, ...]:
    out = []
    for position in positions:
        clef = table.get(position.index)
        if clef is None:
            raise CorruptScoreError(f"clefEnum: unknown clef index {position.index}")
        if sign := _MUSICXML_SIGNS.get(clef.sign):
            out.append(ClefChange(position.offset, sign, _clef_line(clef), position.visible))
    return tuple(out)
