"""Authored numeric repeat records and source trigger normalization."""

import struct

import pytest

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _repeat_back
from finale_file_parser.enigma.repeats import repeats_for
from finale_file_parser.ir import RepeatPlayback


@pytest.mark.parametrize(
    ("flags", "action", "trigger", "reset"),
    [
        (0x0800, "jumpAuto", "untilPass", False),
        (0x0414, "jumpAbsolute", "onPass", True),
        (0x0020, "jumpRelative", "always", False),
    ],
)
def test_serialized_flags_and_signed_target_preserve_their_independent_meaning(
    flags: int,
    action: str,
    trigger: str,
    reset: bool,
) -> None:
    payload = bytearray(24)
    struct.pack_into("<Hh", payload, 2, 3, -2)
    struct.pack_into("<H", payload, 10, flags)
    fields = _repeat_back(bytes(payload))
    assert (fields["action"], fields["trigger"], fields["target"], fields["actuate"]) == (
        action,
        trigger,
        "-2",
        "3",
    )
    assert ("clrOnChange" in fields) is reset


def test_unrecognized_flag_combinations_raise() -> None:
    payload = bytearray(24)
    struct.pack_into("<H", payload, 10, 0xC00)
    with pytest.raises(CorruptScoreError, match="unsupported target or trigger"):
        _repeat_back(bytes(payload))


def test_only_a_placed_backward_barline_gets_the_rule() -> None:
    doc = parse_enigma(b"""<finale><others>
      <measSpec cmper="2"><bacRepBar/></measSpec><measSpec cmper="3"/>
      <repeatBack cmper="2"><actuate>3</actuate><action>jumpAbsolute</action>
        <target>1</target><trigger>untilPass</trigger><clrOnChange/></repeatBack>
      <repeatBack cmper="3"><action>jumpAbsolute</action><target>99</target></repeatBack>
    </others></finale>""")
    assert repeats_for(doc).get(2).playback == RepeatPlayback(
        "jumpAbsolute", "untilPass", 1, 3, True
    )
    assert repeats_for(doc).get(3).playback is None
