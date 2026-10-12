"""Author source flags independently: sound and visibility must not be conflated."""

from fractions import Fraction

import pytest

from finale_file_parser.enigma.mus_entries import _entry_record
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.enigma.pitch import StaffTransposition
from finale_file_parser.enigma.to_ir import _event


@pytest.mark.parametrize("order", ["little", "big"])
@pytest.mark.parametrize(
    "playback, visible", [(True, True), (False, True), (True, False), (False, False)]
)
def test_source_sound_and_visibility_flags_preserve_pitch_rhythm_and_ties(
    order: ByteOrder, playback: bool, visible: bool
) -> None:
    slot = bytearray(38)
    fields = {
        0: (1, 4),
        14: (1024, 2),
        18: (0xC0000000 | (0 if visible else 0x8000), 4),
        22: (0x0100 | (0 if playback else 0x0400), 2),
        24: (1, 2),
        28: (0xC0010000, 4),
    }
    for at, (value, size) in fields.items():
        slot[at : at + size] = value.to_bytes(size, order)
    record = _entry_record(bytes(slot), 0, 1, order)
    entry = read_entry(record)
    event = _event(
        record=record,
        key_raw=0,
        transposition=StaffTransposition(0, 0),
        written_edu=1024,
        sounded_edu=Fraction(1024),
    )
    assert entry.playback is playback and event.playback is playback
    assert entry.visible is visible and event.visible is visible
    assert not event.is_rest and len(event.pitches) == 1
    assert event.duration == event.written_duration == Fraction(1, 4)
    assert event.note_ties[0].start
    assert "slashGrace" in record.fields
