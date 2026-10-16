"""Which expressions a score actually places, and where.

Three records, and the middle one is a library rather than a list of what is
used:

    measExprAssign(measure)  -- a marking is placed here, on this staff
    textExprDef(cmper)       -- what it is: category, playback level, description
    texts/expression(number) -- what it prints, usually one music-font character

**Only an assignment puts a marking in the music.** Every corpus document ships
the same expression library whether it uses any of it or not -- sixteen
dynamics, a shelf of tempo words -- so reading `textExprDef` alone would print a
fortissimo in every part of every file. The same trap as `textRepeatText`; see
`enigma.jumps`.

## The join

`measExprAssign.textExprID` names the definition, and it holds up: across the
401-document corpus **every** assignment that carries an id resolves --
5,663 through `textExprID` to a `textExprDef` and 91 through `shapeExprID` to a
`shapeExprDef`, with none left dangling. The remaining 7,488 carry no id at all
and place nothing.

The historical corpus audit yielded **6,672 assigned dynamics across 315 documents**,
distributed as real music is rather than as a library is: f 1,715, mf 1,501,
p 1,461, mp 777, ff 420, pp 161, ppp 45, fff 38, ffff 12. A palette read by
mistake would instead give a flat count of about 400 for every entry.

Definition to printed text pairs on **`cmper`**, not `textIDKey` -- see
`docs/formats/expressions-and-dynamics.md` for why, and for how the ten dynamics
came to be named.

## When a glyph counts as a dynamic

Five of the ten dynamic characters are **plain ASCII letters** -- Maestro writes
forte as `f` and mezzo piano as `P` -- so matching the character alone would read
a literal "f" label as a fortissimo. Two signals settle it, and the corpus says
which to trust:

| category | font | glyph in the table | count |
| --- | --- | --- | --- |
| `dynamics` | `^fontMus` | yes | 6,182 |
| `techniqueText` | `^fontMus` | yes | 1,191 |
| `dynamics` | none | yes | 114 |
| `misc` / `tempoMarks` / `expressiveText` | none | yes | 129 |
| anything | `^fontTxt` | **yes** | **0** |

The last row is the useful one: across 401 documents **nothing set in a text
font ever matches the table**, so the font markup never produces a false
dynamic. The 1,191 `techniqueText` rows are user copies of a dynamic glyph filed
in a custom category -- still a dynamic, since it is the Maestro character.

So `marking` is claimed when the glyph is in the table **and** either the text is
set in a music font or the document's own category is `dynamics`. The 129 rows
with neither signal are left unmarked: a bare `f` in `misc` with no font at all
is as likely to be a label as a dynamic, and this project does not guess. The
text is still carried, so nothing is lost.

An explicit graded-dynamic description is sufficient on its own. For an attack
description, the documented glyph must also match: `sforzato` with `§` identifies
`sfz`, while the other identically described variant stays unnamed. This handles
legacy compiled font markup without inventing a font or category. Unicode
description decoding and glyph evidence are recorded in ARCHITECTURE.md.

## Score expressions, and what still does not reach the IR

This module returns 11,732 markings and **11,367 reach a `Measure`**.

**596 of them name no staff at all.** `staffAssign = -1` means the marking belongs
to a **staff list**, and the file says so: all 746 corpus assignments carrying it
also carry `staffGroup` *and* `staffList`, where a positive-staff assignment
almost never does (138 of 11,687). 81 are a second copy of a marking the same
measure already places on a real staff, and this module drops those as redundant;
the remaining **563 are placed on the topmost part** by
`to_ir._place_score_wide`, which explains why that is a convention rather than a
reading. `Expression.score_wide` records the fact so it is not lost in the move.

**365 remain dropped**, all one cause: they are assigned to a staff that holds no
notes anywhere in the document, and one `Part` is built per staff *with music*, so
there is nowhere to put them. Whether such a staff should become an empty part is
a question about part construction, not about expressions.

`tests/enigma/test_expressions_ir_corpus_sweep.py` pins every number here, in
both directions. It exists because the sweep beside it does not catch this: that
one asks `expressions_by_measure` what `expressions_by_measure` found, which is a
reader confirming itself. Measure the delivered object.

## Rehearsal marks

Their label is not in the file: the expression text is the bare `^rehearsal()`
insert, so `plain_text` yields nothing and all 113 corpus assignments were
dropped for having nothing to print. `rehearsalMarkStyle` says how to work it out
-- `measNum` for 99 of them, where the label is the measure number and no
convention is involved, `letters` for 12, numbered by position. See
`_rehearsal_labels`. 90 marks are placed across 10 documents.

## What is not read

**Placement.** `horzEvpuOff` and `vertOff` carry the offsets Finale drew the
marking at. They are not converted: EVPU to tenths is a scaling this project has
not confirmed, and an exporter placing a dynamic at a wrong offset is worse than
one letting the consumer default it.

**Shape expressions.** `shapeExprID` names a drawn shape rather than text --
91 assignments in the corpus. There is nothing to print as text, and this module
carries text markings only.

**A 2001-2005 `.mus`.** The numeric era is read -- `others` 241 is the definition
and 177 the assignment, see `mus_others` -- and yields 3,022 markings across 186
documents. The DCL era is not: it spells them `^DT` and `^DY`, and only one `DT`
field is decoded (the playback value at `+4`, confirmed 434/434 by the record's
own description). See `mus_document.UNTRANSLATED`.

**A `.mus` expression has no category and no layer.** `categoryID` is not
identified in the 241 record (best offset 20.3%, which is noise) and `layer`
collides with `staffAssign` at `+8`. Both are absent rather than invented, so
`category` is `""` and `layer` is None for every `.mus` expression -- and the
dynamics are still named from their descriptions, with an evidenced glyph needed
for the otherwise ambiguous attack variants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.fonts import FontRun, readable_text, text_runs
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.text import plain_text, text_block
from finale_file_parser.enigma.timesig import time_signatures
from finale_file_parser.formats.dynamics import (
    DYNAMICS_CATEGORY,
    described_dynamic,
    dynamic_for,
)
from finale_file_parser.ir import Expression, ExpressionPlayback, Tempo

__all__ = ["SCORE_WIDE_STAFF", "expressions_by_measure", "first_page_tempos"]

SCORE_WIDE_STAFF = -1
"""The `staffAssign` a score expression carries instead of a staff number.

