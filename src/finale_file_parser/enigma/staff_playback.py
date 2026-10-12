"""Apply explicit staff/layer routing and play flags, independent of drawing groups."""

from dataclasses import replace

from finale_file_parser.enigma.document import EnigmaDocument, Record, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.ir import Part


def with_playback_scopes(document: EnigmaDocument, parts: tuple[Part, ...]) -> tuple[Part, ...]:
    settings = {
        staff: record
        for record in document.others.of_tag("staffPlayData")
        if "part" not in record.attrs
        and (staff := field_int(record.attrs.get("cmper"))) is not None
    }
    out = []
    for part in parts:
        staff = int(part.id[1:])
        source = settings.get(staff)
        if source is None:
            out.append(part)
            continue
        measures = []
        for measure in part.measures:
            voices = []
            for voice in measure.voices:
                control = source.fields.get(f"layer{voice.number}")
                if not isinstance(control, Record):
                    voices.append(voice)
                    continue
                route = field_int(control.fields.get("playbackRouteNum"))
                if route is None or not 0 <= route < 65535:
                    raise CorruptScoreError("staffPlayData: invalid playback route")
                voices.append(
                    replace(
                        voice,
                        instrument_id=f"source-instrument:{route + 1}",
                        playback="play" in control.fields,
                        solo="solo" in control.fields,
                    )
                )
            measures.append(replace(measure, voices=tuple(voices)))
        identities = {v.instrument_id for m in measures for v in m.voices}
        identity = next(iter(identities)) if len(identities) == 1 else None
        out.append(replace(part, measures=tuple(measures), instrument_id=identity))
    if any(v.solo for part in out for m in part.measures for v in m.voices):
        out = [
            replace(
                part,
                measures=tuple(
                    replace(
                        m,
                        voices=tuple(replace(v, playback=v.playback and v.solo) for v in m.voices),
                    )
                    for m in part.measures
                ),
            )
            for part in out
        ]
    return tuple(out)
