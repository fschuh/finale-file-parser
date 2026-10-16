"""The title block as page one prints it: title, subtitle, composer, arranger, copyright.

File Info alone is not what a reader sees. NinSheetMusic templates leave
placeholders there ("Title", "Game", "Arranged by ...") and type the real text on
the page, or splice literal words around a File Info insert -- Spring Yard's
title block is `^title()"` around a File Info title that lacks its closing quote.
So each page-one text block is rendered as printed, inserts replaced by their File
Info text, and every printed line is given a role.

Insert codes in a `.mus` text stream (`^legacycmd(NN,)`), placed by where each
sits on the corpus pages and matched to the PDFs: 0x99 title, 0xA3 subtitle, 0x8A
composer, 0xA2 arranger, 0x8B copyright. EnigmaXML spells them `^title()` and so
on. A line without an insert is classified by its words: a copyright sign or web
address is the copyright, "Composed by"/"Music by" a composer credit, "Arranged
by"/"Edited by" an arranger credit, a line opening with "&" or "and" continues the
credit above it, and otherwise the title block's first line is the title and any
further centred line the subtitle.
"""

from __future__ import annotations

import re

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.text import file_info, plain_text, text_block

__all__ = ["page_header", "page_notes"]

_INSERTS = {
    "99": "title",
    "A3": "subtitle",
    "8A": "composer",
    "A2": "arranger",
    "8B": "copyright",
    "title": "title",
    "subtitle": "subtitle",
    "composer": "composer",
    "arranger": "arranger",
    "copyright": "copyright",
}
_INSERT = re.compile(
    r"\^legacycmd\((99|A3|8A|A2|8B),\)|\^(title|subtitle|composer|arranger|copyright)\(\)"
)
_SIZE = re.compile(r"\^legacycmd\(86,([0-9a-f]{4,})\)|\^size\((\d+)\)")
_COPYRIGHT = re.compile(r"©|\bhttps?://|\bwww\.", re.IGNORECASE)
_COMPOSER = re.compile(r"^(composed|composition|music|written)\b", re.IGNORECASE)
_ARRANGER = re.compile(r"^(arranged|arrangement|arr\.|edited|transcribed)\b", re.IGNORECASE)
_CONTINUES = re.compile(r"^(&|and\b)", re.IGNORECASE)
_TEMPO = re.compile(r"=\s*\d")
_MARK = "\x00"
_TOP_CENTRED = 40
"""The placement every corpus title and subtitle block uses (centred, page top)."""
_NEAR_TITLE = -400
"""EVPU below the top within which an uncentred block can still be the subtitle
(Zelda Title's at -114); performance notes sit thousands of EVPU lower."""


def page_header(document: EnigmaDocument) -> dict[str, str]:
    """Roles -> printed text for page one; File Info fills any role the page lacks."""
    info = file_info(document)
    blocks: list[tuple[str, int, int]] = []  # markup, placement flags, vertical offset
    for record in document.others.of_tag("pageTextAssign"):
        if "part" in record.attrs or "postIt" in record.fields:
            continue
        page, start = (
            field_int(record.attrs.get("cmper")),
            field_int(record.fields.get("startPage")),
        )
        if page != 1 and start != 1:
            continue
        number = field_int(record.fields.get("block"))
        markup = text_block(document, number) if number else None
        if markup:
            blocks.append(
                (
                    markup,
                    field_int(record.attrs.get("sourceFlags")) or 0,
                    field_int(record.fields.get("ydisp")) or 0,
                )
            )
    title_block = next(
        (i for i, (markup, _, _) in enumerate(blocks) if "title" in _insert_roles(markup)), None
    )
    if title_block is None and blocks:
        title_block = max(range(len(blocks)), key=lambda i: _size(blocks[i][0]))
    result: dict[str, list[str]] = {}
    candidates: list[tuple[int, str]] = []  # (vertical offset, line) for the subtitle
    for index, (markup, flags, offset) in enumerate(blocks):
        role_before: str | None = None
        for line, hint in _lines(markup, info):
            role = hint or _role(line)
            if role is None and _CONTINUES.match(line) and role_before in {"composer", "arranger"}:
                role = role_before
            if role is None and not _TEMPO.search(line):
                if index == title_block and "title" not in result:
                    role = "title"
                elif index == title_block or role_before in {"title", "subtitle"}:
                    role = "subtitle"
                elif flags == _TOP_CENTRED or (flags == 0 and _NEAR_TITLE < offset <= 0):
                    candidates.append((offset, line))
            if role is None:
                continue
            result.setdefault(role, []).append(line)
            role_before = role
    if "subtitle" not in result and candidates:
        # The centred line nearest the top: a game name typed in its own block.
        result["subtitle"] = [max(candidates)[1]]
    out = {role: "\n".join(lines) for role, lines in result.items()}
    for role in ("title", "subtitle", "composer", "arranger", "copyright"):
        if role not in out and info.get(role):
            out[role] = info[role].replace("\r\n", "\n").replace("\r", "\n")
    return out


_PAGE_NOTE = 256
"""A text placed by page coordinates alone (Memories of Green's performance notes)."""


def page_notes(document: EnigmaDocument) -> tuple[tuple[int, str], ...]:
    """(page, text) for page-placed performance notes that are not title-block text."""
    info = file_info(document)
    out = []
    for record in document.others.of_tag("pageTextAssign"):
        if "part" in record.attrs or "postIt" in record.fields:
            continue
        page = field_int(record.attrs.get("cmper"))
        if not page or field_int(record.attrs.get("sourceFlags")) != _PAGE_NOTE:
            continue
        number = field_int(record.fields.get("block"))
        markup = text_block(document, number) if number else None
        if not markup:
            continue
        lines = _lines(markup, info)
        if not lines or any(hint or _role(line) or _TEMPO.search(line) for line, hint in lines):
            continue
        out.append((page, " ".join(line for line, _ in lines)))
    return tuple(out)


def _insert_roles(markup: str) -> set[str]:
    return {_INSERTS[m.group(1) or m.group(2)] for m in _INSERT.finditer(markup)}


def _size(markup: str) -> int:
    found = [int(a[-4:], 16) if a else int(b) * 32 for a, b in _SIZE.findall(markup)]
    return max(found, default=0)


def _lines(markup: str, info: dict[str, str]) -> list[tuple[str, str | None]]:
    """Printed lines, each with the role of the insert it came from, if any."""

    def expand(match: re.Match[str]) -> str:
        role = _INSERTS[match.group(1) or match.group(2)]
        text = info.get(role, "").replace("\r\n", "\n").replace("\r", "\n")
        # Mark every line of the insert so the role survives the split below.
        return "\n".join(f"{_MARK}{role}{_MARK}{part}" for part in text.split("\n"))

    printed = _INSERT.sub(expand, markup).replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for raw in printed.split("\n"):
        hint = None
        found = re.search(f"{_MARK}([a-z]+){_MARK}", raw)
        if found:
            hint = found.group(1)
            raw = re.sub(f"{_MARK}[a-z]+{_MARK}", "", raw)
        line = re.sub(r"\s+", " ", plain_text(raw)).strip()
        if line:
            out.append((line, hint))
    return out


def _role(line: str) -> str | None:
    if _COPYRIGHT.search(line):
        return "copyright"
    if _COMPOSER.match(line):
        return "composer"
    if _ARRANGER.match(line):
        return "arranger"
    return None
