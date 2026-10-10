"""Resolve Finale's global and individual slash settings after grace beaming."""

from __future__ import annotations

from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument
from finale_file_parser.ir import Event

__all__ = ["grace_slash", "slash_flagged_grace_notes"]


def slash_flagged_grace_notes(document: EnigmaDocument) -> bool | None:
    """None means the setting is unavailable; an omitted XML boolean is false."""
    for record in document.options.of_tag("graceNoteOptions"):
        if "part" not in record.attrs:
            return "slashFlaggedGraceNotes" in record.fields
    return None


def grace_slash(event: Event, always_slash: bool | None) -> bool | None:
    """Finale slashes only flagged graces, enabled globally or individually.

    A beam or a quarter-note (or longer) value has no flag to slash. Neither the
    individual setting nor the global setting forces a slash on those notes.
    """
    if not event.is_grace:
        return None
    base = event.written_duration * (1 << event.dots) / ((1 << (event.dots + 1)) - 1)
    if event.is_rest or event.beams or base <= 0 or base >= Fraction(1, 4):
        return False
    return True if event.grace_slash else always_slash
