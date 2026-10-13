"""Retain explicit articulation playback independently of display and Human Playback."""

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.fonts import font_names
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import ArticulationPlayback, PlaybackAdjustment, ScoreDiagnostic


def _adjustment(definition: Record, name: str, delta_unit: str) -> PlaybackAdjustment:
    percent = f"{name}TopNotePercent" in definition.fields
    unit = "Percent" if percent else "Delta"
    top = field_int(definition.fields.get(f"{name}TopNote{unit}", "0"))
    bottom = field_int(definition.fields.get(f"{name}BotNote{unit}", "0"))
    if top is None or bottom is None:
        raise CorruptScoreError("articDef: invalid playback adjustment")
    return PlaybackAdjustment(top, bottom, "percent" if percent else delta_unit)


def articulation_playback_by_entry(
    document: EnigmaDocument,
) -> tuple[dict[int, tuple[ArticulationPlayback, ...]], tuple[ScoreDiagnostic, ...]]:
    definitions = {
        n: r
        for r in document.others.of_tag("articDef")
        if "part" not in r.attrs and (n := field_int(r.attrs.get("cmper"))) is not None
    }
    fonts = font_names(document)
    out: dict[int, list[ArticulationPlayback]] = {}
    diagnostics: dict[tuple[str, int], ScoreDiagnostic] = {}
    for assignment in document.details.of_tag("articAssign"):
        if "part" in assignment.attrs:
            continue
        entry = field_int(assignment.attrs.get("entnum"))
        identity = field_int(assignment.fields.get("articDef"))
        if entry is None or identity is None or identity not in definitions:
            continue
        definition = definitions[identity]
        source_ref = f"articDef:{identity}"
        character = field_int(definition.fields.get("charMain"))
        font = field_int(definition.fields.get("fontMain"))
        if (
            "mainIsShape" not in definition.fields
            and character is not None
            and 0 <= character < 32
            and font is not None
            and fonts.get(font, "").casefold() == "maestro"
        ):
            diagnostics["nonprinting-articulation", identity] = ScoreDiagnostic(
                "nonprinting-articulation",
                f"Maestro character {character} supplies no printable symbol; "
                "its source definition and independent playback controls are retained.",
                source_ref,
            )
        if "playArtic" not in definition.fields:
            continue
        control = ArticulationPlayback(
            _adjustment(definition, "start", "edu"),
            _adjustment(definition, "dur", "edu"),
            _adjustment(definition, "amp", "key-velocity"),
            source_ref,
        )
        out.setdefault(entry, []).append(control)
        diagnostics["articulation-playback", identity] = ScoreDiagnostic(
            "articulation-playback",
            "Explicit top/bottom articulation playback values are retained in IR; "
            "MusicXML export leaves their realization to the player. "
            "Finale Human Playback can override these manual controls.",
            source_ref,
        )
    return {entry: tuple(values) for entry, values in out.items()}, tuple(diagnostics.values())
