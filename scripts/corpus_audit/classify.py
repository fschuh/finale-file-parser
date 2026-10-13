"""Contextual residual labels preserve raw mismatches and uncertainty."""

from dataclasses import asdict
from fractions import Fraction

from .attacks import Attack, Comparison, SourceAttacks
from .midi import MidiNote


def _window(source: SourceAttacks, pitch: int, onset: Fraction) -> str | None:
    for window in source.windows:
        margin = Fraction(2, 5) if window.kind == "glissando" else Fraction(1, 8)
        if pitch in window.pitches and window.start - margin <= onset <= window.end + margin:
            return window.kind
    return None


def residuals(
    source: SourceAttacks, comparison: Comparison, notes: tuple[MidiNote, ...]
) -> dict[str, object]:
    missing = []
    extra = []
    if (len(comparison.missing) + len(comparison.extra)) * (
        len(source.windows)
        + len(comparison.matched)
        + len(comparison.missing)
        + len(comparison.extra)
    ) > 8_000_000:
        raise ValueError("residual classification exceeds the audit work limit")
    end = max((n.onset + n.duration for n in notes), default=Fraction(0))
    for attack in comparison.missing:
        kind = _missing_kind(source, comparison, attack, end)
        missing.append({"kind": kind, "source": asdict(attack)})
    for note in comparison.extra:
        extra_kind = _extra_kind(source, comparison, note)
        extra.append({"kind": extra_kind, "midi": asdict(note)})
    return {"missing": missing, "extra": extra}


def _extra_kind(source: SourceAttacks, comparison: Comparison, note: MidiNote) -> str:
    window = _window(source, note.pitch, note.onset)
    if window is not None:
        return window
    # Candidate contexts retain the raw residual and require review; they are
    # not exemptions that turn unknown attacks into a perfect match.
    if any(
        a.pitch == note.pitch
        and a.onset != a.metric_onset
        and abs(float(a.metric_onset - note.onset)) <= 0.16
        for a in comparison.missing
    ):
        return "selective-swing-realization-candidate"
    if any(
        m.source.grace
        and m.source.pitch == note.pitch
        and abs(float(m.source.onset - note.onset)) <= 0.4
        for m in comparison.matched
    ):
        return "grace-reattack-candidate"
    if any(
        m.source.pitch == note.pitch
        and not m.source.grace
        and m.source.onset <= note.onset < m.source.onset + m.source.duration
        for m in comparison.matched
    ):
        return "sustain-reattack-candidate"
    return "unexplained"


def _missing_kind(
    source: SourceAttacks, comparison: Comparison, attack: Attack, reference_end: Fraction
) -> str:
    if _window(source, attack.pitch, attack.onset) == "two-note-tremolo":
        return "two-note-tremolo"
    if attack.grace and _window(source, attack.pitch, attack.onset) == "glissando":
        return "glissando-grace-anchor"
    if attack.onset != attack.metric_onset and any(
        n.pitch == attack.pitch and abs(float(n.onset - attack.metric_onset)) <= 0.16
        for n in comparison.extra
    ):
        return "selective-swing-realization-candidate"
    peers = [
        m.source
        for m in comparison.matched
        if m.source.pitch == attack.pitch
        and m.source.onset == attack.onset
        and not m.source.grace
        and not attack.grace
    ]
    if peers:
        if attack.instrument is not None and any(p.instrument == attack.instrument for p in peers):
            return "shared-instrument-unison"
        return "unison-routing-unresolved"
    if attack.onset > reference_end and source.length > reference_end:
        return "reference-ended-before-source-route"
    return "unexplained"
