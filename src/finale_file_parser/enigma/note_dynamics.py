"""Resolve music-font dynamic glyphs assigned through the articulation pool."""

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.formats.dynamics import dynamic_for
from finale_file_parser.ir import Expression


def dynamics_by_entry(document: EnigmaDocument) -> dict[int, tuple[Expression, ...]]:
    fonts = font_names(document)
    definitions = {}
    for record in document.others.of_tag("articDef"):
        if "part" in record.attrs or {"mainIsShape", "noPrint"}.intersection(record.fields):
            continue
        number, font, char = (
            field_int(record.attrs.get("cmper")),
            field_int(record.fields.get("fontMain")),
            field_int(record.fields.get("charMain")),
        )
        if (
            number is None
            or font is None
            or fonts.get(font, "").casefold() != "maestro"
            or char is None
            or not 0 <= char <= 0x10FFFF
        ):
            continue
        dynamic = dynamic_for(chr(char))
        if dynamic is not None and dynamic.marking is not None:
            definitions[number] = Expression(chr(char), "", marking=dynamic.marking)
    out: dict[int, list[Expression]] = {}
    for record in document.details.of_tag("articAssign"):
        if "part" in record.attrs or "hide" in record.fields:
            continue
        entry = field_int(record.attrs.get("entnum"))
        mark = definitions.get(field_int(record.fields.get("articDef")) or -1)
        if entry is not None and mark is not None and mark not in out.get(entry, []):
            out.setdefault(entry, []).append(mark)
    return {entry: tuple(items) for entry, items in out.items()}
