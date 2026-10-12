"""Export placed navigation without inferring source actions from printed words."""

from fractions import Fraction
from xml.etree import ElementTree as ET

from finale_file_parser.ir import Navigation, Part, Score
from finale_file_parser.playback import PlaybackError, navigation_target


def append_navigation(root: ET.Element, score: Score) -> None:
    if not score.parts:
        return
    part = score.parts[0]
    element = root.find("part")
    if element is None:
        return
    divisions = 1
    for measure, xml in zip(part.measures, element.findall("measure"), strict=True):
        divisions = int(xml.findtext("attributes/divisions", str(divisions)))
        for mark in measure.navigation:
            attrs = _sound(part, measure.number, mark)
            if mark.kind == "unknown-glyph" and not attrs:
                continue
            direction = ET.Element("direction", placement="above", system="only-top")
            kind = ET.SubElement(direction, "direction-type")
            if not mark.visible:
                ET.SubElement(kind, "other-direction", {"print-object": "no"}).text = mark.text
            elif mark.kind in {"segno", "coda"}:
                ET.SubElement(kind, mark.kind)
            else:
                ET.SubElement(kind, "words").text = mark.text
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
                if "al fine" in mark.text.casefold() or "al coda" in mark.text.casefold():
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


def _sound(part: Part, number: int, mark: Navigation) -> dict[str, str]:
    if mark.kind in {"segno", "coda"}:
        return {mark.kind: mark.mark_id}
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
            attrs["tocoda" if target > number else "dalsegno"] = targets[0].mark_id
    if rule.trigger == "onPass":
        attrs["time-only"] = str(rule.passes)
    elif rule.trigger == "untilPass" and rule.passes > 1:
        attrs["time-only"] = ",".join(str(p) for p in range(1, min(rule.passes, 32768)))
    return attrs