It means "this belongs to a **staff list**", and the file says so: all 746 corpus
assignments carrying it also carry `staffGroup` *and* `staffList`, where a
positive-staff assignment almost never does (138 of 11,687). Kept as the key so
`to_ir` can decide where a score-wide marking goes; nothing downstream should
treat it as a staff.
"""

_ASSIGN = "measExprAssign"
_DEF = "textExprDef"
_CATEGORY = "markingsCategory"
_TEXT = "expression"

_REHEARSAL = re.compile(r"\^rehearsal\(\)")
"""The insert that stands where a rehearsal mark's label would be.

The label is not in the file. The expression text is this command and nothing
else, so `plain_text` yields `""` -- correctly, since it has no literal text --
and every one of the corpus's 113 marks was dropped for having nothing to print.
What the file gives instead is `rehearsalMarkStyle`, which says how to work the
label out. See `_rehearsal_labels`.
"""

_MEASURE_NUMBER_STYLE = "measNum"
_LETTER_STYLE = "letters"
_NUMBER_STYLE = "numbers"

_TEMPO = re.compile(
    r"(?<!\w)(?P<unit>quarter|half|eighth|whole|[qhew♩♪𝅘𝅥𝅗𝅥𝅝])"
    r"(?P<dots>\.{0,3})\s*=\s*(?P<bpm>\d{1,4}(?:\.\d{1,3})?)"
    r"(?:\s*[-–]\s*(?P<upper>\d{1,4}(?:\.\d{1,3})?))?"
    r"(?![\w./]|\s*[-–]\s*\d)",
    re.IGNORECASE,
)
"""An explicit beat = number, not a tempo word or an untyped playback value.

