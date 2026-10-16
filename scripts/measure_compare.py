"""Compare written MusicXML bars with a reference performance MIDI, bar by bar.

Used to check a converted corpus against the MIDI files Finale exported from the
same documents. Each written bar's notes (onset within the bar in quarters, sounding
pitch) come straight from the MusicXML; the MIDI timeline is then walked bar by bar,
taking at each step the written bar that best explains the reference notes there and
preferring the next bar in written order. That tolerates any repeat, D.C. or D.S.
route without modelling one. Tie continuations, grace notes and silent cue notes
are not expected to attack.

    python scripts/measure_compare.py REF_MIDI_DIR XML_DIR OUT.json [NAME ...]
"""

from __future__ import annotations

import json
import struct
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from defusedxml import ElementTree as ET

_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ORNAMENTS = (
    "trill-mark",
    "tremolo",
    "glissando",
    "slide",
    "mordent",
    "inverted-mordent",
    "turn",
    "inverted-turn",
    "arpeggiate",
    "wavy-line",
    "shake",
    "grace",
)
_TOLERANCE = 0.07
"""Quarter notes an onset may differ by and still match (swing excepted)."""


@dataclass
class Bar:
    index: int
    number: str
    length: Fraction = Fraction(0)
    notes: list[tuple[Fraction, int]] = field(default_factory=list)
    ornamented: bool = False


