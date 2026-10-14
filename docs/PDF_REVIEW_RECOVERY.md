# PDF-review recovery - 2026-10-14

All 22 approved tasks have been addressed. Source-proved omissions were fixed;
source/reference uncertainties and reproduced MuseScore limitations remain
explicit. This does not establish identical performances or perfect printed
matches for all scores. No PR or push was created.

The private audit contains the regenerated MusicXML, per-score source/MIDI
evidence, native artifacts, input/output hashes, the task/commit ledger and
97 refreshed comparison cards. Third-party scores and generated media remain
outside git under `files/ninsheetmusic-audit/`.

## Implemented recovery

| Task | Result |
|---|---|
| P01 | Recover stored clef tables and staff defaults; retain literal zero as a real clef selector. A counterexample corrected the earlier universal zero/default interpretation. |
| P02 | Keep active resting staves without adding reserved templates or inactive palette staves. |
| P03 | Join stable per-note cross-staff destinations, preserve mixed chords/voices and connect their exported staff structure. Missing destinations remain diagnostic. |
| P04 | Recover assigned font-gated cross noteheads, retaining source pitch and playback. |
| P05 | Recover explicit open notehead overrides independently of source duration and dots. Dot suppression remains unproved. |
| P06 | Decode explicit rest-beam preferences and preserve evidenced beam groups through rests. Do not create automatic groups. |
| P07 | Retain navigation drawing coordinates and distinguish passive references from real reused destinations. Native symbol positioning remains limited. |
| P08 | Recover explicit score/part staff hiding while preserving the underlying music. Cutaway/style and initial empty-staff heuristics remain separate. |
| P09 | Project explicit initial frame spacers as short printed pickups; keep ordinary delayed entries. Preserve source display labels independently of XML measure IDs. |
| P10 | Recover expression visibility/scope and explicitly cleared text while retaining independent playback controls. |
| P11 | Resolve the flagged duplicate dynamics using P10's actual hidden assignment flags; no value-based deduplication. |
| P12 | Retain manual rest positions independently of silence, visibility and metric time. Explicit visible layer rests are preserved. |
| P13 | Recover ending-label text independently of actual playback pass lists. |
| P14 | Honor per-staff ending/text-repeat print scope; preserve independent visible brackets and all playback rules. |
| P15 | Retain genuine final measures. A MIDI ending does not establish a score print boundary. |
| P16 | Reproduce native glissando geometry limitations without changing endpoint notes, voices or durations. |
| P17 | Reproduce native ornament accidental-mark omission; retain the correct typed accidental/auxiliary in IR/XML. |
| P18 | Place octave directions at their actual standard MusicXML cursor times, restoring native 15ma without changing sounding pitches. |
| P19 | Verify P18 also handles partial-bar octaves and notes already sustained in another voice. |
| P20 | Retain the exact hairpin stop and source end inset. Native ignores the tested positioning attributes. |
| P21 | Recover bounded, inert custom endpoint drawing programs through separate resource joins; retain exact parameters on canonical line endpoints. Native bracket/image rendering remains limited. |
| P22 | Pin words-only To Coda printing and its source rule/destination. Native adds a glyph even when sound is separated or absent, so no misleading workaround is shipped. |

Format offsets, independent source evidence and native experiments are recorded
in [ARCHITECTURE.md](ARCHITECTURE.md). Architectural choices are recorded in
[DECISIONS.md](DECISIONS.md). New fixtures are original authored MIT test data.

## Integration evidence

Tested code revision: `64b82307909b3a7e7af666cdf5c5f4c6c9d85f93`.

- All 105 MUS files build and export, preserve their written-note projection
  and validate against the official MusicXML 4.0 schema.
- All 105 MIDI files have a MUS partner; no unmatched filenames remain.
  All 210 MUS/MIDI hashes and 25 reviewed source-PDF hashes are unchanged.
- All 105 have fresh native MSCX, MIDI and PDF artifacts that parse. MuseScore
  4.7.5 first exited -11 on MAP 2 Overworld before completing its PDF; the exact
  same XML passed with a fresh process/profile. Both attempts are recorded.
- `make check`: 2,491 passed, 7 skipped. `make check-full`: 2,491 passed,
  177 skipped. Unavailable licensed repository-corpus fixtures account for the
  additional skips; the external 105-score audit was run separately.
- 83 pairs have no raw attack residuals under the performance-aware model.
  17 retain differences, and five have unresolved source navigation policies.
  Previously compared pairs retain exactly their prior attack counts.
  The added Vampire Killer reference contributes 646 matched attacks, 0/0
  residuals. The existing 317 source-only / 321 MIDI-only residuals remain.

These counts do not assert equal note-offs, tempo curves, velocities,
controllers or renderer playback. Context labels retain the raw discrepancies;
they are not automatic exemptions or newly established parser defects.

## Remaining limits

MuseScore still ignores tested bracket/hairpin endpoint geometry, arbitrary
endpoint SVG directions and ornament accidental marks. Some overlapping
glissandi remain contracted. It infers an extra coda glyph from To Coda words
and a dashed tempo-change line from legitimate accel. text. It also has
separate repeat/pass and ornament-playback limitations. Preserve correct source
data rather than change notes, text, timing or navigation to fit these behaviors.

Manual rest geometry is retained, but native multivoice rest consolidation and
unproved layer/style print policies still prevent some PDF matches. Uncover
Secret has a genuine second source measure; the selected print configuration
or reference-version difference remains unproved. Athletic Theme's PDF is a
different arrangement.

The final review also corrects an earlier overly broad statement about Spring
Yard Zone 27. Source staff 1/layer 1 entries 6368-6373 contain F5 quarter, F5
quarter, E5 eighth, F5 eighth, E5 eighth, D5 eighth (last accented), without
per-entry ignore flags. The full eighth-note run is absent from the supplied
PDF. Layer 2 independently contains F4 half, C#6 dotted quarter, D6 eighth.
Both voices were already present before these fixes. The exact print-scope or
reference-version explanation is unproved; preserve and flag those source
notes instead of deleting them.

Five literal navigation policies remain outside passing playback comparisons:
Terra, MAP 7 Special, Death Mountain and Spear of Justice use unresolved target
zero rules; Crash Man's 32-to-9 / 16-to-33 / 40-to-9 controls form a literal
cycle. Printed signs and a reference performance cannot establish their hidden
sentinel/counter/reset semantics.
