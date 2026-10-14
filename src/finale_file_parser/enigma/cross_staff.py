"""Recover explicitly flagged per-note cross-staff destinations."""

from collections import defaultdict

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.location import RESERVED_STAFF
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.ir import CrossStaff


def cross_staff_by_entry(document: EnigmaDocument) -> dict[int, tuple[CrossStaff, ...]]:
    staves = {
        field_int(r.attrs.get("cmper"))
        for r in document.others.of_tag("staffSpec")
        if "part" not in r.attrs
    } - {None, RESERVED_STAFF}
    destinations: dict[int, dict[int, int]] = defaultdict(dict)
    for record in document.details.of_tag("crossStaff"):
        if "part" in record.attrs:
            continue
        entnum = field_int(record.attrs.get("entnum"))
        if entnum is None:
            raise CorruptScoreError("cross-staff modification has an invalid entry")
        if document.entries.get(entnum) is None:
            continue
        note_id = field_int(record.fields.get("noteID"))
        staff = field_int(record.fields.get("staff"))
        if note_id is None or note_id <= 0:
            raise CorruptScoreError("cross-staff modification has an invalid note ID")
        if staff is None or staff <= 0 or staff not in staves:
            raise CorruptScoreError("cross-staff modification names a missing score staff")
        previous = destinations[entnum].get(note_id)
        if previous is not None and previous != staff:
            raise CorruptScoreError("conflicting cross-staff modifications for one note")
        destinations[entnum][note_id] = staff
    result = {}
    for record in document.entries.of_tag("entry"):
        entry = read_entry(record)
        assigned = destinations.get(entry.entnum, {})
        marks = []
        for index, note in enumerate(entry.notes):
            if not note.cross_staff:
                continue
            staff = assigned.get(note.note_id)
            if staff is None or sum(n.note_id == note.note_id for n in entry.notes) != 1:
                raise CorruptScoreError("cross-staff note has a missing or ambiguous attachment")
            marks.append(CrossStaff(index, f"P{staff}"))
        if marks:
            result[entry.entnum] = tuple(marks)
    return result
