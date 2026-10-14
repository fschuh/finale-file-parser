"""Preserve assigned custom endpoint programs as bounded, inert drawing data."""

from collections.abc import Mapping

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_others import TAG_SHAPE_DATA, TAG_SHAPE_DEF, TAG_SHAPE_LIST
from finale_file_parser.ir import GraphicInstruction, ShapeGraphic

# These are resource limits, applied before expanding binary arrays or typed
# XML fields. They are not sizes supplied by an input file.
MAX_GRAPHIC_WORDS = 65536
MAX_GRAPHIC_INSTRUCTIONS = 8192

# FCShapeDefInstruction::GetTagAsString independently identifies the numeric
# tags; ShapeDesigner.h and FieldPopulatorsOthers.cpp corroborate names/arities.
_COMMANDS = {
    0x736F: ("startObject", 11),
    0x6C77: ("lineWidth", 1),
    0x726D: ("rMoveTo", 2),
    0x7364: ("setDash", 2),
    0x726C: ("rLineTo", 2),
    0x7374: ("stroke", 0),
}
_ARITIES = dict(_COMMANDS.values())
_SHAPE_TYPES = (
    "other",
    "articulation",
    "barline",
    "executable",
    "expression",
    "note",
    "frame",
    "arrowhead",
    "fretboard",
    "clef",
)


def normalize_shape_record(tag: int, payload: bytes, attrs: Mapping[str, str]) -> Record:
    """Normalize only the evidenced numeric layouts, without following refs."""
    if tag == TAG_SHAPE_DEF:
        if len(payload) != 12:
            raise CorruptScoreError("shapeDef: expected 12-byte resource header")
        kind = int.from_bytes(payload[4:6], "little")
        return Record(
            "shapeDef",
            attrs,
            "",
            {
                "instList": str(int.from_bytes(payload[:2], "little")),
                "dataList": str(int.from_bytes(payload[2:4], "little")),
                "shapeType": _SHAPE_TYPES[kind] if kind < len(_SHAPE_TYPES) else f"unknown:{kind}",
            },
        )
    if tag == TAG_SHAPE_DATA:
        if len(payload) % 4 or len(payload) > 4 * MAX_GRAPHIC_WORDS:
            raise CorruptScoreError("shapeData: invalid or excessive signed-word array")
        return Record(
            "shapeData",
            attrs,
            "",
            {
                "data": tuple(
                    str(int.from_bytes(payload[at : at + 4], "little", signed=True))
                    for at in range(0, len(payload), 4)
                )
            },
        )
    if tag != TAG_SHAPE_LIST:
        raise CorruptScoreError("unsupported Shape Designer record tag")
    if len(payload) % 4 or len(payload) > 4 * MAX_GRAPHIC_INSTRUCTIONS:
        raise CorruptScoreError("shapeList: invalid or excessive instruction array")
    end = len(payload)
    while end and payload[end - 4 : end] == bytes(4):
        end -= 4  # Numeric others rows pad their instruction array with nulls.
    instructions = []
    for at in range(0, end, 4):
        opcode = int.from_bytes(payload[at : at + 2], "little")
        command = _COMMANDS.get(opcode, (f"opcode:{opcode:04x}", 0))[0]
        instructions.append(
            Record(
                "instruct",
                {
                    "sourceTag": str(opcode),
                    "sourceFormat": str(payload[at + 3]),
                },
                "",
                {"tag": command, "numData": str(payload[at + 2])},
            )
        )
    return Record("shapeList", attrs, "", {"instruct": tuple(instructions)})


def _items(record: Record, field: str, limit: int) -> tuple[str | Record, ...]:
    value = record.fields.get(field, ())
    items = value if isinstance(value, tuple) else (value,)
    if len(items) > limit:
        raise CorruptScoreError(f"{record.tag}: excessive {field} array")
    return items


def resolve_shape_graphic(
    document: EnigmaDocument, identity: int
) -> tuple[ShapeGraphic | None, str]:
    """Resolve a visible assignment's resources; never execute its commands.

    Missing resources or an unproved instruction format remain explicit
    references. A structurally invalid assigned program raises a clear error.
    Unknown opcodes keep their exact parameters and produce a diagnostic.
    """
    header = document.others.get("shapeDef", identity)
    if header is None:
        return None, "custom endpoint definition is missing"
    instruction_id = field_int(header.fields.get("instList", "0"))
    data_id = field_int(header.fields.get("dataList", "0"))
    if instruction_id is None or data_id is None or instruction_id < 0 or data_id < 0:
        raise CorruptScoreError(f"shapeDef:{identity}: invalid drawing resource reference")
    kind = header.fields.get("shapeType", "other")
    if not isinstance(kind, str):
        raise CorruptScoreError(f"shapeDef:{identity}: invalid graphic type")
    blank = ShapeGraphic(
        (), f"shapeDef:{identity}", f"shapeList:{instruction_id}", f"shapeData:{data_id}", kind
    )
    if not instruction_id:
        return blank, ""
    instructions = document.others.get("shapeList", instruction_id)
    if instructions is None:
        return None, "custom endpoint instruction resource is missing"
    items = _items(instructions, "instruct", MAX_GRAPHIC_INSTRUCTIONS)
    if not items:
        return blank, ""
    data = document.others.get("shapeData", data_id)
    if data is None:
        return None, "custom endpoint data resource is missing"
    values = []
    for value in _items(data, "data", MAX_GRAPHIC_WORDS):
        number = field_int(value)
        if number is None or not -(2**31) <= number < 2**31:
            raise CorruptScoreError(f"shapeDef:{identity}: invalid signed drawing parameter")
        values.append(number)
    commands = []
    cursor = 0
    unknown = False
    for instruction in items:
        if not isinstance(instruction, Record):
            raise CorruptScoreError(f"shapeDef:{identity}: invalid drawing instruction")
        source_format = instruction.attrs.get("sourceFormat")
        if source_format is not None and source_format != "2":
            return None, "custom endpoint instruction format is unestablished"
        command = instruction.fields.get("tag", "unknown")
        count = field_int(instruction.fields.get("numData", "0"))
        if not isinstance(command, str) or count is None or not 0 <= count <= len(values) - cursor:
            raise CorruptScoreError(f"shapeDef:{identity}: invalid drawing parameter count")
        expected = _ARITIES.get(command)
        if expected is not None and count != expected:
            raise CorruptScoreError(f"shapeDef:{identity}: {command} expects {expected} parameters")
        unknown |= expected is None
        commands.append(
            GraphicInstruction(
                command,
                tuple(values[cursor : cursor + count]),
                field_int(instruction.attrs.get("sourceTag")),
            )
        )
        cursor += count
    return ShapeGraphic(
        tuple(commands),
        f"shapeDef:{identity}",
        f"shapeList:{instruction_id}",
        f"shapeData:{data_id}",
        kind,
    ), "custom endpoint includes unestablished drawing commands" if unknown else ""
