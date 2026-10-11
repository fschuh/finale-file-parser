"""Clefs: the definition table, and which clef is in force where.

Enigma keeps a document-wide table of clef definitions (`clefOptions.clefDef`,
18 entries) and refers to them by index:

* `staffSpec.defaultClef` -- the staff's clef, omitted when it is 0.
* `gfhold.clefID` -- the initial clef at that (staff, measure).
* `gfhold.clefListID` -- a list of `clefEnum` records with exact EDU positions.

The original paired corpus had only literal clefs. Change lists also occur in
legacy scores; their first element supplies the initial clef and their final
element supplies the clef inherited by a following measure without a holder.

A definition gives a font character (`clefChar`) plus staff placement, or, when
`isShape` is set, a drawn shape instead of a character.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record
from finale_file_parser.enigma.models import CorruptScoreError

__all__ = [
    "Clef",
    "ClefSign",
    "clef_definitions",
    "clefs_by_measure",
    "clef_changes_by_measure",
    "default_clefs",
]

_CLEF_OPTIONS = "clefOptions"
_CLEF_DEF = "clefDef"
_STAFF_SPEC = "staffSpec"
_GFHOLD = "gfhold"


class ClefSign(Enum):
    """What kind of clef a definition draws.

    Derived from the Maestro font character. Only G and F are *confirmed by use*
    in the corpus, which exercises clef indices 0, 3 and 16 only; C and the other
    characters appear in the definition table but no staff selects them, so their
    mapping is from the font's layout rather than from observed data. Anything
    unrecognised stays UNKNOWN rather than being guessed into a wrong clef.
    """

    G = "G"
    F = "F"
    C = "C"
    SHAPE = "shape"
    """Drawn from a shape rather than a character -- percussion, in practice."""
    UNKNOWN = "unknown"


_CHARACTER_SIGNS = {
    38: ClefSign.G,
    63: ClefSign.F,
    66: ClefSign.C,
}
"""Maestro characters: '&' treble, '?' bass, 'B' the C clef. Confirmed for 38 and
63, which are the only characters any corpus staff actually selects."""


@dataclass(frozen=True)
class Clef:
    """One entry in the document's clef table."""

    index: int
    clef_char: int | None
    """Maestro font character, or None for a shape clef."""

    adjust: int
    """Staff-position offset for the clef's placement."""

    y_displacement: int
    shape_id: int | None
    """Set instead of `clef_char` when the clef is drawn as a shape."""

    @property
    def is_shape(self) -> bool:
        return self.shape_id is not None

    @property
    def sign(self) -> ClefSign:
        if self.is_shape:
            return ClefSign.SHAPE
        if self.clef_char is None:
            return ClefSign.UNKNOWN
        return _CHARACTER_SIGNS.get(self.clef_char, ClefSign.UNKNOWN)


def _optional_int(record: Record, name: str) -> int | None:
    """A numeric field, or None when absent.

    Absent is meaningful here: EnigmaXML omits a field rather than writing 0, so
    `adjust` missing means 0 while `clefChar` missing means there is no character.
    """
    raw = record.fields.get(name)
    if not isinstance(raw, str) or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise CorruptScoreError(f"clefDef {name}={raw!r} is not an integer") from exc


def clef_definitions(document: EnigmaDocument) -> dict[int, Clef]:
    """The document's clef table, keyed by index.

    Returns an empty mapping when the document defines no `clefOptions`.
    """
    options = [r for r in document.options.of_tag(_CLEF_OPTIONS) if "part" not in r.attrs]
    if not options:
        return {}
    raw = options[0].fields.get(_CLEF_DEF)
    definitions = raw if isinstance(raw, tuple) else (raw,) if isinstance(raw, Record) else ()
    out: dict[int, Clef] = {}
    for index, record in enumerate(definitions):
        if not isinstance(record, Record):
            continue
        out[index] = Clef(
            index=index,
            clef_char=_optional_int(record, "clefChar"),
            adjust=_optional_int(record, "adjust") or 0,
            y_displacement=_optional_int(record, "clefYDisp") or 0,
            shape_id=_optional_int(record, "shapeID"),
        )
    return out


def default_clefs(document: EnigmaDocument) -> dict[int, int]:
    """Each staff's default clef index, keyed by staff number.

    `defaultClef` is omitted when it is 0 (treble), so an absent field is reported
    as 0 rather than skipped -- dropping those staves would lose every
    treble-clef staff in the document.
    """
    out: dict[int, int] = {}
    for record in document.others.of_tag(_STAFF_SPEC):
        if "part" in record.attrs:
            continue
        raw = record.attrs.get("cmper")
        if raw is None:
            raise CorruptScoreError("staffSpec has no cmper")
        out[int(raw)] = _optional_int(record, "defaultClef") or 0
    return out


def clefs_by_measure(document: EnigmaDocument) -> dict[tuple[int, int], int]:
    """Effective clef index at each (staff, measure).

    Taken from `gfhold.clefID` or the first element of its change list. A holder
    without either falls back to the staff's default rather than being dropped.
    """
    defaults = default_clefs(document)
    changes = clef_changes_by_measure(document)
    out: dict[tuple[int, int], int] = {}
    for record in document.details.of_tag(_GFHOLD):
        if "part" in record.attrs:
            continue
        staff = int(record.attrs["cmper1"])
        measure = int(record.attrs["cmper2"])
        clef = _optional_int(record, "clefID")
        if (staff, measure) in changes:
            clef = changes[staff, measure][0].index
        out[(staff, measure)] = defaults.get(staff, 0) if clef is None else clef
    return out


@dataclass(frozen=True)
class ClefPosition:
    offset: Fraction
    index: int
    visible: bool = True


def clef_changes_by_measure(
    document: EnigmaDocument,
) -> dict[tuple[int, int], tuple[ClefPosition, ...]]:
    """Resolve score clef lists, ordered by incidence and measured in whole notes."""
    lists: dict[int, list[tuple[int, ClefPosition]]] = {}
    for record in document.others.of_tag("clefEnum"):
        if "part" in record.attrs:
            continue
        try:
            number = int(record.attrs["cmper"])
            inci = int(record.attrs.get("inci", "0"))
            clef = int(str(record.fields.get("clef", "0")))
            edu = int(str(record.fields.get("xEduPos", "0")))
        except (ValueError, KeyError) as exc:
            raise CorruptScoreError("clefEnum: invalid identity or position") from exc
        if number <= 0 or inci < 0 or clef < 0 or not 0 <= edu < (1 << 31):
            raise CorruptScoreError("clefEnum: invalid clef or position")
        lists.setdefault(number, []).append(
            (
                inci,
                ClefPosition(Fraction(edu, 4096), clef, record.fields.get("clefMode") != "hidden"),
            )
        )
    out = {}
    for holder in document.details.of_tag(_GFHOLD):
        if "part" in holder.attrs or "clefListID" not in holder.fields:
            continue
        list_id = _optional_int(holder, "clefListID")
        changes = tuple(
            change for _, change in sorted(lists.get(list_id or 0, []), key=lambda row: row[0])
        )
        if (
            not changes
            or changes[0].offset != 0
            or any(
                right.offset <= left.offset
                for left, right in zip(changes, changes[1:], strict=False)
            )
        ):
            raise CorruptScoreError(f"gfhold: missing or unordered clef list {list_id}")
        if "clefID" in holder.fields:
            raise CorruptScoreError("gfhold: both clefID and clefListID")
        out[int(holder.attrs["cmper1"]), int(holder.attrs["cmper2"])] = changes
    return out
