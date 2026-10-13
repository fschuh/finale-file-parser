"""Resolve the upper mordent shared by Finale's legacy music fonts.

Maestro, Engraver and Broadway Copyist document glyph 109 (``m``) as the
unstruck mordent. The PDF and performance MIDI in the local Scars investigation
independently show main/upper/main at all ten assignments. Evidence and the
MusicXML naming distinction are recorded in docs/ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import replace

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.ir import Ornament

__all__ = ["ornaments_by_entry"]

_UPPER_MORDENT = 109
_TRILL = 217


def ornaments_by_entry(document: EnigmaDocument) -> dict[int, tuple[Ornament, ...]]:
    """Only visible score ornaments; unknown glyphs and linked-part overrides stay out."""
    fonts = font_names(document)
    definitions: dict[int, str] = {}
    for record in document.others.of_tag("articDef"):
        if "part" in record.attrs or {"mainIsShape", "noPrint"}.intersection(record.fields):
            continue
        number = field_int(record.attrs.get("cmper"))
        character = field_int(record.fields.get("charMain"))
        font = field_int(record.fields.get("fontMain"))
        if number is None:
            continue
        if character == _UPPER_MORDENT:
            definitions[number] = "upper-mordent"
        elif (
            character == _TRILL and font is not None and fonts.get(font, "").casefold() == "maestro"
        ):
            definitions[number] = "trill"
    out: dict[int, list[Ornament]] = {}
    assignments: dict[int, list[tuple[int, int]]] = {}
    small_accidentals: dict[int, int] = {}
    for record in document.others.of_tag("articDef"):
        if "part" in record.attrs or {"mainIsShape", "noPrint"}.intersection(record.fields):
            continue
        number = field_int(record.attrs.get("cmper"))
        font = field_int(record.fields.get("fontMain"))
        accidental = {105: -1, 73: 1, 233: 0}.get(field_int(record.fields.get("charMain")) or -1)
        if (
            number is not None
            and font is not None
            and fonts.get(font, "").casefold() == "maestro"
            and accidental is not None
        ):
            small_accidentals[number] = accidental
    for record in document.details.of_tag("articAssign"):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entry = field_int(record.attrs.get("entnum"))
        definition = field_int(record.fields.get("articDef"))
        if entry is None or definition is None:
            continue
        if definition in definitions or definition in small_accidentals:
            assignments.setdefault(entry, []).append(
                (definition, field_int(record.fields.get("vertOff")) or 0)
            )
        if definition in definitions:
            out.setdefault(entry, []).append(Ornament(kind=definitions[definition]))
    for entry, marks in out.items():
        rows = assignments[entry]
        auxiliaries = [
            (small_accidentals[number], vertical)
            for number, vertical in rows
            if number in small_accidentals
        ]
        ornament_positions = [vertical for number, vertical in rows if number in definitions]
        # Same-entry, unique, small music-font accidental drawn above the
        # ornament: do not steal a main-note accidental or guess between ornaments.
        if len(marks) == len(auxiliaries) == 1 and auxiliaries[0][1] > ornament_positions[0]:
            out[entry] = [replace(marks[0], auxiliary_alteration=auxiliaries[0][0])]
    return {entry: tuple(items) for entry, items in out.items()}
