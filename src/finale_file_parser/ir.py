"""The format-neutral intermediate representation.

Every input converges here before any exporter sees it (`docs/DECISIONS.md`,
2026-07-20). This module therefore imports **nothing** from `enigma` or
`container`: readers build an IR, exporters consume one, and neither knows about
the other. A `.mus` reader added later produces the same types and every exporter
works unchanged.

Consequence recorded in that decision, and worth restating because it shapes the
types: **MusicXML's limits must not constrain the IR.** Where Finale represents
something MusicXML cannot, the IR keeps it and the exporter drops it at the edge.
So durations here are exact `Fraction`s of a whole note rather than MusicXML
integer divisions, and a `Voice` carries its source layer number rather than a
MusicXML voice index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

__all__ = [
    "Arpeggio",
    "Beam",
    "ClefChange",
    "Ending",
    "Event",
    "Expression",
    "ExpressionPlayback",
    "Fermata",
    "Glissando",
    "Hairpin",
    "Lyric",
    "Measure",
    "Navigation",
    "NoteTies",
    "NoteEndpoint",
    "OctaveShift",
    "Ornament",
    "Part",
    "PartGroup",
    "Pedal",
    "Pitch",
    "PlaybackPreferences",
    "RepeatPlayback",
    "Score",
    "Slur",
    "SlurEndpoint",
    "Tempo",
    "TimeSignature",
    "Tremolo",
    "Voice",
]


@dataclass(frozen=True)
class Pitch:
    """A spelled pitch: letter, chromatic alteration, and octave."""

    step: str
    """Letter name, ``A``-``G``."""

    octave: int
    """Scientific pitch notation: middle C is octave 4."""

    alteration: int
    """Semitones from the natural: -1 flat, 0 natural, +1 sharp."""


@dataclass(frozen=True)
class NoteTies:
    """Tie flags for one pitched note, including unmatched source flags."""

    start: bool = False
    stop: bool = False


@dataclass(frozen=True)
class Ornament:
    """An ornament attached to an event, rather than additional written notes."""

    kind: str
    """upper-mordent or trill, retained as notation rather than written MIDI notes."""

    auxiliary_semitones: int | None = None
    """Distance to the auxiliary note when established by the key. None when unknown."""

    pitch_index: int = 0
    """The principal note's index in the event's pitches, independent of chord order."""

    auxiliary_alteration: int | None = None
    """An explicit accidental on the auxiliary (vs its natural), separate from the main note."""


@dataclass(frozen=True)
class Fermata:
    """A normal rounded hold symbol, without an inferred playback duration."""

    inverted: bool = False
    """False for the upright, above-note symbol; True for the below-note symbol."""


@dataclass(frozen=True)
class Tempo:
    """An explicit metronome marking, independent of the output format."""

    beat_unit: Fraction
    """Undotted beat length as a fraction of a whole note."""

    per_minute: Fraction
    dots: int = 0
    words: str = ""
    """Surrounding words, e.g. ``Faster``, without duplicating the metronome marking."""
    upper_per_minute: Fraction | None = None
    """Optional upper limit of a printed range, without choosing a playback rate."""
    equivalents: tuple[Tempo, ...] = ()
    """Additional explicit beat/rate pairs with the same quarter-note rate."""

    @property
    def quarter_bpm(self) -> Fraction:
        """Playback rate in quarter notes per minute."""
        return self.per_minute * self.beat_unit * (2 - Fraction(1, 2**self.dots)) * 4


@dataclass(frozen=True)
class TimeSignature:
    """A conventional time signature."""

    beats: int
    beat_type: int


@dataclass(frozen=True)
class Beam:
    """One beam level on one note, and what it does there."""

    number: int
    """1 is the primary beam, 2 the sixteenth's second, and so on."""

    type: str
    """MusicXML's vocabulary: begin, continue, end, forward hook, backward hook."""


