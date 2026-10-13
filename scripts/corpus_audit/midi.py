"""Bounded Standard MIDI File reader for audit observations, not score inference."""

from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 1_000_000


class MidiError(ValueError):
    """Unsupported or malformed MIDI, with no partial-success result."""


@dataclass(frozen=True)
class MidiNote:
    track: int
    channel: int
    pitch: int
    onset: Fraction
    duration: Fraction
    velocity: int


@dataclass(frozen=True)
class MidiControl:
    track: int
    channel: int
    onset: Fraction
    number: int
    value: int


@dataclass(frozen=True)
class MidiProgram:
    track: int
    channel: int
    onset: Fraction
    value: int


@dataclass(frozen=True)
class MidiTempo:
    onset: Fraction
    quarter_bpm: Fraction


@dataclass(frozen=True)
class Midi:
    ppq: int
    tracks: int
    notes: tuple[MidiNote, ...]
    controls: tuple[MidiControl, ...]
    programs: tuple[MidiProgram, ...]
    tempos: tuple[MidiTempo, ...]


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def take(self, length: int) -> bytes:
        if length < 0 or length > len(self.data) - self.position:
            raise MidiError("truncated MIDI field or chunk")
        result = self.data[self.position : self.position + length]
        self.position += length
        return result

    def number(self, length: int) -> int:
        return int.from_bytes(self.take(length), "big")

    def vlq(self) -> int:
        value = 0
        for _ in range(4):
            byte = self.number(1)
            value = (value << 7) | (byte & 127)
            if not byte & 128:
                return value
        raise MidiError("MIDI variable-length integer exceeds four bytes")

    @property
    def finished(self) -> bool:
        return self.position == len(self.data)


@dataclass
class _Observation:
    notes: list[MidiNote]
    controls: list[MidiControl]
    programs: list[MidiProgram]
    tempos: list[MidiTempo]
    events: int = 0


def read_midi(path: Path) -> Midi:
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    return parse_midi(data)


def parse_midi(data: bytes) -> Midi:
    if len(data) > MAX_FILE_BYTES:
        raise MidiError("MIDI exceeds the 16 MiB audit limit")
    reader = _Reader(data)
    if reader.take(4) != b"MThd":
        raise MidiError("MIDI header is missing")
    header = _Reader(reader.take(reader.number(4)))
    mode, tracks, ppq = (header.number(2) for _ in range(3))
    if mode not in {0, 1} or not 1 <= tracks <= 1024 or (mode == 0 and tracks != 1):
        raise MidiError("unsupported MIDI format or track count")
    if ppq == 0 or ppq & 0x8000:
        raise MidiError("audit requires a positive PPQ MIDI clock")
    observed = _Observation([], [], [], [])
    for track in range(tracks):
        if reader.take(4) != b"MTrk":
            raise MidiError("MIDI track header is missing")
        _track(_Reader(reader.take(reader.number(4))), track, ppq, observed)
    if not reader.finished:
        raise MidiError("unexpected data after the declared MIDI tracks")
    return Midi(
        ppq,
        tracks,
        tuple(observed.notes),
        tuple(observed.controls),
        tuple(observed.programs),
        tuple(observed.tempos),
    )


def _track(reader: _Reader, track: int, ppq: int, observed: _Observation) -> None:
    tick = 0
    running: int | None = None
    active: dict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
    while not reader.finished:
        observed.events += 1
        if observed.events > MAX_EVENTS:
            raise MidiError("MIDI exceeds the audit event limit")
        tick += reader.vlq()
        byte = reader.number(1)
        if byte < 128:
            if running is None:
                raise MidiError("MIDI running status has no preceding channel event")
            reader.position -= 1
            status = running
        else:
            status = byte
        onset = Fraction(tick, ppq)
        if status == 0xFF:
            kind, payload = reader.number(1), reader.take(reader.vlq())
            if kind == 0x51:
                if len(payload) != 3 or not int.from_bytes(payload, "big"):
                    raise MidiError("invalid MIDI tempo event")
                observed.tempos.append(
                    MidiTempo(onset, Fraction(60_000_000, int.from_bytes(payload, "big")))
                )
            running = None
        elif status in {0xF0, 0xF7}:
            reader.take(reader.vlq())
            running = None
        elif 0x80 <= status < 0xF0:
            running = status
            kind, channel = status >> 4, status & 15
            args = reader.take(1 if kind in {0xC, 0xD} else 2)
            if any(a > 127 for a in args):
                raise MidiError("invalid MIDI channel data byte")
            if kind == 9 and args[1]:
                active[channel, args[0]].append((tick, args[1]))
            elif kind in {8, 9}:
                if not active[channel, args[0]]:
                    raise MidiError("MIDI note off has no active note")
                start, velocity = active[channel, args[0]].popleft()
                observed.notes.append(
                    MidiNote(
                        track,
                        channel,
                        args[0],
                        Fraction(start, ppq),
                        Fraction(tick - start, ppq),
                        velocity,
                    )
                )
            elif kind == 0xB:
                observed.controls.append(MidiControl(track, channel, onset, args[0], args[1]))
            elif kind == 0xC:
                observed.programs.append(MidiProgram(track, channel, onset, args[0]))
        else:
            raise MidiError(f"unsupported MIDI system status 0x{status:02x}")
    if any(active.values()):
        raise MidiError("MIDI track ends with active notes")
