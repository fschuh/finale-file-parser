"""Join assigned notehead glyphs to stable note IDs, with verified font mappings."""

from collections import defaultdict

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.ir import Notehead

_CROSS_FONTS = frozenset({"maestro", "engraverfontset", "engraver font set"})


def noteheads_by_entry(document: EnigmaDocument) -> dict[int, tuple[Notehead, ...]]:
    """Keep score assignments; linked parts and unassigned/dead entries place nothing."""
    fonts = font_names(document)
    result: dict[int, dict[int, Notehead]] = defaultdict(dict)
    for record in document.details.of_tag("noteheadMod"):
        if "part" in record.attrs:
            continue
        entnum = _required_int(record.attrs.get("entnum"), "entry")
        entry = document.entries.get(entnum)
        if entry is None:
            continue
        character = _required_int(record.fields.get("customChar"), "character")
        if not 0 <= character <= 0x10FFFF:
            raise CorruptScoreError("notehead character is outside the Unicode range")
        # Zero explicitly clears the glyph, leaving positioning/font-only data.
        if not character:
            continue
        note_id = _required_int(record.fields.get("noteID"), "note ID")
        indices = [i for i, note in enumerate(read_entry(entry).notes) if note.note_id == note_id]
        if note_id <= 0 or len(indices) != 1:
            raise CorruptScoreError("notehead modification has an invalid or ambiguous note ID")
        font_id = (
            _required_int(record.fields.get("fontID"), "font ID")
            if "useCustomFont" in record.fields
            else 0
        )
        font = fonts.get(font_id)
        shape = "x" if character == 192 and font and font.casefold() in _CROSS_FONTS else None
        index = indices[0]
        head = Notehead(index, shape, source_character=character, source_font=font)
        previous = result[entnum].get(index)
        if previous is not None and previous != head:
            raise CorruptScoreError("conflicting notehead modifications for one note")
        result[entnum][index] = head
    return {entry: tuple(heads.values()) for entry, heads in result.items()}


def _required_int(value: object, label: str) -> int:
    number = field_int(value)
    if number is None:
        raise CorruptScoreError(f"notehead modification has an invalid {label}")
    return number
