"""Export placed navigation without inferring source actions from printed words."""

from fractions import Fraction
from xml.etree import ElementTree as ET

from finale_file_parser.ir import Navigation, Part, Score
from finale_file_parser.playback import PlaybackError, navigation_target


def append_navigation(root: ET.Element, score: Score) -> None:
    if not score.parts:
        return
    part = score.parts[0]
    references, marker_ids = _marker_placements(part)
    element = root.find("part")
    if element is None:
        return
    divisions = 1
    for measure, xml in zip(part.measures, element.findall("measure"), strict=True):
        divisions = int(xml.findtext("attributes/divisions", str(divisions)))
        for mark in measure.navigation:
            reference = (measure.number, mark.kind, mark.mark_id) in references
            attrs = _sound(part, measure.number, mark, reference=reference, marker_ids=marker_ids)
            if mark.kind == "unknown-glyph" and not attrs:
                continue
            direction = ET.Element("direction", placement="above", system="only-top")
            kind = ET.SubElement(direction, "direction-type")
            positioning = _positioning(mark)
            if not mark.visible:
                ET.SubElement(kind, "other-direction", {"print-object": "no"}).text = mark.text
            elif mark.kind in {"segno", "coda"}:
                if reference:
                    # A reused glyph referring to a real destination is an
                    # inline musical symbol, not a second playback marker.
                    ET.SubElement(kind, "symbol", positioning).text = mark.kind
                else:
                    ET.SubElement(kind, mark.kind, positioning)
            else:
                ET.SubElement(kind, "words", positioning).text = mark.text
            if mark.kind not in {"segno", "coda"}:
                # Source text repeats act at a bar boundary, not at their EVPU
                # drawing adjustment. Keep right-side jumps in their own bar.
                extent = max(
                    (
                        v.start_offset
                        + sum((e.duration for e in v.events if not e.is_grace), Fraction())
                        for v in measure.voices
                    ),
                    default=Fraction(),
                )
                ET.SubElement(direction, "offset", sound="yes").text = str(
                    int(extent * 4 * divisions)
                )
            if attrs:
                if mark.kind not in {"segno", "coda"} and (
                    "al fine" in mark.text.casefold() or "al coda" in mark.text.casefold()
                ):
                    # Keep sound independent so MuseScore can infer the complete
                    # jump text. Embedded dalsegno otherwise loses 'al Fine'.
                    sound = ET.Element("sound", attrs)
                    ET.SubElement(sound, "offset").text = str(int(extent * 4 * divisions))
                    position = next(
                        (i for i, e in enumerate(xml) if e.tag not in {"attributes", "barline"}),
                        len(xml),
                    )
                    xml.insert(position, sound)
                else:
                    ET.SubElement(direction, "sound", attrs)
            position = next(
                (i for i, e in enumerate(xml) if e.tag not in {"attributes", "barline"}), len(xml)
            )
            xml.insert(position, direction)


def _sound(
    part: Part,
    number: int,
    mark: Navigation,
    *,
    reference: bool = False,
    marker_ids: dict[tuple[int, str, str], str] | None = None,
) -> dict[str, str]:
    if mark.kind in {"segno", "coda"}:
        if reference:
            return {}
        return {mark.kind: (marker_ids or {}).get((number, mark.kind, mark.mark_id), mark.mark_id)}
    rule = mark.playback
    if rule is None or rule.action == "noJump":
        return {}
    attrs: dict[str, str] = {}
    if rule.action == "stop":
        attrs["fine"] = "yes"
    else:
        try:
            target = navigation_target(part, number, mark)
        except PlaybackError:
            return {}
        if target == part.measures[0].number:
            attrs["dacapo"] = "yes"
        else:
            targets = [
                n
                for m in part.measures
                if m.number == target
                for n in m.navigation
                if n.kind in {"segno", "coda"}
            ]
            if len(targets) != 1:
                return {}
            marker = targets[0]
            attrs["tocoda" if target > number else "dalsegno"] = (marker_ids or {}).get(
                (target, marker.kind, marker.mark_id), marker.mark_id
            )
    if rule.trigger == "onPass":
        attrs["time-only"] = str(rule.passes)
    elif rule.trigger == "untilPass" and rule.passes > 1:
        attrs["time-only"] = ",".join(str(p) for p in range(1, min(rule.passes, 32768)))
    return attrs


def _positioning(mark: Navigation) -> dict[str, str]:
    attrs = {}
    if mark.x_offset is not None:
        if mark.kind in {"segno", "coda"} and mark.justification in {None, "left"}:
            attrs["default-x"] = f"{float(mark.x_offset * 10):.5f}"
        elif mark.kind == "words" and mark.justification == "right":
            attrs["relative-x"] = f"{float(mark.x_offset * 10):.5f}"
    if mark.y_offset is not None:
        attrs["default-y"] = f"{float(mark.y_offset * 10):.5f}"
    if mark.kind == "words" and mark.justification in {"left", "center", "right"}:
        attrs["justify"] = mark.justification
    return attrs


def _marker_placements(
    part: Part,
) -> tuple[set[tuple[int, str, str]], dict[tuple[int, str, str], str]]:
    occurrences: dict[tuple[str, str], set[int]] = {}
    passive: dict[tuple[int, str, str], bool] = {}
    for measure in part.measures:
        for mark in measure.navigation:
            if mark.kind in {"segno", "coda"} and mark.mark_id:
                occurrences.setdefault((mark.kind, mark.mark_id), set()).add(measure.number)
                key = measure.number, mark.kind, mark.mark_id
                passive[key] = passive.get(key, True) and (
                    mark.playback is None or mark.playback.action == "noJump"
                )
    destinations = set()
    for measure in part.measures:
        for jump in measure.navigation:
            if (
                jump.kind != "words"
                or jump.playback is None
                or jump.playback.action in {"noJump", "stop"}
            ):
                continue
            try:
                destinations.add(navigation_target(part, measure.number, jump))
            except PlaybackError:
                continue
    references = set()
    marker_ids = {}
    for (kind, identifier), measures in occurrences.items():
        if len(measures) < 2:
            continue
        used = measures & destinations
        for number in measures:
            marker_ids[number, kind, identifier] = f"{identifier}-measure-{number}"
            if len(used) == 1 and number not in used:
                if passive[number, kind, identifier]:
                    references.add((number, kind, identifier))
    return references, marker_ids
