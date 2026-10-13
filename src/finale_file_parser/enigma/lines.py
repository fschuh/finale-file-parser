"""Resolve assigned line drawings independently of musical performance meaning."""

from collections.abc import Collection
from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.enigma.hairpins import _endpoint
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.slurs import _drawing_adjustment
from finale_file_parser.enigma.text import plain_text
from finale_file_parser.ir import LineSpan, ScoreDiagnostic

_PRESETS = {
    "10": ("dashed", "none", "none"),
    "11": ("solid", "none", "none"),
    "32": ("dashed", "up", "none"),
}


def _label(document: EnigmaDocument, definition: Record, name: str) -> str:
    number = field_int(definition.fields.get(name))
    text = document.texts.get("smartShapeText", number) if number else None
    return plain_text(text.text) if text is not None else ""


def _cap(definition: Record, name: str) -> tuple[str, str, Fraction | None]:
    kind = definition.fields.get(f"lineCap{name}Type", "none")
    if kind == "hook":
        length = field_int(definition.fields.get(f"lineCap{name}HookLength"))
        if length is None:
            return "none", f"hook:{name}", None
        cap = "up" if length > 0 else "down" if length < 0 else "none"
        return cap, "", Fraction(abs(length), 64 * 24)
    if kind == "arrowheadPreset":
        return "arrow", "", None
    if kind == "arrowheadCustom":
        return "none", f"shape:{definition.fields.get(f'lineCap{name}ArrowID', '')}", None
    if kind != "none":
        raise CorruptScoreError("unsupported custom line cap")
    return "none", "", None


def lines_by_staff(
    document: EnigmaDocument, *, ignored_shapes: Collection[int] = ()
) -> tuple[dict[int, tuple[LineSpan, ...]], tuple[ScoreDiagnostic, ...]]:
    assigned = {
        n
        for r in (
            *document.others.of_tag("smartShapeMeasMark"),
            *document.details.of_tag("smartShapeEntryMark"),
        )
        if "part" not in r.attrs and (n := field_int(r.fields.get("shapeNum"))) is not None
    } - set(ignored_shapes)
    fonts = font_names(document)
    result: dict[int, list[LineSpan]] = {}
    diagnostics = []
    for record in document.others.of_tag("smartShape"):
        number = field_int(record.attrs.get("cmper"))
        kind = str(record.fields.get("shapeType"))
        if number not in assigned or "part" in record.attrs or "hidden" in record.fields:
            continue
        if kind not in {*_PRESETS, "29"}:
            continue
        ref = f"smartShape:{number}"
        if {"entryBased", "lyricBased"}.intersection(record.fields):
            diagnostics.append(
                ScoreDiagnostic(
                    "line-attachment",
                    "Entry/lyric-based line drawing requires note placement; "
                    "source shape is retained.",
                    ref,
                )
            )
            continue
        line_type, start_cap, end_cap = _PRESETS.get(kind, ("solid", "none", "none"))
        start_symbol = end_symbol = start_text = end_text = ""
        start_cap_length = end_cap_length = None
        if kind == "29":
            identity = field_int(record.fields.get("ssLineStyleID"))
            definition = document.others.get("smartShapeCustomLine", identity) if identity else None
            if definition is None or definition.attrs.get("sourceLayout") == "unknown":
                diagnostics.append(
                    ScoreDiagnostic(
                        "line-definition",
                        "Custom line definition/layout is unresolved; "
                        "source shape and definition are retained.",
                        ref,
                    )
                )
                continue
            style = definition.fields.get("lineStyle")
            parameters = definition.fields.get("charParams")
            if style == "char":
                font_id = (
                    field_int(parameters.fields.get("fontID"))
                    if isinstance(parameters, Record)
                    else None
                )
                if (
                    not isinstance(parameters, Record)
                    or field_int(parameters.fields.get("lineChar")) != 126
                    or font_id is None
                    or fonts.get(font_id, " ").casefold()
                    not in {"maestro", "engraverfontset", "engraver font set"}
                ):
                    diagnostics.append(
                        ScoreDiagnostic(
                            "line-character",
                            "Custom repeated line glyph is unestablished; "
                            "its source font and definition are retained.",
                            ref,
                        )
                    )
                    continue
                line_type = "wavy"
            elif style in {"solid", "dashed"}:
                line_type = str(style)
            else:
                raise CorruptScoreError(f"{ref}: unsupported custom line style")
            start_cap, start_symbol, start_cap_length = _cap(definition, "Start")
            end_cap, end_symbol, end_cap_length = _cap(definition, "End")
            start_text = _label(document, definition, "leftStartRawTextID")
            end_text = _label(document, definition, "rightEndRawTextID")
            if any(
                _label(document, definition, name)
                for name in ("leftContRawTextID", "centerFullRawTextID", "centerAbbrRawTextID")
            ):
                diagnostics.append(
                    ScoreDiagnostic(
                        "line-label-placement",
                        "Center/continuation line labels require manual placement; "
                        "their source text references are retained.",
                        ref,
                    )
                )
        staff, sm, so = _endpoint(record, "startTermSeg")
        end_staff, em, eo = _endpoint(record, "endTermSeg")
        if (em, eo) < (sm, so):
            raise CorruptScoreError(f"{ref}: reversed line span")
        sx, sy = _drawing_adjustment(record, "startTermSeg")
        ex, ey = _drawing_adjustment(record, "endTermSeg")
        result.setdefault(staff, []).append(
            LineSpan(
                start_measure=sm,
                start_offset=so,
                end_measure=em,
                end_offset=eo,
                line_type=line_type,
                start_cap=start_cap,
                end_cap=end_cap,
                start_x=sx,
                start_y=sy,
                end_x=ex,
                end_y=ey,
                start_text=start_text,
                end_text=end_text,
                start_symbol=start_symbol,
                end_symbol=end_symbol,
                end_part_id=f"P{end_staff}" if end_staff != staff else None,
                source_ref=ref,
                start_cap_length=start_cap_length,
                end_cap_length=end_cap_length,
            )
        )
        if (sm, so) == (em, eo):
            diagnostics.append(
                ScoreDiagnostic(
                    "graphical-line",
                    "Same-time line drawing retains its geometry; "
                    "MusicXML players may require manual layout.",
                    ref,
                )
            )
        if start_symbol or end_symbol:
            diagnostics.append(
                ScoreDiagnostic(
                    "line-endpoint-graphic",
                    "Custom line endpoint graphics retain their resource references; "
                    "standard MusicXML exports the line without those graphics.",
                    ref,
                )
            )
    return {staff: tuple(spans) for staff, spans in result.items()}, tuple(diagnostics)
