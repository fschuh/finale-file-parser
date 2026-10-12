"""Read independently mapped document playback controls, without MIDI inference."""

from fractions import Fraction

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.timesig import time_signatures
from finale_file_parser.ir import PlaybackPreferences


def playback_preferences(document: EnigmaDocument) -> PlaybackPreferences | None:
    records = document.options.of_tag("playbackOptions")
    record = next(iter(records), None)
    if record is None:
        return None
    values = {}
    defaults = {
        "swing": 0,
        "baseKeyVelocity": 64,
        "startAtMeas": 1,
        "startEdu": 0,
        "startAtMode": 0,
        "stopAtMeas": 32767,
        "stopEdu": 0,
        "startPass": 1,
        "endPass": 1,
    }
    for name in ("metronomeBeat", "metronomeSpeed", *defaults):
        value = field_int(record.fields.get(name, str(defaults.get(name, ""))))
        if value is None:
            raise CorruptScoreError(f"playbackOptions: invalid {name}")
        values[name] = value
    if (
        not 0 < values["metronomeBeat"] <= 32767
        or not 0 < values["metronomeSpeed"] <= 1000
        or not 0 <= values["swing"] <= 32767
        or not 0 <= values["baseKeyVelocity"] <= 127
        or values["startAtMode"] not in {0, 1, 2}
        or any(
            not 1 <= values[n] <= 32767
            for n in ("startAtMeas", "stopAtMeas", "startPass", "endPass")
        )
        or any(not 0 <= values[n] <= 0x7FFFFFFF for n in ("startEdu", "stopEdu"))
    ):
        raise CorruptScoreError("playbackOptions: controls are outside supported bounds")
    stop = values["stopAtMeas"]
    if stop == 32767:
        stop_measure = None
    else:
        stop_measure = stop - (values["stopEdu"] == 0)
        if stop_measure < 1:
            raise CorruptScoreError("playbackOptions: stop precedes the score")
    signatures = time_signatures(document) if document.others.of_tag("measSpec") else {}
    initial = signatures.get(min(signatures)) if signatures else None
    unit = (
        Fraction(initial.division_edu, 8192)
        if initial is not None and not initial.is_compound
        else None
    )
    return PlaybackPreferences(
        Fraction(values["metronomeBeat"], 4096),
        Fraction(values["metronomeSpeed"]),
        Fraction(values["swing"], 1024),
        values["baseKeyVelocity"],
        values["startAtMeas"],
        Fraction(values["startEdu"], 4096),
        values["startAtMode"],
        stop_measure,
        Fraction(values["stopEdu"], 4096),
        values["startPass"],
        values["endPass"],
        unit,
    )
