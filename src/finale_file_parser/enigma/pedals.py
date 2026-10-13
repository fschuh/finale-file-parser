"""Resolve only explicit, visible source music-font sustain pedal assignments."""

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names


def pedals_by_entry(document: EnigmaDocument) -> dict[int, tuple[str, ...]]:
    fonts = font_names(document)
    definitions = {}
    for record in document.others.of_tag("articDef"):
        if "part" in record.attrs or {"mainIsShape", "noPrint"}.intersection(record.fields):
            continue
        number = field_int(record.attrs.get("cmper"))
        font = field_int(record.fields.get("fontMain"))
        kind = {161: "start", 42: "stop"}.get(field_int(record.fields.get("charMain")) or -1)
        if (
            number is not None
            and font is not None
            and fonts.get(font, "").casefold() == "maestro"
            and kind is not None
        ):
            definitions[number] = kind
    result: dict[int, list[str]] = {}
    for assignment in document.details.of_tag("articAssign"):
        if "part" in assignment.attrs or "hide" in assignment.fields:
            continue
        entry = field_int(assignment.attrs.get("entnum"))
        kind = definitions.get(field_int(assignment.fields.get("articDef")) or -1)
        if entry is not None and kind is not None and kind not in result.get(entry, []):
            result.setdefault(entry, []).append(kind)
    return {entry: tuple(kinds) for entry, kinds in result.items()}
