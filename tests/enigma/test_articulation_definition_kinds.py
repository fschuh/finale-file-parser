"""Authored font/character/shape records cover both independently evidenced layouts."""

import struct

import pytest

from finale_file_parser.enigma.articulations import articulations_by_entry
from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.fermatas import fermatas_by_entry
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _artic_def


@pytest.mark.parametrize("size", [48, 60])
def test_font_size_and_shape_are_not_read_from_character_or_neighboring_fields(size: int) -> None:
    data = bytearray(size)
    if size == 48:
        data[0] = 85
        data[2] = 7
        data[3] = 24
        struct.pack_into("<H", data, 22, 2)
        struct.pack_into("<H", data, 32, 19)
    else:
        struct.pack_into("<4H", data, 0, 0, 85, 7, 24)
        struct.pack_into("<H", data, 24, 2)
        struct.pack_into("<H", data, 34, 19)
    fields = _artic_def(bytes(data))
    assert fields["charMain"] == "85" and fields["fontMain"] == "7" and fields["sizeMain"] == "24"
    assert "mainIsShape" in fields and fields["mainShape"] == "19"


def test_unicode_character_uses_high_platform_endian_word_first() -> None:
    data = bytearray(60)
    struct.pack_into("<HH", data, 0, 1, 0xD11E)
    assert _artic_def(bytes(data))["charMain"] == str(0x1D11E)


def test_unknown_definition_layout_fails_before_reading_fields() -> None:
    with pytest.raises(CorruptScoreError, match="layout"):
        _artic_def(b"\0" * 59)


def test_custom_shape_with_a_familiar_character_does_not_become_a_false_symbol() -> None:
    doc = parse_enigma(b"""<finale><others>
      <articDef cmper="1"><charMain>85</charMain><mainIsShape/><mainShape>4</mainShape></articDef>
      <articDef cmper="2"><charMain>62</charMain><mainIsShape/><mainShape>5</mainShape></articDef>
    </others><details>
      <articAssign entnum="1"><articDef>1</articDef></articAssign>
      <articAssign entnum="2"><articDef>2</articDef></articAssign>
    </details></finale>""")
    assert not articulations_by_entry(doc) and not fermatas_by_entry(doc)