def _vlq(data: bytes, at: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[at]
        at += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, at


def midi_onsets(path: Path) -> list[tuple[float, int]]:
    """(onset in quarter notes, pitch) for every note-on in a standard MIDI file."""
    data = path.read_bytes()
    if data[:4] != b"MThd":
        raise ValueError(f"{path} is not a MIDI file")
    header = struct.unpack(">I", data[4:8])[0]
    _, tracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError(f"{path} uses SMPTE time")
    at, notes = 8 + header, []
    for _ in range(tracks):
        while data[at : at + 4] != b"MTrk":
            at += 1
        end = at + 8 + struct.unpack(">I", data[at + 4 : at + 8])[0]
        at, tick, status = at + 8, 0, 0
        while at < end:
            delta, at = _vlq(data, at)
            tick += delta
            byte = data[at]
            if byte == 0xFF:
                length, at = _vlq(data, at + 2)
                at += length
                continue
            if byte in (0xF0, 0xF7):
                length, at = _vlq(data, at + 1)
                at += length
                continue
            if byte & 0x80:
                status, at = byte, at + 1
            if status & 0xF0 in (0xC0, 0xD0):
                at += 1
                continue
            pitch, velocity = data[at], data[at + 1]
            at += 2
            if status & 0xF0 == 0x90 and velocity:
                notes.append((tick / division, pitch))
        at = end
    return sorted(set((round(t, 4), p) for t, p in notes))


def written_bars(path: Path) -> list[Bar]:
    root = ET.parse(path).getroot()
    if root is None:
        raise ValueError(f"{path} has no root element")
    parts = root.findall("part")
    count = max(len(p.findall("measure")) for p in parts)
    bars = [Bar(i, "") for i in range(count)]
    for part in parts:
        divisions, transpose = 1, 0
        for index, measure in enumerate(part.findall("measure")):
            bar = bars[index]
            bar.number = bar.number or measure.get("number", "")
            cursor = last = longest = Fraction(0)
            for element in measure:
                if element.tag == "attributes":
                    divisions = int(element.findtext("divisions") or divisions)
                    if element.find("transpose") is not None:
                        transpose = int(element.findtext("transpose/chromatic") or 0) + 12 * int(
                            element.findtext("transpose/octave-change") or 0
                        )
                elif element.tag in {"backup", "forward"}:
                    step = Fraction(int(element.findtext("duration") or 0), divisions)
                    cursor += step if element.tag == "forward" else -step
                    longest = max(longest, cursor)
                elif element.tag == "note":
                    if any(element.find(".//" + name) is not None for name in _ORNAMENTS):
                        bar.ornamented = True
                    if element.find("grace") is not None:
                        continue
                    chord = element.find("chord") is not None
                    onset = last if chord else cursor
                    if not chord:
                        last = cursor
                        cursor += Fraction(int(element.findtext("duration") or 0), divisions)
                        longest = max(longest, cursor)
                    pitch = element.find("pitch")
                    if pitch is None or element.find("cue") is not None:
                        continue  # a cue takes time and sounds nothing
                    if "stop" in {t.get("type") for t in element.findall("tie")}:
                        continue
                    midi = (
                        12 * (int(pitch.findtext("octave") or 0) + 1)
                        + _STEP[pitch.findtext("step") or "C"]
                        + round(float(pitch.findtext("alter") or 0))
                        + transpose
                    )
                    bar.notes.append((onset, midi))
            bar.length = max(bar.length, longest)
    for bar in bars:
        bar.notes = sorted(set(bar.notes))
    return bars


def _matches(bar: Bar, start: float, window: Sequence[tuple[float, int]]) -> set[int]:
    used: set[int] = set()
    for offset, pitch in bar.notes:
        at = start + float(offset)
        best = None
        for k, (time, ref_pitch) in enumerate(window):
            if ref_pitch == pitch and k not in used and abs(time - at) <= _TOLERANCE:
                if best is None or abs(time - at) < abs(window[best][0] - at):
                    best = k
        if best is not None:
            used.add(best)
    return used


@dataclass
class BarResult:
    number: str
    ref_only: int
    xml_only: int
    ornamented: bool


def compare(bars: list[Bar], reference: list[tuple[float, int]]) -> list[BarResult]:
    """Walk the reference through the bars; count unmatched notes on each side."""
    playable = [b for b in bars if b.length > 0]
    first = next((b for b in bars if b.notes), bars[0])
    lead = sum(float(b.length) for b in bars[: first.index])
    starts = {0.0}
    if first.notes:
        starts.add(reference[0][0] - float(first.notes[0][0]) - lead)
    end = max(t for t, _ in reference) + 1e-3
    best: list[BarResult] | None = None
    for start in starts:
        rows: list[BarResult] = []
        time, expected = start, 0
        while time < end and len(rows) < 5000:
            scored = []
            for bar in playable:
                length = float(bar.length)
                window = [n for n in reference if time - 1e-6 <= n[0] < time + length - 1e-6]
                hits = len(_matches(bar, time, window))
                ratio = hits / max(len(bar.notes), len(window), 1)
                scored.append((round(ratio, 3), bar.index == expected, bar, window, hits))
            scored.sort(key=lambda s: (s[0], s[1], -abs(s[2].index - expected)), reverse=True)
            choice = next((s for s in scored if s[2].index == expected), None)
            if choice is None or choice[0] < scored[0][0] - 0.02:
                choice = scored[0]
            _, _, bar, window, hits = choice
            rows.append(
                BarResult(bar.number, len(window) - hits, len(bar.notes) - hits, bar.ornamented)
            )
            time += float(bar.length)
            expected = bar.index + 1 if bar.index + 1 < len(bars) else 0
        if best is None or _misses(rows) < _misses(best):
            best = rows
    assert best is not None
    return best


def _misses(rows: list[BarResult]) -> int:
    return sum(r.ref_only + r.xml_only for r in rows)


def main(argv: Sequence[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    reference_dir, xml_dir, out = Path(argv[0]), Path(argv[1]), Path(argv[2])
    names = set(argv[3:])
    results = []
    for xml in sorted(xml_dir.glob("*.musicxml")):
        if names and xml.stem not in names:
            continue
        reference = midi_onsets(reference_dir / f"{xml.stem}.mid")
        rows = compare(written_bars(xml), reference)
        ref_only = sum(r.ref_only for r in rows)
        xml_only = sum(r.xml_only for r in rows)
        results.append(
            {
                "name": xml.stem,
                "ref_notes": len(reference),
                "ref_only": ref_only,
                "xml_only": xml_only,
                "bars": [asdict(r) for r in rows],
            }
        )
        matched = 100 * (len(reference) - ref_only) / max(len(reference), 1)
        print(f"{matched:6.1f}% ref_only={ref_only} xml_only={xml_only} {xml.stem}")
    out.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
