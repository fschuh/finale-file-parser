"""Recover Finale's hidden-tuplet, custom-display two-note tremolo construction."""

from __future__ import annotations

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.enigma.tuplet import read_tuplet
from finale_file_parser.ir import SlurEndpoint, Tremolo


def recover_tremolos(
    document: EnigmaDocument, positions: dict[tuple[int, int, int], list[SlurEndpoint]]
) -> tuple[dict[int, int], dict[int, tuple[Tremolo, ...]]]:
    """Return true written values and exact spans; ordinary tuplets keep their meaning."""
    extensions: set[int] = set()
    heads: dict[int, set[int]] = {}
    fonts = font_names(document)
    for record in document.details.records:
        if "part" in record.attrs:
            continue
        entry = field_int(record.attrs.get("entnum"))
        if entry is None:
            continue
        if record.tag in {"beamExtUp", "beamExtDown"}:
            mask = field_int(record.fields.get("beamMask")) or 0
            left = field_int(record.fields.get("leftAdjust")) or 0
            right = field_int(record.fields.get("rightAdjust")) or 0
            if mask & 0x800 and mask & 0x380 == 0x380 and left > 0 > right:
                extensions.add(entry)
        if (
            record.tag == "noteheadMod"
            and "useCustomFont" not in record.fields
            and record.fields.get("customChar") == "250"
        ):
            note = field_int(record.fields.get("noteID"))
            if note is not None and fonts.get(0, "").casefold() in {
                "maestro",
                "engraverfontset",
                "engraver font set",
            }:
                heads.setdefault(entry, set()).add(note)
    written: dict[int, int] = {}
    spans: dict[int, list[Tremolo]] = {}
    for record in document.details.of_tag("tupletDef"):
        if (
            "part" in record.attrs
            or record.fields.get("numberStyle") != "0"
            or record.fields.get("brackStyle") != "0"
        ):
            continue
        number = field_int(record.attrs.get("entnum"))
        first = document.entries.get(number) if number is not None else None
        if first is None:
            continue
        tuplet = read_tuplet(record)
        if tuplet.ratio <= 1:
            continue
        partner = field_int(first.attrs.get("next"))
        second = document.entries.get(partner) if partner else None
        if second is None:
            if number in extensions:
                raise CorruptScoreError("tremolo display refers to a missing partner entry")
            continue
        assert number is not None and partner is not None
        a, b = read_entry(first), read_entry(second)
        short = a.duration.edu
        if short != 128 or b.duration.edu != short or tuplet.span != short * 2:
            continue
        if (
            not a.notes
            or not b.notes
            or "graceNote" in first.fields
            or "graceNote" in second.fields
        ):
            continue
        if "beam" not in first.fields or "beam" in second.fields:
            continue
        first_ids, last_ids = {note.note_id for note in a.notes}, {note.note_id for note in b.notes}
        half_heads = (
            0 not in first_ids | last_ids
            and heads.get(number, set()) == first_ids
            and heads.get(partner, set()) == last_ids
        )
        if number not in extensions and not half_heads:
            continue
        value = tuplet.reference_number * tuplet.reference_duration
        if half_heads and value != 2048:
            continue
        if number in written or partner in written:
            raise CorruptScoreError("overlapping tremolo pairs")
        written[number] = written[partner] = value
        for (staff, measure, entry), starts in positions.items():
            if entry != number:
                continue
            ends = positions.get((staff, measure, partner), [])
            for start in starts:
                end = SlurEndpoint(measure, start.voice, start.event_index + 1)
                if end not in ends:
                    raise CorruptScoreError("tremolo partner is not adjacent in the same voice")
                spans.setdefault(staff, []).append(Tremolo(start, end, 3))
    return written, {staff: tuple(items) for staff, items in spans.items()}