The legacy `.mus` cannot identify playType. Its printed q = 82 / q = 112 marks
are independent evidence, and agree with the performance MIDI. Keep ranges,
equivalences and unknown symbols as words instead of inventing a playback rate.
"""

_TEMPO_UNITS = {
    "quarter": Fraction(1, 4),
    "q": Fraction(1, 4),
    "♩": Fraction(1, 4),
    "𝅘𝅥": Fraction(1, 4),
    "half": Fraction(1, 2),
    "h": Fraction(1, 2),
    "𝅗𝅥": Fraction(1, 2),
    "eighth": Fraction(1, 8),
    "e": Fraction(1, 8),
    "♪": Fraction(1, 8),
    "whole": Fraction(1),
    "w": Fraction(1),
    "𝅝": Fraction(1),
}


def _tempo(text: str, *, runs: tuple[FontRun, ...] = ()) -> Tempo | None:
    # Text already read through `readable_text` spells its beats as note symbols,
    # which the pattern accepts; the run translation below is for raw text.
    if runs and not any(symbol in text for symbol in _READABLE_NOTES):
        translated = []
        for run in runs:
            literal = run.text
            if run.name == "MaestroTimes":
                literal = literal.translate(str.maketrans("ŒÓ‰\uf0ce", "qheq"))
            if run.name in {"EngraverTextT", "EngraverTextH", "EngraverTextNCS"}:
                literal = re.sub(r"(?i)([qhe])d", r"\1.", literal)
            translated.append(literal)
        # Run boundaries may separate a beat symbol from its literal equality.
        text = " ".join(translated)
    matches = list(_TEMPO.finditer(text))
    if not matches:
        return None
    tempos = []
    for match in matches:
        rate = Fraction(match["bpm"])
        upper = Fraction(match["upper"]) if match["upper"] else None
        if not 0 < rate <= 1000 or (upper is not None and not rate <= upper <= 1000):
            return None
        tempos.append(
            Tempo(
                _TEMPO_UNITS[match["unit"].lower()],
                rate,
                len(match["dots"]),
                upper_per_minute=upper,
            )
        )
    if len(tempos) > 1 and (
        any(t.upper_per_minute is not None for t in tempos)
        or any(t.quarter_bpm != tempos[0].quarter_bpm for t in tempos[1:])
    ):
        return None
    remainder = _TEMPO.sub("", text)
    words = " ".join(remainder.strip(" ()=;,").split())
    return replace(tempos[0], words=words, equivalents=tuple(tempos[1:]))


def expressions_by_measure(
    document: EnigmaDocument,
) -> dict[tuple[int, int], tuple[Expression, ...]]:
    """The markings the score places, keyed by `(staff, measure)`.

    A staff and measure can carry more than one, and order follows the document.
    """
    categories = _categories(document)
    definitions = _definitions(document)
    texts = _texts(document)

    on_a_staff = _staffed(document)
    labels = _rehearsal_labels(document, definitions, texts)
    swing_units = _swing_units(document)

    out: dict[tuple[int, int], list[Expression]] = {}
    for record in document.others.of_tag(_ASSIGN):
        # A linked part repeats every assignment. Counting those doubles each
        # marking: 20,606 of the corpus's 33,039 records carry a `part`.
        if "part" in record.attrs:
            continue
        measure = field_int(record.attrs.get("cmper"))
        staff = field_int(record.fields.get("staffAssign"))
        expr_id = field_int(record.fields.get("textExprID"))
        if measure is None or staff is None or expr_id is None:
            continue
        definition = definitions.get(expr_id)
        if definition is None:
            continue
        offset = _offset(record)
        if (
            staff == SCORE_WIDE_STAFF
            and (measure, expr_id, offset, "hidden" not in record.fields) in on_a_staff
            and _score_assignment(record)
        ):
            # The same expression is already placed on a real staff in this
            # measure, so the score-wide copy would print it twice. 102 of the
            # corpus's 746 list assignments are this shape.
            continue
        found = texts.get(expr_id)
        printed = found.printed if found is not None else ""
        # A rehearsal mark prints a label the file does not store; everything
        # else prints what its text record says.
        label = labels.get(measure) if found is not None and found.is_rehearsal else None
        text = label if label is not None else printed
        category = categories.get(field_int(definition.fields.get("categoryID")), "")
        marking = _marking(
            printed,
            category=category,
            in_music_font=found.in_music_font if found is not None else False,
            description=str(definition.fields.get("descStr") or ""),
            in_maestro_font=any(
                run.name is not None
                and run.name.casefold() in _MAESTRO_LAYOUT
                and run.text.strip() == printed
                for run in found.runs
            )
            if found
            else False,
        )
        # Keep it if there is something to print *or* something to call it. An
        # expression with neither is not a marking -- 461 corpus assignments
        # resolve to a definition with no text record and no naming description,
        # and a rehearsal mark whose style is unreadable has no label to print.
        playback = _playback(definition)
        if not text and marking is None and (playback is None or playback.kind == "none"):
            continue
        if playback is not None and playback.kind == "swing":
            playback = replace(playback, beat_unit=swing_units.get(measure))
        out.setdefault((staff, measure), []).append(
            Expression(
                text=text,
                category=category,
                marking=marking,
                velocity=field_int(definition.fields.get("value")),
                score_wide=staff == SCORE_WIDE_STAFF,
                is_rehearsal=label is not None,
                layer=field_int(record.fields.get("layer")),
                tempo=_tempo(printed, runs=found.runs if found else ())
                if marking is None and label is None
                else None,
                offset=offset,
                playback=playback,
                visible="hidden" not in record.fields
                and not _empty_printed_text(document, definition, found),
                score_assignment=_score_assignment(record),
                part_assignment="noPartAssignment" not in record.fields
                and record.fields.get("showStaffList") != "scoreOnly",
            )
        )
    return {where: _framed(tuple(items)) for where, items in out.items()}


_EMPTY_FRAME = re.compile(r"\(\s+\)")


def _framed(items: tuple[Expression, ...]) -> tuple[Expression, ...]:
    """Fold an empty parenthesis frame around the lone glyph it was drawn for.

    SMB2 Title bar 5 prints "(//)" as two expressions: "(   )" with only spaces
    inside, and the caesura glyph placed between the parentheses. Exported apart
    they read "(      )" and "//"; joined they read as printed.
    """
    frames = [e for e in items if _EMPTY_FRAME.fullmatch(e.text) and e.visible]
    glyphs = [e for e in items if e.text == _CAESURA and e.visible]
    if len(frames) != 1 or len(glyphs) != 1:
        return items
    frame, glyph = frames[0], glyphs[0]
    return tuple(
        replace(glyph, text=f"({glyph.text})") if e is glyph else e for e in items if e is not frame
    )


def first_page_tempos(document: EnigmaDocument) -> tuple[Expression, ...]:
    """Visible page-one metronomes, independent of expression palette definitions.

    A page text has no rhythmic playback instruction. Preserve it as a printed
    header with explicitly disabled expression playback. Later-page and repeated
    header text cannot establish a bar attachment and is not promoted to a tempo.
    The normalized document retains every assignment and its page coordinates.
    """
    result = []
    for record in document.others.of_tag("pageTextAssign"):
        if "part" in record.attrs or "postIt" in record.fields:
            continue
        if field_int(record.attrs.get("cmper")) != 1:
            continue
        block = field_int(record.fields.get("block"))
        if block is None:
            continue
        markup = text_block(document, block)
        if markup is None:
            continue
        printed = plain_text(markup)
        runs = text_runs(document, markup)
        if any((run.name or "").casefold() in _NOTE_TEXT_FONTS for run in runs):
            spaced = text_runs(document, markup, keep_spaces=True)
            printed = re.sub(r"\s+", " ", readable_text(spaced)).strip() or printed
        explicit_unit = bool(re.search(r"\b(?:quarter|half|eighth|whole)\b|[♩♪𝅘𝅥𝅗𝅥𝅝]", printed))
        known_beat_font = any(
            run.name is not None
            and run.name.casefold()
            in {
                "maestro",
                "maestrotimes",
                "engraverfontset",
                "engraver font set",
                "jazz",
                "engravertextt",
                "engravertexth",
                "engravertextncs",
            }
            and re.search(r"(?<!\w)[qhewŒÓ‰\uf0ce](?:d|\.)?(?=\s|=|$)", run.text)
            for run in runs
        )
        if not explicit_unit and not known_beat_font:
            continue
        tempo = _tempo(printed, runs=runs)
        if tempo is not None:
            result.append(
                Expression(
                    printed,
                    "",
                    tempo=tempo,
                    score_wide=True,
                    playback=ExpressionPlayback("none", 0),
                    page=1,
                )
            )
    return tuple(result)


def _swing_units(document: EnigmaDocument) -> dict[int, Fraction]:
    # Finale swings half of the actual metric division, not a metronome glyph
    # or the displayed numerator. Compound divisions already subdivide by 3.
    if not document.others.of_tag("measSpec"):
        return {}
    return {
        number: Fraction(signature.division_edu, 8192)
        for number, signature in time_signatures(document).items()
        if not signature.is_compound
    }


def _playback(definition: Record) -> ExpressionPlayback | None:
    kind = definition.fields.get("playType")
    if not isinstance(kind, str) or "valueIsExecutableShape" in definition.fields:
        return None
    value = field_int(definition.fields.get("playbackValue", definition.fields.get("value", "0")))
    play_pass = field_int(definition.fields.get("playPass", "0"))
    if value is None or play_pass is None or not 0 <= play_pass <= 32767:
        raise CorruptScoreError("textExprDef: invalid typed playback value/pass")
    unit = None
    if kind == "tempo":
        edu = field_int(definition.fields.get("auxdata1", "0"))
        if edu is None or not 0 <= edu <= 32767:
            raise CorruptScoreError("textExprDef: invalid tempo beat unit")
        unit = Fraction(edu, 4096) if edu else None
    if kind == "amplitude" and not -32768 <= value <= 32767:
        raise CorruptScoreError("textExprDef: stored key velocity is outside signed 16-bit bounds")
    if kind == "swing" and not 0 <= value <= 32767:
        raise CorruptScoreError("textExprDef: swing value is outside supported bounds")
    return ExpressionPlayback(kind, value, unit, play_pass)


def _rehearsal_labels(
    document: EnigmaDocument, definitions: dict[int, Record], texts: dict[int, _Text]
) -> dict[int, str]:
    """Measure -> the label its rehearsal mark prints.

    A mark placed on several staves of one measure is **one** mark, so the label
    is keyed by measure: numbering per assignment would give the same bar two
    different letters.

    Three styles, and only one of them needs a convention:

    * `measNum` -- the label *is* the measure number. 99 of the corpus's 113
      marks, and nothing is guessed.
    * `numbers` -- the mark's position, counting from 1.
    * `letters` -- A, B, C in measure order. 12 corpus marks. This is the
      convention, and it is Finale's own; past Z it continues AA, AB.

    A mark whose definition gives no style is left out rather than defaulted:
    two corpus marks are that shape, and inventing a label for them would put a
    letter in the score that the file does not ask for.
    """
    styles: dict[int, str] = {}
    for record in document.others.of_tag(_ASSIGN):
        if "part" in record.attrs:
            continue
        measure = field_int(record.attrs.get("cmper"))
        expr_id = field_int(record.fields.get("textExprID"))
        if measure is None or expr_id is None or expr_id not in texts:
            continue
        if not texts[expr_id].is_rehearsal:
            continue
        definition = definitions.get(expr_id)
        style = str(definition.fields.get("rehearsalMarkStyle")) if definition else ""
        if style in (_MEASURE_NUMBER_STYLE, _LETTER_STYLE, _NUMBER_STYLE):
            styles.setdefault(measure, style)

    out: dict[int, str] = {}
    for position, measure in enumerate(sorted(styles)):
        style = styles[measure]
        if style == _MEASURE_NUMBER_STYLE:
            out[measure] = str(measure)
        elif style == _NUMBER_STYLE:
            out[measure] = str(position + 1)
        else:
            out[measure] = _letter(position)
    return out


def _letter(position: int) -> str:
    """A, B, ... Z, AA, AB -- the spreadsheet-column sequence Finale uses."""
    letters = ""
    position += 1
    while position:
        position, remainder = divmod(position - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _offset(record: Record) -> Fraction:
    edu = field_int(record.fields.get("horzEduOff", "0"))
    if edu is None or not -(1 << 31) <= edu < (1 << 31):
        raise CorruptScoreError("measExprAssign: invalid horzEduOff")
    return Fraction(edu, 4096)


def _score_assignment(record: Record) -> bool:
    mode = record.fields.get("showStaffList")
    if mode is not None and (
        not isinstance(mode, str) or mode not in {"", "scoreOnly", "partOnly"}
    ):
        raise CorruptScoreError("measExprAssign: unsupported showStaffList")
    return (
        "noScoreAssignment" not in record.fields
        and record.fields.get("showStaffList") != "partOnly"
    )


def _empty_printed_text(document: EnigmaDocument, definition: Record, found: _Text | None) -> bool:
    if found is not None:
        return not found.printed and not found.is_rehearsal
    block_id = field_int(definition.fields.get("textBlockID"))
    if block_id == 0:
        return True
    block = document.others.get("textBlock", block_id) if block_id is not None else None
    return block is not None and field_int(block.fields.get("textID")) == 0


def _staffed(document: EnigmaDocument) -> set[tuple[int, int, Fraction, bool]]:
    """(measure, expression id) pairs already assigned to a real staff.

    A score expression is drawn once; where the document also assigns the same
    expression to a staff in that measure, the score-wide copy is redundant.
    """
    out: set[tuple[int, int, Fraction, bool]] = set()
    for record in document.others.of_tag(_ASSIGN):
        if "part" in record.attrs or not _score_assignment(record):
            continue
        staff = field_int(record.fields.get("staffAssign"))
        measure = field_int(record.attrs.get("cmper"))
        expr_id = field_int(record.fields.get("textExprID"))
        if staff is None or staff < 0 or measure is None or expr_id is None:
            continue
        out.add((measure, expr_id, _offset(record), "hidden" not in record.fields))
    return out


def _categories(document: EnigmaDocument) -> dict[int | None, str]:
    """categoryID -> the type the document itself gives it.

    `dynamics`, `tempoMarks`, `techniqueText` and the rest are the file's own
    words. Nothing here is inferred from what a marking looks like.
    """
    out: dict[int | None, str] = {}
    for record in document.others.of_tag(_CATEGORY):
        kind = record.fields.get("categoryType")
        if isinstance(kind, str):
            out[field_int(record.attrs.get("cmper"))] = kind
    return out


def _definitions(document: EnigmaDocument) -> dict[int, Record]:
    out: dict[int, Record] = {}
    for record in document.others.of_tag(_DEF):
        if "part" in record.attrs:
            continue
        cmper = field_int(record.attrs.get("cmper"))
        if cmper is not None:
            out[cmper] = record
    return out


_MAESTRO_LAYOUT = frozenset({"maestro", "engraverfontset", "engraver font set"})
"""Fonts laid out on Maestro's character map: Engraver Font Set's "S" prints the
same sf (Dreadful Fight bar 47)."""

_CAESURA = "//"

_READABLE_NOTES = ("\u2669", "\u266a", "\u266b", "\U0001d15e", "\U0001d15d")

_NOTE_TEXT_FONTS = frozenset({"maestrotimes", "engravertextt", "engravertexth", "engravertextncs"})


def _marking(
    text: str,
    *,
    category: str,
    in_music_font: bool,
    description: str,
    in_maestro_font: bool = False,
) -> str | None:
    """The readable dynamic this expression is, or None if it is not one.

    Three signals, strongest first:

    1. **The description names it.** `'fortissimo (velocity = 101)'` identifies
       a graded dynamic. An attack description also needs its documented glyph,
       since two variants share the word `sforzato`. This handles a legacy
       `.mus` whose compiled font markup and category are not decoded.
    2. **The glyph is in the table and set in a music font.** For a `.musx`,
       where the markup distinguishes.
    3. **The glyph is in the table and the document's own category is
       `dynamics`.**

    Anything else is left unnamed -- see "When a glyph counts as a dynamic" in
    the module docstring for the counts behind the rule.
    """
    if text == "S":
        return "sf" if in_maestro_font else None
    described = described_dynamic(description, glyph=text)
    if described is not None:
        return described.marking
    entry = dynamic_for(text)
    if entry is None:
        return None
    if in_music_font or category == DYNAMICS_CATEGORY:
        return entry.marking
    return None


@dataclass(frozen=True)
class _Text:
    """What one expression text record says, once its markup has been read."""

    printed: str
    """The literal characters, markup stripped. Empty for a rehearsal mark,
    whose text is only an insert command."""

    in_music_font: bool
    """The font matters because five dynamics are plain letters."""

    is_rehearsal: bool
    """The text is the `^rehearsal()` insert, so the label has to be worked out."""
    runs: tuple[FontRun, ...] = ()


def _texts(document: EnigmaDocument) -> dict[int, _Text]:
    """Expression number -> what its text record says.

    The markup is kept long enough to answer both questions it decides -- which
    font, and whether the label is an insert -- and then discarded.
    """
    out: dict[int, _Text] = {}
    for record in document.texts.records:
        if record.tag != _TEXT or "part" in record.attrs:
            continue
        number = field_int(record.attrs.get("number"))
        if number is None:
            continue
        out[number] = _as_text(document, record.text or "")
    for number, definition in _definitions(document).items():
        if "textBlockID" not in definition.fields:
            continue
        # Raw legacy IDs name a text block, not the expression's text section.
        # A missing/empty reference must never fall back to an unrelated section
        # that merely has the same number as the definition.
        out.pop(number, None)
        block = field_int(definition.fields.get("textBlockID"))
        markup = text_block(document, block) if block is not None else None
        if markup is not None:
            out[number] = _as_text(document, markup)
    return out


def _as_text(document: EnigmaDocument, markup: str) -> _Text:
    all_runs = text_runs(document, markup)
    runs = tuple(run for run in all_runs if run.text.strip())
    printed = plain_text(markup)
    if printed == '"' and all((run.name or "").casefold() in _MAESTRO_LAYOUT for run in runs):
        # Maestro's caesura; written as the two strokes it draws.
        printed = _CAESURA
    elif any(
        (run.name or "").casefold() in _NOTE_TEXT_FONTS or (run.is_music and len(runs) > 1)
        for run in runs
    ):
        spaced = text_runs(document, markup, keep_spaces=True)
        printed = re.sub(r"\s+", " ", readable_text(spaced)).strip() or printed
    return _Text(
        printed=printed,
        in_music_font=bool(runs) and all(run.is_music for run in runs),
        is_rehearsal=bool(_REHEARSAL.search(markup)),
        runs=all_runs,
    )
