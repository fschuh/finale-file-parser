"""Resolve the font active on each literal text run, including legacy commands."""

import re
from dataclasses import dataclass

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_text import strip_compiled_commands
from finale_file_parser.enigma.text import plain_text

_COMMAND = re.compile(r"\^(?P<name>[A-Za-z]+)\((?P<args>[^)]*)\)")
_COMPILED_FONTS = frozenset({"85", "A4", "A5", "A6"})
_MUSIC_FONTS = frozenset({"maestro", "engraverfontset", "engraver font set", "jazz"})


@dataclass(frozen=True)
class FontRun:
    text: str
    name: str | None
    is_music: bool


def _compiled_id(arguments: str) -> int:
    try:
        raw = bytes.fromhex(arguments)
    except ValueError as error:
        raise CorruptScoreError("compiled font command has invalid argument bytes") from error
    if len(raw) != 4 or not all(1 <= value <= 16 for value in raw):
        raise CorruptScoreError("compiled font command requires four biased hexadecimal digits")
    number = 0
    for value in raw:
        number = number * 16 + value - 1
    return number


def font_names(document: EnigmaDocument) -> dict[int, str]:
    """Only score font IDs name the registry used by score definitions."""
    result = {}
    for record in document.others.of_tag("fontName"):
        number = field_int(record.attrs.get("cmper"))
        if "part" not in record.attrs and number is not None:
            result[number] = str(record.fields.get("name", ""))
    return result


def text_runs(
    document: EnigmaDocument, markup: str, *, keep_spaces: bool = False
) -> tuple[FontRun, ...]:
    """Literal runs with their fonts; `keep_spaces` keeps each run's edge spacing."""
    fonts = font_names(document)

    def literal_of(segment: str) -> str:
        if not keep_spaces:
            return plain_text(segment)
        return strip_compiled_commands(_COMMAND.sub("", segment))

    result: list[FontRun] = []
    name: str | None = None
    is_music = False
    cursor = 0
    for command in _COMMAND.finditer(markup):
        literal = literal_of(markup[cursor : command.start()])
        if literal:
            result.append(FontRun(literal, name, is_music))
        token, args = command["name"], command["args"]
        font_id: int | None = None
        explicit_music = False
        font_command = False
        if token == "legacycmd":
            opcode, separator, arguments = args.partition(",")
            if separator and opcode in _COMPILED_FONTS:
                font_id = _compiled_id(arguments)
                font_command = True
        elif token in {"font", "fontid", "fontMus", "fontTxt", "fontNum"}:
            font_command = True
            explicit_music = token == "fontMus"
            font_id = field_int(args.split(",", 1)[0])
            if font_id is None:
                name = args.split(",", 1)[0].strip()
        if font_command:
            if font_id is not None:
                name = fonts.get(font_id)
            is_music = explicit_music or bool(name and name.casefold() in _MUSIC_FONTS)
            if token == "fontTxt":
                is_music = False
        cursor = command.end()
    literal = literal_of(markup[cursor:])
    if literal:
        result.append(FontRun(literal, name, is_music))
    return tuple(result)


_NOTE_SYMBOLS = {
    "quarter": "♩",
    "eighth": "♪",
    "beamed": "♫",
    "half": "\U0001d15e",
    "whole": "\U0001d15d",
    "sixteenth": "\U0001d161",
}
_MAESTRO_TIMES = (
    # Finale's text-with-notes font: a quarter followed by the beam joiner draws a
    # beamed pair; Ç draws the small triplet "3" over the next note.
    ("ŒÂ", _NOTE_SYMBOLS["beamed"]),
    ("Œ", _NOTE_SYMBOLS["quarter"]),
    ("\uf0ce", _NOTE_SYMBOLS["quarter"]),
    ("Ó", _NOTE_SYMBOLS["half"]),
    ("‰", _NOTE_SYMBOLS["eighth"]),
    ("Ç", "³"),
)
_LETTER_NOTES = {
    "q": _NOTE_SYMBOLS["quarter"],
    "Q": _NOTE_SYMBOLS["quarter"],
    "e": _NOTE_SYMBOLS["eighth"],
    "E": _NOTE_SYMBOLS["eighth"],
    "h": _NOTE_SYMBOLS["half"],
    "H": _NOTE_SYMBOLS["half"],
    "w": _NOTE_SYMBOLS["whole"],
    "x": _NOTE_SYMBOLS["sixteenth"],
    "X": _NOTE_SYMBOLS["sixteenth"],
}
_ENGRAVER_TEXT = frozenset({"engravertextt", "engravertexth", "engravertextncs"})


def readable_text(runs: tuple[FontRun, ...]) -> str:
    """The runs as a reader sees them, note glyphs as Unicode note symbols.

    Text fonts that carry notes spell them with letters: MaestroTimes uses Œ Ó ‰
    for quarter, half and eighth; the EngraverText fonts and Maestro use q h e,
    with EngraverText's `d` as the dot. Those runs are translated so "q.=q" reads
    "♩.=♩". A run in Maestro or Engraver Font Set is translated only beside other
    text: a run that stands alone there is a dynamic or symbol glyph, read as such
    elsewhere.
    """
    alone = len([run for run in runs if run.text.strip()]) <= 1
    out = []
    for run in runs:
        name = (run.name or "").casefold()
        text = run.text
        if name == "maestrotimes":
            for glyph, symbol in _MAESTRO_TIMES:
                text = text.replace(glyph, symbol)
        elif name in _ENGRAVER_TEXT:
            text = re.sub(r"(?<=[qhewxQHEX])d", ".", text)
            text = "".join(_LETTER_NOTES.get(c, c) for c in text)
        elif run.is_music and not alone and re.fullmatch(r"[qQeEhHwxX.\s]+", text):
            text = "".join(_LETTER_NOTES.get(c, c) for c in text)
        out.append(text)
    return "".join(out)