@dataclass(frozen=True)
class Lyric:
    """One syllable sung by one event, in one verse.

    `syllabic` says where the syllable sits in its word -- "single", "begin",
    "middle" or "end". Enigma stores only the hyphens, so this is derived; see
    `enigma.lyrics`.
    """

    number: int
    """Verse number. Several lyrics on one event are several verses."""

    text: str
    syllabic: str = "single"
    extend: bool = False
    """A word extension: the line drawn under a syllable held across notes."""


@dataclass(frozen=True)
class Arpeggio:
    """A rolled-chord sign, shared across its participating pitches.

    A connected sign has the same ``group`` on all participating events and
    lists their staff-part ids in score order. Empty ids mean one staff. The
    exporter can put connected staves in one MusicXML part without changing
    the reader's one-part-per-staff representation.
    """

    group: str | None = None
    part_ids: tuple[str, ...] = ()
    pitch_indices: tuple[int, ...] = ()
    """Explicit covered chord notes; empty means the entire event."""
    direction: str | None = None
    """A printed up/down arrow; None retains the plain sign and default upward roll."""


@dataclass(frozen=True)
class Parenthesis:
    """One drawn parenthesis attached to an event.

    Offsets retain glyph positioning in staff spaces. A paired pitch_index
    identifies a notehead enclosure only when its note attachment is established;
    None preserves drawing information without guessing a chord note or span.
    """

    side: str
    x_offset: Fraction = Fraction(0)
    y_offset: Fraction = Fraction(0)
    pitch_index: int | None = None


@dataclass(frozen=True)
class Event:
    """One note, chord, or rest.

    A chord is one event with several pitches; a rest is one with none. Keeping
    them a single type means duration handling is written once, and a chord
    cannot accidentally be emitted as separate notes with separate durations.
    """

    duration: Fraction
    """Sounded length as a fraction of a whole note, tuplet scaling already
    applied. Exact rather than rounded: a triplet eighth is 1/12, which no
    integer division count represents without a common denominator chosen later
    by the exporter."""

    written_duration: Fraction
    """Length as written, before tuplet scaling -- what determines the notehead.
    A triplet eighth is written 1/8 but sounds 1/12."""

    pitches: tuple[Pitch, ...] = ()
    """Empty for a rest."""

    dots: int = 0
    tie_start: bool = False
    tie_end: bool = False
    is_grace: bool = False
    """A grace note: it is written and played, but occupies no metric time.

    Kept as a flag rather than as a zero duration because the two are not the
    same thing -- a grace note still has a notehead and a written value, and
    MusicXML represents it by omitting duration entirely rather than by writing
    zero, which its schema rejects.
    """
    tuplet_ratio: Fraction | None = None
    """Sounded over written, when this event is inside a tuplet. 2/3 for a
    triplet. None outside one."""

    lyrics: tuple[Lyric, ...] = ()
    """Syllables sung on this event, one per verse, in verse order."""

    beams: tuple[Beam, ...] = ()
    """One entry per beam level: 1 is the primary beam. Empty on a note that
    carries a flag rather than a beam."""

    is_measure_rest: bool = False
    """A rest filling the whole measure, however long the measure is.

    Distinct from a rest that happens to last a whole note: it is written as one
    symbol centred in the bar, and its length follows the time signature rather
    than any note value -- so a 3/4 measure rest is 3/4 long and has no note
    value at all.
    """

    fingerings: tuple[str, ...] = ()
    """Which finger plays this note, one entry per fingered pitch, in document
    order. Digits rather than numbers: MusicXML prints the text as given."""

    articulations: tuple[str, ...] = ()
    """MusicXML articulation names -- "staccato", "accent", "tenuto",
    "strong-accent", "breath-mark" -- in document order. "strong-accent-down"
    preserves an inverted marcato; the exporter maps it to strong-accent type=down."""

    note_ties: tuple[NoteTies, ...] = ()
    """One set of flags per pitch. Readers supply these, including explicit false flags.

    When present these override the legacy event-wide ``tie_start``/``tie_end``
    fields during export. Those fields remain aggregate summaries for existing
    callers; an authored event without ``note_ties`` keeps their old behavior.
    """

    ornaments: tuple[Ornament, ...] = ()

    fermatas: tuple[Fermata, ...] = ()
    """Hold symbols attached to this note, chord or rest in source order."""

    grace_slash: bool | None = None
    """The resolved grace-note slash: True slashed, False unslashed, None unknown.

    Describes notation, independently of playback duration. Ignored for ordinary
    events; None retains the exporter's bare grace element for authored scores
    or a source whose slash settings could not be read.
    """

    arpeggios: tuple[Arpeggio, ...] = ()
    """Rolled-chord signs in source order; rests do not participate."""

    playback: bool = True
    """False for an explicitly silent source event; written pitches survive."""
    visible: bool = True
    """Source notation visibility, independent of whether the event sounds."""

    parentheses: tuple[Parenthesis, ...] = ()
    """Notehead enclosures or retained positioned glyphs needing attachment review."""

    @property
    def is_rest(self) -> bool:
        return not self.pitches

    @property
    def is_chord(self) -> bool:
        return len(self.pitches) > 1


