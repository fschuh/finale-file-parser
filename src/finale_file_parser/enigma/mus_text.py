"""Decode bounded compiled text commands independently of literal encoding.

The supported command arities are evidenced in ARCHITECTURE. Command meaning
is not guessed: an opaque named token retains its opcode and exact arguments.
"""

from finale_file_parser.enigma.models import CorruptScoreError

# Bytes after the opcode, excluding the caret and the opcode itself.
COMPILED_ARGUMENT_BYTES = {
    0x81: 8,
    0x84: 4,
    0x85: 4,
    0x86: 4,
    0x8A: 0,
    0x8B: 0,
    0x8E: 0,
    0x8F: 0,
    0x92: 0,
    0x94: 0,
    0x95: 8,
    0x96: 0,
    0x99: 0,
    0x9C: 0,
    0xA0: 0,
    0xA2: 0,
    0xA3: 0,
    0xA4: 4,
    0xA5: 4,
    0xA6: 4,
    0xA7: 0,
}


def _literal(raw: bytes, fallback: str) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode(fallback, errors="replace")
    for char in text:
        codepoint = ord(char)
        if (codepoint < 32 and char not in "\t\r\n") or codepoint in (0xFFFE, 0xFFFF):
            raise CorruptScoreError(f"literal text contains an illegal character U+{codepoint:04X}")
    return text


def _command(raw: bytes, at: int) -> tuple[int, int] | None:
    if raw[at] != 0x5E or at + 1 >= len(raw):
        return None
    opcode = raw[at + 1]
    after = at + 2
    # Some sections encode the high-byte opcode as its UTF-8 scalar, while
    # retaining byte-valued arguments. Both dialects use the same arity.
    if opcode in (0xC2, 0xC3) and after < len(raw) and 0x80 <= raw[after] <= 0xBF:
        opcode = (opcode & 0x1F) * 64 + (raw[after] & 0x3F)
        after += 1
    return (opcode, after) if opcode in COMPILED_ARGUMENT_BYTES else None


def decode_mus_text(raw: bytes, fallback: str) -> str:
    """Preserve literal UTF-8/legacy text and normalize known compiled tokens.

    Constant arities bound every read and every iteration consumes input. A
    truncated known command raises rather than leaking arguments into lyrics
    or expression words. Unknown caret sequences remain literal source text.
    """
    chunks: list[str] = []
    at = literal_start = 0
    while at < len(raw):
        command = _command(raw, at)
        if command is None:
            at += 1
            continue
        opcode, after = command
        end = after + COMPILED_ARGUMENT_BYTES[opcode]
        if end > len(raw):
            raise CorruptScoreError(f"text command 0x{opcode:02X}: truncated argument bytes")
        chunks.append(_literal(raw[literal_start:at], fallback))
        chunks.append(f"^legacycmd({opcode:02X},{raw[after:end].hex()})")
        at = literal_start = end
    chunks.append(_literal(raw[literal_start:], fallback))
    return "".join(chunks)


def _decoded_command_arities() -> dict[str, int]:
    result = {}
    for opcode, arity in COMPILED_ARGUMENT_BYTES.items():
        result[chr(opcode)] = arity
        alias = bytes([opcode]).decode("cp1252", errors="replace")
        if alias != "\ufffd":
            result[alias] = arity
    return result


_DECODED_ARITIES = _decoded_command_arities()


def strip_compiled_commands(markup: str) -> str:
    """Compatibility for already decoded legacy command strings.

    New MUS text uses byte-normalized named tokens instead. Recognize only
    known opcode spellings, preserving unrelated non-ASCII literal carets.
    """
    out = []
    at = 0
    while at < len(markup):
        arity = (
            _DECODED_ARITIES.get(markup[at + 1])
            if markup[at] == "^" and at + 1 < len(markup)
            else None
        )
        if arity is None:
            out.append(markup[at])
            at += 1
            continue
        end = at + 2 + arity
        if end > len(markup):
            raise CorruptScoreError("compiled text command has truncated arguments")
        at = end
    return "".join(out)
