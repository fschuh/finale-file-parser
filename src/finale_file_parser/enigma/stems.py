"""Stem directions Finale fixes rather than computes.

Finale draws a stem in one of three ways. An entry whose stem was flipped by hand
carries FREEZSTEM with UPSTEMBIT giving the direction. Otherwise, when a layer's
Document Options freeze its stems and another layer of the same staff and measure
holds notes, the layer's direction applies (factory settings: layer 1 up, layer 2
down). Anything else is computed from the notes, which the consumer can do as
well as Finale. The stored UPSTEMBIT of an unfrozen entry is not reliable -- it is
"recomputed on the fly" (eeppd.txt) and is clear on most corpus up-stems -- so it
is never read on its own.
"""

from collections.abc import Sequence
from dataclasses import replace

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.ir import Event


def layer_stems(document: EnigmaDocument) -> dict[int, str]:
    """The fixed direction of each frozen layer, keyed 1-4."""
    result: dict[int, str] = {}
    for record in document.others.of_tag("layerAtts"):
        if "part" in record.attrs or "freezeLayer" not in record.fields:
            continue
        index = field_int(record.attrs.get("cmper"))
        if index is None or not 0 <= index <= 3:
            continue
        result[index + 1] = "up" if "upStems" in record.fields else "down"
    return result


def frozen_stem(record: Record) -> str | None:
    """A hand-set stem direction, or None when Finale computes it."""
    if "freezeStem" not in record.fields:
        return None
    return "up" if "upStem" in record.fields else "down"


def assign_stems(
    events_by_layer: dict[int, list[Event]], layers: dict[int, str]
) -> dict[int, list[Event]]:
    """Fill in the directions a beam group or a frozen layer fixes.

    Events arrive carrying only their own frozen direction. A beam group takes
    its first frozen member's direction, since one beam has one stem side; an
    event still unset then takes its layer's direction if that layer is frozen
    and another layer in the cell has notes.
    """
    noted = {
        layer
        for layer, events in events_by_layer.items()
        if any(e.pitches and not e.is_grace for e in events)
    }
    result: dict[int, list[Event]] = {}
    for layer, events in events_by_layer.items():
        fixed = layers.get(layer) if noted - {layer} else None
        directions = [e.stem for e in events]
        for group in _beam_groups(events):
            chosen = next((directions[i] for i in group if directions[i] is not None), None)
            if chosen is not None:
                for i in group:
                    directions[i] = directions[i] or chosen
        result[layer] = [
            replace(event, stem=direction or fixed)
            if event.pitches and not event.is_grace and (direction or fixed)
            else event
            for event, direction in zip(events, directions, strict=True)
        ]
    return result


def _beam_groups(events: Sequence[Event]) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] | None = None
    for index, event in enumerate(events):
        primary = next((b.type for b in event.beams if b.number == 1), None)
        if primary == "begin":
            current = [index]
        elif primary in {"continue", "end"} and current is not None:
            current.append(index)
            if primary == "end":
                groups.append(current)
                current = None
    return groups