@dataclass(frozen=True)
class Voice:
    """A single line of music within a measure."""

    number: int
    """The source layer, 1-based. Preserved rather than renumbered so a reader's
    layout stays inspectable; an exporter maps it to its own voice numbering."""

    events: tuple[Event, ...] = ()

    start_offset: Fraction = Fraction(0)
    """Initial silence in whole-note units, without inventing a written rest."""
    instrument_id: str | None = None
    """Explicit shared playback identity; None when the source does not establish one."""
    playback: bool = True
    solo: bool = False


@dataclass(frozen=True)
class Ending:
    """One end of an ending bracket -- a "first time" / "second time" volta."""

    numbers: tuple[int, ...]
    """The passes this bracket is taken on. `1.` is (1,), `1., 2.` is (1, 2)."""

    type: str
    """`start` where the bracket opens; at its close, `stop` if it ends in a
    downward hook and `discontinue` if it just stops being drawn."""


@dataclass(frozen=True)
class ExpressionPlayback:
    """A typed source playback instruction; printed text does not define its type."""

    kind: str
    value: int
    beat_unit: Fraction | None = None
    pass_number: int = 0


@dataclass(frozen=True)
class Expression:
    """A marking the score attaches to one measure of one staff.

    A dynamic, a tempo word, a technique instruction -- whatever the document
    actually placed, as opposed to the library of definitions every Finale file
    ships whether it uses them or not.

    Distinct from `Measure.directions`, which is text repeats ("Fine", "D.C. al
    Coda"): those belong to the measure across every part, while an expression
    is placed on a particular staff and can differ between them.
    """

    text: str
    """What is printed. For most dynamics this is a single music-font character
    rather than letters -- `marking` is the readable form.

    **Empty where the file has no text for it but names it anyway.** 180 corpus
    dynamics are this shape: the definition's description says
    `'mezzo piano (velocity = 62)'` while the expression text record it points at
    is absent. `marking` carries the answer, and a consumer needs no character to
    render `<dynamics><mp/></dynamics>`. Empty text with no `marking` never
    reaches here -- an expression with neither is dropped at the reader.
    """

    category: str
    """The document's own `categoryType`: `dynamics`, `tempoMarks`,
    `techniqueText`, `expressiveText`, `rehearsalMarks`, `tempoAlts`, `misc`.
    Read from the file, not inferred from what the marking looks like."""

    marking: str | None = None
    """The conventional spelling of a dynamic -- `"ff"`, `"mp"`. None when the
    text is not one of the ten graded dynamics, including for a user-made
    expression that merely sits in the dynamics category."""

    velocity: int | None = None
    """The playback level the file gives this expression, where it gives one.
    Kept even though the MusicXML exporter does not emit it -- the IR holds what
    the reader found; see the module docstring."""

    layer: int | None = None
    """The layer this marking is attached to, 1-based, or None where the file
    attaches it to the staff rather than to one layer -- which is how 1,708 of
    the corpus's 6,672 assigned dynamics are placed."""

    is_rehearsal: bool = False
    """A rehearsal mark, whose `text` this project computed rather than read.

    The file stores no letter: the expression text is the bare insert command
    `^rehearsal()`, and Finale works the label out when it draws. What the file
    *does* say is the style -- `rehearsalMarkStyle` -- and for 99 of the corpus's
    113 marks that style is `measNum`, so the label is the measure number and no
    convention is involved. The 12 `letters` marks are numbered A, B, C in
    measure order, which is a convention and the only one here.

    Kept as a flag because `text` alone cannot distinguish the mark `A` from the
    word "A": MusicXML writes the first as `<rehearsal>` and the second as
    `<words>`.
    """

    score_wide: bool = False
    """A staff-list expression or a metronome header applying to the score.

    596 corpus markings are placed this way. Kept because the reader found it and
    the placement is a convention rather than a reading: `enigma.to_ir` puts such
    a marking on the topmost part, which is where a score expression is engraved,
    and an exporter that can say "this applies to the whole score" should prefer
    that. What the staff list actually selects is not decoded -- see
    `to_ir._place_score_wide`.
    """

    tempo: Tempo | None = None
    """An explicit metronome marking; ``text`` still retains the source wording."""

    offset: Fraction = Fraction(0)
    """Rhythmic attachment from the measure start, in whole-note units.

    Independent of drawing adjustments; signed offsets are preserved.
    """
    playback: ExpressionPlayback | None = None
    page: int | None = None
    """Original page placement when a first-page tempo header is projected above the score."""


