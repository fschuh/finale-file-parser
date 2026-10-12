"""Authored mixed text and compiled commands; no copied score data."""

from pathlib import Path

import pytest

from finale_file_parser.enigma import mus_document as adapter
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_text import decode_mus_text
from finale_file_parser.enigma.text import plain_text


@pytest.mark.parametrize("opcode,arguments", [(0x84, 4), (0xA5, 4), (0x81, 8), (0x95, 8)])
@pytest.mark.parametrize("utf8_opcode", [False, True])
def test_exact_command_boundaries_preserve_the_following_literal_text(
    opcode: int,
    arguments: int,
    utf8_opcode: bool,
) -> None:
    op = chr(opcode).encode("utf-8") if utf8_opcode else bytes([opcode])
    raw = "Été ".encode() + b"^" + op + bytes([1]) * arguments + " q = 112 ✓".encode()
    decoded = decode_mus_text(raw, "cp1252")
    assert f"^legacycmd({opcode:02X},{(bytes([1]) * arguments).hex()})" in decoded
    assert plain_text(decoded) == "Été  q = 112 ✓"


@pytest.mark.parametrize("opcode", [0x8B, 0x99, 0x9C, 0xA7])
def test_zero_argument_inserts_do_not_eat_copyright_or_following_text(opcode: int) -> None:
    text = decode_mus_text(b"^" + bytes([opcode]) + b"1988 Composer", "cp1252")
    assert plain_text(text) == "1988 Composer"


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "mac_roman"])
def test_command_data_cannot_force_literal_unicode_through_the_wrong_decoder(encoding: str) -> None:
    raw = b"^\xa5\x01\x01\x01\xfb" + "Célesta".encode(encoding)
    assert (
        plain_text(decode_mus_text(raw, "mac_roman" if encoding == "mac_roman" else "cp1252"))
        == "Célesta"
    )


@pytest.mark.parametrize("opcode,arity", [(0xA5, 4), (0x81, 8)])
def test_truncated_known_commands_fail_at_their_byte_boundary(opcode: int, arity: int) -> None:
    for remaining in range(arity):
        with pytest.raises(CorruptScoreError, match="truncated argument bytes"):
            decode_mus_text(b"^" + bytes([opcode]) + bytes([1]) * remaining, "cp1252")


def test_literal_carets_and_unrelated_unicode_are_preserved() -> None:
    raw = "x^2 and ^λabcde".encode()
    assert plain_text(decode_mus_text(raw, "cp1252")) == "x^2 and ^λabcde"


@pytest.mark.parametrize("literal", [b"word\x01", b"word\x00", "word\ufffe".encode()])
def test_illegal_literal_characters_raise_instead_of_producing_invalid_xml(literal: bytes) -> None:
    with pytest.raises(CorruptScoreError, match="illegal character"):
        decode_mus_text(literal, "cp1252")


def test_eight_argument_commands_do_not_leak_control_bytes_from_an_expression_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"^\x81" + bytes([1]) * 7 + b"\x04q" + b"^\x81" + bytes([1]) * 8 + b" = 112"
    stream = b"^expression(7)" + body + b"^end"
    monkeypatch.setattr(adapter, "read_mus_streams", lambda _: [b"", b"", b"", stream])
    monkeypatch.setattr(adapter, "_banner_platform", lambda _: "WIN")
    record = adapter._texts_records(Path("not-opened.mus"))[0]
    assert record.tag == "expression"
    assert plain_text(record.text) == "q = 112"
    assert all(ord(char) >= 32 for char in record.text)


def test_smart_shape_text_has_its_own_pool_and_compiled_font_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"^\x85" + bytes([1]) * 4 + b"Ped."
    stream = b"^smartshape(7)" + body + b"^end^expression(7)quarter = 120^end"
    monkeypatch.setattr(adapter, "read_mus_streams", lambda _: [b"", b"", b"", stream])
    monkeypatch.setattr(adapter, "_banner_platform", lambda _: "WIN")
    records = adapter._texts_records(Path("not-opened.mus"))
    assert [r.tag for r in records] == ["smartShapeText", "expression"]
    assert [r.attrs["number"] for r in records] == ["7", "7"]
    assert [plain_text(r.text) for r in records] == ["Ped.", "quarter = 120"]
