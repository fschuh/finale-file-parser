"""Retain assigned parentheses without guessing optional chord-note attachments.

Maestro characters40/41 are matched glyphs. A compact pair on a single pitched
entry encloses its notehead. Chord notes, unusually wide spans and unmatched
glyphs retain drawing offsets for review, with no pitch or playback changes.
See ARCHITECTURE.md for positioning evidence and importer limitations.
"""

from dataclasses import replace
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import Parenthesis


def parentheses_by_entry(document: EnigmaDocument) -> dict[int, tuple[Parenthesis, ...]]:
    fonts = font_names(document)
    definitions = {
        field_int(r.attrs.get("cmper")): r
        for r in document.others.of_tag("articDef")
        if "part" not in r.attrs
        and "mainIsShape" not in r.fields
        and "noPrint" not in r.fields
        and "noPrint" not in r.fields
        and field_int(r.fields.get("charMain")) in {40, 41}
        and fonts.get(field_int(r.fields.get("fontMain")) or 0, "").casefold() == "maestro"
    }
    result: dict[int, list[Parenthesis]] = {}
    seen = set()
    for r in document.details.of_tag("articAssign"):
        if "part" in r.attrs or "hide" in r.fields:
            continue
        entry = field_int(r.attrs.get("entnum"))
        definition = definitions.get(field_int(r.fields.get("articDef")))
        if entry is None or definition is None:
            continue
        side = "left" if field_int(definition.fields.get("charMain")) == 40 else "right"
        x = _offset(r, "horzOff") + _offset(definition, "xOffsetMain")
        y = _offset(r, "vertOff") + _offset(definition, "yOffsetMain")
        mark = Parenthesis(side, Fraction(x, 24), Fraction(y, 24))
        if (entry, mark) not in seen:
            seen.add((entry, mark))
            result.setdefault(entry, []).append(mark)
    return {entry: _resolve_pair(document, entry, marks) for entry, marks in result.items()}


def _offset(record: Record, name: str) -> int:
    value = record.fields.get(name)
    if value is None:
        return 0
    result = field_int(value)
    if result is None:
        raise CorruptScoreError(f"{record.tag}: invalid parenthesis {name}")
    return result


def _resolve_pair(
    document: EnigmaDocument, entry: int, marks: list[Parenthesis]
) -> tuple[Parenthesis, ...]:
    source = document.entries.get(entry)
    if source is None or field_int(source.fields.get("numNotes")) != 1 or len(marks) != 2:
        return tuple(marks)
    left = next((m for m in marks if m.side == "left"), None)
    right = next((m for m in marks if m.side == "right"), None)
    if (
        left is not None
        and right is not None
        and left.x_offset < 0 < right.x_offset
        and abs(left.x_offset + right.x_offset) <= 1
        and left.y_offset == right.y_offset
    ):
        return tuple(replace(m, pitch_index=0) for m in marks)
    return tuple(marks)
