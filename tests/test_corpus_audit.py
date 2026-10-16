"""Original C/D-note examples and authored malformed bytes; repository MIT license."""

import struct
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path
from typing import cast

import pytest
from corpus_audit import attacks, midi
from corpus_audit.attacks import compare, source_attacks
from corpus_audit.classify import residuals
from corpus_audit.midi import MidiError, MidiNote, parse_midi
from corpus_audit.projection import check_projection
from corpus_audit.runner import AuditOptions, audit
from defusedxml import ElementTree as ET

from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import (
    Event,
    Glissando,
    Measure,
    NoteEndpoint,
    NoteTies,
    Ornament,
    Part,
    Pitch,
    PlaybackPreferences,
    Score,
    SlurEndpoint,
    TimeSignature,
    Voice,
)


def _midi(track: bytes, clock: int = 480) -> bytes:
    return (
        b"MThd"
        + struct.pack(">I3H", 6, 0, 1, clock)
        + b"MTrk"
        + struct.pack(">I", len(track))
        + track
    )


def test_midi_observations_preserve_patch_bank_tempo_and_performance_note_offs() -> None:
    track = (
        b"\0\xff\x51\x03\x07\xa1\x20"  # quarter120
        b"\0\xc0\x01\0\xb0\0\x02\0\xb0\x20\x03"
        b"\0\x90\x3c\x50\x78\x80\x3c\0\0\xff\x2f\0"
    )
    result = parse_midi(_midi(track))
    assert result.tempos[0].quarter_bpm == 120 and result.programs[0].value == 1
    assert [(c.number, c.value) for c in result.controls] == [(0, 2), (32, 3)]
    assert result.notes == (MidiNote(0, 0, 60, F(0), F(1, 4), 80),)


def test_running_status_and_overlapping_same_pitch_notes_are_not_deduplicated() -> None:
    result = parse_midi(_midi(b"\0\x90\x3c\x50\0\x3c\x60\x78\x3c\0\0\x3c\0"))
    assert len(result.notes) == 2
    assert [n.velocity for n in result.notes] == [80, 96]


@pytest.mark.parametrize(
    "raw",
    [
        b"MThd\0",
        _midi(b"\x80" * 5),
        _midi(b"\0\x3c\x50"),
        _midi(b"\0\x90\xff\x50"),
        _midi(b"\0\x80\x3c\0"),
        _midi(b"\0\x90\x3c\x50"),
        _midi(b"\0\xff\x51\x03\0\0\0"),
        _midi(b"", 0xE728),
    ],
)
def test_hostile_midi_fields_raise_clear_errors(raw: bytes) -> None:
    with pytest.raises(MidiError):
        parse_midi(raw)


