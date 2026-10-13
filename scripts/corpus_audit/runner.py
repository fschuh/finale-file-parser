"""I/O edges for a reproducible external-corpus audit with hash manifests."""

import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

from defusedxml import ElementTree as ET

from finale_file_parser import read_document
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Score
from finale_file_parser.playback import PlaybackError

from .attacks import compare, source_attacks
from .classify import residuals
from .midi import Midi, read_midi
from .projection import check_projection


@dataclass(frozen=True)
class AuditOptions:
    root: Path
    output: Path
    schema: Path | None = None
    musescore: Path | None = None


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, Fraction):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, default=_json_default, indent=2) + "\n", encoding="utf-8")


def _by_name(paths: list[Path]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        result[path.stem].append(path)
    return dict(result)


def _observations(midi: Midi) -> dict[str, object]:
    return {
        "notes": len(midi.notes),
        "ppq": midi.ppq,
        "tracks": midi.tracks,
        "note_channels": dict(Counter(n.channel for n in midi.notes)),
        "programs": [asdict(p) for p in midi.programs],
        "controllers": dict(Counter(c.number for c in midi.controls)),
        "initial_controllers": [asdict(c) for c in midi.controls if c.onset == 0],
        "tempos": [asdict(t) for t in midi.tempos],
        "velocity_range": [
            min((n.velocity for n in midi.notes), default=0),
            max((n.velocity for n in midi.notes), default=0),
        ],
        "note_offs_compared": False,
    }


def _compare(score: Score, midi: Midi) -> dict[str, object]:
    source = source_attacks(score)
    comparison = compare(source.attacks, midi.notes)
    labels = residuals(source, comparison, midi.notes)
    return {
        "route": list(source.route),
        "quarter_length": source.length,
        "expected_attacks": len(source.attacks),
        "matched": len(comparison.matched),
        "missing": len(comparison.missing),
        "extra": len(comparison.extra),
        "source_swing_shifted_attacks": source.swing_shifted,
        "max_matched_onset_delta": max((abs(m.delta) for m in comparison.matched), default=0.0),
        "residuals": labels,
        "channel_policy": "No source channel mapping is inferred from MIDI; "
        "unisons require the explicit source instrument identity.",
    }


def _case(path: Path, midi_path: Path | None, options: AuditOptions) -> dict[str, object]:
    row: dict[str, object] = {"name": path.stem, "completed": []}
    completed = cast(list[str], row["completed"])
    stage = "read_document"
    try:
        doc = read_document(path)
        completed.append(stage)
        stage = "build_score"
        score = build_score(doc)
        completed.append(stage)
        row["diagnostics"] = [asdict(d) for d in score.diagnostics]
        row["source_features"] = _features(score)
        row["source_playback"] = asdict(score.playback) if score.playback else None
        stage = "musicxml_export"
        xml = to_musicxml(score)
        xml_path = options.output / "corrected" / (path.stem + ".musicxml")
        xml_path.write_bytes(xml)
        row["musicxml_sha256"] = hashlib.sha256(xml).hexdigest()
        completed.append(stage)
        stage = "xml_parse"
        tree = ET.fromstring(xml)
        completed.append(stage)
        stage = "ir_musicxml_projection"
        row["written_projection"] = check_projection(score, tree)
        completed.append(stage)
        if options.schema:
            stage = "musicxml_schema"
            result = subprocess.run(
                [
                    "xmllint",
                    "--nonet",
                    "--noout",
                    "--schema",
                    str(options.schema),
                    str(xml_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            (options.output / "cases" / (path.stem + ".schema.log")).write_text(result.stderr)
            if result.returncode:
                raise ValueError(result.stderr.strip())
            completed.append(stage)
        if midi_path is None:
            row["missing_midi"] = True
            return row
        stage = "midi_read"
        midi = read_midi(midi_path)
        completed.append(stage)
        row["midi_observations"] = _observations(midi)
        stage = "source_midi_comparison"
        try:
            row["comparison"] = _compare(score, midi)
            completed.append(stage)
        except PlaybackError as error:
            row["source_route_error"] = str(error)
            # An explicitly marked diagnostic linear probe is useful evidence,
            # but cannot turn an invalid source route into a passing comparison.
            probe = source_attacks(score, linear_probe=True)
            result_probe = compare(probe.attacks, midi.notes)
            row["diagnostic_linear_probe"] = {
                "matched": len(result_probe.matched),
                "missing": len(result_probe.missing),
                "extra": len(result_probe.extra),
                "route_is_source_playback": False,
            }
    except Exception as error:
        row["failure"] = {"stage": stage, "type": type(error).__name__, "message": str(error)}
    return row


def _features(score: Score) -> dict[str, int]:
    result: Counter[str] = Counter()
    for part in score.parts:
        for name in ("slurs", "hairpins", "octave_shifts", "tremolos", "glissandi", "lines"):
            result[name] += len(getattr(part, name))
        for measure in part.measures:
            result["expressions"] += len(measure.expressions)
            result["pedals"] += len(measure.pedals)
            for voice in measure.voices:
                for event in voice.events:
                    result["written_pitches"] += len(event.pitches)
                    result["grace_events"] += event.is_grace
                    result["silent_events"] += bool(event.pitches) and not (
                        event.playback and voice.playback
                    )
                    for name in (
                        "articulations",
                        "ornaments",
                        "fermatas",
                        "arpeggios",
                        "parentheses",
                        "articulation_playback",
                    ):
                        result[name] += len(getattr(event, name))
    return dict(result)


def audit(options: AuditOptions) -> dict[str, object]:
    root, output = options.root.resolve(), options.output.resolve()
    if not root.is_dir() or not (root / "mus").is_dir():
        raise ValueError("audit root must contain a mus directory")
    if output == root or root in output.parents:
        raise ValueError("audit output must be outside the read-only corpus root")
    paths = sorted(
        p for p in (root / "mus").rglob("*") if p.is_file() and p.suffix.lower() == ".mus"
    )
    midis = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".mid", ".midi"}
    )
    mus_by_name, midi_by_name = _by_name(paths), _by_name(midis)
    collisions = {
        name: [str(p.relative_to(root)) for p in group]
        for by_name in (mus_by_name, midi_by_name)
        for name, group in by_name.items()
        if len(group) > 1
    }
    if collisions:
        raise ValueError(f"ambiguous corpus filenames: {collisions}")
    output.mkdir(parents=True, exist_ok=True)
    for directory in ("corrected", "cases"):
        (output / directory).mkdir(exist_ok=True)
    hashes = {str(p.relative_to(root)): _hash(p) for p in paths + midis}
    inventory: dict[str, object] = {
        "mus": len(paths),
        "midi": len(midis),
        "pairs": len(mus_by_name.keys() & midi_by_name.keys()),
        "midi_only": sorted(midi_by_name.keys() - mus_by_name.keys()),
        "mus_only": sorted(mus_by_name.keys() - midi_by_name.keys()),
        "hashes": hashes,
    }
    _write(output / "inventory.json", inventory)
    rows = []
    for index, path in enumerate(paths, 1):
        group = midi_by_name.get(path.stem, [])
        row = _case(path, group[0] if group else None, options)
        _write(output / "cases" / (path.stem + ".json"), row)
        rows.append(row)
        _write(output / "results.json", {"inventory": inventory, "cases": rows})
        print(f"{index}/{len(paths)} {path.stem}: {row.get('failure', 'converted')}", flush=True)
    unchanged = hashes == {str(p.relative_to(root)): _hash(p) for p in paths + midis}
    summary: dict[str, object] = {
        "inventory": inventory,
        "input_hashes_unchanged": unchanged,
        "cases": rows,
        "schema": str(options.schema) if options.schema else "not run",
        "method": {
            "ordinary_onset_tolerance_quarters": 0.16,
            "grace_context_tolerance": 0.4,
            "arpeggio_tolerance": 0.75,
            "durations_compared": False,
            "source_routes_fitted_to_midi": False,
            "unisons_deleted": False,
        },
    }
    if options.musescore:
        summary["musescore"] = _import_native(options, rows)
    _write(output / "results.json", summary)
    _report(output / "report.md", summary, rows)
    if not unchanged:
        raise ValueError("corpus input hashes changed during the audit")
    return summary


def _import_native(options: AuditOptions, rows: list[dict[str, object]]) -> dict[str, object]:
    directory = options.output / "musescore"
    directory.mkdir(exist_ok=True)
    # A fresh directory prevents artifacts from a previous run from turning an
    # unsuccessful import into a false success. Preserve earlier review files.
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
    jobs = []
    names = []
    for row in rows:
        completed = cast(list[str], row["completed"])
        if "xml_parse" not in completed:
            continue
        name = str(row["name"])
        names.append(name)
        jobs.append(
            {
                "in": str((options.output / "corrected" / (name + ".musicxml")).resolve()),
                "out": [
                    str((directory / (name + ext)).resolve()) for ext in (".mscx", ".mid", ".pdf")
                ],
            }
        )
    job_path = directory / "job.json"
    _write(job_path, jobs)
    environment = os.environ.copy()
    environment.update(
        {"QT_QPA_PLATFORMTHEME": "generic", "QT_STYLE_OVERRIDE": "Fusion", "QT_IM_MODULE": "none"}
    )
    for key, leaf in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_DATA_HOME", "data"),
    ):
        environment[key] = str((directory / "profile" / leaf).resolve())
    statuses: dict[str, int | str] = {}
    for index, (name, job) in enumerate(zip(names, jobs, strict=True), 1):
        single_job = directory / "single-job.json"
        _write(single_job, [job])
        try:
            result = subprocess.run(
                [
                    str(options.musescore),
                    "-platform",
                    "offscreen",
                    "--musicxml-infer-text-type",
                    "-j",
                    str(single_job.resolve()),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            (directory / (name + ".import.log")).write_text(result.stdout + result.stderr)
            statuses[name] = result.returncode
        except subprocess.TimeoutExpired:
            statuses[name] = "timeout"
        print(f"MuseScore {index}/{len(names)} {name}: {statuses[name]}", flush=True)
    artifacts = {
        name: {ext: (directory / (name + ext)).is_file() for ext in (".mscx", ".mid", ".pdf")}
        for name in names
    }
    return {
        "process_statuses": statuses,
        "failed_processes": {name: value for name, value in statuses.items() if value != 0},
        "directory": str(directory.resolve()),
        "artifacts": artifacts,
        "complete_artifact_sets": sum(all(files.values()) for files in artifacts.values()),
        "playback_matches_reference": "not implied by successful import",
    }


def _report(path: Path, summary: dict[str, object], rows: list[dict[str, object]]) -> None:
    inventory = cast(dict[str, object], summary["inventory"])
    failures = sum("failure" in row for row in rows)
    routes = sum("source_route_error" in row for row in rows)
    text = [
        f"Corpus audit: {inventory['mus']} MUS, {inventory['midi']} MIDI, "
        f"{inventory['pairs']} stem pairs.",
        f"Pipeline failures: {failures}. Source navigation exceptions: {routes}.",
        f"Inputs unchanged: {summary['input_hashes_unchanged']}. Schema: {summary['schema']}.",
        f"MIDI-only: {inventory['midi_only']}. MUS-only: {inventory['mus_only']}.",
        "",
        "Performance note-off durations are excluded. Raw attack residuals remain visible; "
        "ornament/unison labels do not assert exact playback equivalence. Diagnostic linear "
        "probes do not replace malformed source routes.",
        "",
        "| Case | Matched | Missing | Extra | Source route / pipeline exception |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        comparison = cast(dict[str, object], row.get("comparison", {}))
        name = str(row["name"]).replace("|", "\\|")
        error = str(row.get("failure", row.get("source_route_error", ""))).replace("|", "\\|")
        text.append(
            f"| {name} | {comparison.get('matched', '')} | {comparison.get('missing', '')} "
            f"| {comparison.get('extra', '')} | {error} |"
        )
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
