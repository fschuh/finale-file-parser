"""Resolve the upper mordent shared by Finale's legacy music fonts.

Maestro, Engraver and Broadway Copyist document glyph 109 (``m``) as the
unstruck mordent. The PDF and performance MIDI in the local Scars investigation
independently show main/upper/main at all ten assignments. Evidence and the
MusicXML naming distinction are recorded in docs/ARCHITECTURE.md.
"""

from __future__ import annotations

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
        if "part" in record.attrs or "mainIsShape" in record.fields:
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
    for record in document.details.of_tag("articAssign"):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entry = field_int(record.attrs.get("entnum"))
        definition = field_int(record.fields.get("articDef"))
        if entry is None or definition is None or definition not in definitions:
            continue
        out.setdefault(entry, []).append(Ornament(kind=definitions[definition]))
    return {entry: tuple(items) for entry, items in out.items()}
