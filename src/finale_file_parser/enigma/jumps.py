"""Resolve placed text repeats independently of the unused definition palette.

Both normalized MUSX and evidenced numeric MUS records use assignment -> font
definition/text. Playback target, trigger and pass conditions are retained
separately from printed words. Known segno/coda characters require their font;
unknown glyphs remain in canonical navigation rather than becoming guessed signs.
The legacy words-only helper remains available for existing consumers.
"""

from __future__ import annotations

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import text_runs
from finale_file_parser.enigma.text import plain_text
from finale_file_parser.ir import Navigation, RepeatPlayback

__all__ = ["jumps_by_measure", "navigation_by_measure"]

_ASSIGN = "textRepeatAssign"
_TEXT = "textRepeatText"

_MAX_GLYPH = 2
"""A marking this short and not alphanumeric is a music-font character rather
than words -- `%` for the segno. See the module docstring."""


def navigation_by_measure(document: EnigmaDocument) -> dict[int, tuple[Navigation, ...]]:
    """Resolve only placed marks, retaining hidden marks' independent controls."""
    texts = {
        field_int(r.attrs.get("cmper")): plain_text(str(r.fields.get("rptText", ""))).strip()
        for r in document.others.of_tag(_TEXT)
        if "part" not in r.attrs
    }
    definitions = {
        field_int(r.attrs.get("cmper")): r
        for r in document.others.of_tag("textRepeatDef")
        if "part" not in r.attrs
    }
    result: dict[int, list[Navigation]] = {}
    for record in document.others.of_tag(_ASSIGN):
        if "part" in record.attrs:
            continue
        number = field_int(record.attrs.get("cmper"))
        repnum = field_int(record.fields.get("repnum"))
        if number is None or repnum is None:
            continue
        text = texts.get(repnum, "")
        definition = definitions.get(repnum)
        kind = "words"
        if definition is not None:
            font = field_int(definition.fields.get("fontID"))
            runs = text_runs(document, f"^fontid({font}){text}") if font is not None else ()
            if runs and all(run.is_music for run in runs):
                names = {run.name.casefold() if run.name else "" for run in runs}
                kind = "unknown-glyph"
                if text == "%" and names <= {"maestro", "engraverfontset", "engraver font set"}:
                    kind = "segno"
                elif text == "Þ" and names == {"maestro"}:
                    kind = "coda"
            replacement = definition.fields.get("poundReplace")
            if "#" in text and replacement in {"measNum", "repeatID", "passes"}:
                field = "actuate" if replacement == "passes" else "target"
                value = field_int(record.fields.get(field))
                if value is not None:
                    text = text.replace("#", str(value))
        elif _is_glyph(text):
            kind = "unknown-glyph"
        action = record.fields.get("action")
        playback = None
        if isinstance(action, str):
            playback = RepeatPlayback(
                action=action,
                trigger=str(record.fields.get("trigger", "always")),
                target=field_int(record.fields.get("target")) or 0,
                passes=field_int(record.fields.get("actuate")) or 0,
                reset_on_action="clrOnChange" in record.fields,
            )
        if text or playback is not None:
            result.setdefault(number, []).append(
                Navigation(text, kind, f"repeat-{repnum}", playback, "hidden" not in record.fields)
            )
    return {number: tuple(marks) for number, marks in result.items()}


def jumps_by_measure(document: EnigmaDocument) -> dict[int, tuple[str, ...]]:
    """The words each measure carries, keyed by measure number.

    A measure can hold more than one, and order follows the document.
    """
    out = {}
    for number, marks in navigation_by_measure(document).items():
        words = tuple(
            mark.text for mark in marks if mark.visible and mark.kind == "words" and mark.text
        )
        if words:
            out[number] = words
    return out


def _is_glyph(text: str) -> bool:
    return len(text) <= _MAX_GLYPH and not any(character.isalnum() for character in text)