def test_midi_allocation_and_event_caps_are_effective(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(midi, "MAX_FILE_BYTES", 8)
    with pytest.raises(MidiError, match="MiB"):
        parse_midi(_midi(b""))
    monkeypatch.setattr(midi, "MAX_FILE_BYTES", 1024)
    monkeypatch.setattr(midi, "MAX_EVENTS", 1)
    with pytest.raises(MidiError, match="event limit"):
        parse_midi(_midi(b"\0\xc0\x01\0\xc0\x02"))


def _score(events: tuple[Event, ...], *, start: F = F(0), instrument: str | None = None) -> Score:
    return Score(
        parts=(
            Part(
                "P1",
                "Authored",
                (
                    Measure(
                        1,
                        (Voice(1, events, start_offset=start, instrument_id=instrument),),
                        time=TimeSignature(4, 4),
                    ),
                ),
                instrument_id=instrument,
            ),
        )
    )


def _note() -> Event:
    return Event(F(1, 4), F(1, 4), (Pitch("C", 4, 0),))


def test_attack_comparison_excludes_note_offs_and_preserves_onset_errors() -> None:
    source = source_attacks(_score((_note(),)))
    short = MidiNote(0, 0, 60, F(0), F(1, 32), 90)
    assert len(compare(source.attacks, (short,)).matched) == 1
    wrong_onset = replace(short, onset=F(1, 2))
    result = compare(source.attacks, (wrong_onset,))
    assert len(result.missing) == len(result.extra) == 1


def test_voice_offset_silence_and_real_tie_continuity_are_preserved() -> None:
    first = replace(_note(), note_ties=(NoteTies(True, False),))
    last = replace(_note(), note_ties=(NoteTies(False, True),))
    silent = replace(_note(), playback=False)
    result = source_attacks(_score((first, last, silent), start=F(1, 4)))
    assert len(result.attacks) == 1 and result.attacks[0].onset == 1
    orphan = source_attacks(_score((_note(), last)))
    assert len(orphan.attacks) == 2


def test_source_swing_changes_only_evidenced_offbeat_timing() -> None:
    eighth = replace(_note(), duration=F(1, 8), written_duration=F(1, 8))
    score = replace(
        _score((eighth, eighth)),
        playback=PlaybackPreferences(
            F(1, 4),
            F(120),
            swing_amount=F(1),
            swing_unit=F(1, 8),
        ),
    )
    source = source_attacks(score)
    assert [a.onset for a in source.attacks] == [F(0), F(2, 3)]
    assert source.swing_shifted == 1
    assert score.parts[0].measures[0].voices[0].events[1].duration == F(1, 8)


def test_tie_sustain_and_explicit_backbeat_timing_remain_independent() -> None:
    eighth = replace(_note(), duration=F(1, 8), written_duration=F(1, 8))
    tied = replace(eighth, note_ties=(NoteTies(True, False),))
    continuation = replace(_note(), note_ties=(NoteTies(False, True),))
    score = replace(
        _score((eighth, tied, continuation)),
        playback=PlaybackPreferences(
            F(1, 4),
            F(120),
            swing_amount=F(1),
            swing_unit=F(1, 8),
        ),
    )
    source = source_attacks(score)
    assert len(source.attacks) == 2
    assert source.attacks[1].onset == F(2, 3)
    assert source.attacks[1].event_duration == F(1, 2)
    assert source.attacks[1].duration == F(3, 2)


def test_unisons_are_retained_and_require_explicit_source_routing_for_classification() -> None:
    score = _score((_note(),), instrument="source-instrument:1")
    lower = replace(score.parts[0], id="P2")
    source = source_attacks(replace(score, parts=(*score.parts, lower)))
    observed = (MidiNote(0, 0, 60, F(0), F(1), 80),)
    result = compare(source.attacks, observed)
    assert len(source.attacks) == 2 and len(result.missing) == 1
    labels = residuals(source, result, observed)
    missing = cast(list[dict[str, object]], labels["missing"])
    assert missing[0]["kind"] == "shared-instrument-unison"
    unknown = source_attacks(
        replace(
            score,
            parts=(
                replace(
                    score.parts[0],
                    instrument_id=None,
                    measures=(replace(score.parts[0].measures[0], voices=(Voice(1, (_note(),)),)),),
                ),
                replace(
                    lower,
                    instrument_id=None,
                    measures=(replace(lower.measures[0], voices=(Voice(1, (_note(),)),)),),
                ),
            ),
        )
    )
    labels = residuals(unknown, compare(unknown.attacks, observed), observed)
    assert (
        cast(list[dict[str, object]], labels["missing"])[0]["kind"] == "unison-routing-unresolved"
    )


def test_only_the_explicit_chord_principal_supplies_an_ornament_window() -> None:
    event = replace(
        _note(),
        pitches=(Pitch("C", 4, 0), Pitch("E", 4, 0)),
        ornaments=(Ornament("trill", 1, pitch_index=1),),
    )
    source = source_attacks(_score((event,)))
    assert len(source.windows) == 1 and source.windows[0].pitches == (64, 65)


def test_hidden_silent_gliss_anchor_still_bounds_a_performance_window() -> None:
    score = _score((_note(), replace(_note(), pitches=(Pitch("G", 4, 0),), playback=False)))
    gliss = Glissando(
        NoteEndpoint(SlurEndpoint(1, 1, 0), 0), NoteEndpoint(SlurEndpoint(1, 1, 1), 0)
    )
    score = replace(score, parts=(replace(score.parts[0], glissandi=(gliss,)),))
    source = source_attacks(score)
    assert len(source.attacks) == 1 and source.windows[0].pitches == tuple(range(60, 68))


def test_alignment_work_cap_is_checked_before_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_attacks(_score((_note(), _note())))
    monkeypatch.setattr(attacks, "MAX_MATCH_CELLS", 2)
    with pytest.raises(ValueError, match="allocation/work limit"):
        compare(source.attacks, (MidiNote(0, 0, 60, F(0), F(1), 80),))


def test_written_projection_preserves_silent_tie_notation_without_sound_ties() -> None:
    score = _score((replace(_note(), playback=False, note_ties=(NoteTies(True, False),)),))
    xml = ET.fromstring(to_musicxml(score))
    assert check_projection(score, xml)["source_written_notes_and_rests"] == 1
    assert xml.find(".//note/tie") is None and xml.find(".//notations/tied") is not None


def test_written_projection_detects_a_lost_unison_or_wrong_voice_offset() -> None:
    chord = replace(_note(), pitches=(Pitch("C", 4, 0), Pitch("C", 4, 0)))
    score = _score((chord,), start=F(1, 4))
    xml = ET.fromstring(to_musicxml(score))
    measure = xml.find("part/measure")
    assert measure is not None
    measure.remove(measure.findall("note")[1])
    with pytest.raises(ValueError, match="1 missing"):
        check_projection(score, xml)


def test_external_inventory_flags_midi_only_names_and_keeps_failures_visible(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corpus"
    (root / "mus").mkdir(parents=True)
    mus = root / "mus" / "broken.mus"
    mus.write_bytes(b"authored malformed MUS")
    (root / "orphan.mid").write_bytes(_midi(b""))
    before = mus.read_bytes()
    result = audit(AuditOptions(root, tmp_path / "output"))
    inventory = cast(dict[str, object], result["inventory"])
    assert inventory["midi_only"] == ["orphan"] and inventory["mus_only"] == ["broken"]
    assert result["input_hashes_unchanged"] is True and mus.read_bytes() == before
    rows = cast(list[dict[str, object]], result["cases"])
    assert cast(dict[str, object], rows[0]["failure"])["stage"] == "read_document"
    assert result["schema"] == "not run"


def test_audit_refuses_to_write_inside_the_input_corpus(tmp_path: Path) -> None:
    (tmp_path / "mus").mkdir()
    with pytest.raises(ValueError, match="read-only corpus"):
        audit(AuditOptions(tmp_path, tmp_path / "output"))