@dataclass(frozen=True)
class ClefChange:
    """One timed clef, in whole-note units from the measure start."""

    offset: Fraction
    sign: str
    line: int | None = None
    visible: bool = True


@dataclass(frozen=True)
class RepeatPlayback:
    """Explicit source repeat destination and trigger, independent of its barline."""

    action: str = "jumpAuto"
    trigger: str = "untilPass"
    target: int = 0
    passes: int = 2
    reset_on_action: bool = False


@dataclass(frozen=True)
class Navigation:
    """A placed navigation mark with source playback independent of its words."""

    text: str
    kind: str = "words"
    """words, segno or coda; sign recognition requires the source font."""
    mark_id: str = ""
    playback: RepeatPlayback | None = None
    visible: bool = True
    """Hiding a printed sign does not disable its source playback rule."""


@dataclass(frozen=True)
class Pedal:
    """An explicit sustain-pedal change on a staff at an exact metric offset."""

    offset: Fraction
    kind: str
    """start, stop or change (release and reapply at the same instant)."""
    sign: bool = True
    line: bool = False


@dataclass(frozen=True)
class Measure:
    """One measure of one part."""

    number: int
    voices: tuple[Voice, ...] = ()

    key_fifths: int | None = None
    """Position on the circle of fifths, negative for flats. Set only where it
    changes, so an exporter emits an attribute only when it must."""

    is_minor: bool = False
    time: TimeSignature | None = None
    clef_sign: str | None = None
    """``G``, ``F``, ``C``, or ``percussion``."""

    clef_line: int | None = None

    directions: tuple[str, ...] = ()
    """Legacy words-only view, including text repeats. Structured navigation
    retains source playback independently; export avoids printing both views."""

    expressions: tuple[Expression, ...] = ()
    """Markings placed on *this staff* at this measure -- dynamics, tempo words,
    technique text. Unlike `directions` these differ between parts, and unlike
    the expression library every document ships, these are the ones the score
    actually uses; see `enigma.expressions`."""

    barline_style: str | None = None
    """MusicXML `bar-style` for this measure's right barline -- `light-light`
    for a double bar, `light-heavy` for a final one. None for an ordinary
    barline, which needs no element at all."""

    repeat_forward: bool = False
    """A forward repeat barline on the left of this measure."""

    repeat_backward: bool = False
    """A backward repeat barline on the right of this measure."""

    repeat_passes: int = 2
    """How many times the repeated section is played. Only meaningful with
    `repeat_backward`; 2 is the ordinary "play it twice"."""

    endings: tuple[Ending, ...] = ()
    """Ending brackets opening or closing at this measure. A single-measure
    ending does both, so this can hold two."""

    clef_changes: tuple[ClefChange, ...] = ()
    """Timed clefs, including a source list's initial clef at offset zero."""
    repeat_playback: RepeatPlayback | None = None
    navigation: tuple[Navigation, ...] = ()
    pedals: tuple[Pedal, ...] = ()


