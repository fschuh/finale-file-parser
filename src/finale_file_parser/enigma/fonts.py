"""Resolve the font active on each literal text run, including legacy commands."""

import re
from dataclasses import dataclass

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError
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


def text_runs(document: EnigmaDocument, markup: str) -> tuple[FontRun, ...]:
    fonts = font_names(document)
    result: list[FontRun] = []
    name: str | None = None
    is_music = False
    cursor = 0
    for command in _COMMAND.finditer(markup):
        literal = plain_text(markup[cursor : command.start()])
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
    literal = plain_text(markup[cursor:])
    if literal:
        result.append(FontRun(literal, name, is_music))
    return tuple(result)
