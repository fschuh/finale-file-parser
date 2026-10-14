"""Simple source decimal measure labels, independent of measure identities."""

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import ScoreDiagnostic


def measure_labels(
    document: EnigmaDocument, numbers: list[int]
) -> tuple[dict[int, str], tuple[ScoreDiagnostic, ...]]:
    records = tuple(
        r for r in document.others.of_tag("measNumbRegion") if r.attrs.get("part", "0") == "0"
    )
    if not records:
        return {}, ()
    if len(records) > 256:
        raise CorruptScoreError("measure numbering exceeds the region limit")
    regions: list[tuple[int, int, int] | None] = []
    bounds: list[tuple[int, int]] = []
    diagnostics = []
    for record in records:
        typed_flags = sum(
            bit
            for name, bit in (("countFromOne", 128), ("doubleUp", 32), ("noZero", 64), ("time", 16))
            if name in record.fields
        )
        typed_affixes = int(bool(record.fields.get("prefix") or record.fields.get("suffix")))
        defaults = {
            "startMeas": None,
            "endMeas": None,
            "startChar": "0",
            "base": "0",
            "offset": "0",
            "numberFlags": str(typed_flags),
            "hasAffixes": str(typed_affixes),
        }
        values = {
            name: field_int(record.fields.get(name, default)) for name, default in defaults.items()
        }
        if any(v is None for v in values.values()):
            raise CorruptScoreError("measNumbRegion: invalid scalar")
        start, end, offset = values["startMeas"], values["endMeas"], values["offset"]
        assert start is not None and end is not None and offset is not None
        if not 1 <= start < end <= 32767 or not -32768 <= offset <= 32767:
            raise CorruptScoreError("measNumbRegion: invalid range or number offset")
        bounds.append((start, end))
        flags = values["numberFlags"]
        assert flags is not None
        supported = (
            values["startChar"] == 48
            and values["base"] == 10
            and flags & ~2 == 0x80
            and not values["hasAffixes"]
        )
        regions.append((start, end, offset) if supported else None)
        if not supported:
            diagnostics.append(
                ScoreDiagnostic(
                    "measure-numbering",
                    "Source measure numbering uses an unsupported character, affix or time "
                    "policy; its label is not guessed.",
                    f"measNumbRegion:{record.attrs.get('cmper', '')}",
                )
            )
    excluded = {
        int(r.attrs["cmper"])
        for r in document.others.of_tag("measSpec")
        if r.attrs.get("part", "0") == "0" and "noMeasNum" in r.fields
    }
    result: dict[int, str] = {}
    skipped = [0] * len(regions)
    for number in numbers:
        selected = next((i for i, (start, end) in enumerate(bounds) if start <= number < end), None)
        if selected is None:
            result[number] = ""
            continue
        region = regions[selected]
        if region is None:
            continue
        if number in excluded:
            skipped[selected] += 1
            result[number] = ""
        else:
            result[number] = str(number - region[0] + region[2] + 1 - skipped[selected])
    return result, tuple(diagnostics)