@dataclass(frozen=True)
class Hairpin:
    """A crescendo or diminuendo spanning exact positions on one staff-part.

    Offsets are fractions of a whole note from the beginning of the named
    measure, including its end. A complete span keeps pairing independent of
    the output format's numbering or note placement.
    """

    kind: str
    """``crescendo`` or ``diminuendo``."""

    start_measure: int
    start_offset: Fraction
    end_measure: int
    end_offset: Fraction

    start_x_offset: Fraction = Fraction(0)
    end_x_offset: Fraction = Fraction(0)
    """Horizontal endpoint adjustments in staff spaces; independent of time."""


@dataclass(frozen=True)
class OctaveShift:
    """A staff-wide sounding displacement over inclusive source onsets."""

    octaves: int
    """Positive sounds above the written notes; negative sounds below."""
    start_measure: int
    start_offset: Fraction
    end_measure: int
    end_offset: Fraction

    def contains(self, measure: int, offset: Fraction) -> bool:
        return (
            (self.start_measure, self.start_offset)
            <= (measure, offset)
            <= (self.end_measure, self.end_offset)
        )


@dataclass(frozen=True)
class SlurEndpoint:
    """An exact event on a staff-part, including a particular grace note.

    Measure and voice use their source numbers; event_index is zero-based
    within that voice. An onset alone cannot distinguish several grace notes
    from the following ordinary note, which all share the same metric time.
    """

    measure: int
    voice: int
    event_index: int


@dataclass(frozen=True)
class LineSpan:
    """An assigned visible line, with timing separate from drawing geometry.

    This carries no inferred pedal, octave, glissando or playback meaning.
    Custom endpoint resource IDs survive for renderers that can resolve them.
    Offsets/lengths use staff spaces; musical offsets use whole-note units.
    """

    start_measure: int
    start_offset: Fraction
    end_measure: int
    end_offset: Fraction
    line_type: str = "solid"
    start_cap: str = "none"
    end_cap: str = "none"
    start_x: Fraction = Fraction(0)
    start_y: Fraction = Fraction(0)
    end_x: Fraction = Fraction(0)
    end_y: Fraction = Fraction(0)
    start_text: str = ""
    end_text: str = ""
    start_symbol: str = ""
    end_symbol: str = ""
    end_part_id: str | None = None
    source_ref: str = ""
    start_cap_length: Fraction | None = None
    end_cap_length: Fraction | None = None


@dataclass(frozen=True)
class Slur:
    """A phrase span, or an explicitly positioned curve on one event."""

    start: SlurEndpoint
    end: SlurEndpoint
    placement: str | None = None
    """``above`` or ``below`` when explicit; None leaves direction automatic."""

    graphical: bool = False
    """A same-event drawing with distinct endpoints, independent of playback."""
    start_x_offset: Fraction = Fraction(0)
    start_y_offset: Fraction = Fraction(0)
    end_x_offset: Fraction = Fraction(0)
    end_y_offset: Fraction = Fraction(0)
    """Active drawing adjustments in staff spaces, without invented notes."""


