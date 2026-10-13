# External MUS/MIDI audit

`make audit-corpus` converts an external corpus without copying its inputs into
git. The root must contain `mus/` and its MIDI files; pairing uses exact filename
stems and reports MIDI-only/MUS-only names. Duplicate stems are an error.

```sh
make audit-corpus AUDIT_ROOT=/path/to/ninsheetmusic \
  AUDIT_OUTPUT=files/my-audit \
  AUDIT_SCHEMA=/path/to/musicxml-4.0/musicxml.xsd \
  AUDIT_MUSESCORE=/path/to/mscore
```

The schema and player are optional. Their absence is recorded as a check that
was not run. `xmllint --nonet` needs a local schema and its dependencies. An
AppImage needs working FUSE or an already extracted executable. All Python
still runs through the repository's make/uv command surface.

Outputs include:

- `inventory.json`: exact pairing and SHA-256 hashes of every input.
- `corrected/*.musicxml`: production conversions, retaining the source names.
- `cases/*.json`: pipeline stages, IR diagnostics, written-note projection,
  source navigation, MIDI observations and every unmatched attack.
- `results.json` and `report.md`: corpus coverage and case summaries.
- Optional `musescore/run-*`: native scores, PDFs, MIDIs and per-case process
  statuses. Each score imports in a separate process with a temporary profile;
  fresh directories prevent stale artifacts from counting as successes.

The audit checks exact aggregate written pitch, onset, metric duration, grace,
tie and silence multiplicity from IR to MusicXML, including duplicate unisons.
Cue notes retain notation ties while omitting sounding ties. The production
test suite separately checks voice/staff projection and notation semantics.

MIDI comparison uses the canonical source route; it never chooses a replay
route because it happens to fit the reference. A malformed/nonterminating
route remains a source exception, with a clearly labelled diagnostic linear
probe. Playback-control UI start/stop preferences remain data rather than a
license to truncate the source to a shorter MIDI.

Per-pitch ordered matching uses ordinary onset tolerance0.16 quarters,
grace/context0.4 and arpeggio-chord context0.75. Actual rolled-pitch coverage
remains separate from the timing context. Ties are joined only when their
same-voice/pitch flags reach a contiguous source note; their notated sustain
is retained independently of explicit triplet backbeat timing. Written IR
durations and source files are never changed by this analysis.

MIDI note-off durations are deliberately excluded: performance-mode note
lengths do not identify written rhythm. Velocity, tempo, program, bank and
controller observations remain separate. Source channel/program meaning is
not guessed from those observations. Unisons are never globally deleted;
classification requires an explicit shared source instrument identity.

Trills, mordents, two-note tremolos and glissandi have source-bound performance
windows, including silent/glissando anchors. A label explains the context of
a raw residual; it does not assert identical renderer behavior. Sustain/grace
reattacks and selective swing are explicitly **candidates** needing evidence,
and unexplained events remain visible. Neither a successful exit nor valid
MusicXML means the corpus perfectly matches its performance MIDIs.

The MIDI reader caps files at16 MiB, tracks at1024 and events at1,000,000. It
bounds chunks and four-byte variable-length integers, rejects unsupported
clocks/malformed channel data and tracks overlapping note lifetimes. Source
attacks, span lookups, alignment work/allocations and residual classification
also have explicit caps. Regression tests use original C/D-note examples and
authored malformed bytes under the repository's MIT license. No external
score, font or application binary is a committed test fixture.
