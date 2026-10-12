"""Resolve a document's articulations: which marks sit on which entry.

Two records, as usual. An `articAssign` entry detail names an `articDef`, and
the definition says what the mark *is* -- not by name, but as a **character in a
music font**:

    articAssign(entnum) -> articDef -> charMain

So the meaning has to come from the character, the way `clef.py` reads a clef
from `clefChar`. The characters below sit at the same ASCII positions in every
music font the corpus uses -- Maestro, Engraver Font Set and Broadway Copyist
each write staccato as `.`, accent as `>`, tenuto as `-` and marcato as `^` --
which is what makes reading them without resolving the font defensible.

The same fonts also use characters 249 and 223 for an accent combined with
staccato. Each of those expands to both MusicXML articulation names; their
above/below variants do not change the meaning. See ARCHITECTURE for the charts.

**Anything outside the evidenced mappings produces nothing.** The corpus assigns 29 distinct
characters, and the rest are either marks with no MusicXML equivalent or
symbols this project has no evidence for. Emitting a guess would put a wrong
articulation on a note, which is worse than leaving the note bare.

Fingerings have a separate resolver; numeral glyphs do not become articulation
names here.
"""

from __future__ import annotations

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names

__all__ = ["ARTICULATION_CHARACTERS", "articulations_by_entry"]

_ASSIGN = "articAssign"
_DEFINITION = "articDef"

ARTICULATION_CHARACTERS = {
    46: "staccato",  # .
    62: "accent",  # >
    45: "tenuto",  # -
    94: "strong-accent",  # ^  (marcato)
    44: "breath-mark",  # ,
    34: "caesura",  # double quote (railroad tracks)
}
"""Music-font character -> MusicXML articulation element.

Ordered by how often the corpus uses them: staccato 6,594, accent 3,123, tenuto
845, marcato 138, breath mark 54 in a 150-document sample. That ranking is what
you would expect of this repertoire, which corroborates the reading without
proving it -- the characters' meaning comes from the fonts' shared layout, not
from the corpus.

`breath-mark` is the least certain of the five and the rarest; it is included
because a comma is the breath mark in every music font here.
"""

_COMBINED_ARTICULATIONS = {
    249: ("accent", "staccato"),  # above-note form
    223: ("accent", "staccato"),  # below-note form
}
"""Cross-font combined glyphs; see the chart evidence in ARCHITECTURE."""


def _articulation_names(character: int, font: str = "") -> tuple[str, ...]:
    if font.casefold() == "maestro" and character in {248, 60}:
        return ("tenuto", "staccato")
    if font.casefold() == "maestro":
        if character in {171, 216}:
            return ("strong-accent" if character == 171 else "strong-accent-down",)
        if character in {172, 232}:
            return ("strong-accent" if character == 172 else "strong-accent-down", "staccato")
    name = ARTICULATION_CHARACTERS.get(character)
    return (name,) if name is not None else _COMBINED_ARTICULATIONS.get(character, ())


def articulations_by_entry(document: EnigmaDocument) -> dict[int, tuple[str, ...]]:
    """MusicXML articulation names, grouped by the entry they are attached to.

    An entry can carry several -- a staccato and an accent, say -- and order
    follows the document, expanding a combined glyph at its assignment. A
    `.mus` repeats one assignment 23 times in the corpus, which its reader
    drops as a storage artifact. This layer does not collapse distinct source
    assignments.
    """
    definitions = _definitions(document)
    out: dict[int, list[str]] = {}
    for record in document.details.of_tag(_ASSIGN):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entnum = field_int(record.attrs.get("entnum"))
        definition = field_int(record.fields.get(_DEFINITION))
        if entnum is None or definition is None:
            continue
        names = definitions.get(definition, ())
        if not names:
            continue
        out.setdefault(entnum, []).extend(names)
    return {entnum: tuple(names) for entnum, names in out.items()}


def _definitions(document: EnigmaDocument) -> dict[int, tuple[str, ...]]:
    """articDef cmper -> meanings established for its main character and font."""
    fonts = font_names(document)
    out: dict[int, tuple[str, ...]] = {}
    for record in document.others.of_tag(_DEFINITION):
        if "part" in record.attrs or "mainIsShape" in record.fields:
            continue
        cmper = field_int(record.attrs.get("cmper"))
        character = field_int(record.fields.get("charMain"))
        if cmper is not None and character is not None:
            font = field_int(record.fields.get("fontMain"))
            out[cmper] = _articulation_names(
                character, fonts.get(font, "") if font is not None else ""
            )
    return out
