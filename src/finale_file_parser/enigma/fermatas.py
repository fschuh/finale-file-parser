"""Resolve normal fermatas assigned through Finale's articulation records.

Maestro, Engraver and Broadway Copyist all use U (85) above the note and
u (117) below it. Only these independently documented legacy glyphs are
mapped; see docs/ARCHITECTURE.md for the charts and local binary evidence.
"""

from __future__ import annotations

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.ir import Fermata

__all__ = ["fermatas_by_entry"]

_FERMATA_GLYPHS = {85: Fermata(), 117: Fermata(inverted=True)}


def fermatas_by_entry(document: EnigmaDocument) -> dict[int, tuple[Fermata, ...]]:
    """Resolve visible score fermatas, excluding library-only and linked-part marks."""
    definitions: dict[int, Fermata] = {}
    for record in document.others.of_tag("articDef"):
        if "part" in record.attrs or "mainIsShape" in record.fields:
            continue
        definition = field_int(record.attrs.get("cmper"))
        character = field_int(record.fields.get("charMain"))
        if definition is not None and character is not None and character in _FERMATA_GLYPHS:
            definitions[definition] = _FERMATA_GLYPHS[character]

    out: dict[int, list[Fermata]] = {}
    for record in document.details.of_tag("articAssign"):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entry = field_int(record.attrs.get("entnum"))
        definition = field_int(record.fields.get("articDef"))
        if entry is None or definition is None or definition not in definitions:
            continue
        out.setdefault(entry, []).append(definitions[definition])
    return {entry: tuple(items) for entry, items in out.items()}