@dataclass(frozen=True)
class NoteEndpoint:
    """One exact pitch of a part-local event, including an individual chord note."""

    event: SlurEndpoint
    pitch_index: int
    part_id: str | None = None
    """None uses the owning part; an explicit ID preserves a cross-staff endpoint."""


@dataclass(frozen=True)
class Glissando:
    """A slide between two written pitches, independent of intermediate MIDI attacks."""

    start: NoteEndpoint
    end: NoteEndpoint
    line_type: str = "wavy"
    start_x_offset: Fraction = Fraction(0)
    start_y_offset: Fraction = Fraction(0)
    end_x_offset: Fraction = Fraction(0)
    end_y_offset: Fraction = Fraction(0)


@dataclass(frozen=True)
class Tremolo:
    """Two written notes/chords alternating over their shared rhythmic span."""

    start: SlurEndpoint
    end: SlurEndpoint
    marks: int
    """The number of detached tremolo strokes, without inserted performance notes."""


@dataclass(frozen=True)
class Part:
    """One instrumental part."""

    id: str
    name: str
    measures: tuple[Measure, ...] = ()

    hairpins: tuple[Hairpin, ...] = ()
    """Dynamic spans on this staff, without inferred playback velocities."""

    slurs: tuple[Slur, ...] = ()
    """Phrase spans with exact note attachments, independent of ties."""

    abbreviation: str = ""
    """The staff's abbreviated name, kept separately from a group label."""
    octave_shifts: tuple[OctaveShift, ...] = ()
    """Written Event pitches remain unchanged; these determine sounding octaves."""
    tremolos: tuple[Tremolo, ...] = ()
    glissandi: tuple[Glissando, ...] = ()
    instrument_id: str | None = None
    """Shared playback identity when every used layer routes to the same source instrument."""
    lines: tuple[LineSpan, ...] = ()


@dataclass(frozen=True)
class PartGroup:
    """A brace or bracket joining a run of consecutive parts."""

    part_ids: tuple[str, ...]
    """The parts it joins, in score order. Always contiguous in `Score.parts`."""

    symbol: str | None = None
    """MusicXML `<group-symbol>` -- "brace", "bracket", "line", "square" -- or
    None where the source names a shape this project cannot identify."""

    barline: bool = False
    """Barlines run through the group rather than stopping at each staff."""

    name: str = ""
    abbreviation: str = ""


@dataclass(frozen=True)
class ScoreDiagnostic:
    """A source condition requiring review, carried without changing the music."""

    code: str
    message: str
    source_ref: str = ""


@dataclass(frozen=True)
class PlaybackPreferences:
    """Explicit document controls, independent of printed score instructions."""

    beat_unit: Fraction
    per_minute: Fraction
    swing_amount: Fraction = Fraction(0)
    base_velocity: int = 64
    start_measure: int = 1
    start_offset: Fraction = Fraction(0)
    start_mode: int = 0
    stop_measure: int | None = None
    stop_offset: Fraction = Fraction(0)
    start_pass: int = 1
    stop_pass: int = 1
    swing_unit: Fraction | None = None
    """Half the initial actual metric division, independent of display meter."""

    @property
    def quarter_bpm(self) -> Fraction:
        return self.beat_unit * self.per_minute * 4


@dataclass(frozen=True)
class Score:
    """A whole score."""

    parts: tuple[Part, ...] = ()
    groups: tuple[PartGroup, ...] = ()
    """Braces and brackets down the left edge, outermost first."""

    title: str = ""
    composer: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    """Anything a reader recovered that the IR does not model yet. Kept so
    information is not silently discarded on the way in -- the decision above
    puts the loss at the exporter, not the reader."""
    diagnostics: tuple[ScoreDiagnostic, ...] = ()
    """Recoverable source conditions, independent of notation or playback."""
    playback: PlaybackPreferences | None = None
