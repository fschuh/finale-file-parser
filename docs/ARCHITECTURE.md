# Architecture

How the system is shaped. Keep this current as the design settles — a fresh session reads this before
working on structure.

## Overview

The system consists of a parser library that reads Finale `.mus` and `.musx` files and exports
MusicXML, plus a diagnostic frontend built from two functions:

- **A diagnostic view of the source and decoded structure** — delivered as `finale-parser inspect
  --report`, a self-contained HTML report (`src/finale_file_parser/report/`) rather than a desktop
  application: the stage ladder, score and document summaries, every decoded record, and the raw
  bytes — each pool embedded whole and paged through 4 KB at a time. A `.musx` report also carries
  its complete EnigmaXML in a foldable XML tab; a binary `.mus` has no source XML, so that tab is
  absent. See
  `docs/DECISIONS.md`'s 2026-08-04 entry for why this shape was chosen over a GUI, and
  `docs/superpowers/specs/2026-08-04-diagnostic-frontend-design.md` for the full design.
- **A rendering of the corresponding music notation** — the report's Music tab sends the shared
  `Score` through the existing MusicXML exporter and engraves it with Verovio as bounded inline SVG.
  Engraving is a non-halting report stage: if it fails, records, XML and diagnostics still render.

Because parsing supports multiple inputs, all data flows into a single intermediate representation
(IR). The library stays independently usable and takes no GUI dependency.

## Modules

<!-- List the top-level modules under src/ and the single responsibility of each. -->

- `src/` — the main source directory.
- `src/finale_file_parser/version/` — identifies which Finale version wrote a file, before any
  record parsing. `models.py` (types), `family.py` (magic → family), `mus.py` (banner parsing),
  `musx.py` (archive metadata), `detect.py` (public entry).
- `src/finale_file_parser/container/` — owns all `.musx` archive access. `models.py`
  (`ContainerEntry`, `CorruptContainerError`), `names.py` (member-name safety), `musx.py`
  (`open_musx`, `MusxContainer`). `version/musx.py` is a client of this module; nothing else
  opens archives directly.
- `src/finale_file_parser/reader.py` — the small application-facing facade. `read_document(path)`
  detects the container family from file contents and returns the shared `EnigmaDocument`;
  `read_score(path)` adds the single `build_score` step and returns the format-neutral IR. It does
  not translate exceptions or dispatch by filename suffix.
- `src/finale_file_parser/enigma/` — decodes a `.musx`'s `score.dat` into EnigmaXML and parses that
  EnigmaXML into a navigable document. `crypt.py` (the cipher, pure — no I/O), `models.py`
  (`CorruptScoreError`), `score.py` (`score_xml`, composing `container.open_musx` with the cipher
  and a capped inflate), `document.py` (`parse_enigma`, `EnigmaDocument`, `Pool`, `Record` — the
  uniform record/pool model), `music.py` (`read_entry`, `Entry`, `Note`, `Duration` — the first
  typed layer over the generic `entry`/`note` records), `location.py` (`locate_entries`,
  `EntryLocation`, `MalformedScoreError` — the first cross-pool link resolution, placing each entry
  in every staff/measure that displays it and computing the raw key signature in force),
  `percussion.py` (`percussion_notes` — resolves a selected staff percussion map to its assigned
  notes while preserving unresolved appearances), `key.py` (`decode_key`,
  `KeySignature`, `Mode`, `UnsupportedKeyError` — decodes the raw `keySig.key` integer into fifths,
  mode, and tonic). See "Known format facts — score.dat", "Known format facts — EnigmaXML
  structure", "Known format facts — entries and pitch", "Known format facts — score linkage",
  "Known format facts — percussion mapping", and "Known format facts — key signatures" below.
- The same package holds the legacy `.mus` readers, which produce the same types from the other
  container: `mus_payload.py` (`read_mus_payload`, `read_mus_streams` — the two eras' codecs),
  `mus_entries.py` (`read_mus_entries` — the entry pool), `mus_others.py` (`read_mus_others`,
  `MusOther` — the `others` pool as tagged, self-identifying records), `mus_details.py`
  (`read_mus_details`, `MusDetailRecord` — the `details` pool, the same shape with a two-cmper key),
  and `mus_document.py` (`read_mus_document` — the adapter that turns those pools into an
  `EnigmaDocument`, which is what lets one IR builder and one exporter serve both containers). See
  the "Known format facts — … `.mus` …" sections below.

### Known format facts — version

- `.mus` begins with `ENIGMA BINARY FILE` at offset 0, identical across Finale 2001–2012. The
  writing version is an ASCII banner at offset `0x20`, e.g.
  `Finale(R) 2011 Copyright (c) 1987-2010 MakeMusic Inc.`
  Evidence: 238 corpus files; see `docs/superpowers/specs/2026-07-21-version-detection-design.md`.
- That banner field is fixed-size and is **not** zero-filled on rewrite, so a shorter banner can
  leave a tail of the previous, longer one behind (observed: `logy` from the Finale 2004 Coda
  banner surviving into a 2005 file). Always cut at the first NUL.
- `.mus` carries two provenance stamps (date, application, platform) at fixed offsets: created —
  date `0x66`, application tag `0x70`, platform tag `0x74`; modified — date `0x8C`, application tag
  `0x96`, platform tag `0x9A`. The date is `[year - 1900, month, day]` as three `u8`. Present in
  238/238 corpus files, with `created <= modified` in all of them. **Platform is recoverable from
  `.mus`, not `.musx`-only** (see the correction note in
  `docs/superpowers/specs/2026-07-21-version-detection-design.md`, which had claimed otherwise).
  Corpus tally: `MAC` in 136 files, `WIN` in 102.
- Both formats produce the same provenance type, `ProvenanceStamp` (date, application, platform,
  plus `modified_by` and `app_version`) — see the 2026-07-22 "one provenance type for both formats"
  decision in `docs/DECISIONS.md`. `.musx`'s stamps are a strict superset of `.mus`'s: `.mus` always
  leaves `modified_by` and `app_version` at their defaults, `.musx` fills both. `MusxDetail.platform`
  was removed; platform now lives on each stamp, matching `.mus`'s rule that both stamps must not be
  assumed to agree.
- 89 of the 136 `MAC` `.mus` files (0 of the 102 `WIN` files) end in a **macOS plist trailer**
  occupying the last 1-3% of the file (938-1694 bytes) — apparently appended OS-level metadata.
  Not parsed; recorded so the next investigation starts from it.
- **A hypothesis that did not survive testing:** `.mus` was suspected to share `.musx`'s
  record-type numbering (`10001`, `10002`, ...). Scanning all 238 files for those values as aligned
  little-endian `u16` gave occurrence rates close to the chance baseline expected in files dense
  with small integers and zero runs. The hypothesis is **not supported** — recorded here so it is
  not re-derived from the same coincidence.
- `.mus` has **no member table** — it is a monolithic binary with no directory and no confirmed
  record framing, unlike `.musx`. There is no container abstraction to build for it; locating any
  internal record pools remains open-ended research.
- `.musx` is a zip with `mimetype` = `application/vnd.makemusic.notation`. Version data lives in
  `NotationMetadata.xml` as plaintext, with separate `created` and `modified` blocks. **`modified`
  is the layout authority** — 267 of 401 corpus files were created by major=16 but last written by
  major=18, and **370 of 401 diverge between the `created` and `modified` majors at all** (not only
  the 16-to-18 case). (The 2026-07-21 design spec recorded the first figure as 264; a direct corpus
  measurement pinned in
  `tests/version/test_corpus_sweep.py::test_musx_modified_over_created_divergence_still_holds`
  found 267 (and asserts 370 alongside it). The spec is left as originally written per this
  project's practice of not rewriting a spec's history; this figure is corrected here since
  `ARCHITECTURE.md` is the current source of truth.)
- `score.dat` is obfuscated high-entropy data. Version detection never reads it.
- The `.musx` `major` version number (15/16/17/18) has no established mapping to Finale's
  marketing years (2009/2011/2012/2014...). Nothing in the corpus bridges the two schemes, so
  version labels report the raw major/maint/build instead of a year. Open question.
- `scripts/build_version_fixtures.py` strips `NotationMetadata.xml` down to only the root
  `version` attribute and the `created`/`modified` subtrees, building the output tree fresh so any
  field not explicitly listed is absent by construction. Every attribute on every element within
  those subtrees is also stripped (an allowlist of zero attributes — none are read by version
  detection, so none are kept), and every `<modifiedBy>` is blanked rather than dropped. This is
  deliberate: the corpus metadata carries `title`, `subtitle`, `composer`, `arranger`, `lyricist`,
  `copyright` (including a MakeMusic notice restricting commercial redistribution), and
  `modifiedBy` — non-empty in 28 of the 802 `created`/`modified` blocks across the corpus (14
  files), where it holds real people's initials — plus attributes such as `<created author="...">`
  that could carry the same kind of identifying data. `modified_by` is exposed through
  `ProvenanceStamp` for parsing, but every committed fixture's `<modifiedBy>` stays blanked. Do not
  loosen this filter to pass through more fields or attributes.

### Known format facts — the .musx container

Evidence: all 401 corpus archives, surveyed 2026-07-21. See
`docs/superpowers/specs/2026-07-21-musx-container-design.md`.

- A `.musx` is a zip. `mimetype` is always the **first** member and always **stored
  uncompressed** (401/401) — the ODF/EPUB convention. Member order is structural; do not
  assume alphabetical. This is an *observed* fact, asserted of the fixtures and the corpus by
  tests — `open_musx` deliberately does not enforce `mimetype`'s position or its compression
  method, so a future Finale variant that reorders members stays inspectable rather than being
  rejected outright.
- Members observed: `mimetype`, `META-INF/container.xml`, `NotationMetadata.xml`, `score.dat`,
  `presets/<n>.preset`, `graphics/<n>.jpg`. Archives embed images, so container content is not
  limited to notation.
- Member count 5-10; per-archive uncompressed total 89 KB - 420 KB; `score.dat` 86 KB - 413 KB.
- 22 distinct **ordered sequences of member names**. This is measured by name and order only —
  not by (name, size, compress method) — because size and method vary between archives that share
  the same name sequence, which would otherwise inflate the count. Comparing *sorted* name sets
  instead of ordered sequences gives 18 and discards ordering, which is meaningful here: this
  distinction caused a real bug during implementation.
- `score.dat` is high-entropy obfuscated data and barely compresses. It is extracted, never
  interpreted, at this layer.
- No corpus archive has duplicate or unsafe member names, so the reader's safety checks cannot be
  exercised by real files — they are covered by synthetic hostile input and verified by mutation.

### Known format facts — score.dat

Full reference, evidence, and derivation: `docs/formats/score-dat.md`. Headline: `score.dat` is
encrypted with a keystream from a fixed-seed BSD `rand()` linear congruential generator that resets
every 128 KiB; the decrypted plaintext is a gzip stream that inflates roughly 28× into EnigmaXML.
Verified against all 401 corpus archives: 401/401 decode, every result is schema `version="18.0"`.
The cipher parameters are not this project's discovery — see the attribution in
`docs/REFERENCES.md` and the DECIDED entry in `docs/DECISIONS.md`.

### Known format facts — the legacy `.mus` payload

Full reference, evidence, and the false starts: `docs/formats/mus-binary-notes.md`. Headline: a `.mus`
file is a plaintext header followed by a **compressed** payload, and the codec depends on the era.

| banner year | files | payload | offset |
| --- | --- | --- | --- |
| 2001–2005 | 139 | **chain of PKWARE DCL "implode"** records, `lit=0`, `dict=4`, 4 per file | first at `0x200` |
| 2011–2012 | 99 | **chain of consecutive zlib streams**, ~4 per file | first at `0x216` (2 files `0x20A`) |

Verified against every `.mus` in the corpus: **238/238 decode**. Inflation is 3.25×–4.51× for the DCL
chain and 5.87×–8.63× for the concatenated zlib chain; decoded payloads run 32,816–699,585 bytes.

**The DCL era labels its pools; the zlib era does not.** Each DCL record is `[u16 kind][u32 length,
header included][u32 checksum][DCL stream]`, laid end to end from `0x200` to the last byte of the
file, with `kind` 15 others, 16 details, 17 entries, 18 text. A `length` of exactly 6 means the pool
is empty. Byte order is the writing platform's — 102 little-endian, 37 big-endian — and it is read
off the first record's kind rather than assumed. All 139 tile exactly. The old fixed `0x20A` was
`0x200` plus one ten-byte header, which is why decoding there worked and returned only the first
pool of four. Full reference: `docs/formats/mus-dcl-container.md`.

Two practical notes that cost real time to learn:

- **Locate zlib streams by header, not by offset.** The preamble ahead of the first stream is
  variable-length. `enigma/mus_payload.py` validates a candidate with zlib's own rule — low nibble 8,
  and the two header bytes a multiple of 31 — rather than matching the literal `78 9c` pair, which
  would miss any file written at another compression level.
- **A raw inflate at an arbitrary offset can hit a DEFLATE *stored* block** and return a verbatim copy
  of its input, which looks exactly like a large successful decode. Any offset-scanning decoder needs
  to reject that explicitly.

The decoded payload is **not** EnigmaXML and is not yet parsed into records; that is the next step.
`docs/eeppd.txt` and `docs/etfspec.pdf` give the record *semantics*, but their ETF field order and
widths do not transfer to the binary layout — see the notes for the two experiments that establish it.

The PKWARE DCL format knowledge is not this project's discovery — see the attribution in
`docs/REFERENCES.md` and the DECIDED entry in `docs/DECISIONS.md`.

### Known format facts — staff names and file info

**A staff does not carry its own name.** `staffSpec.fullName` holds a number, and reaching the string
takes *two* hops:

```
staffSpec.fullName → others.textBlock[cmper] → textID → texts.blockText[number] → the text
```

Going straight from `fullName` to `blockText` resolves **nothing** — all 24 named staves in the sampled
corpus fail that way, because the two numbers live in different spaces. That failure is silent: the
exporter simply falls back to "Staff N", which looks like valid output.

The text is Enigma's tagged markup (`^fontid(9)^size(12)^nfx(0)Voice`) and also carries **inserts** —
`^title()`, `^partname()` — which are placeholders resolved at render time, not literal text.
`plain_text` strips both, so a block consisting only of inserts correctly yields an empty string.

**Most staves are unnamed:** 24 of 84 in the sample carry a name. `staff_names` omits the rest rather
than returning blanks, so a caller can tell "unnamed" from "named blank" and choose its own fallback.

`fileInfo` records in the texts pool hold **title, composer, copyright and description** as literal
strings, with no indirection and no markup.

## The IR and exporters

`docs/DECISIONS.md` (2026-07-20) settles the shape: readers produce a **format-neutral IR**, exporters
consume one, and neither knows the other. The dependency runs one way only:

```
container ──▶ enigma ──▶ enigma/to_ir ──▶  ir  ◀── export/musicxml
                                          (knows nobody)
```

`finale_file_parser/ir.py` imports nothing from `enigma` or `container`. A `.mus` reader added later
produces the same `Score` and every exporter keeps working — which is the whole point of paying for the
extra hop rather than exporting from `EnigmaDocument` directly.

The decision's other consequence shapes the types: **MusicXML's limits must not constrain the IR.**
Durations are exact `Fraction`s of a whole note, not MusicXML integer divisions, and a `Voice` keeps its
source layer number rather than a MusicXML voice index. The exporter picks a divisions value per part by
taking the LCM of the durations' denominators — a triplet eighth is 1/12 of a whole note, so a
power-of-two divisions count truncates it to zero.

**Naming collision worth knowing about:** `ir.TimeSignature` and `enigma.timesig.TimeSignature` are
different types — conventional beats/beat-type versus Enigma's beats/division-EDU. The IR types are
deliberately *not* flattened into the package root for that reason; import them from
`finale_file_parser.ir`.

### Individual note ties in a chord

`tieStart` and `tieEnd` belong to each source `note`, not its containing `entry`.
The legacy entry reader already decodes them separately. Reducing them to `any(...)`
on an IR event and applying that flag to every pitch invents ties on otherwise untied
chord tones. The local Scars of Time comparison exposed four copied starts (upper
staff, measures 52 and 56) and one copied stop (lower staff, measure 54); the PDF
corroborates the partial upper-staff ties.

`Event.note_ties` carries one `NoteTies(start, stop)` per pitch in the same order.
Readers include explicit false flags. MusicXML emits both sounding `<tie>` and
visual `<tied>` from these individual flags. `Event.tie_start` and `tie_end` remain
aggregate summaries for existing callers; authored events with an empty `note_ties`
retain their previous event-wide export behavior. A nonempty tuple of the wrong
length raises `ExportError`. No pairing repair is attempted: the source can contain
unmatched flags, as noted under "three things that are not invariants" below.

### Known format facts — pickup display and numbering (2026-10-14, P09)

#### Expression printing and assignment scope (2026-10-14, P10/P11)

Numeric177's complete24-byte assignment slots have their flag word at+10.
FCExpression::GetID1A1824 reads object+38, anchoring serialized offset0;
GetVisible1A3DEC inverts mask0x4000 at object+42(+10), while
GetScoreAssignment1A201C and GetPartAssignment1A12E4 invert0x1000/0x0800.
The [published FCExpression API](https://pdk.finalelua.com/class_f_c_expression.html)
independently distinguishes visibility from score/part assignment. These bits
are also separate from the previously established0x2000 shape-assignment bit.
Normalized XML `hidden` and showStaffList=`scoreOnly`/`partOnly` have their
published [musxdom factory meanings](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsOthers.cpp).
Score-specific and linked-part records remain independent. Unsupported typed
scope values raise a clear source error, including nonscalar values.

Canonical Expression.visible, score_assignment and part_assignment retain
these independent facts. Hidden expressions retain their typed controls and
original rhythmic offsets; part-only assignments retain their source data but
do not execute or print in the score. A hidden real-staff copy cannot swallow
a visible staff-list copy in the pre-existing redundancy check. Swing display
deduplication also distinguishes visibility. Intentionally independent real
staff assignments remain distinct. Hidden controls serialize with standard
other-direction print-object=no and independent sound; hidden explicit tempo
keeps the prior rate projection, including untyped explicit metronomes.

Air Man's expression61 names a pppp description and amplitude0, but its actual
textBlock12 explicitly stores textID0 (numeric183+0). This is a cleared printed
text, not a missing text record or permission to fall back to the unrelated
expression section12. Preserve its mute instruction while suppressing the
description-derived printed dynamic. An actually missing reference still keeps
the prior description-based graded-symbol recovery. Explicitly resolved blank
text is likewise distinct from unavailable text. Assigned typed controls with
no printed text now survive as hidden controls instead of disappearing.

Opening19's Coraggioso assignment has flags0x4200: its text is hidden and its
tempo180 remains active. Battle's lower mp/ff/f at1/11/27 and Slider's lower f
at1 also have the hidden bit; Slider's quarter-note-later offset is unchanged.
The duplicated glyphs therefore need no coincident-position or value-dedup
workaround (P11 reassessment). Native imports show only the intended upper
dynamics. Four targeted projection/schema/native checks have unchanged attack
comparisons; an authored native hidden-tempo fixture retains120BPM and an
invisible Tempo object, with no printed mark. All105 scores build/project.

**Native limit:** Opening's extra dashed continuation at16-19 is a synthesized
GradualTempoChange from its correctly printed accel. at13. It is not an assigned
source line at16-19. Its native MSCX records an accelerando span ending19; the
standard XML contains accel. words and no such source bracket. Retain the
legitimate words and separate this importer inference from P21 source geometry.
The real visible graphical/custom lines retain their source endpoints (for
example smartShape38 is within bar6); they are not deleted to hide the native
continuation. No whole-source/PDF perfect-match claim follows from this fix.

A legacy pickup is represented by a separate frame incidence containing
startTime before the incidence containing its entries. This is the documented
spacer mechanism in [musxdom's Frame](https://github.com/openmusx/musxdom/blob/main/src/musx/dom/Others.h)
and GFrameHoldContext::calcMinLegacyPickupSpacer (Entries.cpp): take the minimum
spacer among populated layers/staves, including a zero from an unspaced real
layer. Empty default-rest staves do not supply a real frame. The numeric/DCL
adapters already merge these incidences; they now retain `legacySpacer` to
distinguish that mechanism from an ordinary combined frame startTime delay.
Do not infer a pickup merely because a first bar is incomplete or notes start
late. Only the initial score measure receives the global printed spacer.

Battle stores2048EDU and Maya/Koopa3584EDU in their real pickup frame spacers.
Hikari instead encodes an actual1/4 opening meter and has no spacer; that
construction is unchanged. The separate [FCMiscDocPrefs pickup duration](https://pdk.finalelua.com/class_f_c_misc_doc_prefs.html)
is not a prerequisite for legacy pickups: its getter0x54745A reads object+80,
allocated base3A, and the MI conversion table maps offset46 to preference71
(numeric85), incidence0, word2. All four controls store0 there, consistent
with the independently documented legacy-spacer mechanism.

Canonical Measure.leading_spacer preserves the raw frame clock, and every
written pitched event retains its original onset, metric duration and voice.
The MusicXML view omits that nonmusical space from voice starts and timed
attachments uniformly, shortening only generated whole-measure default rests.
A real event before the spacer or a timed control inside it is an export error,
not a clamp or deletion. Measure-wide offset0 controls still apply at the
printed start. Hairpin/octave/custom-line endpoints share the translation;
note-index slur/tremolo/glissando endpoints retain their identity. Source IR is
immutable. The written-projection audit independently subtracts the explicit
spacer and checks default-rest extent, as well as every pitched note/tie/cue.

The Unicode measure-number-region body is numeric tag164, 350 bytes padded to
360 in the record pool. FCMeasureNumberRegion's vtable0x6E21C8 allocation
getter0x4B9962 selects object+1D6 for this era. GetStartMeasure4BCD46,
GetEndMeasure4BCD8C and GetStartNumber4BCDD6 independently establish offsets
140,142(exclusive),150(stored numberOffset, display adds1). Start character,
base, prefix, suffix and flags are at144(u16),148(u16),152/248(96-byte Unicode
arrays),344(u16). Their getters and decimal/time policy are separately visible
in the SDK disassembly. Only this exact body is decoded; older/newer region
layouts remain raw. All four controls select measures2..999 with decimal
character48/base10/offset0/flags0x82 and empty affixes, independently proving
the first full bar's printed1. Exotic styles/affixes/time policies remain
diagnostics rather than inferred decimal labels; region count is capped256.

measSpec's common flag word+10 mask0x1000 is `noMeasNum`: FCMeasure's
GetIncludeInNumbering28AA2E inverts that bit through the already established
MeFlag pointer. Excluded measures do not advance a region's counter. First
matching source region wins, matching the published region-selection rule.
Canonical display_number is independent of the source measure identity;
MusicXML number/implicit print the label, while unique source-measure IDs keep
the audit's original numbering. Navigation actions still use the original
identities before final label serialization. Bundling and source timing remain
unchanged. Native authored fixtures show pickup attacks at0 and1/2q versus
ordinary delayed attacks at3 and7/2q. Four target source/projection/schema/native
checks and the105-file build/projection smoke pass with unchanged source/MIDI
attack counts. Initial default-rest visibility remains the separate P12 policy.

### Known format facts — clefs

#### Explicit staff hiding (2026-10-14, PDF review P08)

The numeric staffSpec (231) 84/96-byte layouts carry `moreFlags` at +44.
Mask 0xC000 is independent of line/staff-element flags: 0 is normal, 0x4000
is hide in score, 0x8000 is hide in score and parts, and 0xC000 is cutaway.
The independent [FCStaff API](https://pdk.finalelua.com/class_f_c_staff.html)
defines these four policies. RGP's read-only `__FCStaffBase::GetHideMode`
disassembly (0x4BF132) masks that word and returns the corresponding enum;
FCStaff vtable0x6E4218+0x128 selects getter0x10CE70, which adds0x2C to
version-specific serialized storage. Its older pre-2011 path uses a different
flag, so neither older/unknown sizes nor DCL payloads receive this interpretation.
Normalized XML `hideMode` values (`score`, `scoreParts`, `cutaway`) are also
independently established by [musxdom's staff factory](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsOthers.cpp).

Air Man's staves3-6 and Crash Man's staff3 store0x641F versus the visible
staves1/2's0x241F. Their score-system instUsed lists independently select only
staves1/2, matching the source's hide-in-score policy. Score and linked-part
definitions remain separate. Canonical `Part.staff_hide_mode` retains the
explicit policy without removing music, measure rests, voices or playback.
Cutaway is retained with a diagnostic: system/style geometry is not yet
decoded, and cutaway must not be treated as permanent hiding.

MusicXML emits standard staff-details print-object=no/print-spacing=no.
Bundled staves keep their numbered details after clefs in schema order.
The unchanged persistent policy is reaffirmed after the first pitched measure's
notes: MuseScore4.7.5 otherwise interprets a hidden initially resting staff
as global hide-empty-staves and shows it when its music begins. Reaffirming
does not change the musical clock or add notes. Both target scores now render
two staves and retain their source attack/projection data. Uncover's visible
resting bass remains present. Authored musical/empty/linked-part/bundled tests
cover the independent print/playback policies and unsupported layouts.

**Native limit:** a permanently hidden staff containing only rests can still
enable MuseScore's global hide-empty-staves style. An authored visible-empty
counterexample also produces a blank native first system with this importer;
the standard XML still retains the visible staff and its rest. No fake voices,
notes, cutaway flags or deletion are used to bypass that native heuristic.

#### NotePad clef tables (2026-10-14, PDF review P01)

The related default-clef path now preserves a nonzero stored index from
`staffSpec`'s packed word at payload+12, using its low byte. Its high byte is
independent transposition-clef data. The existing paired-container evidence
in `formats/mus-binary-notes.md` establishes defaultClef at+12 for little-endian
payloads; the word is read in the container's byte order. Uncover's staff2
stores0x0303, but has no musical gfhold, so recovering only the table still
left its restored empty staff in treble. Read the stored3 and let the existing
default/carried-clef logic select the source F clef. A stored zero remains
zero/omitted; unresolved instrument-derived defaults are not invented.
Literal legacy gfhold reference0 keeps its real clef-table selection. A first
P01 follow-up incorrectly normalized every0 as a default request; Title Screen
provides a direct counterexample, with bass holds3,0,3 in bars1,2,3 and a
printed treble switch in2. Its stored default remains3. The
[PDK frame-hold getter](https://pdk.finalelua.com/class_f_c_cell_frame_hold.html)
independently identifies a zero-based index. Staff defaults still apply to
missing holders, including Uncover's resting staff. The original clef-table
fixes for Simone/Spring use explicit3 and are unaffected by this correction.

An unrecognized application banner does not mean the score lacks its clef
definitions. NotePad 2006's Simone file stores numeric tag109, cmper65534,
score part0, with eighteen 18-byte definitions (324 bytes). NotePad's
2000-2012 banner in Spring stores eighteen 20-byte definitions (360 bytes).
The latter complete payload is byte-identical to the recognized Finale2012
Uncover control (SHA256 `4b44528ec5d02c6c05447fa730694b8360b5a442f6da10f935f037ee0d333f11`).
Their resolved definitions agree with the existing legacy/Unicode field
layouts, including index3's bass character63, adjust2 and displacement-2.
Finale's [Clef Designer](https://usermanuals.finalemusic.com/Finale2012Win/Content/Finale/SMCLFDLG.htm)
also documents eighteen customizable definitions.

Use those two complete-table lengths as a bounded layout fallback when the
writer's banner supplies no supported era. Partial tables still require a
known era; no default glyph is invented, and custom/shape definitions survive.
Known-era layouts retain precedence. Linked-part tables cannot replace the
score's table, and definition allocations are capped at256 in both containers.
This corrects missing IR/XML clefs without changing the header's version
evidence or interpreting copyright years as application versions.

Enigma keeps a document-wide table of clef definitions (`clefOptions.clefDef`, **18 entries in every
corpus document**) and refers to them by index. Two things carry an index:

- `staffSpec.defaultClef` — the staff's clef. **Omitted when it is 0**, so an absent field means
  treble, not "missing"; skipping those staves would drop every treble-clef staff.
- `gfhold.clefID` — the clef at that (staff, measure). Present on **every** corpus `gfhold`
  (4,214/4,214), so it is the *effective* clef rather than only a change marker, and unlike the key
  signature there is **no inheritance to apply**.

A definition gives a Maestro font character plus placement, or — when `isShape` is set — a `shapeID`
and no character. The two are mutually exclusive.

`ClefSign` derives the kind from the character: 38 (`&`) → G and 63 (`?`) → F are **confirmed by
use**; 66 (`B`) → C appears in the table but no corpus staff selects it, so it is inferred from the
font. Shape clefs report `SHAPE` (percussion, in practice) rather than being guessed into a sign, and
anything unrecognised stays `UNKNOWN`. Across the sampled corpus every measure resolves to G, F or
SHAPE — no UNKNOWN — over clef indices 0, 3 and 16 only.

### Known format facts — time signatures

Enigma stores no numerator and denominator. A `measSpec` carries **`beats`** (how many divisions the
measure has) and **`divbeat`** (how long each division is, in EDU). That is how compound meters fall
out naturally: 6/8 is *two dotted-quarter divisions*, stored as `beats=2, divbeat=1536`, not six
eighths.

`TimeSignature` keeps that representation and derives the conventional pair. A division that is three
times a power of two is compound, so the numerator multiplies by 3 and the denominator comes from the
undotted unit. Reporting `beats` directly as the numerator would call 6/8 "2/8".

Every one of the 2,622 corpus `measSpec` records carries both fields, so unlike the key signature
there is **no inheritance to apply**. Signatures observed: 4/4, 3/4, 2/4, 2/2, 6/8, 9/8, 3/8, 1/4, 1/8.

**A display time signature is only valid when `useDisplayTimesig` is set.** `dispBeats` and
`dispDivbeat` are present on *every* measure but hold a default when the flag is clear — reading them
unconditionally reports a display signature for 1,937 of 2,622 measures that do not have one, usually
claiming 4/4 over a bar that is really 3/4. Only 76 measures genuinely set the flag.

### Known format facts — layers

A `gfhold` holds up to four frames, which are Finale's **layers**. `EntryLocation.layer` records which
slot placed an entry (1–4).

The legacy numeric `gfhold` (tag1044) stores four u16 frame references at
payload +6,+8,+10,+12. Require all 14 bytes before reading the array and omit
zero references. The 2026-10-11 Objection audit independently resolves +10 to
frames110/148 in staff3 measures16/22; these locate six otherwise orphaned
entries. The normalized resolver already supports four layers, as does the
older DCL adapter. Authored tests exercise nonempty layers3/4 and truncated
arrays without reproducing source music.

**Each layer independently fills its measure**, so anything summing durations must group by
`(staff, measure, layer)`. Grouping by `(staff, measure)` alone makes a two-layer measure appear to
hold exactly twice its time signature — measured on the corpus, 78 measures at exactly 2× and 4 at
exactly 3×, matching their layer counts.

With layer grouping, **1,420 of 1,423 layer-measures sum to exactly their time signature** once tuplet
scaling and grace notes are applied, against 1,248 of 1,333 without it. The 3 that remain sit *below*
capacity (5/6, 1/2) — a layer holding fewer notes than the measure allows, which is ordinary notation.

Layers are distinct from Finale's **voice 1 / voice 2** within a layer (`eeppd.txt`'s `CNTLRBIT`
"V2 launch" and `CNTLBIT`). No voice-2 marker has been located in EnigmaXML entry records yet, and the
measure sums above do not require one, so it remains unmodelled.

### Frame start times and initial voice silence (2026-10-11)

A leading frameSpec incidence can carry `startTime` while the trailing incidence
holds its entry pair. Resolve that time once per frame, across score incidences,
and retain it on each EntryLocation in EDU. Missing means zero; negative,
non-scalar, conflicting or values above signed32 range are malformed. The
musical cell carries the common start per layer into canonical Voice.start_offset
as an exact fraction of a whole note. Different starts in one layer are not
silently combined. No additional written notes/rests are created.

The nine 2026-10-11 source offsets in Chrono Trigger, Wind Scene, Maya Fey,
Star Light, Ending and Hurry Up all agree with the resulting voices. MusicXML
uses a voice-specific forward before its events and includes the initial
silence when rewinding the next voice. Divisions include the offset denominator;
staff projection remaps both forward and note voice IDs. Slur/arpeggio timing
and measure/clef bounds include the same offset. Authored tests cover split
incidences, fractional positions, independent voices, graces, combined staves
and invalid times. All75 exports still validate, with written durations intact.

### Legacy detail scope and linked-part groups (2026-10-11)

The variable-length details header word at **+6** is the **part ID**, with 0
for the score. It was previously called `inci` without evidence because every
record in the original paired corpus held zero. The raw `MusDetailRecord.inci`
constructor/attribute is retained for compatibility; its new `part` property
expresses the corrected meaning. This is not the logical incidence used when
unpacking a payload into normalized records.

Evidence: the published [PDK FCGroup source](https://pdk.finalelua.com/ff__details_8h_source.html)
derives groups from `__FCNoInciDetail` and explicitly initializes logical
incidence to zero. In the attributed RGP Lua 0.79 binary, its `Load(cmper1,
cmper2)` at **0x4cbb06** writes those two keys and clears the actual incidence
word. The supplied 75 MUS files have **131** group records: **76** have header
part 0, **54** have part 1 and **one** has part 2. Every nonzero value resolves
to a stored linked-part definition (others 238 cmper), while other translated
detail types have header part 0 in these files. Multiple score groups retain
part 0; this field is not a group ordinal or a duplicate counter.

Birth of the People's `(0,1)` group has part 0 and `(0,2)` has part 1. Both
have the same two-staff span, brace and full measure range; they belong to
different contexts. Normalize the header scope as `part` on **all** translated
detail records, and keep the existing score-only filters in the shared
resolvers. This exports the score's one brace without deleting its linked-part
record or comparing labels/endpoints. Genuine nested groups and score groups
sharing endpoints remain distinct.

Packed assignment incidence counters and duplicate suppression are local to
each part, so a part's copy cannot swallow a score articulation or lyric.
The compatibility `sourceInci` backlink continues to carry the raw header
value; inspector references select this raw scope or normalized `part`, never
the packed element's logical incidence or a different part's first row. The
raw Records tree retains its existing `inci` key spelling for link compatibility.
No new IR layout or name-based group policy is introduced.

### Legacy staff and group names (2026-10-11)

Names use the document's stored two-hop references, not a fixed palette:
`staffSpec.fullName` / `abbrvName`, or `staffGroup.fullID` / `abbrvID`, selects
`others.textBlock[cmper]`; that record selects a text pool and text ID. The
earlier claim in `mus-staff-names.md` that an external fixed table was missing
is retracted. Repeated template IDs did not establish such a table.

The vendor ETF specification's **Text Block** section names the record `TX`
and documents its first word as the `^block(N)` reference. The published
[PDK FCTextBlock source](https://pdk.finalelua.com/ff__others_8h_source.html)
confirms distinct `textID` and `textTag` fields and `GetRawTextExtag()` selecting
the text pool. Read-only inspection of the previously attributed RGP Lua 0.79
binary confirms the pre-25.4 offsets: `GetRawTextID()` at `0x18ebbe` reads the
legacy structure at object `+0x38`; `CreateRawTextString()` at `0x4bfb36` reads
its tag at object `+0x50`, hence payload `+24`.

For the 2011/2012 variable-length pool this is numeric tag **183**, with a
36-byte payload: textID is u16 `+0`, textTag is u16 `+24`; on-wire selectors
**2004** and **2006** address block and expression text respectively. All 6,907
textBlock records in the 75 supplied Ninsheetmusic files have this layout
(1,439 block references and 5,468 expression references). Unknown selectors
are retained and unresolved rather than treated as block text. Truncated
references raise `CorruptScoreError`. The DCL `TX` path reads the same fields
in the file's byte order; a zero selector uses the older ETF default block
pool, whose trailing incidences were documented as unused. This older path is
covered with authored rows; the supplied 75 files do not exercise it.

Staff full/abbreviated IDs are u16 `+30/+32`, in the ETF IS field order; group
IDs remain u16 `+4/+22`. Zero means absent. The adapter now retains stream 3's
`^block(N)` sections as `blockText`; stream 2 is never merged into it. Existing
UTF-8/Windows/Macintosh decoding is used for literal text. Binary font/style/
size commands `^84/^85/^86` and their four byte arguments are decoded
separately, so their opcodes do not force UTF-8 instrument names through a
legacy code page. Markup is retained in the normalized document and stripped
by the existing name resolver. Linked-part textBlock variants cannot override
the score's reference. Full and abbreviated staff names and group labels
remain distinct through the IR and MusicXML.

Birth of the People's group 1 fullID **2** resolves through tag 183 cmper 2,
textID **30**, selector **2004**, to the stored literal **Piano**. Its group 2
has separate fullID 5 and abbrvID 6 references to blocks 32/33 (**Piano/Pno.**).
Neither record is selected or dropped based on its name; applicability is a
separate issue. The unnamed staves retain their fallback names.

### Mid-measure clefs (2026-10-11)

Legacy GF/numeric 1044 payload +0 is a **clef-list ID**, rather than a literal
clef index, when flag word +2 has `GF_CLEFISLIST` (0x0400). The published
[FCCellFrameHold source](https://pdk.finalelua.com/ff__celldetails_8h_source.html)
names the flag; released RGP Lua 0.79 x86_64 `GetIsClefList` at 0x31f198 tests
object byte +0x43 bit 0x04, while `GetClefIndex` reads +0x40. This confirms both
the field-relative offset and mask without executing or copying plugin code.

Others CE/numeric 127 contains packed 12-byte list elements, keyed by that ID.
The published `ff_others.h` `__EDTMidClef` is six signed 16-bit words: clef +0,
EDU +2, vertical adjustment +4, percent +6, horizontal adjustment +8, flags +10.
Its `GetClefShow` getter tests flag 0x02 for hidden, else 0x08 for forced.
Split these into normalized `clefEnum(cmper, inci)` records (`clef`, `xEduPos`,
`yEvpuPos`, `percent`, `xEvpuOffset`, `clefMode`). DCL reads its own byte order;
2011/2012 reads little-endian. Reject truncated lists, more than 4096 elements,
missing references, negative positions, or non-increasing times. Incidence zero
must be at EDU zero. Literal clef index 1 remains a valid C clef.

ActRaiser lower bar 8 references list 1, whose two elements are clef 0 at EDU 0
and clef 3 at EDU 1536, both 75 percent. The PDF corroborates treble followed by
bass before its last two sixteenths. Clef changes do not alter decoded pitches.

### Assigned caesuras (2026-10-11)

Music-font character 34 (double quote, Shift+apostrophe) is a caesura in the
official [Maestro](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[Engraver](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm), and
[Broadway Copyist](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-broadway-copyist.htm)
charts. Resolve only assigned, visible score articulations using the existing
glyph resolver, and export `<articulations><caesura/></articulations>` once per
chord. Literal quotes in text are unaffected. ActRaiser bar 8 entry 1054 has
definition 35/character 34 alongside its fermata, corroborated by the source PDF.
Written time and tempo remain unchanged; performance holds are not tempo marks.

### Expression rhythmic attachment (2026-10-11)

`measExprAssign.horzEduOff` is a rhythmic EDU position (4096 per whole note),
separate from `horzEvpuOff` and `vertOff` drawing adjustments. The existing legacy
assignment adapter already decodes it at payload +2; the normalized reader now
preserves it in `Expression.offset`. The ActRaiser bar-8 mf assignment stores 1536
EDU: 3/8 whole notes, after the fermata. The source PDF and MIDI velocity transition
corroborate the attachment. The published PDK FCExpression measure-position accessor
and musxdom MeasureExprAssign `eduPosition` describe the same normalized field.

MusicXML directions at measure cursor zero use `<offset sound="yes">` before
staff/sound, with denominators included in divisions. MuseScore 4.7.5's inspected
`importmusicxmlpass2.cpp` reads the offset and places dynamics at tick + offset.
This is source inspection, not a claim of runtime MuseScore validation.

### Known format facts — the `.mus` entry pool

#### Manual rest positions (2026-10-14, PDF review P12)

A valid rest with FLOATREST clear and first stored note ID31 has an explicit
drawing position. This is separate from NOTEBIT and never supplies a musical
pitch. The published [FCNoteEntry API](https://pdk.finalelua.com/class_f_c_note_entry.html)
calls this a movable rest; read-only SDK inspection independently shows
IsRestMovable0x4D5954 and GetRestDisplacement0x4D591E checking NOTEBIT,
the stored-note count and ID31 before reading the signed harmonic level.
The vendor `eeppd.txt` describes nonfloating rests' stored positions.
[musxdom Entries.cpp](https://github.com/openmusx/musxdom/blob/main/src/musx/dom/Entries.cpp)
distinguishes floating/zero-note rests from ordinary stored Note records;
Note::calcNoteProperties applies the established key/clef position calculation
to those records. No new numeric tag or allocation is required here.

Entry.rest_position retains that first record independently of Entry.notes.
The existing written-pitch spelling path supplies Event.rest_display_pitch,
with no sounding pitch or accidental. MusicXML uses standard rest display-step
and display-octave; hidden rests keep print-object=no, geometry and duration.
Floating rests or an unestablished record identity do not invent a manual
position. Invalid MusicXML octave positions fail clearly at export.

Mario Main22's visible entries1642/1643 store level-5 (E3 in C), and24's
1667/1668 store-6 (D3). Title Screen2's110/111 store23 (B7 in G).
The converter formerly discarded all these positions. Source-visible entries
are preserved even where the reference PDF differs. Maya5's204/210 and13's
980/990 are coincident visible floating eighth rests in independent layers;
209/979 are explicitly hidden quarter rests and remain hidden. Mario60's
1606/1609 are visible floating quarter rests. There is no source evidence here
for suppressing those events. Unproved layer/consolidation/style settings are
not decoded from guessed numeric tags.

The three target exports pass projection, schema and native import without
changing their attack counts. An authored native fixture demonstrates that
MuseScore4.7.5 separates two coincident rests above/below the staff even with
identical center display pitches; zero manual offsets return to automatic
voice layout. Target rest glyphs therefore are **not claimed PDF-perfect**.
Default empty pickup rests and automatic native voice completion also remain
separate from explicit source rest visibility. Seven authored regressions
cover key-relative positions, floating/unknown records, hidden positions and
invalid assignments; no source notes or metric time are removed.

`read_mus_entries(path)` returns the same `Entry`/`Note`/`Duration` objects the `.musx` path builds,
so `spell_note`, `decode_key` and the rest attach unchanged. Layout is Coda's, from `docs/eeppd.txt`,
confirmed field-by-field against paired `.musx` files.

The pool is a flat array of fixed **38-byte slots**, each tagged with the entry it belongs to:

```
0-3   entnum        the entry this slot belongs to
4-5   slot index    0 for an entry's first slot, then 1, 2, ...
6-37  payload
```

First slot: `prev(4) next(4) dura(2) pos(2) flag(4) extflag(2) count(2)` then two note records.
Continuation slots carry five more notes each, from offset 6. A note is `TCD(2) + flag(4)`.

**Cleared database slots are not musical entries.** The 2026-10-11 Dark World
audit finds 615 active entries and 440 inactive slots. An inactive slot keeps
its nonzero entry number at +0 and has exactly 34 zero bytes at +4..37,
including slot index, links, duration, flags, count and stored-note area. Skip
only this exact representation. Partially cleared records remain invalid.
Unlabelled pool recognition requires at least one active entry; otherwise an
arbitrary zero-filled stream could be mistaken for an entry database. An
explicitly labelled pool may legitimately contain only inactive slots.
Active chords still require complete continuation slots bearing the same entry
number and consecutive slot indices. Authored tests cover both byte orders,
interleaved cleared slots, chords and truncated/incorrect continuation headers.

Three details that are easy to get wrong, each caught by comparing against ground truth:

- **The TCD's alteration nibble is sign-and-magnitude**, bit 3 being the sign — not two's complement.
  `eeppd.txt` calls it "a signed quantity … -8 to +7", which reads as two's complement; under that
  reading `0x9` decodes to −7 where the corpus says −1.
- **`NOTEBIT` (0x40000000) distinguishes musical notes from rests.** `FLOATREST` (0x01000000)
  controls rest positioning, not pitch content: a positioned rest can store a note-shaped record
  for its vertical position, and a musical note can have FLOATREST set. See the vendor's
  `eeppd.txt` entry-flag definitions. The raw document retains the stored count and geometry,
  which still determine slot traversal. Typed entries with `isValid` use the presence of
  `isNote` (the normalized NOTEBIT) to select pitches; minimal authored records without source
  flags retain count-based semantics. Count/record agreement is validated even for rests.
- **Notes do not run at a fixed stride from the entry start.** Note 3 onward lives in the next slot,
  after that slot's own 6-byte tag.

The earlier paired-container comparison covered **30,420 entries**, but its count-based typed XML
reader also treated positioned-rest geometry as pitches; agreement did not prove note/rest semantics.
The Ninsheetmusic audit and ActRaiser PDF/MIDI expose both directions of the error. Authored tests
cover positioned/floating rests, pitched entries with FLOATREST, continuation slots, both byte orders,
and both supported container eras. The corrected ActRaiser export removes the false E4 in bar 30.

**Transposing staves place `harm_lev` in a different octave.** On a staff with a transposition, the
two containers disagree by whole octaves, and `harm_lev_octave_shift(interval)` converts a `.mus`
value to the `.musx` convention. Measured across every confirmed pair, 30,891 notes over seven
distinct transpositions:

| staff transposition interval | shift |
| --- | --- |
| 0, 1, 4 | 0 |
| 5, 7, 8 | −7 |
| 12 | −14 |

i.e. `-7 * ((interval + 2) // 7)`. **The boundary is the surprising part** — the octave moves at
interval 5, not 7 — so a plain "divide by 7" passes the 0/7/12 cases and silently breaks 5 and 8. The
rule is empirical; *why* it breaks at 5 is not understood.

`read_mus_entries` does not apply it, because the entry pool carries no staff information — the
transposition lives in the `others` pool, which is not yet readable from `.mus`. Apply it where the
staff is known.

With the shift applied, 30,888 of 30,891 notes agree exactly. The three that do not are pinned in the
corpus sweep: one entry stores two notes in `.mus` and one in `.musx` with an adjacent entry off by an
octave (a revision made to the `.musx` afterwards), and two notes on one octave-transposed staff are
off by a single step, cause unknown.

**Scope:** both eras. In the 2011/2012 era each pool is its own zlib stream and the entry pool is
recognised by structure; 97 of 99 corpus files place it in a standalone stream and the other 2 lay
the payload out as three streams rather than four, which raises `CorruptScoreError` rather than
guessing. The 2001–2005 era stores the same 38-byte slots **the platform's way round** and names the
entry pool in the container, so no recognition is needed: 136 non-empty pools tile exactly, 70,428
entries decode, and 3 documents carry a pool that is legitimately empty. Two documents fail on a
breve (8192 EDU) or a dotted whole (6144), which `duration_from_edu` rejects — a limit of the
note-value model, not of the container, and one a `.musx` would hit too.

### Known format facts — the `.mus` others pool

`read_mus_others(path)` returns every `others` record as a `MusOther(tag, cmper, part, payload)`.
The pool is a flat run of **self-identifying, variable-length records**: each carries its own key, so
addressing one needs nothing outside it. Little-endian:

```
0-1    tag       record type (numeric; .musx names the same types)
2-3    cmper     the (n) in an ETF ^XX(n)
4-5    part      0 for the score, then 1, 2, ... per linked part
6-9    length    payload size in bytes
10-    payload   `length` bytes
10+length  extra length   LE32
14+length  extra          that many bytes; usually empty, preserved verbatim
```

so one record occupies **`14 + length + extra_length`** bytes. Records of one tag sit together in a
section, and sections may be separated by `0x0000` or `0xFFFF` padding words. The second block is
empty on 99.4% of records; where present it is 24, 48 or 96 bytes and remains uninterpreted.

**This answers the long-open `cmper` question.** There is no directory, no key array and no
positional convention, and the search for them failed for a mundane reason: every earlier attempt
located a section by searching for payload values known from the paired `.musx` and then read
*forward*, while the key sits ten bytes *behind* that anchor. Two ~95% near-misses came from reading
the neighbouring record's header as part of the anchored one. See `docs/formats/mus-binary-notes.md`
for the full account, the retractions it forces, and the candidate tag-id table.

Verified against paired `.musx` files. The walk tiles stream 1 exactly in **97 of 97** current oracle
pairs, and on same-content pairs:

| check | result |
| --- | --- |
| `frameSpec` (tag 146) `(cmper, part)` sequence | every `.mus` key appears in `.musx` order; 5 documents have additional `.musx` part overrides |
| `frameSpec` `startEntry`/`endEntry` payload | over 8,000 compared, 15 differences |
| `measSpec` (tag 176) `beats`, `divbeat` payload | over 5,000 compared, zero differences |
| `measSpec` `width` payload | 59 differences, all in one document |

`width` is layout, not music: re-spacing a score between the two saves changes every measure width
and no `beats`/`divbeat`. Only these two tags are confirmed by payload content; the rest of the tag
table is key-sequence matching and is recorded as leads.

**Scope.** The 2011/2012 era only, as with the entry pool. The seven former refusals were reader
defects, not corrupt files: `0xFFFF` is padding, the previous 64 KiB record cap was measured only on
documents that already passed it, and the supposed fixed trailer is the extra block described above.

### Known format facts — the `.mus` details pool

`read_mus_details(path)` returns every `details` record as a
`MusDetailRecord(tag, cmper1, cmper2, inci, payload)`. The pool has the **same shape as `others`** and
differs in exactly one way, for the obvious reason — a `details` record is keyed by a *pair* of
cmpers, so its header carries one more field:

```
0-1    tag       record type (numeric; .musx names the same types)
2-3    cmper1    first key component (staff, for gfhold)
4-5    cmper2    second key component (measure, for gfhold)
6-7    part      score (0) or linked-part ID; compatibility attribute named inci
8-11   length    payload size in bytes
12-    payload   `length` bytes
12+length  extra length   LE32
16+length  extra          that many bytes; usually empty, preserved verbatim
```

so one record occupies **`16 + length + extra_length`** bytes, against the `others` pool's
`14 + length + extra_length`.

`gfhold` (**tag 1044**) is why this pool matters: it ties a measure on a staff to the entry frames
that fill it. Its 20-byte payload holds `clefID` at +0, `clefPercent` at +4 and `frame1` at +6.

Verified against paired `.musx` files. The walk tiles stream 2 exactly in **97 of 97** current oracle
pairs, all of which are same-content pairs carrying `gfhold`:

| check | result |
| --- | --- |
| `gfhold` key sequence | every document — the `.musx` sequence restricted to the keys `.mus` holds |
| `clefPercent` at payload +4 | over 8,000 compared, every record exact |
| `frame1` at payload +6 | over 8,000 compared, one dangling-reference difference |
| `clefID` at payload +0 | Historical9,736 exact;272 differed as described below |

**Correction2026-10-14:** the272 historical pairs had legacy0 versus a
materialized default in MUSX. That observation does not establish a universal
zero sentinel. Title Screen's explicit3→0→3 and the PDK zero-based getter
disprove that inference. Retain stored indices, including0; the context behind
those old materialized defaults remains an instrument/version investigation.
The licensed paired corpus is unavailable in this workspace, so its historical
counts are not a new validation run.

**The header's earlier incidence hypothesis is retracted (2026-10-11).** The
all-zero paired corpus could not determine the word's meaning. Nonzero groups,
their linked-part definitions and the PDK's no-incidence contract establish
part scope; see [the evidence above](#legacy-detail-scope-and-linked-part-groups-2026-10-11).
The reader retains `inci` as a compatibility spelling and exposes `part`.

Locating `gfhold` cost a third repeat of the same mistake: the previously recorded offsets (staff at
+20, measure+1 at +22, both ~160/164) were the **next record's key pair**, read from an anchor that
sat 16 bytes inside the record. See `docs/formats/mus-binary-notes.md`.

### Known format facts — reading a `.mus` as an EnigmaDocument

`read_mus_document(path)` translates the `.mus` pools into the `Record` model `parse_enigma` builds
from a `.musx`, so every module over that model reads a `.mus` unchanged. `read_mus_entry_records`
is the same idea one level down: the entry pool's primitive is now a `Record`, and
`read_mus_entries` is that composed with `read_entry` — one decode of entry semantics, not one per
container.

**It is an MVP and translates only the record types whose payloads are decoded**: `frameSpec`
(startEntry, endEntry), `measSpec` (keySig.key, beats, divbeat), `gfhold` (clefID, frame1, frame2),
`clefOptions` (the clef table), `tupletDef`, entries, and the tagged text records listed by
`mus_document`. A record type it does not understand is **absent** from the document rather than
present and wrong. `enigma.UNTRANSLATED` names each remaining gap and its consequence.

**2011-era bibliographic metadata is tagged text, not a field inferred from the preamble.** The
text stream writes `^fileInfo(kind)…^end`; exact body matches to paired `.musx` records establish
kind 1 as title (15 matches), 2 as composer (12), and 3 as copyright (4). The adapter emits those as
ordinary `fileInfo type="…"` records, so the existing `file_info` → `Score` path reads both
containers unchanged. Across the 238-file `.mus` corpus, all 145 `fileInfo` sections occur in the
99 later-era files; the 139 DCL-era files carry none in their text streams and still yield no
bibliographic metadata. Kinds 4, 6 and 7 remain untranslated: the paired evidence is insufficient
to ship semantic names for them.

**The clef table** comes from `others` tag 109 under cmper `0xFFFE`, Enigma's sentinel for a
document-wide option. Its entry stride is set by the banner year — 2011 uses 18 bytes, 2012 uses 20
and moves `clefYDisp` and `shapeID` — which is the same era split `mus_payload` uses to choose a
codec. All four fields match the paired `.musx` on 1,512 of 1,512 entries.

**The 2001–2005 era carries the same table under tag `^95`**, again under the `0xFFFE` sentinel.
It is the same table and not merely a similar one: the DCL payload is byte-for-byte identical to
the 2011 one over all 288 of its bytes in 98 of the 102 little-endian documents that carry it, and
identical again in 24 of the 37 big-endian ones once each field is read in the document's own
order — 288 bytes being 16 entries of the same 18-byte stride, and the 324-byte payloads 18 of
them. Reading it closed the gap that left the whole DCL cohort exporting **no clef at all**: 132
documents and 416 parts, where a consumer given none assumes treble and a bass staff reads an
octave and a half wrong. The clef plays no part in decoding a pitch, so the result checks itself —
parts now given F sound at a median MIDI 52, C at 62 and G at 67, each in the middle of its own
staff. See `_ROWS_CLEF_OPTIONS`.

Deriving the stride from the payload length instead would be ambiguous: 324 and 360 are both
divisible by 18 and 20, and reading a 360-byte table as 20 entries of 18 rather than 18 of 20 puts
every field two bytes out.

Three translations are omissions rather than values, and all three matter:

- **A `measSpec` key of 0 becomes no `keySig` element at all.** An absent key means "inherit the
  previous measure's"; writing `key="0"` would silently make every inheriting measure C major.
  Verified: a `.musx` never writes `key="0"`, and `.mus` stores 0 exactly where the `.musx` omits it.
- **A `gfhold` frame of 0 is an empty layer and is omitted**, rather than sending `locate_entries`
  after a `frameSpec` numbered 0.
- **A clef entry's `clefChar` or `shapeID` of 0 is omitted**, because absent means "there is no
  character/shape" — which is what makes `Clef.sign` report UNKNOWN or SHAPE instead of inventing a
  G clef.

**Validation is IR against IR** — the same document built from both containers, compared field by
field (`tests/enigma/test_mus_to_ir_corpus_sweep.py`). Over 81 same-content pairs:

| result | count |
| --- | --- |
| parts, measures and events, one for one | **no differences** |
| key signatures and time signatures | **no differences** |
| written duration, dots, ties, grace notes | **no differences** |
| sounded duration and tuplet ratio | **no differences** |
| pitch | 4,140 differ; 4,138 on transposing staves (`staffSpec` untranslated), 2 are known content revisions |
| clef | 22 measures differ, all instrument-derived (see below); was 327 before the clef table was decoded |

The structural row is the load-bearing one: a difference there would mean entries placed in the
wrong measure, which produces plausible output nobody notices.

**Every remaining difference is instrument-derived**, and there is no instrument table to find: only
two record types are keyed per staff in the whole `.mus` (`staffSpec` and `gfhold`), so there is no
third place for one to hide. The `.musx` materialises these values from its `instUuid`, which has no
`.mus` counterpart.

The transposition's **key alteration** is recovered (`staffSpec` +20, low nibble, sign-and-magnitude
as `eeppd.txt` documents for a note TCD), and that is all the *written* pitch needs — `transpose_key`
uses `adjust` alone. So every note letter and accidental is now right, and only the octave is wrong,
on exactly the staves where `harm_lev_octave_shift` is non-zero. The **`interval` is left absent**,
which is correct for the written pitch and wrong for the concert pitch `spell_note` returns
alongside it: a `.mus` cannot supply that.

**Why it cannot.** Finale normalises a staff's transposition into a residue of −4..+2 and keeps the
octave count separately; the `.mus` stores only the residue, so intervals 0 and 7 both store
`0x0000`, 1 and 8 both `0x0042`, 5 and 12 both `0x0F83`. The octave is absent from the file rather
than hidden in it — which is also why `harm_lev_octave_shift`'s boundary sits at interval 5: its
`+ 2` is the normalisation boundary, not a fitted constant. See `harm_lev_octave_shift` and
`docs/formats/mus-binary-notes.md`.

`tupletDef` (details tag 1072) is keyed by **entry**, not by a (staff, measure) pair: entry-attached
details pack the 32-bit `entnum` into the two key fields, high word first. Its four fields all have
a single value corpus-wide, so the layout rests on ETF's field order plus the end-to-end duration
check rather than on an offset sweep.

One document fails to build: its `.mus` frame chain references an entry its pool does not hold. It
is the same document whose `.musx` carries three `frameSpec` records its `.mus` does not, so the two
containers disagree about its frames rather than the adapter mis-reading them.

**A record's tag is spelled three different ways, by family and era, and the diagnostic report
(`finale-parser inspect --report`) shows the raw spelling rather than a normalised one.** A
2011-era `.mus`'s `others`/`details` pools tag each record numerically (`mus_others.TAG_FRAME_SPEC =
146`, `mus_details.TAG_GFHOLD = 1044`, and so on). A 2001-2005 (DCL) `.mus` tags each 16-byte row
with ETF's two-character code instead (`enigma.mus_rows.MusRowRecord.tag`; `MS` = `measSpec`, `IS` =
`staffSpec`, `FR` = `frameSpec`, `GF` = `gfhold` — see `_rows_others`/`_rows_details` in
`mus_document.py`). A `.musx`'s `Record.tag` is the symbolic EnigmaXML element name (`measSpec`,
`gfhold`, `frameSpec`, ...). `read_mus_document` normalises the handful of record types it
translates onto the `.musx` spelling (the table above), but the report's "records" depth
(`report.model._mus_records`) deliberately bypasses that translation and reads the raw `others`/
`details` pools directly — see that function's own docstring for why: a tag `mus_document` does not
yet translate is exactly what a diagnostic needs to still show. So the same musical concept — a
frame's entry span, a measure's key and beats, a group-fill hold — appears in a report under `146`,
under `FR`/`MS`/`GF`, or under `frameSpec`/`measSpec`/`gfhold`, depending only on which family and
era produced the file being inspected.

### The diagnostic report walks the entry join twice, on purpose

**`locate_entries` raises on exactly the documents the report exists for, so the report has its own
walk.** `enigma.location.locate_entries` is the single walk from a `gfhold` through its `frameSpec`
records to the entries filling a measure, and it raises on a document that gets any of that wrong —
right for a converter, where a broken join means there is no score to build. A diagnostic exists for
those documents, so `report.entry_facts.placements_by_entry` walks the same join tolerantly: each
break becomes a string a reader can see, and nothing stops the rest of the report being written. The
two must not disagree about a document they can both read — with one bounded, deliberate exception:
the tolerant walk stops at `_MAX_FRAME_INCIDENCES` incidences of a single frame (16; the corpus
maximum is 2) where `locate_entries` keeps going, because tolerance is what makes an unbounded
accumulation possible in the first place. It says so in `unresolved` rather than diverging quietly.
Two tests keep the rest from drifting. `tests/report/test_entry_facts_corpus_sweep.py` compares
placements entry by entry across both containers, and separately asserts the tolerant walk raises on
nothing in the corpus, including the document `locate_entries` refuses — wide, but `corpus/` is
gitignored, so it is skipped in CI. `test_the_two_walks_agree_on_a_document_locate_entries_accepts`
therefore runs both walks over synthetic documents (a clean chain, a linked-part gfhold, a mirror,
and one with several gfholds, two layers and a real `next` chain) and compares the placements **in
order**, which the sweep sorts away — so the drifts that matter are caught everywhere the suite
runs. Both walks import `_CHAIN_GUARD` and `_MAX_PLACEMENTS_PER_ENTRY` from `location.py` rather
than restating them, so a bound tightened in one cannot be forgotten in the other.

**Tolerance is what has to be bounded.** `locate_entries` raises at the first failure, so it never
accumulates; a walk that records and continues can be asked for as much work and as much text as the
file likes. Three bounds keep it linear, each with its measurement in its docstring:
`_MAX_DOCUMENT_FAILURES` caps the messages that belong to no single entry (the count is `gfholds × 4
slots × frameSpec incidences`) and ends the list with what it dropped; `_MAX_FRAME_INCIDENCES` caps
the incidences one frame contributes, and the filtered list is built once per frame number rather
than once per gfhold slot naming it — without both, 1,000 gfholds naming one 1,000-incidence frame
took 0.39 s and quadrupled per doubling; and `effective_keys` now refuses a `measSpec` span wider
than `_MAX_MEASURE_SPAN`, since it walks a dense range between two cmpers read straight out of the
file (the largest cmper in 633 corpus documents is 1,028). Failures belonging to no entry are filed
under `DOCUMENT_KEY`, a key no `str(entnum)` can equal, so a document declaring an entry numbered 0
cannot absorb them.

A mirrored entry has more than one placement (see `_mirrored_cells`), and mirrored staves may
transpose differently, so the index spells from the **first** placement and the pane shows every
placement rather than hiding that a choice was made. Exactly one corpus document in 632 places an
entry twice, so that rule is pinned by a synthetic test rather than by the sweep — the corpus is
absent in CI, where the rule still has to hold.

**A reference into the Records tree needs translating, because the report deliberately shows raw
tags.** The pane lists the `details` records that name an entry — its articulations, its lyrics, its
tuplet — and a reader can click one to select that record in the tree. On a `.musx` both sides speak
the same language. On a `.mus` they do not, and the paragraph above is why: the reference is
computed from the `EnigmaDocument`, where `read_mus_document` has already normalised the record to
`articAssign` keyed `(entnum 501, inci 0)`, while the tree shows it as the raw pool holds it — tag
`1009`, keyed `(cmper1 0, cmper2 501, inci 0)`. `report.model` joins them through
`mus_details.entry_key`, which reads a detail's 32-bit entry number out of the two key fields it
reuses, **high word first** (`cmper1 << 16 | cmper2`); `mus_details.ENTRY_DETAIL_TAGS` names the
three detail types keyed that way (`articAssign`, `tupletDef`, `lyrDataVerse`) and no others are.
Where the join does not resolve — a 2001-2005 file, whose tree is built from ETF rows instead — the
reference renders as plain text rather than pointing at a record that merely looks right.

One trap is worth stating outright, because two of the three tags would join wrongly without it:
`inci` does not mean the same thing on both sides. Unpacking `articAssign` can create several
identities from one raw row: the adapter keeps their incidences unique and retains the raw
incidence as its own `sourceInci` metadata attribute. The report uses `sourceInci` for the join,
falling back to `inci` for older documents without that metadata. `tupletDef` carries no `inci`
at all; and `lyrDataVerse`'s is a synthetic per-entry counter assigned while one raw record is
expanded into several verse records. The join matches on the full triple where a raw incidence
exists, and otherwise falls back to the first record of that tag on that entry.

### The pattern that reads a `.mus`'s pools in a hex editor

**`finale-parser extract` writes the pools out because ImHex cannot decompress them.** Its
`hex::dec::` namespace covers zlib, bzip, lzma, zstd and lz4 — there is no PKWARE implode, which is
what the 2001–2005 era uses in 139 of the corpus's 238 documents. Implementing implode in the
pattern language does not work either, for reasons that are not about the format: `std::mem` can
copy bytes between sections but cannot emit a *computed* one, overlapping LZ77 copies force
byte-at-a-time loops, and the evaluator caps loop iterations at 4096. Decompressing in Python first
sidesteps all of it.

**The extracted file keeps the container's own framing** — `kind`, `length`, `checksum`, laid end to
end, `length` counting its own header — so walking it teaches a reader the real chain. Only two
things differ: payloads are decompressed, so `length` is the decompressed size, and an 8-byte header
(`FMUS`, version, byte order, era, pool count) is prepended so the file announces itself rather than
impersonating a score. The checksum is written as zero: the container's covers the compressed
stream, which the file does not hold.

**A 2011-era container labels no pool**, so `extract` identifies them with the same walks the
readers already use to pick their own stream — `mus_others._walk`, `mus_details._walk` and
`mus_entries._looks_like_entry_pool`. Across all 99 zlib-era corpus documents those three identify
positively in 99 of 99, with no stream matching two tests; the fourth is the text pool by
elimination, agreeing with the order the DCL container states outright. Only one pool may be
inferred that way — two would make the fourth a coin toss, and a wrong kind sends a reader to the
wrong record shape.

**The header's `era` byte is the container's own answer, not a guess.** A DCL container labels its
pools and a 2011-era one labels none, so `era_of` reads the era off the pools *as read* — asking
after `identify_pools`, which labels every pool, can only ever answer DCL. The byte decides which
record shape the pattern applies to a whole pool, so getting it wrong reads a 2011 pool of
variable-length records as a table of 16-byte rows.

**The pattern dispatches on era and kind, and stops there.** A 2011 `others` pool is placed as
`OthersRecord`s and its `details` pool as `DetailsRecord`s; a DCL pool of either kind is placed as
16-byte rows. `entries` and `text` have no catalogued record shape and stay raw bytes. So does a
record's payload: which struct applies depends on the record's tag, and the tags this project has
not decoded have no shape to give them, so the pattern lists the tag-to-struct mapping for a reader
to place by hand rather than inventing one. In the DCL era those structs must be laid over a
record's *gathered* rows — 12 data bytes from each `others` row, 10 from each `details` row — never
over a single row.

`docs/formats/finale-mus.hexpat` is generated from `formats/layouts.py` by `make hexpat`, and
`tests/formats/test_hexpat.py` fails if the committed copy is stale. Layouts marked `computed` —
`frameSpec` and `gfhold` — are named but never laid over bytes, because their readers work the
offsets out per record or era.

### Known format facts — the reserved staff 32767

#### Active resting staves (2026-10-14, PDF review P02)

The active score `instUsed` list establishes staff membership as well as
ordering. Uncover's score list explicitly contains staves1/2 and its piano
brace joins both, but only staff1 has a musical `gfhold`. Selecting parts
solely from cells with entries discarded the real resting staff2 and shrank
the brace. Keep listed resting staves and fill their existing measure range
with the normal canonical measure rests. Stored `staffSpec` definitions alone
do not establish active membership; linked-part lists and reserved32767
remain separate. Staffs with music outside the list retain their placement.

This expansion is bounded by1024 staves and1,000,000 staff/measure cells,
before allocating complete parts or carried-clef grids. Repeated staff IDs
in one active layout are rejected rather than emitted as duplicate XML parts.
Authored C/D-score tests exercise resting and unused staves, score/part scope,
clefs, measure rests, groups and malformed/allocation-boundary inputs.

Every corpus document declares a staff numbered **32767** (0x7FFF, the sentinel the format also uses
for "to the end" in `staffGroup.endMeas`). It is real data — its own `staffSpec`, a `gfhold` per
measure, its own entries — but it is not part of the score:

| check | result over 401 documents |
| --- | --- |
| in the score's instrument list (`instUsed`) | never |
| named by a staff group | never |
| distinct `staffSpec` bodies | **two**, all with one fixed `instUuid` |
| display features | one-line `customStaff`; clefs, key signatures, measure numbers, repeats and repeat barlines all hidden |
| its music | in the 398 documents measured when the rule was established, a single repeated pitch in 376, always layer 1, never a lyric; the final 3 became buildable later and were not part of this content count |
| entries shared with a real staff | none — disjoint in all 401 |

It is also the only staff in the corpus absent from the instrument list. `build_score` therefore
makes no part for it; see `docs/DECISIONS.md` for why the exclusion is by staff id rather than by
absence from the list (a `.mus` has no such list, and the containers must agree). What Finale uses it
for is **not** established — a hidden one-line staff of repeated quarter notes would fit a click
track, rhythmic notation or a chord-symbol carrier equally well.

The raw document retains all its entries. By default `locate_entries` still
includes it for callers inspecting raw placements. `build_score` now requests
musical scope explicitly: reserved-staff chains are validated and recorded as
template ownership, without requiring a real measure/key or producing a part.
This handles stale template measures observed in Wind Scene, Prelude, Simone,
Dungeon and Dark World in the 2026-10-11 audit. Entries shared with an ordinary
staff retain that staff's placement; genuine orphans and broken links still
raise, and template claims have the same per-entry allocation cap. No key is
fabricated for template measures outside the real score.

The first scoped rerun additionally exposes dormant, still-active entry chains
in Prelude (56 entries), Simone (56) and Dark World (24). Their frameSpec
records exist, but no current gfhold references them in any layer or part.
The legacy adapter derives `unassignedFrame` only for frames with complete
start/end references into the active entry pool and no assignment from any of
the four layers, including linked-part contexts. It preserves all raw entries
and frames. Musical location resolution can validate those chains as dormant
ownership without fabricating a staff/measure placement. An unassigned frame
alone does not put notes in the score. Genuine frameless entries, broken chains,
ordinary missing references and claim caps remain errors. Direct raw placement
inspection keeps the original strict orphan behavior. No pitch/duration or
filename heuristic selects dormant data. The 75-file rerun builds all three;
Dark World then reveals the already predicted invalid-font-text export failure.

### Known format facts — staff groups

A `staffGroup` detail record spans a run of staves and says how they are joined — the braces and
brackets down the left edge of a score. Its field order is **documented**: `etfspec.pdf` describes
the ETF `NG` record as `startInst endInst fullNameID fullXadj fullYadj | bracketType bracPos bracTop
bracBot bracFlag | flag abrvNameID …`, and the `.mus` binary lays those out in exactly that order.
Six offsets were confirmed independently against the paired `.musx`, each with one candidate, and
each landed where the spec predicts.

**`startInst` and `endInst` are staff numbers, not slots in the instrument list.** The two readings
agree wherever a document numbers its slots and staves alike, which is most of them; the 31 corpus
documents where they differ are the ones that decide, and there all 75 groups name a staff.

The staves a group covers are the run **in instrument-list order** (`instUsed`), not the numeric
range between its endpoints. Those differ in 14 of 230 corpus groups, because a score may lay its
staves out in an order its staff numbers do not follow.

Bracket shapes are an enum with partial evidence:

| id | reading | evidence |
| --- | --- | --- |
| 3 | `brace` | `etfspec.pdf`: "bracket type: 3 (piano brace)". All 132 span exactly two staves, none nests, none is named. |
| 6 | `bracket` | The only id that ever contains another group (14 of 78), the only one spanning more than two staves (34 of 78), the only one carrying a name (31 of 78). |
| 8 | *unmapped* | All 20 sit nested inside another group and none is named — a sub-group marker, but MusicXML's `square` and `brace` are both consistent with that. |

The id-6 argument is about the grammar of a score rather than what this repertoire contains: a brace
cannot span five staves or wrap another group, and a bracket can. Id 8's groups are still exported,
with their extent and barline; only the symbol is withheld.

`groupBarlineStyle` is `group` where barlines run through the whole group and absent otherwise; only
the positive is read. In a `.mus` it is bit `0x0400` of the flag word at +20 — the only exact
candidate against the paired corpus, and independently the bit `etfspec.pdf`'s worked example sets
when it reads `flag: 1088 = 0x0440 (barline through all staves…)`.

Corpus: 209 group records, 201 reaching the IR across 155 documents. The 8 that do not are groups
whose staves are not contiguous once parts are ordered by staff number — `build_score` orders parts
numerically, so bracing them would join a run of parts the score does not group. Ordering parts by
the instrument list instead would fix those 8 and is a change to every part's position, so it is its
own slice.

The earlier `.mus` gaps here have since been closed: instrument-list tag 159
recovers staff order (including paired documents whose order is not numeric),
and textBlock tag 183 resolves staff/group names through the source's own
text references. See the adapter and [name-layout evidence](#legacy-staff-and-group-names-2026-10-11).

### Known format facts — text repeats

"Fine", "D.C. al Coda" and their kin are three records:

    textRepeatAssign(measure)  -- a marking is placed here, naming a definition
    textRepeatDef(repnum)      -- how it is drawn
    textRepeatText(repnum)     -- what it says

**`textRepeatText` is a palette, not a list of what the score uses.** Every one of the 401 corpus
documents carries the same nine or so definitions — "D.C. al Fine", "D.S. al Coda", "Fine",
"To Coda #" — whether or not it uses any, roughly 400 occurrences each. Reading the palette puts a
D.S. in every score in the corpus. Only an **assignment** places a marking, and there are 17 of
those across 10 documents.

`repnum` names the definition, confirmed by what comes back: measure 5 of one score resolves to
"Fine" and measure 10 of another to "D.C. al Coda", which is not what a wrong link produces. Five of
the 17 name a `textRepeatDef` that exists while its `textRepeatText` does not, so the file carries no
words for them.

The original MVP had three deliberate limits (superseded by the source-evidenced
navigation work below):

| not done | why |
| --- | --- |
| playback semantics (`<sound dacapo>`, `dalsegno`, `fine`) | `action` is `stop`/`jumpAbsolute`/`noJump` with a `target` measure, but the corpus holds one or two distinct situations per value. A wrong guess sends a player to the wrong bar — worse than a marking that only prints. |
| segno and coda signs | Some markings are a single music-font character (`%` for the segno). Printing that literally puts a percent sign in the score, and the definitions carrying one have **no `fontID`** to identify the glyph with — the same blocker as fingerings. |
| the `.mus` side | Exactly **one** paired document carries a text repeat, with two assignments. A key set that small matches several tags by chance, so no tag can be identified. |

Original corpus: **6 markings across 3 documents** — "Fine" and "D.C. al Coda". Small, and that is the point:
the palette would have given hundreds.

#### Numeric navigation and traversal (2026-10-12)

Numeric tags **243** (24-byte assignment slots), **244** (12-byte definition
core) and **246** (aligned UTF-16LE text) form the same three-record join. The
text records identify their own palette by spelling D.C./D.S./Fine; only 21
actual assignments in 14 supplied scores place marks. UTF-16 is independent
of the file's 2011/2012 banner and is decoded with aligned terminators and strict
Unicode/control-character validation. A further definition block is retained
as opaque legacyExtra rather than guessed as a pass list.

Assignment offsets: +0 signed horizontal EVPU, +2 signed actuate/pass, +4 signed
target, +6 repnum, +8 signed vertical EVPU, +10 flags, +12 staff list. The RGP
FCTextRepeat loaded structure starts at +0x38, anchored by GetHorizontalPos
0x1368c8, GetTotalPasses 0x137d88, GetTarget 0x138150 and GetID 0x134fce. Flags
&0x70 give automatic/absolute/relative/mark/stop/disabled actions at
0/0x10/0x20/0x30/0x40/0x50; &0xC00 give always/on-pass/until-pass at
0/0x400/0x800. Hidden 0x4000, reset 4 and top-staff 2 match published getters.
GetAction 0x4c4830 independently tests stop/disabled and the pass controls.
The definition's font ID +4, size +6 and styles +8 are anchored by GetFontInfo
0x12fb9e; +10 carries alignment and pound substitution. Resolve the font registry
before interpreting % as segno (Maestro/Engraver) or character 222 as coda
(Maestro). Text alone never supplies a playback destination.

Canonical `Measure.navigation` preserves printed text/sign, mark identity,
visibility and `RepeatPlayback`. Hidden marks retain independent playback;
disabled optional text acquires no invented jump. A bounded traversal keeps
separate text-repeat counters and advances the consumed pass at alternative
endings without a closing repeat. Pass lists 1,3 and 2,4 therefore select the
correct branches after a D.C./D.S.; ordinary 1/2 lists retain their consumed
final ending unless the source resets them. No filename/MIDI routes are used.
All source controls in the supplied scores operate at bar boundaries; EVPU
drawing positions do not become rhythmic offsets or partial-note stops.

Ten navigation-bearing paired scores now match every source/MIDI attack using
the source route (including optional Dire Dire Docks). SM64 has two silent-anchor
source attacks and 34 glissando realizations; Spider has 40 trill/tremolo
realizations; MEGALOVANIA has 16 optional coincident unisons and four ornament
auxiliaries. These remain separately tracked. Spear of Justice's always-absolute
D.C. targets measure 0: preserve the rule, issue unresolved-navigation-target,
and refuse to invent a canonical route for it. Its words still render; a player
may interpret them independently from this invalid source setting.

MusicXML emits placed signs, exact destination labels, fine and pass conditions,
with end-of-bar offsets for jump words. For D.S./D.C. al Fine/Coda, the standard
sound is measure-level and the direction retains its complete words. This avoids
a verified MuseScore 4.7.5 importer issue: embedded dalsegno makes it classify
D.S. al Fine as plain D.S. and set playUntil=end; independent sound plus words
correctly imports playUntil=fine. Both encodings validate against MusicXML 4.0.
The importer ignores time-only/after-jump policy, so its default playback still
skips some repeats after jumps in Dr Wily, Star Light, Scrap Brain, SM64, Ground,
MEGALOVANIA and Spider. Retain correct source rules/XML and report that playback
limit rather than changing ending labels or expanding the written score.

Evidence: [PDK text-repeat API](https://pdk.finalelua.com/class_f_c_text_repeat.html),
its ff_other.h layout/getters, released RGP disassembly (the previously recorded
binary hash), [Maestro chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[MusicXML sound](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/sound/),
the source records and the user's isolated MuseScore 4.7.5 runtime. Local check
artifacts are retained outside git; authored records exercise parser bounds.

### Known format facts — three things that are not invariants

Found by auditing the exported documents rather than any one feature. Each looks like a defect and
is not, so each is recorded here rather than asserted in a test.

**Finale attaches lyrics to rests.** 165 `lyrDataVerse` records in the corpus name an entry that is a
rest, against 16,591 naming a note. The export carries them through, because the file says so; the
count is pinned so that a change means the lyric-to-entry mapping moved rather than that the corpus
did.

**Ties do not pair.** The corpus carries 7,017 tie starts against 6,990 ends — 27 ties begin and
never finish. That is in the files, so "every tie start has a stop" cannot be asserted of the output.

**A voice need not fill its measure.** A second layer holding a half note in a whole-note bar is
ordinary Finale, and MusicXML represents it directly. Requiring every voice in a measure to be the
same length flags 301 corpus measures that are perfectly correct.

### Known format facts — barline styles

`measSpec.barline` names the right barline's style outright in a `.musx`: `normal`, `double` or
`final`, and nothing else in 21,855 corpus measures. Only the two that are not ordinary need an
element — `double` → `light-light` (228 measures, 87 documents), `final` → `light-heavy` (110
measures, 23 documents). Writing `regular` on the other 21,517 would say nothing.

A `.mus` keeps the same thing in the **high nibble of the flags byte at `measSpec` +10**, whose low
bits are the repeat flags. Nibble 1 is ordinary and 2 is a double bar: paired documents agree on
3,960 ordinary measures and all 11 double bars, with no counterexample. The two readings share a
byte, so masking matters in both directions — reading either off the whole byte breaks the other.

**A `.mus` never reports a final barline.** Nibble 3 is the obvious reading and it does not occur
once in 4,427 measures across 99 `.mus` documents, so there is nothing to check a guess against.
Either no `.mus` here carries a final bar, or it is not in this nibble, and the corpus cannot say
which. A wrong guess would put a double bar at the end of pieces that end plainly.

A repeat overrides the style: the repeat's own heavy line is what gets drawn, and four corpus
measures ask for both.

### Known format facts — repeats

Repeats live in two places at once, and reconstructing one bracket needs both.

The **barlines** are flags on `measSpec`: `forRepBar` means a forward repeat at that measure's left
barline, `bacRepBar` a backward repeat at its right. Nothing else is stored about a forward repeat —
it is only ever a barline. A backward one also gets a `repeatBack` record keyed by measure, whose
`actuate` is Finale's "Total Passes"; the corpus has 25 measures where it is not the default 2.

The **endings** need three records and one flag:

| what | where |
| --- | --- |
| the bracket opens here | `repeatEndingStart(measure)` |
| which passes it is taken on | `repeatPassList(measure)` → one `act` per pass |
| how far it extends | `measSpec.barEnding` |

That last one does not mean what it looks like it means. **`barEnding` is not set on every measure a
bracket covers**: in a four-measure first ending the corpus flags the first measure and the fourth
and leaves the two between them clear. So a bracket runs to *the last flagged measure at or after
its start and before the next bracket starts* — not to the end of a run of consecutive flags.
Reading it as a run stops a four-measure bracket after one measure, and without the next-start
boundary a bracket swallows the ending that follows it.

The rule was checked against the two independent things that ought to agree with it: the measure
carrying the backward repeat (71 brackets, no disagreement) and `nextEnd` where a
`repeatEndingStart` supplies one. The other 67 brackets are single measures with no backward
repeat — a final "2." ending, which MusicXML closes with `discontinue` rather than `stop`.

Corpus: 109 forward repeats, 121 backward, 142 brackets, across 109 documents. Each matches the raw
element count in the pool exactly, so nothing is invented or lost on the way to the IR.

In a `.mus` all three flags sit in **one byte at `measSpec` +10**, on adjacent bits — `barEnding`
0x02, `bacRepBar` 0x04, `forRepBar` 0x08. Each was found by testing every (byte, bit) in the payload
against the paired `.musx`: each has exactly one candidate agreeing on all 1,025 measures of the 20
paired documents that use repeats. That they land on three adjacent bits of one byte is the
corroboration the correlation alone would not give. The byte's high nibble is the barline style
(1 normal, 2 double), **not read**: the paired corpus holds 11 double barlines and no final one,
which is too thin to commit to. The records are tags **203** (`repeatBack`), **204**
(`repeatEndingStart`) and **206** (`repeatPassList`); 204 and 206 share a key set, and the payload
separates them — 206 is 12 bytes opening with the pass number, 204 is 24 bytes of bracket geometry.

The original implementation did not read `repeatBack.target`, `trigger`, `action`, or the `textRepeatAssign` family
(D.C., D.S., Fine, To Coda). Those describe *jumps* rather than repeat barlines and MusicXML spells
them differently. `repeatEndingText` — a bracket's custom label, used by three corpus documents — is
also unread; the text is derived from the pass numbers instead.

### Silent entries and independent visibility (2026-10-12)

Extended entry word **slot+22 bit 0x0400** disables entry playback. The
published FCNoteEntry.GetPlayback and released RGP getter 0x468e46 test the
loaded entry byte +0x0D mask 4. The independently established grace-slash
getter 0x467efa reads that same byte with mask 1, anchoring it to serialized
extended bit 0x0100 at slot+22. Thus mask 4 in that byte is exactly extended
0x0400; it is not a live-object-offset guess fitted to unmatched MIDI notes.
Main entry flag **0x00008000** independently hides notation, documented as
IGNOREBIT in eeppd.txt. Normalized noPlayback/ignore fields feed typed Entry
and canonical Event.playback/visible for both containers and byte orders.
Neither field removes pitches, metric time, source ties or span endpoints.

The supplied corpus has 167 active disabled entries in 25 files, mostly rests
used for layout. Seventeen pitched entries in five files contain 18 written
pitches: Corridors1, Slider4, SM64Main3, SMWAthletic2 and ZeldaTitle8. The newly
covered Athletic chord is coincident with sounding material, explaining why an
earlier attack-only candidate probe did not name it separately. Scope follows
the production musical frames, not a MIDI note-selection heuristic.

MusicXML uses the standard silent cue representation at full size for disabled
pitches, preserving duration and graphical tied/slur endpoints. Cue notes cannot
carry sounding tie elements, so only their visual tied elements are emitted;
the complete source ties remain in IR. Hidden notation uses note print-object=no
independently of cue/silence. Rests do not become synthetic pitched cue notes.
Every exported silent cue has type size=full and a standard defaults/appearance
note-size type=cue value100. MuseScore 4.7.5 ignores the individual full-size cue
attribute but honors this default, setting smallNoteMag=1. An authored four-note
runtime check verifies visible C/D at the same full size, hidden E/F, only C/E
MIDI attacks, and native play=0 for both silent notes. Zero dynamics is unsuitable
for this build: the importer discards it; instrument mute is a playing technique.

Source-derived attack comparison after suppression: Corridors1188/0/0,
ZeldaTitle1308/0/0, SMWAthletic1308/0/0 (matched/source-only/MIDI-only).
Slider2250/0/13 and SM64Main1093/0/34 retain the separately planned grace-chord
and glissando realization gaps. Source visibility is preserved, not inferred
from silence or whether a note happens to match the MIDI.

Evidence: [PDK entry API](https://pdk.finalelua.com/class_f_c_note_entry.html),
eeppd.txt and the released getter pair, [MusicXML silent/full-size cues](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/cue/),
[cue-size default](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/note-size/),
and the user's isolated MuseScore 4.7.5 runtime. Its exact pass-1/2 importer
source independently confirms the cue playback and size behavior.

### Typed expression playback controls (2026-10-12)

Numeric textExprDef tag 241's flags are the word at +10: low byte 0 none, 1
tempo, 2 key velocity, 14 swing. Published EDT/PDK methods and the read-only RGP
type dispatch independently corroborate these meanings; the already paired
value +4, auxdata1 +6 and playPass +8 anchor the structure. Value is signed
16-bit for typed playback, even though the older untyped field retained its
unsigned reading. Flag 0x1000 enables auxiliary tempo beat EDU; 0x2000 makes
the value an executable-shape ID instead of a scalar playback rate. A zero
typed value must not vanish through the old optional-value convention.

`Expression.playback` separates these instructions from printed metronomes and
from the old untyped `velocity`. Export uses explicit tempo value/unit in sound
while retaining the printed beat/rate: Dr Wily prints 180 and plays 178; Athletic
prints 150 and plays 152, matching the source/MIDI. Explicit key velocity in
0..127 uses MusicXML dynamics as a percentage of default MIDI forte 90. Pass
conditions use time-only. An explicit no-playback expression does not invent a
tempo from its printed words. Swing is typed here for its separate export step.

The audit also exposes source controls that are not valid absolute rates:
Objection's copied forte stores -100; Player Select and Ending contain a tempo
type with value zero, eighth-note unit and words "Swing e's". Retain and diagnose
these exact settings instead of turning them into velocity 65436, zero BPM or
an inferred typed swing setting. Human Playback can interpret instruction words
independently; reproducing that interpretation is a separate renderer issue.
Executable scalar-shape playback likewise is not converted to a tempo.

Evidence: [PDK expression API](https://pdk.finalelua.com/class_f_c_text_expression_def.html),
its `ff_other.h` source, released RGP getters, source definitions and
[MusicXML sound units](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/sound/).

### Document playback controls (2026-10-12)

The published PDK `_FCEDTPlaybackPrefs` names each legacy field, and RGP Lua
0.79 `__FCPrefsBase::MapPrefStruct` selects 48 PL mapping rows at virtual
0x705660 (Mach-O file 0x709660). The mapping identifies preference number,
incidence, word, size and conversion; numeric preference tags equal decimal ETF
preference numbers plus 14. This follows the independently established grace
preference mapping, not a fitted MIDI correlation. All supplied files contain
these complete 12-byte score preference records at comparator 65534.

| Field | Numeric tag, byte offset | Meaning |
|---|---|---|
| metronomeBeat | 27, +2 i16 | Beat duration in EDU |
| metronomeSpeed | 53, +6 i16 | Beats per minute in that unit |
| swing | 50, +0 i16 | Amount/1024, 0 straight and 1 standard triplet swing |
| baseKeyVelocity | 50, +10 i16 | Base MIDI key velocity |
| startAtMeas/startAtMode/stopAtMeas | 51, +0/+2/+4 i16 | Playback control measures/mode |
| startEdu/stopEdu | 61, +0/+4 | Signed 32-bit EDU, high platform-endian word first |
| startPass/endPass | 61, +8/+10 i16 | Control repeat passes |

Conversion 1 is verified by `MakePrefsFourbyte`: first word becomes the high
16 bits, second the low 16 bits. Stop 32767 means end of piece; a zero stop EDU
stores the measure *after* the actual stop. These fields normalize into
`playbackOptions` and canonical `Score.playback`, independently of notation.
Missing complete preference sets do not invent controls; malformed complete
records and invalid values fail with a clear error. Playback-range/mode data is
retained without rewriting the score or imposing UI "current counter" state
on a full-score conversion.

Simone stores quarter=96; Invincibility stores half=130 (quarter=260). When no
explicit first-bar metronome already establishes the tempo, export writes a
measure-level `<sound tempo>` with no new printed marking. MuseScore 4.7.5's
measure importer creates an invisible TempoText for this standard instruction
before the first note. Displayed header text remains a distinct placement task.
1UP stores quarter=100, Get Treasure/Uncover quarter=120, corroborating their
reference MIDI rates independently of printed 225/100 markings. Other playback
toggles must be decoded before selecting those rates over an explicit expression.
Spring Yard stores end-of-piece, zero stop EDU and pass 1; no stored range in
these controls explains its MIDI ending during the replay. The observed shorter
reference is retained as an export/reference exception, not a parser stop rule.

Evidence: [PDK playback controls](https://pdk.finalelua.com/class_f_c_playback_prefs.html),
[`ff_prefs.h`](https://pdk.finalelua.com/ff__prefs_8h_source.html), read-only RGP
mapping/getters (binary hash recorded with the grace evidence), source records
and the verified MuseScore importer source. No released binary is executed or
committed.

### Source swing and straight instructions (2026-10-12)

Typed swing expressions use the independently mapped signed value/1024;
zero explicitly restores straight time and 1024 requests standard triplet swing.
Finale's actual metric division determines the swung subdivision, at half of
that division. A displayed 4/4 over actual 8/8 therefore swings sixteenths, not
eighths. `ExpressionPlayback.beat_unit` and `PlaybackPreferences.swing_unit`
preserve that subdivision separately from the displayed meter and tempo glyph.
Compound or unknown units and unestablished intermediate amounts are not guessed.
The supplied seven swing scores use established eighth-note, zero/1024 controls;
Duck Tales' stored default 512 is overridden by its explicit initial 1024.

Export writes recognizable Swing/Straight words with MusicXML sound/swing:
first=2, second=1 and the eighth/16th unit, or straight. Written durations, grace
notes and tuplets are unchanged. Score-wide controls use direction system=only-top;
coincident equivalent controls print once while retaining both source assignments
in IR. An active document default attaches to an existing initial Swing heading
where available, avoiding a second visible heading (Player Select).

**Verified MuseScore 4.7.5 limitation:** the user's build 3654226 imports standard
first=2/second=1 as native ratio=50 instead of approximately 67. An authored
two-part Swing/Straight/Swing score imported and exported to MIDI plays all three
bars straight. Changing only the temporary native test's swing ratio to 66
produces offbeats at approximately .658 quarter notes in both parts, with .5
offbeats in the straight bar. Thus scope/reset import works, but the ratio
conversion is incorrect. Preserve standards-compliant MusicXML; do not invert
its ratio or change written rhythms to compensate for this importer bug.
The extracted AppImage ran offscreen with an isolated XDG profile; only the
temporary copy's GTK platform-theme plugin was disabled to permit headless use.

Evidence: [Finale swing value](https://usermanuals.finalemusic.com/Finale2012Win/Content/Finale/SwingPlayback.htm),
[actual metric unit](https://www.finalemusic.com/blog/swing-16th-notes-playback-in-finale/),
[MusicXML ratio semantics](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/swing/),
MuseScore importer `MusicXmlParserDirection::swing` at revision 3654226 and the
local authored runtime check. Exact Human Playback timing remains separate.

### Explicit backward-repeat state (2026-10-12)

The 24-byte numeric tag-203 record stores actuate +2, signed target +4 and
flags +10. Published PDK `FCBackwardRepeat` exposes the same EDT structure:
the loaded object starts at +0x36, so its independently confirmed actuate
getter +0x38 anchors the serialized translation rather than treating a live
object offset as a file offset. Target +0x3a and flag +0x40 corroborate the
relative field spacing. Paired legacy pass evidence, source barlines/ending
lists and all supplied repeat routes provide independent checks.

Flags &0x70: 0 automatic/nearest preceding forward repeat, 0x10 absolute
measure, 0x20 relative measure. Flags &0xc00: 0 always, 0x400 on pass, 0x800
until pass. Flag 0x4 resets the counter when another repeat action occurs;
0x1 is not that reset flag. Unsupported combinations fail, and records without
an actual backward barline do not install playback rules. Older short records
retain only their previously evidenced pass count. The canonical
`Measure.repeat_playback` retains these independent values.

`playback.measure_route` performs bounded traversal with separate per-repeat
encounter counts and consumed ending state. An outer repeat does not erase an
inner repeat unless its source reset bit requests that action. This recovers
Memories of Green's final return to bar 5 while skipping its first ending,
without filename-specific route logic. The 56-measure visit route has the
expected 224 quarters. Spring Yard's notation alone gives a longer route than
its MIDI's 156-quarter replay; playback-control stop preferences still need
their own serialized mapping before that discrepancy can be classified.

MusicXML preserves ordinary repeat/ending notation and its standard after-jump
attribute for reset behavior. This does not claim every Finale action/trigger
can be expressed by a repeat barline or verified in the user's MuseScore.
Nonstandard targets remain in IR for the navigation/export work. Evidence:
[published PDK](https://pdk.finalelua.com/class_f_c_backward_repeat.html), its
`ff_other.h` source, read-only RGP Lua getters and source/MIDI route checks.

### Known format facts — beams

**Enigma does not store beams.** It stores one bit per entry — `BEATBIT` in `eeppd.txt`, surfaced by
EnigmaXML as a `beam` field — meaning *this entry starts a beam group*. Everything else follows from
the durations: consecutive beamable entries belong to the group opened by the last entry carrying
the bit.

Confirmed against the corpus: a measure of eight eighth notes carries the bit on the first and the
fifth — exactly two groups of four. It matches the `.mus` `BEATBIT` on 30,819 of 30,820 paired
entries, the one exception being the `.mus`/`.musx` revision the entry-pool sweep already pins.

`enigma/beams.py` turns that into what MusicXML asks for, which is more: each note carries one
`<beam>` per level — an eighth has one, a sixteenth two — saying whether that level begins,
continues or ends there. Where a level covers a single note the beam becomes a **hook**, the stub on
the sixteenth of a dotted-eighth pair; it points forward if the note opens the group and backward
otherwise. 93% of corpus groups are one duration throughout and need no hooks; the other 6.6% are
why they exist.

Three decisions worth knowing. Dots are divided out before counting beams, so a dotted eighth (3/16)
beams once like the eighth it is. A group of one gets **no** beam, because a lone eighth is written
with a flag. And a rest breaks a group — MusicXML can beam over one, but Enigma's bit says where
groups *start*, not where they survive a rest, so that is the reading the data supports.

Because beams are computed rather than stored, the two containers agreeing (30,072 of 30,074 events)
shows they feed the same bit and the same durations into the same rule.

### Known format facts — fingerings

Finale has no fingering object. A fingering is an ordinary `articDef` whose `charMain` is a numeral,
which is why `enigma.articulations` cannot pass it through — it would have to call `1` an
articulation named "1".

**The character alone identifies one**, and the objection to answer is that a music font also has
glyphs at those code points. It does not arise here:

* every numeral definition in the corpus — 2,062 of them, `1` through `5` — carries an explicit
  `fontMain`. **Not one uses the document's music font.**
* those definitions occupy a font of their own. Across the corpus the numerals are assigned under
  exactly one font id, and no other character is ever assigned under it: 834 assignments, all
  numerals, nothing else.

That is what unblocks the `.mus`, which this project previously recorded as impossible. `fontMain`'s
offset in the `.mus` `articDef` genuinely does move within the 2011 era — the best single offset
matches 363 of 373 paired records, so it cannot be read — but the **character** is already
recovered, and the character is enough.

`0` is deliberately not read: three definitions carry it, none is ever assigned, and nothing says
whether it means an open string or an unused slot.

Corpus: **834 fingerings across 18 documents** from the `.musx`, 218 across 5 from the `.mus`. The
distribution corroborates the reading — 3 (261), 1 (219), 2 (174), 4 (126), 5 (54), the shape you
would expect of keyboard and string music.

**The `.mus` side is unverified against a paired document.** Six pairs carry a fingering in their
`.musx`; four have a `.mus` that does not read, and two are a different arrangement. What *is*
verified is the mechanism — `articDef.charMain` agrees across 72 pairs and 25,000-odd assignments.
Fingerings add no new field, only different values in the same one.

### Known format facts — articulations

Two records again. An `articAssign` entry detail names an `articDef`, and the definition says what
the mark is — not by name, but as a **character in a music font**:

```
articAssign(entnum) -> articDef -> charMain
```

So the meaning comes from the character, as `clef.py` reads a clef from `clefChar`. Five characters
sit at the same ASCII positions in every music font the corpus uses — Maestro, Engraver Font Set and
Broadway Copyist all write `.` staccato, `>` accent, `-` tenuto, `^` marcato, `,` breath mark — which
is what makes reading them without resolving the font defensible.

Two extended characters also have cross-font evidence: **249** (above-note form)
and **223** (below-note form) both mean **accent with staccato**, in Finale's
official [Maestro](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[Engraver](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm)
and [Broadway Copyist](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-broadway-copyist.htm)
charts (read 2026-10-11). Each expands to `("accent", "staccato")` in the existing
`Event.articulations` tuple. The public single-character table stays unchanged;
the resolver handles these composite glyphs separately and in assignment order.
MusicXML's [articulations](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/articulations/)
container permits both children on one note. The exporter already emits each
event's marks once on a chord's principal note, so no new IR type or exporter
path is needed. This recovers semantic marks; manual placement and automatic
alternate-glyph selection remain outside the resolver.

**Other characters produce no articulation.** The corpus assigns 29 distinct characters; emitting a guess would
put a wrong articulation on a real note, which is worse than leaving the note bare. Coverage is
22,821 marks across 273 documents. Separate resolvers handle evidenced fingerings, ornaments
and fermatas.

Fingerings use numerals 1–5 rather than articulation names; their resolver and evidence are
described above. The original font-layout gap is resolved for complete numeric
48/60-byte definitions below; new glyph mappings still require font/chart evidence.

#### Articulation fonts and symbol kind (2026-10-12)

Numeric tag121 has two complete layouts. RGP Allocate 0x4c1198 and DataSizeLoad
0x4c117a independently establish loaded bases +0x38/+0x68 and sizes48/60.
Subtract those actual bases, not the old low-character-word offsets: using +0x66
as the modern base would incorrectly treat font size as font ID. Font getter
0x4c1382 reads old byte+0x3A/new word+0x6C, size getter0x4c11b4 supplies the
neighboring size field, and flag2 getter0x4c0fc6 reads +0x4E/+0x80. The symbol-kind
getter tests flag2 mask2. Main-shape pointer0x4c0fe6 uses +0x58/+0x8A.

| Field | 48-byte legacy | 60-byte Unicode |
|---|---|---|
| main character | +0 u8 | +0/+2 two u16 words, high word first |
| main font ID | +2 u8 | +4 u16 |
| main font size | +3 u8 | +6 u16 |
| flag2 / main-is-shape mask2 | +22 u16 | +24 u16 |
| separate main shape ID | +32 u16 | +34 u16 |

The modern lower word at+2 was previously sufficient for BMP glyphs; it is not
two bytes of padding before the character. Combining the words preserves the
published 32-bit Unicode range. The high-word-first serialization also matches
the independently mapped numeric four-byte playback controls. Every offset is
read only after its exact complete-layout length is established.

Normalize fontMain/sizeMain/mainIsShape/mainShape without treating a shape ID as
a character. All articulation-derived resolvers reject mainIsShape before glyph
lookup, including MUSX data. A shared score-only font registry resolves font IDs.
In the supplied corpus all5167 visible assignments use character definitions:
4889Maestro,270EngraverFontSet,8TimesNewRoman. The outstanding trill217 (three),
portato248 (50), marcato171/172 (three) all explicitly use Maestro. Objection's
161 character8 assignments and Athletic's two character0 assignments are also
Maestro character definitions, not custom shapes; do not label them as invented
visible accents. Their separate playback values remain a research item.

Evidence: published [articulation API](https://pdk.finalelua.com/class_f_c_articulation_def.html),
its ff_other.h structure/version selection, released RGP allocation/size/font/
flag/shape-pointer getters and the complete source-font registry inventory.
Authored tests distinguish neighboring fields, Unicode words and shape aliases.

On the `.mus` side: `articAssign` is details tag 1009 with the definition's cmper at payload +0;
`articDef` is others tag 121 with `charMain` at +0 (2011, 48-byte payload) or +2 (2012, 60-byte) —
the same era split as the clef table. A `.mus` sometimes **repeats** an assignment, on 23 corpus
entries; no `.musx` ever assigns the same `articDef` twice in 11,404 assignments, so the repeat is a
storage artifact its reader drops. Both containers then agree on all 27,155 events of the 72 paired
documents that carry articulations.

**Packed articulation assignments (fixed 2026-10-08).**
The local Scars of Time `.mus` contains 225 tag-1009 payloads of 20 bytes and six
of 40 bytes. The longer payloads hold two consecutive 20-byte assignment groups,
each beginning with the existing `articDef` u16 reference. On entry 114 (lower
staff, measure 5, beat 3), payload +0 is definition 5 (`charMain=103`, arpeggio)
and +20 is definition 14 (`charMain=85`, uppercase U). Finale's
[Maestro chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm)
identifies U as an above-note fermata, matching the original PDF on that chord.
All six trailing groups resolve to existing definitions: 14, 2, 1, 7, 1 and 7.
The former `_details_records` read only +0, discarding those trailing marks.
`_artic_records` now splits all complete 20-byte groups, preserving their order
and per-entry/definition deduplication, now distinguishing visibility as described
below. Empty payloads or partial
groups raise `CorruptScoreError` instead of silently dropping a marking.
Each emitted incidence is at least the raw incidence and the next available
incidence on that entry, avoiding collisions with following raw records;
`sourceInci` retains the raw row for report links. This is adapter metadata,
not a newly decoded file field.

At that stage no other group fields were interpreted; the arpeggio work below
now preserves the four positioning words. The local export recovers the fermata.
The two recovered accent assignments were subsequently found to be hidden and
are excluded from visible notation; their separate `sfz` expression now exports.
The remaining pedal assignments reach the normalized document but still need
a pedal resolver/exporter. Authored
synthetic tests cover multiple groups, repeated definitions, identity collisions,
partial groups and the full reader-to-export path. The licensed corpus is absent
in this checkout, so a new sweep over its era variants remains outstanding.

**Assignment visibility (fixed 2026-10-10).** In each complete legacy 20-byte
tag-1009 group, the **u16 at +10 has a hide flag in bit 0 (`0x0001`)**.
The adapter emits the EnigmaXML presence flag `hide` when that bit is set;
other bits do not imply hidden notation. All articulation-derived resolvers
(articulations, fingerings, ornaments, fermatas and arpeggios) exclude hidden
and linked-part assignments from the score IR. The normalized records retain
the flag and source-row link. Deduplication includes visibility, so an earlier
hidden copy of a definition cannot swallow a later visible assignment.

Evidence: read-only inspection of the released RGP Lua 0.79 binary referenced
below finds `FCArticulation::GetVisible` at x86_64 VM **0x4df13c** testing bit 0
of object **+0x4a**, returning true when clear. `SetVisible` at **0x4df15a**
sets or clears that same bit inversely. Subtracting the established assignment
base +0x40 gives serialized group +10. The published
[visibility API](https://pdk.finalelua.com/class_f_c_articulation.html)
gates the getter on Finale 2014b; this is API availability, not evidence that
the file field began in that version. Scars' Finale-2012-converter file already
uses it: upper m59 entry **1005** and lower m59 entry **1251** each pack visible
staccato def3 with hidden accent def7 (`+10=1`). Its PDF prints staccatos and
the separate `sfz`, without the two accents. Forty-seven pedal assignments
also carry the bit; they remain outside the current notation resolvers.
This does not change the meaning of visible accent glyph 62 or convert it to
a dynamic. Authored tests exercise each resolver and hidden/visible duplicates.

**Combined accent/staccato recovery (fixed 2026-10-11).** A fresh local audit
finds **25 visible assignments** of Scars definition **8**, `charMain=249`,
on lower-staff events in m20–35 and m55. At m28, entry **764** is at EDU0
(beat 1), and **769** at EDU2048 (beat 3). The previous resolver recognized
only single-component characters, dropping both the accent and staccato dot.
Raw definition/assignment joins independently match the new IR and XML
locations for all 25 events. The two hidden plain accents at m59, entries
1005 and 1251, remain hidden; `sfz` remains an independent expression.

The corrected MusicXML adds exactly **25 accents and 25 staccatos**. Removing
only those new articulation groups reproduces the complete prior score tree
and all metric note onsets, including all 928 pitches, 87 slurs, eight dynamics,
two hairpins and their three recovered positioning attributes. Original input
and unrelated `uv.lock` hashes are unchanged. Official MusicXML 4.0 schema
validation passes; Verovio imports 25 `acc` and 171 `stacc` articulations and
87 slurs across three visually inspected pages, including the m28 and m55
accents. `make check` passes lint/format/strict typing and
**1,785 tests** (seven skipped), including **13 new authored cases**. New cases
cover both glyph forms, visibility/linked-part filtering, assignment order,
both binary era layouts, packed duplicate assignments, unaffected following
notes and emitting both components only once per chord. Nine cases failed
against the previous resolver before the fix. No supplied score becomes a
fixture. MuseScore runtime and the licensed corpus remain unavailable here;
its inspected 4.7.5 importer recognizes both standard articulation names.

### Known format facts — arpeggios and their vertical extent

`enigma/arpeggios.py` recognizes an assigned, visible score `articDef.charMain`
of **103**, lowercase `g`, as a plain rolled-chord sign. Finale's official
[Maestro](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[Engraver](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm)
and [Broadway Copyist](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-broadway-copyist.htm)
charts agree. Unassigned definitions, linked-part variants, XML hidden assignments,
shape definitions and unknown glyphs do not place signs. There is no arrow on
this glyph; its default upward roll does not imply a printed upward arrow.

The legacy tag-1009 adapter retains these fields in each complete 20-byte group:

| Group offset | EnigmaXML field | Stored type | PDK name |
| --- | --- | --- | --- |
| +0 | `articDef` | u16 | `imrkdef` |
| +2 | `horzOff` | signed i16 EVPUs | `posadd` |
| +4 | `horzAdd` | signed i16 EVPUs | `posadder` |
| +6 | `vertOff` | signed i16 EVPUs | `noteadd` |
| +8 | `vertAdd` | signed i16 EVPUs | `lonoadd` |
| +10 bit 0 | `hide` | u16 flag | inverse of `GetVisible()` |

Evidence: the ETF specification's `IM` example orders the definition and four
positioning words; published PDK
[articulation getters](https://pdk.finalelua.com/ff__entrydetails_8h_source.html#l02060)
name the corresponding members. The
[vertical-copy API](https://pdk.finalelua.com/class_f_c_articulation.html)
defines the endpoint relative to the lowest note. The same EnigmaXML names are
documented by MIT-licensed musxdom's
[assignment model](https://github.com/openmusx/musxdom/blob/faf0a0156f4073142fe96022f9644a05fb774581/src/musx/dom/Details.h#L146)
and [field map](https://github.com/openmusx/musxdom/blob/faf0a0156f4073142fe96022f9644a05fb774581/src/musx/factory/FieldPopulatorsDetails.cpp#L125).
Read-only inspection of the same released RGP Lua 0.79 binary identified above
confirms signed 16-bit reads at object +0x42/+0x44/+0x46/+0x48, relative to its
definition word at +0x40: getter VMs 0x73c5e, 0x73f50, 0x73e84 and 0x7401a,
with `GetID` at 0x741c4. These are runtime object offsets; subtracting the
definition's base gives the file-group offsets. No plugin code is copied or run.

The tag-159 `instUsed` **24-byte staff slot** also retains signed i32
`distFromTop` at **+8**. The published
[staff-list getter](https://pdk.finalelua.com/ff__other_8h_source.html#l07039)
reads `-_instrumentused.separ`; musxdom's
[StaffUsed model](https://github.com/openmusx/musxdom/blob/faf0a0156f4073142fe96022f9644a05fb774581/src/musx/dom/Others.h#L2987)
uses the stored sign, negative down. In the released binary `SetStaff` at VM
0x1f4e0e writes the slot's leading staff word at object +0x38, and `GetDistance`
at 0x1f4eda negates the i32 at +0x40. Their difference establishes slot +8.
The Scars score's default and page layouts independently store lower-staff
distance **-288**, corroborating the sign and width.

For a two-staff brace with known default score geometry, the reader combines
that distance, a carried G/F/C clef and written pitch to locate notes in EVPUs
(24 per staff space, 12 per diatonic step). A source `vertAdd` extending below
the assigned event connects exactly one ordinary, simultaneous lower chord
only when its entire pitch range lies within the extension. No brace or MIDI
timing alone creates a roll. Missing geometry, ambiguous candidates, graces,
partial chord coverage and an independently marked lower chord retain the
single-staff sign. Larger spans, nonstandard staff geometry, changing system
spacing, manual shapes and arrow glyphs require further evidence.

`Event.arpeggios` appends immutable `Arpeggio` objects to the canonical IR.
Connected events share a group token and the participating staff-part ids;
`Score.parts` remains one part per source staff. MusicXML emits `<arpeggiate>`
directly in each participating pitch's `<notations>`, unlike an accent which
belongs once to the chord. The
[MusicXML reference](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/arpeggiate/)
uses a shared `number` for connected rolls and `unbroken="yes"` as a staff-span
hint. A connected run is projected into one XML part with numbered staves,
clefs, keys, time signatures, unique voices and exact cursor backups. Brace
names/abbreviations become part labels; surrounding groups survive. Independent
simultaneous rolls get different numbers. Without a connection, part layout is
unchanged. This preserves engraving semantics without reconstructing MIDI timing.

Local verification (2026-10-10): Scars has six source assignments, at m1, m5,
m12, m13, m16 and m18. The m1 assignment's `vertAdd=-312` reaches the lower
chord; the other five stay on the lower staff. Export has 22 note-level
`arpeggiate` elements representing **six printed signs**, including the opening
continuous span. All 928 written pitches and every earlier note, onset,
attachment and direction match the previous corrected export after accounting
for staff/voice identities. The official schema validates it; all three
Verovio pages were inspected. Authored regressions cover recognition, packed
positions, source geometry, span ambiguity, cursor rewinds and grouping. The
licensed corpus and a MuseScore runtime are absent here.

### Known format facts — fermatas

`enigma/fermatas.py` uses the existing `articAssign -> articDef -> charMain` join.
Only assigned visible score records place symbols; unused definitions and linked-part
variants do not. Glyph **85**, uppercase `U`, is a normal upright fermata;
glyph **117**, lowercase `u`, is its inverted counterpart. The positions agree
in Finale's official [Maestro](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[Engraver](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm), and
[Broadway Copyist](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-broadway-copyist.htm)
charts. The packed assignment on Scars entry 114 and the PDF's above-note symbol
independently confirm the upright mapping. Unknown shapes, font-specific glyphs
and automatic alternate-glyph placement are not inferred.

`Event.fermatas` carries immutable `Fermata(inverted=False|True)` objects through
the canonical IR. MusicXML emits an empty `<fermata type="upright|inverted"/>`
directly inside the note's `<notations>`, once on a chord's principal note.
Empty content means the normal rounded shape in the
[MusicXML reference](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/fermata/).
Notes and rests retain their metric and written durations; a hold symbol does
not specify a fixed playback stretch or an inferred tempo curve.

### Known format facts — grace-note slashes

Finale has a document-wide
[Always Slash Flagged Grace Notes setting](https://usermanuals.finalemusic.com/Finale2010Mac/Content/Finale/IDD_GRACENOTEOPTIONS.htm)
and an individual entry flag. The published
[entry getter](https://pdk.finalelua.com/ff__noteframe_8h_source.html#l01845)
names `XEF_SLASHGRACE`; the
[preference getter](https://pdk.finalelua.com/ff__prefs_8h_source.html#l02846)
names `graceAlwaysSlash`. Read-only inspection of Robert G. Patterson and
Jari Williamsson's released [RGP Lua 0.79](https://robertgpatterson.com/-fininfo/-rgplua/rgplua.html)
establishes their legacy locations:

| Field | Stored location | Interpretation |
| --- | --- | --- |
| Individual `slashGrace` | entry slot +22, u16 extended flags, mask **0x0100** | Presence enables slashing eligible graces. |
| `slashFlaggedGraceNotes` | ETF **`^44(65534)`**, incidence 0, word 4 (zero-based), payload **+8 u16**; zlib-era numeric tag **58** | Nonzero enables automatic slashing. |

Both words use the document's byte order. `FCNoteEntry::GetGraceNoteSlash` reads
bit 0 of the runtime extended word's high byte; the adjacent SmartShape getter
reads mask 0x20 from its low byte. `FCMiscDocPrefs` stores `graceAlwaysSlash` at
offset 34 in the **assembled PDK preference structure**. Its location map selects
`^44`, word 4, size 2, with no conversion or minimum-version restriction. That
structure offset is not a file offset. The numeric tag follows the existing
`^95 -> 109` mapping: numeric ETF preference tags become tag +14 in the zlib pool.

Reproduction: the inspected `RGPLuaFin26Mac.zip` has SHA-256
`513a926c66a53e39d6a2c3ccce0d318bd6084116c634f790adaeb543abbb6fd1`;
its `RGPLua.bundle/Contents/MacOS/RGPLua` executable has SHA-256
`8060b4416da8671b527ec0eb681d7b95e1dbcbf5c0acbc60168e3fc634a8fc48`.
In the x86_64 slice at file +0x4000, the slash getter is at VM 0x467efa and
`__FCPrefsBase::MapPrefStruct` at 0x4f0a4e. The latter selects a 50-record,
24-byte-stride miscellaneous-preferences map at VM 0x704a90 (file 0x708a90);
record 17 maps structure offset 34 to `^44`, incidence 0, word 4. The binary
was never executed and no binary or implementation code is vendored. See
`docs/REFERENCES.md` for attribution and the released binary's CC BY 4.0 license.

The adapters translate the evidenced **12-byte option incidence** into
`graceNoteOptions`: presence of `slashFlaggedGraceNotes` means true, an empty
record means confirmed false, and an absent or unsupported payload leaves the
setting unknown. Linked-part preferences do not override score preferences.
The entry reader surfaces `slashGrace` independently of ordinary entry flags.
EnigmaXML already uses the same names, corroborated by
[musxdom's options](https://github.com/openmusx/musxdom/blob/faf0a0156f4073142fe96022f9644a05fb774581/src/musx/dom/Options.h)
and [entry semantics](https://github.com/openmusx/musxdom/blob/faf0a0156f4073142fe96022f9644a05fb774581/src/musx/dom/Entries.cpp#L1279).

`enigma/beams.py` groups consecutive grace entries separately from ordinary
entries; ordinary beams can span intervening graces. `enigma/graces.py` resolves
the source style after beaming: a non-rest grace with an eighth-or-shorter base
value and no beam is slashed when either setting enables it. Beamed and unflagged
graces remain unslashed. Manual expression-based slashes and hidden-entry beam
exceptions are not decoded here. `Event.grace_slash` appends an optional boolean
to the canonical IR: true/false exports `<grace slash="yes|no"/>`, and unknown
retains a bare `<grace/>`. Written and metric durations are unchanged.

Local evidence: Scars of Time tag 58 has payload
`000000000000070001000200`, so automatic slashing is enabled. None of its 24
graces has the individual flag. Source-derived output nevertheless restores
the PDF's twenty slashed singles (nineteen upper-staff from m28 onward, one
lower-staff at m19) and preserves four unslashed beamed graces in m7/m8.
Authored regressions cover both byte orders, all three legacy layouts, XML input,
individual/global precedence, missing settings, malformed layouts and beam separation.
No licensed-corpus sweep has run for this change; that corpus is absent locally.

The same PDK map places `gracePlaybackDur` (assembled offset 32) in `^27`, word 4,
zlib tag 41 payload +8. Scars stores **128 EDU**, but this playback preference is
not yet propagated or exported. The inspected
[MuseScore importer](https://github.com/musescore/MuseScore/blob/78f0c2195f2505a1374eda52f13644d2a35838d2/src/importexport/musicxml/internal/import/importmusicxmlpass2.cpp#L6578)
maps an unslashed eighth to an appoggiatura and `slash="yes"` to an acciaccatura;
its steal-time attributes do not retain the percentages as playback duration.
Restoring source notation therefore does not promise Finale's exact Human
Playback timing. The user confirmed the regenerated MusicXML works in MuseScore
on 2026-10-10; import/audio has not been run in this environment.

### Known format facts — upper mordents

`enigma/ornaments.py` follows the same `articAssign -> articDef -> charMain` join.
Only assigned score records count; library entries alone and linked-part variants
do not place ornaments. Glyph **109**, lowercase `m`, occupies the mordent position
in Finale's official [Maestro](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
[Engraver](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm), and
[Broadway Copyist](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-broadway-copyist.htm)
charts. No additional binary field or font offset is inferred.

Independent local evidence: Scars of Time assigns definition 6, `charMain=109`,
ten times, in upper-staff measures 11, 12, 17, 18, 19, 29, 30, 33, 34 and 56.
The PDF shows the unstruck symbol; the performance MIDI plays main/upper/main at
each placement. These explain 20 additional MIDI attacks, without adding written
notes to the score. This score remains a local investigation input, not a licensed
repository fixture; regression tests use authored synthetic fragments.

The IR calls this `Ornament(kind="upper-mordent")`. MusicXML calls the unstruck,
upper-neighbor symbol [`inverted-mordent`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/inverted-mordent/),
whose naming differs from SMuFL. Emit it once on a chord's principal note, with
`start-note="main"`. The written key and principal pitch determine the upper
diatonic neighbor: `harmLev + 1`, `harmAlt = 0`, through the existing pitch speller
and staff transposition. `auxiliary_semitones` records supported distances of one
or two semitones, exported as `trill-step="half"` or `"whole"`. This matters for
F# -> G and B -> C in E minor. Other distances remain unknown and leave the
consumer's ornament playback defaults in effect. Auxiliary accidental signs and
exact performance timing are not decoded. Unknown glyphs still produce no ornament.

#### Assigned trills and principal chord notes (2026-10-12, F15)

Maestro character **217** is the trill symbol in the official font chart. Require
the decoded main font to be Maestro, a character definition, and a visible score
assignment; a text font's character217 is not an ornament. The supplied corpus
has exactly three placements: Hikari upper-staff bars22/23 and Spider Dance
upper-staff bar41. Authored tests cover keys, reversed chord ordering, hidden and
linked-part assignments and unrelated fonts.

An above-chord trill ornaments its upper note. This is Finale's documented
[Human Playback rule](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/Human_Playback_Custom_Style.htm),
independently corroborated by Spider's reference: the C6 alternates with Db6,
while G5 remains held. Preserve `Ornament.pitch_index` and derive the key neighbor
from that note, then put `trill-mark` on that exact MusicXML chord note. The
separate articulation drawing flag `useTopNote` is **not** the playback selector:
RGP's getter0x216AE8 tests flag1 mask0x80 (flag1 at serialized+10), but all three
trill definitions have flag1=0x501A with that bit clear. Do not mistake a drawing
anchor for the musical principal.

The four performed Hikari trills explain44 extra reference attacks; the two
performed Spider trills explain24. Keep their written notes/durations intact.
Human Playback's acceleration is not an additional written rhythm. Actual
MuseScore4.7.5 import recognizes the symbols but attaches ornaments to ChordRest
(`MusicXmlParserNotations::addNotation` -> `addTurnToChord`), discarding the
individual note attachment. Runtime export consequently trills both Spider
chord pitches, even with the mark on C6. This importer limitation and its fixed
trill cadence remain separate from source recovery; no extra written notes or
voice split are manufactured to work around it.

#### Combined tenuto and staccato (2026-10-12, F19)

The official Maestro chart identifies characters248 (above) and60 (below) as
tenuto with staccato. Recognize them only with established Maestro font context
and emit both existing articulation components once per assigned entry, through
the existing chord/hidden/linked-part/packed-assignment handling. All50 source
placements use248: Peaceful Days8, Hikari2, Determination36, MEGALOVANIA4.
There is no new binary layout or performance note-off rule; portato durations
in Human Playback are not rewritten into notation.

#### Marcato glyph variants (2026-10-12, F20)

The official Maestro chart identifies171/216 as above/below marcato and172/232
as above/below marcato plus staccato. With verified Maestro font, map them to
strong-accent and, for composite glyphs, staccato. `strong-accent-down` retains
the inverted glyph orientation and exports as standard `strong-accent type=down`.
SMB3 Athletic assigns172 twice and171 once; its two zero-character assignments
remain separate R01 playback controls, never invented marcato. Main/alternate
symbol placement is independent of identifying this symbol's components.

### Known format facts — Unicode expression descriptions and dynamics

#### Auxiliary ornament accidentals (2026-10-12, F16)

Maestro's small accidental characters105/73/233 mean flat/sharp/natural (official
chart). Resolve a visible score assignment only when it accompanies exactly one
ornament on the same entry and its signed `vertOff` places it above that ornament.
Keep competing ornaments, unrelated text fonts and ordinary adjacent-note
accidentals separate. These use existing signed assignment positioning fields;
there is no new byte offset. The explicit accidental is absolute vs the natural
auxiliary, overriding its key accidental, never altering the main written note.

MEGALOVANIA entry3116, upper-staff bar14, assigns small flat definition65 with
Maestro font12, horzOff11/vertOff75 and mordent definition18 at0/0. The PDF draws
the flat above the mordent and both MIDI traversals use Ab5 above G5. Store
`Ornament.auxiliary_alteration=-1`, update the neighbor distance to1, and export
`accidental-mark placement=above` with the mordent. Above-chord mordents, like
trills, select the upper written note, independent of serialized chord order.
MuseScore4.7.5's inspected ornaments importer skips accidental-mark and ignores
trill-step; runtime support must be distinguished from standard XML preservation.
Authored tests cover altered keys, explicit natural/sharp, chords, visibility and
ambiguous competing ornaments. No performance attacks become written notes.

#### Two-note tremolo display constructions (2026-10-12, F17)

Finale's [tremolo instructions](https://usermanuals.finalemusic.com/Finale2014Mac/Content/Finale/Tremolos.htm)
describe two notes whose combined time is notated on each member, with Human
Playback generating the alternation. The supplied source uses hidden augmented
tuplets plus explicit display modifications, rather than a dedicated tremolo bit.
Require two adjacent pitched non-grace entries of equal32nd value, a single
beam group, a hidden tuplet spanning exactly those entries, and corroborating
display data. Ordinary tuplets, Sub Castle's10/14-note cadenza tuplets, unrelated
custom noteheads and ordinary beams do not meet that rule.

* Title Screen upper bar2: entries99/728 each store128EDU; hidden tuplet1x256 in
  1x2048 yields1024EDU each. Both have Maestro half-notehead override250. Their
  true written tremolo value is2048EDU on each member, spanning2048EDU combined.
* Spider Dance upper bars35/39:1070/1071 and1221/1222 each store128EDU; hidden
  2x128 in1x1024 yields512EDU each. Up/down beam-extension records shorten all
  three beams at both ends, showing detached tremolo strokes. Written values
  become1024EDU each; the combined time remains1024EDU.

Normalize numeric details1021/1022 as beamExtUp/Down: exact10-byte data, signed
left/right adjustments+0/+2, beam mask+8. Spider's four rows have20/-20 and0x0B80.
Published `FCBeamExtensionMod` and released RGP getters corroborate the layout:
base0x40, GetLeftAdjustment0x6DD9C reads+0, GetExtend0x6CB54 reads+8, tests
has-extension bit11 (0x800), and selected levels0x200/0x100/0x80 for eighth,
sixteenth,32nd. These are extension fields, not primary beam-mode or stem fields.

Numeric detail1058 has packed20-byte notehead modifications (20/40/60-byte
payloads in this corpus); split every complete group, retaining source scope
and noteID at+0. Legacy customChar is u16+6, Unicode-era getter uses32bits at+6;
custom-font flag is bit0 at+8/+10 respectively. RGP Allocate0x4DEC22 gives
bases0x40/0x54 and DataSizeLoad0x4DEC0A gives20; GetCustomChar0x5B576 and
GetUseCustomFont0x5BB3A anchor the fields. Tremolo recovery uses only established
inherited Maestro half-heads, excluding custom fonts. Packed note IDs can repeat
in retained source records; do not let one erase its neighboring modification.

#### Assigned cross noteheads (2026-10-14, PDF review P04)

Numeric1058 and typed `noteheadMod` assignments now join to the entry's stable
note ID, not its serialized chord index. Air Man's assigned character192 heads
(including bass26 entries1601/1659/1660 and staff6 equivalents) and Crash Man40
entries1836-1842 use inherited Maestro. The published
[Maestro chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm)
and [Engraver chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm)
identify character192 as the cross/non-pitched head. A visual head does not
convert a pitched note to percussion or modify its playback.

Custom font IDs are at legacy+10/Unicode+12, enabled only by the existing
custom-font bit. RGP GetFontName0x5C0AC reads object+0x4A/+0x60 relative to
the previously established bases0x40/0x54, independently corroborating the
[PDK font selector](https://pdk.finalelua.com/class_f_c_notehead_mod.html).
Inherited heads use the score's established default registry ID0, as tremolo
recovery does. Unknown fonts/characters remain explicit `Notehead` data with
an unresolved-glyph diagnostic, rather than a guessed shape. Linked-part mods
do not override the score. Clear-character0 places no shape. Invalid or
ambiguous note IDs and conflicting modifications raise a clear score error;
identical repeats are idempotent. Authored mixed chords and packed20/40-byte
records test both layouts and custom-font/part boundaries.

`Event.noteheads` preserves per-pitch shape independently of rhythm/ties and
allows later explicit fill recovery. Export combines an enclosure and shape
in a single MusicXML notehead. The targeted Air/Crash exports pass written-note
projection/XSD, import individually in MuseScore4.7.5 and render cross heads
at the inspected passages. Air's extra active staves are a separate print-
visibility investigation; Crash's unresolved literal route remains unchanged.

#### Explicit open-head fill (2026-10-14, PDF review P05)

The same primary Maestro/Engraver charts independently identify character250
as the half/open oval head. Resolve only this evidenced font-gated override
as `Notehead(shape="normal", filled=False)`, using MusicXML
[filled](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/notehead/)
independently of the note type and metric duration. Main Theme60 entry1607
noteID1 stores250; its1536EDU G4 remains a dotted quarter with exact timing,
and its silent invisible F3 glissando endpoint stays intact. MuseScore4.7.5
imports a half `headType` and visibly renders the open head. Title Screen's
already resolved half-head tremolo is a regression control; neither source's
attack comparison changes. The PDF has different dot styling at60, for which
no independently established suppression field was recovered in this task.
Do not manufacture a half-note metric value or remove rhythmic dots to fit it.
Authored chords confirm only the assigned member receives the fill override.

#### Per-note cross-staff placement (2026-10-14, PDF review P03)

Numeric detail1036 is the10-byte `crossStaff`/ETF CD entry detail: stable
noteID u16+0, destination staff s16+2. Retain packed complete records and
linked-part scope. Released RGP's CrossStaff constructor0x6714C establishes
base+0x40/DataSize10; its vtable at0x6D3300 exposes Tag getter0x111B90
(`edCD`) and size getter0x6B658. GetStaff0x67ABC reads signed+0x42.
The [PDK](https://pdk.finalelua.com/class_f_c_cross_staff_mod.html) identifies
this as the note's connected staff, separately from its stable noteID.
`eeppd.txt` independently documents the per-note CROSSBIT0x10000000.
Require that active flag and an unambiguous detail/note-ID join; unflagged
retained modifications do not move notes. Missing/reserved destination staves,
conflicting modifications and ambiguous note IDs fail clearly. Active flags
without a destination retain an unresolved attachment as described below.

Steel Samurai has28 assigned bass-to-upper notes in21-24; Title Screen has
two upper-to-lower notes107/108 in2. Their raw note flags agree with these
details. Canonical `Event.cross_staff` stores per-pitch destination part IDs
while retaining the source part, voice, spelled pitch, time and beam group.
MusicXML bundles explicitly connected staff-parts, emits destination staff on
only the assigned members, and keeps a common exported voice/beam group.
An unassigned member of a mixed chord retains its original staff. Destination
attachments can establish an otherwise resting staff's score membership.

Both sources pass projection/XSD and isolated MuseScore4.7.5 import; actual
Steel beam bridges and Title's changed staff destinations were visually checked.
Their source attack comparisons remain unchanged. This native inspection also
caught the separate P01 default-clef regression on Title's literal0 switch;
that correction is tracked independently. Auxiliary rests remain P12 work.

The subsequent105-source build/export check found Corridors of Time has29
active note cross-staff flags with no1036 destination, alongside96 valid
assignments. A flag alone supplies no destination. Retain these as
`CrossStaff(part_id=None)` with an explicit `cross-staff-destination` diagnostic,
leaving their source part/voice/printed placement intact. This is incomplete
semantic source data, not a truncated record or permission to infer a staff.
Explicit invalid destination references and ambiguous IDs still fail clearly.
An authored missing-detail control pins this behavior. All105 build and pass
written-note projection after this correction; nine scores contain cross-staff
notation. Corridors separately passes schema/native import and keeps all1188
source/MIDI attacks matched. The final105 native/MIDI integration remains due.

#### Stored beams through rests (2026-10-14, PDF review P06)

The previous resolver broke every group at a rest. Actual BEATBIT boundaries
can instead define a continuous group containing interior rests. Recover these
when source beam settings are present; unknown settings retain the prior
conservative behavior. The automatic group-of-four preference does not override
already stored/manual group-start bits. Separate edge and secondary settings
still apply, rather than beaming every rest or synthesizing new groups.

Numeric preference55 (`^41`), score comparator65534, incidence0 word1 (+2)
stores the beam flags. The evidenced complete payloads are12 and36 bytes;
unsupported lengths place no guessed setting. DCL uses the same `41` preference
in its file byte order. RGP FCMiscDocPrefs vtable0x6E6688 gives Allocate0x33A102
(base+0x3A) and Tag0x4FDBEE (`pfMI`). Primary getter0x545442 reads object+0x4C,
bit1; secondary getter0x545520 reads+0x4D, bit1. Subtracting the independently
anchored base gives MI-map offset18. MapPrefStruct's MI table (binary file
0x708A90) maps this to `41`, incidence0, word1, size2, conversion0.
These are unrelated to the similarly named `pfMS` measure-spacing table.

Published [PDK settings](https://pdk.finalelua.com/class_f_c_misc_doc_prefs.html)
and [Finale beam options](https://usermanuals.finalemusic.com/Finale2012Win/Content/Finale/IDD_BEAMOPTIONS.htm)
identify masks0x1 edge-rest primary beams,0x2 automatic rest inclusion,
0x40 half-stems and0x100 secondary beams over rests. Normalize the established
EnigmaXML field names as `beamOptions`: incEdgeRestsInBeamGroups,
incRestsInClassicBeams,doStemStubs,extendSecBeamsOverRests, as independently
described by [musxdom's options](https://github.com/rpatters1/musxdom/blob/main/src/musx/dom/Options.h).
The reviewed Spider/MEGAL/MAP7/Spear/Spring/Slider sources store0x1A;
Death Mountain stores0x9A. Their edge and secondary extensions are off.

Keep interior rests on the primary beam, remove leading/trailing rest coverage
when edge extensions are off, and cap rest beam levels at1 when secondary
extension is off. Emit no lone rest hooks or all-rest beams. Explicit group
breaks, longer rests and grace/ordinary separation remain intact. The canonical
events' pitch/rhythm/rest/visibility stay unchanged. Authored tests cover both
orders/layouts, unknown/part settings, continuous/broken/edge groups, hooks and
graces. Seven targeted exports pass projection/XSD/isolated MuseScore4.7.5;
attack counts and the existing navigation exceptions remain unchanged. Rendered
MEGAL14, Spider35/39 and Slider2 were checked for the recovered primary beams.
Half-stem display controls are retained in the source options; arbitrary manual
stem geometry is outside this beam-group change.

#### Navigation drawing positions and reused signs (2026-10-14, P07)

`textRepeatAssign.horzPos/vertPos` were already correctly decoded but were
discarded at the IR boundary. Retain both as exact staff-space coordinates
(EVPU/24), plus the definition's justification. The
[PDK assignment](https://pdk.finalelua.com/class_f_c_text_repeat.html) independently
identifies the horizontal measure-origin/justification relation and the vertical
top-line reference. These graphical values do not supply a metric note offset
or authorize changing a jump's encounter/pass rules. Bounds-check typed values
as signed32-bit EVPUs; missing values remain unknown.

Crash40 stores left-origin words485/109 and a reference segno649/95, reusing
definition9 from the actual sign in9. Emit standard graphical coordinates on
signs and applicable right-origin words; retain an unresolved left/center word
horizontal transform explicitly in IR/diagnostics. Words keep their existing
bar-end export anchor. A start-anchor experiment with raw word X was valid
XML but regressed MuseScore, which ignored the X and printed words at the bar
start; that serialization was withdrawn. No metric endpoint was moved to fit
a screenshot. Coordinates remain independently recoverable source data.

Repeated glyph-definition IDs are not unique playback-marker identities.
Give actual XML marker placements distinct labels, and resolve each explicit
source jump to its measure's label. A passive duplicate on another measure is
a printed reference only when existing source targets identify exactly one
actual destination for that repeated definition. Emit that reference as the
standard [inline symbol](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/symbol/),
without an added sound marker. Ambiguous/multiple real destinations keep their
markers; no new target is inferred from appearance or drawing position.

Authored cases cover signed positions, malformed bounds, independent jump
timing, references and two real targets sharing one definition. Five affected
sources pass projection/XSD and isolated MuseScore4.7.5 imports with the same
literal-route exceptions. This build's importer ignores horizontal coordinates
on signs and can infer a marker even from an inline symbol when text inference
is enabled. Crash40's sign therefore still renders at the start; this is an
explicit remaining native/layout limit, not a completed visual match. The
original right-side words placement is preserved after the rejected experiment.

Tuplet number style is flag low-nibble at serialized+18; bracket style uses
0x3000 there. RGP GetSymbolicNumber0x796E0 anchors base0x40 to existing+0,
GetNumberStyle0x4DF7F6 and GetShapeStyle0x4DF80E read base+18. Zero/zero explicitly
hides both decorations. Short old ratio-only records do not imply hidden display.

Store canonical `Part.tremolos` with exact event endpoints and stroke count,
correct the written values while retaining exact metric durations, and export
start/stop tremolo ornaments. MusicXML's required duration/type relation and2/1
time-modification follow [W3C](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/tremolo/).
Reject dangling/overlapping/nonadjacent pairs. Authored tests include chords,
ordinary tuplets, packed heads, signed offsets and partial hostile records.
Actual MuseScore4.7.5 imports one Title and two Spider TremoloTwoChord objects;
rendered Title page verified. Its32nd alternation rate differs from Human
Playback's context-dependent rate (reference8+16 extra attacks). Its existing
post-jump-repeat limitation also remains; neither difference changes notation.

Numeric-pool `.mus` **others tag 241** stores the expression description at
serialized **payload +36**. Earlier files use an 8-bit string; a **Finale 2012
or newer banner selects UTF-16LE**. The old adapter stopped at the first NUL
byte, reducing `pianissimo`, `mezzo piano` and `sforzato` to `p`, `m` and `s`.
Decode complete 16-bit code units and stop at an aligned `0000` unit or the
record boundary. A cross-unit pair of zero bytes is not a terminator. Odd tails
and malformed surrogate sequences before the terminator raise a clear
`CorruptScoreError`; bytes after a complete terminator are outside the string.
Older 8-bit platform decoding is unchanged.

The serialized offset is established by the earlier paired-container audit in
`docs/formats/expressions-and-dynamics.md` and the full words at +36 in Scars'
2012-converter payloads. Encoding/era evidence is independent: the published
[PDK header](https://pdk.finalelua.com/ff__other_8h_source.html) selects
`EDTTextExpression2012` for Finale 2012+, and read-only inspection of RGP Lua
0.79's `FCTextExpressionDef::GetDescription` at x86_64 VM **0x4c38c8** chooses
`FCString::SetUnicodeString(unsigned short const*, int)` from host version
**0x11000000** (2012). Its live PDK member offset +0x22 does **not** establish
the serialized +36 offset. Finale's
[Unicode documentation](https://usermanuals.finalemusic.com/Finale2012Win/Content/Finale/Unicode_Fonts.htm)
corroborates the version transition. No plugin code is copied or executed.

Graded dynamics are named from the complete description, retaining the file's
own playback value. Attack descriptions alone can be ambiguous. Legacy Maestro
character **167** (decoded as U+00A7 `§`) is specifically **`sfz`**, shown in the
official [Maestro chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm)
at ALT+0167 and also in the
[Engraver chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm).
Scars assigns expression14, glyph 167, description `sforzato` at m59; its PDF
independently prints `sfz`. With unresolved legacy font markup, require the
matching glyph and attack description. The other `sforzato` glyph `\x8d` and
the `S` sforzando variant remain unnamed pending their own evidence. Neither
MIDI velocities nor articulation accents supply a dynamic name.

Local verification restores eight assigned staff-1 dynamics: **m1 pp, m6 mp,
m20 mf, m28 f, m36 mf, m44 mp, m52 f, m59 sfz**. The existing `Expression` IR
and exporter produce real MusicXML `<dynamics>` elements; m59's hidden accents
stay out while its visible staccatos survive. All 928 pitches, notes, metric
onsets, ties, beams, grace slashes, mordents, arpeggios, the fermata and other
directions match the prior corrected file. Official-schema and three-page
Verovio checks cover this local input; authored regression fragments cover
Unicode, malformed data, attack ambiguity and assignment visibility. Historical
corpus counts above are not remeasured: the licensed corpus is absent here.

### Assigned octave SmartShapes (2026-10-11)

The Finale PDK `FCSmartShape` enum identifies type 4 as octave down, 5 as
octave up, 20 as two octaves down and 21 as two octaves up. These types use the
same measure/staff/EDU termination segments as hairpins, with 4096 EDU per whole
note. Score measure assignments establish ownership; hidden/palette/linked-part
copies do not create score lines. The NinSheetMusic audit has 51 visible assigned
records in 18 files: 50 within the score and one stale Spring Yard record already
covered by the structured stale-shape diagnostic. No in-score intervals overlap
on a staff. MIDI/PDF evidence corroborates both displacement signs and sizes.

Endpoint attacks are included. In particular Memories of Green's shape 32 has
identical endpoints at staff 2, measure 22, EDU 0: it lowers that attack only.
`Part.octave_shifts` retains the source interval and signed sounding displacement;
the events retain written pitch spelling. MusicXML requires *performed* note
pitch values: a positive displacement changes the XML octave and emits type
`down`, size 8 or 15; negative displacement uses type `up`. The MuseScore 4.7.5
importer's `octaveShift()` maps these to 8va/15ma and 8vb/15mb, respectively.
The W3C octave-shift reference explicitly specifies this performed-pitch rule.

An XML stop takes effect before its timed attack. When the source end is exactly
an attack onset, export therefore stops after the covered note, capped by the
next event onset or following line start. This also preserves grace/anchor point
spans. Endpoints between attacks and ordinary barline endpoints remain exact.
Malformed endpoints and ambiguous overlapping staff intervals fail explicitly;
no octave is inferred from clef or MIDI. The existing staff-transposition pitch
spelling runs before this independent displacement.

Evidence: [PDK enum](https://pdk.finalelua.com/class_f_c_smart_shape.html),
[MusicXML octave-shift semantics](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/octave-shift/),
read-only local source/MIDI audit and MuseScore importer revision 3654226.

### Graphical slurs on one event (2026-10-11)

Memories of Green's assigned shape33 has the same source entry230 at both
ends in staff1 measure13, but distinct active drawing adjustments: start
(-112,13) EVPU and end(0,12), with flags16897. The PDF shows an incoming curve
at the second ending. This is geometry on one event, not an invalid zero-time
phrase and not an instruction to manufacture an earlier note or playback tie.
The canonical Slur retains a graphical discriminator and exact endpoint
adjustments in staff spaces (24EVPU per space). Same-event curves require
distinct active horizontal endpoints; ordinary zero/reversed spans still fail.

MusicXML retains a start/stop slur pair on that note with relative endpoint
coordinates in tenths (10tenths per staff space), without any `tie`/`tied`
playback changes. The official [slur reference](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/slur/)
provides these drawing-position attributes. Numbering starts a graphical pair
before stopping it while preserving the usual close-before-open order for
ordinary touching spans. Authored binary and export tests cover coordinates,
inactive adjustments, ordinary invalid spans and unchanged note durations.

**Importer limitation:** MuseScore4.7.5's [importer](https://github.com/musescore/MuseScore/blob/3654226/src/importexport/musicxml/internal/import/importmusicxmlpass2.cpp)
converts slurs anchored to the same chord into a laissez-vibrer item and does
not honor these relative endpoint coordinates. The standard XML and canonical
geometry are preserved, but this curve needs manual graphical correction in
MuseScore. Do not claim the imported display matches the source PDF.

### Stale assigned SmartShapes (2026-10-11)

Spring Yard's active shape records still refer to bars42–43 and45–46 beyond
its 29-bar score; Hurry Up has corresponding bars11–12 and14–15 beyond five
bars. Spring also retains obsolete octave/custom-line records. These are
stored source records, not evidence for extending the current musical score.
Source eligibility requires a score assignment, a visible score definition,
valid positive endpoint fields and both endpoints beyond the actual last bar.
Library/linked-part-only definitions do not count as assigned score shapes.
Partially missing endpoints, malformed fields, reversed spans and zero-length
hairpins remain subject to ordinary validation rather than being quarantined.

`stale_smart_shapes` returns the excluded IDs and structured ScoreDiagnostic
records, which build_score retains on the canonical Score. Raw source records
remain untouched; active musical endpoints are never clamped or rescheduled.
The hairpin/slur resolvers accept these source-scope IDs, and future shape
features must reuse the same eligibility decision. Authored scope tests and
the 75-file production sweep cover this policy; Spring and Hurry now validate.

### Compiled legacy text command boundaries (2026-10-11)

The 75-file raw text-stream inventory disproves the old fixed-four-byte
Unicode-strip rule. Opcode81 appears30times and has **eight** argument bytes
before the literal note glyph/words. Opcode95 appears90times with eight bytes
as well. Consuming four leaves U+0001/U+0004 in ten exported tempo strings.
For example Coin's expression63 has opcode81, seven01bytes plus04, then the
literal `q`; its reset has eight01bytes, then ` = 225`. No argument byte is
written notation. Opcode95's eight01bytes end at the next command/section.

Observed argument widths:

| Bytes | Opcodes (hex) |
|---|---|
| 8 | 81,95 |
| 4 | 84,85,86,A4,A5,A6 |
| 0 | 8A,8B,8E,8F,92,94,96,99,9C,A0,A2,A3,A7 |

Zero-argument commands can precede literal copyright years or instrument
words; a four-character strip also destroys that content. Both single-byte
opcodes and UTF-8 encodings of those high-byte scalars occur, while argument
data stays byte-valued. `decode_mus_text` uses the evidenced constant widths
before decoding literal chunks as UTF-8 or the banner's legacy codepage. It
retains opcode and exact arguments as opaque `^legacycmd(OP,hexbytes)` tags,
without guessing command meaning, font identity or typed values. This is a
normalization for the existing text/Record pipeline, not a second score model.
Known truncated commands and illegal literal XML characters raise clear errors.
Unknown caret sequences remain literal; unrelated Unicode carets are not
swallowed by a generic non-ASCII regex. Already decoded legacy strings retain
compatibility for the known spellings/arities. Authored command-boundary,
Unicode/codepage, literal-caret, insert and malformed-input tests cover it.

All75 production exports now validate against the official MusicXML4 schema.
This resolves text validity, not the outstanding text-block join or font-backed
dynamic semantics. The input scores/MIDIs remain byte-identical.

### Explicit metronome variants (2026-10-11)

After text-block/font resolution, The Moon's assigned `q=180 (e=360)` establishes
two consistent quarter-note rates. Preserve both explicit beat/rate pairs;
contradictory equivalents remain ordinary text. The Engraver Text manual names
`d` as the augmentation dot for quarter/half notes, so Spear of Justice's
registry-backed `qd=88` means dotted-quarter 88 (quarter 132), not quarter 88.
MaestroTimes' documented extended quarter/half/eighth glyphs resolve only in
that font. Fillmore's imported private U+F0CE variant in that same font is
corroborated as quarter=120 by its PDF's first-system marking; it is never
interpreted in an ordinary text font or by source filename.

Dire Dire Docks explicitly prints half=64–68. Preserve both range bounds and
export the standard metronome per-minute text without selecting a single sound
tempo. A typed independent source playback value can later specify its actual
rate; a displayed range by itself cannot. Equivalent marks print as multiple
metronomes with one identical sound rate. Source expression text remains intact.
Page/header block text is a separate placement/evidence issue: the presence of
an unused tempo-like block alone does not create a measure-attached tempo.

Evidence: [Engraver Text chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm),
[Maestro Times chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm),
assigned source records and read-only local PDF renders.

### Legacy font registry and expression runs (2026-10-11)

Numeric others tag 144 is the existing paired-corpus `fontName` match. In the
2011/2012 inputs its bounded payload begins with twelve bytes of registry flags
and metrics, followed by the font name through NUL or the payload end. The key
is the font ID. Names include Maestro, EngraverFontSet, MaestroTimes, EngraverTextT,
Times New Roman and ordinary text fonts; flags are retained raw, not interpreted.

Compiled text commands 85/A4/A5/A6 carry four biased hexadecimal digits: each
byte 1..16 encodes a nibble 0..15, most significant first. For example
`01 01 02 02` is font ID 17, not 1; `01 01 01 01` is ID 0. This interpretation
links every observed dynamic font run to its registry and makes the known
size-24 argument `01 01 02 09` coherent without treating a size as a font ID.
The opcode's font-class variant is not needed to guess an unknown registry name.
Unsupported names and absent registry entries do not identify a musical letter.

The 75-file source audit shows 224 active graded-dynamic glyph assignments with
an explicit registry-backed font command (168 A5/Maestro, 49 A5/EngraverFontSet,
7 85/Maestro). Of these, 44 assignments in 21 files were previously unnamed:
19 mf, 14 f, 8 mp, 2 ff and 1 p. All 44 resolve to the supported source music
font; no category or velocity inference is necessary. Font changes are applied
in sequence to literal runs. A preceding music command does not relabel a later
text-font letter; whitespace or a trailing font command does not erase the
context of an already printed glyph. Existing explicit descriptions, including
copied dynamics with empty text, remain authoritative.

### Legacy expression text indirection — corpus audit (2026-10-11)

The normalized EnigmaXML expression-text convention is not a universally valid
join for the raw legacy text pool. In the supplied 75-file NinSheetMusic audit,
an assigned legacy definition reaches its actual text through:

```
textExprDef.textIDKey -> others.textBlock[cmper]
                     -> textID/textTag -> the selected raw text pool
```

These fields are already decoded: definition payload +0; others tag183 text
reference +0 and text-pool selector +24 (2006 means expression text). This is
the same bounded text-block indirection used for staff and group names. It does
not establish a new serialized offset, and does not change the historical
401-document MUSX observations about normalized expression numbers.

Independent source references and printed-score corroboration:

| Legacy score | Definition | Text-block key | Raw expression section | Correct text |
| --- | ---: | ---: | ---: | --- |
| SMB2 Player Select | 82 | 104 | 83 | half note =145 |
| SMB2 Title Theme | 83 | 105 | 84 | quarter note =216 |
| SMW Ending Theme | 49 | 54 | 82 | Swing eighths |
| SMW Sub Castle | 78 | 13 | 79 | half note =126 |
| SMW Sub Castle | 85 | 107 | 86 | Ghastly quarter note =105 |
| SMW Sub Castle | 86 | 108 | 87 | Frighteningly quarter note =125 |

A direct definition-number lookup previously gave Player Select quarter=75,
Title Theme half=145, and Sub Castle the wrong tempo texts at all three
positions. The source MIDI nominal rates corroborate the referenced beat
markings. Across all score-scope assignments, the reference resolves 401
placements; eight intentionally empty/missing text sections remain (seven
copied Athletic dynamics still have usable naming descriptions). Raw lookup
differences affect 63 placements in 15 files, of which 51 placements in 14
files lie on current musical staves and measures. Out-of-scope records are
not evidence for introducing new printed directions.

The legacy adapter now retains an explicit `textBlockID` reference alongside
the source `textIDKey`. The shared resolver follows that reference using keyed
text-pool lookup, removing any same-number fallback when the reference is
missing or empty. Definitions without this field retain the established MUSX
normalization. Raw definitions, blocks and text sections remain available.
Authored crossed-ID, missing/empty text, copied-dynamic, pool-selection and
MUSX-compatibility tests exercise the join. The audit
and evidence ledger are local files under
`files/ninsheetmusic-audit/current-midi-audit.{md,json}`; all supplied musical
inputs remain external and unlicensed for inclusion as git fixtures.

Additional findings are catalogued in the corresponding corpus fix plan:
50 in-score octave spans in 18 files (plus one stale record), nine delayed
frame starts in six files, trills/ornament accidentals, two-note tremolos,
glissandi, composite articulations, explicit pedal signs and note-attached
dynamics. The recorded repeat target/action, entry-playback flag and custom
symbol hypotheses require serialized-layout evidence before becoming parser
constants; live PDK object offsets alone are not file-offset evidence.

The corrected text join also exposes 44 assigned graded-dynamic glyphs in 21
files whose descriptions do not name a dynamic (for example "Imported from
MusicXML" and "Below Staff"). The current legacy text resolver does not retain
compiled music-font identity, so these remain unnamed even when the glyph is
in the known ladder. Spider Dance's PDF corroborates its bar-26 `mp` and bar-34
`mf`; Spear of Justice has seven corresponding unnamed placements. Preserve
font identity before interpreting an ASCII glyph as a dynamic. A separate
three-assignment `S` sforzando variant (SM64 Main Theme and Athletic) remains
subject to font/render evidence; it is not part of this 44-placement count.

Printed and playback tempos also need distinct interpretation. Dr Wily prints
quarter=180 but its expression value is178 and MIDI starts near178; Athletic
prints150 but has value152 and MIDI near152. These observations do not decode
the serialized playback type. 1UP (printed225/MIDI100), Get Treasure Fanfare and
Uncover Secret (printed100/MIDI120) remain settings/reference investigations.
Invincibility Theme's `h=130` is in blockText25 rather than an assigned expression
and agrees with MIDI260; its page-placement reference still needs decoding.
No source tempo or playback field has been changed on this evidence alone.

### Known format facts — crescendo and diminuendo hairpins

Finale stores these dynamics as **SmartShapes**, separately from text
expressions and articulations. In normalized EnigmaXML, a `smartShape` definition
has `shapeType=cresc|decresc`, `startTermSeg.endPt` and `endTermSeg.endPt`.
Each endpoint names `inst` (staff), `meas` and `edu`; a `smartShapeMeasMark`
assignment references its `shapeNum`. The definition alone does not place a
mark. Multiple measure assignments still reference one complete span.

`enigma/hairpins.py` joins score assignments to visible preset measure-based
definitions. `hidden`, `noPresetShape`, `entryBased`, `lyricBased` and linked-part
records are excluded. An endpoint's EDU defaults to zero only when omitted;
malformed/negative values or missing staff/measure/endpoint records raise
`CorruptScoreError`. EDU must fit its signed 32-bit source field. Equal or
reversed endpoints are rejected. Cross-staff endpoints remain unsupported and
do not become a misleading single-staff mark. Automatic slurs and other shape
kinds remain distinct and are not rendered by this resolver.

The numeric `.mus` pool uses **others tag217** for SmartShape definitions and
**tag218** for measure marks. The evidenced shape payload is **96 bytes**: the
documented 92-byte structure followed by four bytes of padding. Assignment
payloads are arrays of **12-byte** slots, with `u16+0 shapeNum` and
`u16+2 centerShapeNum`; the other eight bytes are not interpreted. The measure
is the record's `cmper`, and normalized `inci` is the slot index. Reject
unrecognized definition lengths and incomplete/empty assignment arrays before
reading fields, rather than silently truncating them.

| Shape payload offset | Type | Meaning |
| --- | --- | --- |
| +0 | signed i16 | shape type: 0 down slur, 1 up slur, 2 diminuendo, 3 crescendo, 15 automatic slur |
| +2 | u32 | attachment/preset flags |
| +6 / +36 | 30-byte segment | left / right termination segment |
| +6 / +36 | signed i16 | endpoint staff |
| +8 / +38 | signed i16 | endpoint measure |
| +10 / +40 | signed i32 | EDU for measure-based shapes, entry number when entry-based |
| +14 / +44 | signed i16 | endpoint horizontal adjustment, separate from musical time |
| +16 / +46 | signed i16 | endpoint vertical adjustment |
| +18 / +48 | u16 | endpoint adjustment flags; bit 0x4000 enables adjustment |
| +82 | u16 | `flag2`; bit0 hides the shape |

Flags **0x40000000** and **0x10000000** identify entry-based and lyric-based
attachments; **0x00008000** selects a preset shape. Clear preset means the type
must not be mistaken for a standard crescendo/diminuendo. The adapter names the
five evidenced enum values above, retains other types numerically, distinguishes
`entryNum` from `edu`, and keeps these filters in the normalized record. Only the
numeric-pool encoding is decoded here; no DCL-era row layout is inferred.

Evidence: published PDK
[SmartShape structs, flags and accessors](https://pdk.finalelua.com/ff__smartshapes_8h_source.html)
define the endpoint/segment layout, enum values and inverse `flag2` visibility.
The MIT-licensed musxdom
[field map](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsOthers.cpp)
(inspected 2026-10-10) corroborates the normalized field names. Independently,
read-only inspection of the released RGP Lua0.79 x86_64 binary identified above
places the shape at object **+0x38**: `GetShapeType` VM **0x2c5fce** reads there,
`GetEntryBased` **0x2c7d68** tests bit6 at +0x3d, and `GetVisible` **0x2c92b6**
tests bit0 at +0x8a. Subtracting the structure base gives the serialized offsets.
Left/right termination getters at **0x2c99d8 / 0x2c98c6** use object
**+0x3e / +0x5c**, corroborating segment **+6 / +36**. Segment staff, measure and
position getters at **0x2c05ec / 0x2c0cce / 0x2bf10a** read signed words at
segment +0/+2 and the 32-bit value at +4. No plugin implementation is copied
or executed; release hash and attribution remain those documented above.

Canonical `Part.hairpins` holds immutable `Hairpin(kind, start_measure,
start_offset, end_measure, end_offset)` objects with optional `start_x_offset`
and `end_x_offset` values. Temporal offsets are exact whole-note fractions;
horizontal offsets are exact staff-space fractions, defaulting to zero.
Both are independent of notes or XML numbering. Export uses paired
[`wedge`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/wedge/)
directions and
[`offset`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/offset/)
values relative to the start-of-measure cursor, with `sound=yes`. They never
advance that cursor. Include endpoint denominators when choosing divisions,
preserving sub-beat positions. Numbers are allocated/reused in actual XML
document order, staff by staff within each measure, and obey the schema's
1–16 overlap bound. Stops precede starts at a shared position. Staff projection
retains the assigned staff and offsets after its backups. Missing measures,
ambiguous duplicate measure numbers, out-of-bounds offsets and reversed spans
raise `ExportError`. Leave the optional `spread` attribute unspecified, so
the reader's style controls the opening; Finale's opening geometry is not decoded.

MuseScore compatibility evidence: the first export specified closed/open spreads
of0/15, which passes schema validation and draws correctly in Verovio. The user
reported flat lines in MuseScore. Its
[pinned wedge importer](https://github.com/musescore/MuseScore/blob/78f0c2195f2505a1374eda52f13644d2a35838d2/src/importexport/musicxml/internal/import/importmusicxmlpass2.cpp#L5470)
sets the **whole hairpin height** from the start's spread when layout import is
enabled, and does not read spread at the stop. A crescendo start with spread0
therefore collapses both lines, even though the MusicXML specification says
to ignore spread at that closed tip. Omit this optional geometry for both kinds,
preserving type, pairing and exact offsets. Regression cases now prohibit height
overrides. The public source was re-fetched read-only on2026-10-10; SHA256 is
`b91458504310c6c570eb7439f2404248390f4c1671122d9da9d50d662f39f05d`.
No MuseScore implementation code is copied or executed. Schema/Verovio rendering
alone does not validate MuseScore's import behavior; runtime verification is
still unavailable here.

Local evidence: Scars contains **two unique visible crescendos on staff1**:
shape94 spans **m51 EDU0..4096** and shape36 spans **m58 EDU0..3584** (last eighth
onset). Shape94 has an identical linked-part copy. Both score shapes carry
flags **0x8600**, visible flag2=0 and explicit tag218 assignments; the PDF's
last page independently shows both. All90 raw shapes normalize (87 automatic
slurs plus these three records), and58 assignment arrays split into118 slots.
No diminuendo is assigned in this input. Its corrected export gains exactly
four wedge directions, and every other score-tree node and note onset matches
the prior dynamics-corrected file. Authored XML/binary/export regressions cover
both kinds, packed groups, hidden/linked/unused records, malformed input,
fractional/end-of-bar/cross-measure positions, overlap numbering and staff
projection. Official MusicXML4.0 schema validation and all three visually
inspected Verovio pages confirm two printed crescendos. `make check` passes
lint/format/strict types and1,680 tests (seven skipped), including69 new
authored cases. The licensed corpus and MuseScore runtime remain unavailable here.

Printed endpoint adjustment evidence (2026-10-11): the PDK's `__SSTERMSEG`
places `__SSENDPTADJ` after the eight-byte endpoint, and
`GetEndpointOffsetX/Y` read its signed `offset.x/y`. `SetCustomOffset()` writes
flag words **0x400c / 0x400d**; both source hairpins have **0x4000** at their
endpoint adjustments. The adapter normalizes the common active bit as `on`,
keeps signed X/Y under `endPtAdj`, and retains the complete flag word as
`sourceFlags` metadata. Other context bits remain uninterpreted. The normalized
`x`, `y` and `on` names are corroborated by musxdom's
[endpoint adjustment field map](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsOthers.cpp#L438).
Inactive coordinates stay in the source record without moving the IR's endpoint.
An active X defaults to zero only when omitted; malformed values or values
outside signed 32-bit Enigma EVPU bounds raise a clear error.

A fresh read of score shape 94 has left X/Y **0 / -175** and right X/Y
**-41 / -175**. Its musical end remains **staff 1, m51, EDU 4096**; the
negative X adjustment pulls the printed end left independently of that time.
Shape 36 in m58 has left/right X **-1 / +1** and Y **-183** at both ends.
Finale's official [measurement equivalents](https://usermanuals.finalemusic.com/FinaleMac/Content/Finale/def-equivalents.htm)
define **24 EVPUs per space**. MusicXML
[`tenths`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/data-types/tenths/)
are **10 per staff space**. The IR divides source X by 24; export writes ten
times that value as optional wedge
[`relative-x`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/wedge/)
in decimal notation, omitting zero adjustments. This leaves the reader's base
placement intact and does not introduce absolute measure coordinates, spreads
or new rhythmic offsets. Geometry denominators do not influence divisions.
Vertical placement, control/break geometry and source anchor contexts remain
outside this horizontal-adjustment path.

The corrected XML now carries **three nonzero relative-x attributes**: m51's
stop at approximately **-17.0833 tenths**, and m58's start/stop at approximately
**-0.4167 / +0.4167 tenths**. The m51 stop still has offset **16** with **4
divisions per quarter**, exactly the end of 4/4; m52 has an explicit `f` at
offset zero and no continued wedge. The local make audit compares source
bytes, canonical spans and XML independently; removing only these three
attributes reproduces the complete prior tree and every note onset. All 928
pitches and 87 slurs remain unchanged. Official MusicXML 4.0 schema validation
passes. `make check` passes lint/format, strict typing and **1,772 tests** (seven
skipped), including **17 new authored cases** for active/inactive flags,
negative/decimal adjustments, malformed data, staff projection and timing.

MuseScore limitation: the user's **4.7.5-260831071**, revision **3654226**, was
inspected at its exact public
[importer revision](https://github.com/musescore/MuseScore/blob/3654226/src/importexport/musicxml/internal/import/importmusicxmlpass2.cpp#L5461).
SHA256: `fa8e02b6cc04b41e47ec6081f72ed71a89961cbbbbb0c82114ccbcb3ffd32f01`.
The generic direction loop reads relative-x (line 4020), but only text/sticking
handling applies it; the wedge function (lines 5461–5511) reads no horizontal
geometry. Hairpin stop time still comes from `tick + m_offset`. Thus the
standard XML retains the recovered inset, but that build needs a manual visual
endpoint adjustment to display it. No upstream implementation is copied/run.
The Verovio audit similarly imports both hairpins and all 87 slurs but produces
three byte-identical SVG pages before/after these relative-x attributes; it
does not verify applied horizontal geometry. Its m51 and m58 pages are visually
inspected for notation preservation. No MuseScore runtime result is claimed.
Scratch `BoundaryMakefile` targets `hairpin-boundary` and
`verify-hairpin-position` preserve diagnosis and final verification separately.

### Known format facts — entry-attached phrase slurs

#### Individual-note glissando attachments (2026-10-12, F18)

Preset SmartShape type25 is glissando in the published PDK enum. Its existing
entry-based endpoints and start/endNoteID words (serialized+76/+78) identify
individual chord pitches. Recover only assigned, visible, preset score shapes;
keep the existing stale-shape quarantine and reject ambiguous/missing note IDs.
Entry location validation is shared with slurs. Cross-voice endpoints are exact,
and the canonical part-local representation reports an unsupported cross-staff
span instead of silently moving it to a different note.

`docs/eeppd.txt` documents TGFNID=0x001F0000 in each note's32-bit flag. Decode
those bits into normalized `note id` and typed `Note.note_id`, retaining zero
as absence. These IDs are independent of chord order and pitch; never treat
ID7 as pitch index6 or guess the first pitch when an ID does not resolve.
Notehead/tremolo override matching also uses these stable IDs. Authored tests
use nonconsecutive/reordered IDs, tie-bit coexistence and silent hidden chord
anchors; the same normalized note attrs are used by MUSX.

SM64 Main Theme has exactly three visible assigned wavy glissandi:
shape104 bar22, entry1839 ->1644 (voices1 ->2); shape106 bar24,1840 ->1670
(voices1 ->2); shape80 bar60,1607 ->1608 (voice1). All endpoints specify noteID1.
The final anchor is both hidden and playback-disabled; retain that written pitch
and its line attachment while suppressing its direct attack through F12. Shape106's
active drawing adjustments8/-17 and-37/-5EVPU survive independently of timing.

Canonical `Part.glissandi` uses `NoteEndpoint(event,pitch_index)` and wavy/solid
appearance plus active drawing adjustments. Export standard numbered start/stop
glissando notation on those exact MusicXML notes, allocating at most16 concurrent
numbers and rejecting dangling or reversed endpoints. No intermediate notes are
added. The three source spans explain34 reference performance attacks. Actual
MuseScore4.7.5 imports all three Glissando objects with exact cross-voice/hidden
anchors; page1/page3 rendering and MIDI checked. Its glide scale/timing and
post-jump traversal differ from Finale Human Playback, so a glyph recovery is
not an assertion of MIDI identity.

#### Explicit staff playback scopes (2026-10-12, R04/F21 prerequisite)

Numeric others230 is staffPlayData, keyed by source staff. The exact48-byte body
matches the published `__EDTPlayData2006` in ff_other.h: six8-byte controls for
chords, MIDI expressions and note layers1–4. Each contains u16 playbackRouteNum
at+0, velControlLevel+2, velControlSaveFlags+4 and playFlags+6. Play mask1 and solo
mask2 are published; route numbers are zero-based (`FCLayerPlaybackData` adds1
to obtain the InstrumentDef ID). Keep velocity control fields separate from
key velocity until their function is established. The expanded93-file source
inventory has194 complete records, routes0–3 and1164 playFlags=1 controls.

Carry explicit identities/play/solo on canonical voices and a shared identity
on a part only when its used layers agree. Apply solo scope without deleting
written notes; disabled voices export as full-size silent cues through F12.
Join adjacent staves with the same explicit instrument identity into one
MusicXML instrument, so a pedal-down on the bass staff and release on the treble
staff control one instrument. Names/braces do not establish this identity.
Program/channel/bank and Human Playback controls are separate R04 work; no patch
number is inferred from these indices. Authored tests exercise different routes,
disabled/solo voices, independent velocity controls and truncated48-byte bodies.

The user added18 files during this session: current inventory93MUS/92MIDI with
no MIDI-only names; Vampire Killer remains MUS-only. Preserve the original75-file
baseline and149 hashes as that earlier snapshot. New expanded checks expose one
cross-staff and two same-chord glissando cases, tracked separately; original75
still export and validate.

#### Additional SmartShape pitch attachments in the expanded corpus (2026-10-12)

The18 added files expose one cross-staff glissando (Mega Man2 Opening, shape39,
upper bar18 entry573 to lower bar19 entry1371) and eight same-chord wavy shapes
(SMW Game Over/Swimming, four each). The latter have distinct stable note IDs
on the same event and active drawing coordinates entirely before the noteheads.
Both original PDFs clearly show arpeggio signs. Normalize that evidenced drawing
construction to an arpeggio covering the notes between its pitch endpoints;
do not manufacture a temporal glide between simultaneous chord notes or infer
roll direction from which end of the wavy line was drawn first.

Append optional part_id to NoteEndpoint for cross-staff references and covered
pitch_indices to Arpeggio (empty keeps whole-chord semantics). Glissando numbers
are allocated across the entire exported staff bundle in XML order, including
voice order, instead of requiring musical time to equal serialization order.
Explicit cross-staff glissando connections join the relevant staves for export,
as explicit cross-staff arpeggios already do; source voice routing identities
remain independent in IR. This supersedes the earlier F18 cross-staff limitation.

The full93-file production path now parses, builds, exports and validates against
official MusicXML4.0 with185 input hashes unchanged; no MIDI-only filenames.
MuseScore4.7.5 imports the cross-staff line and four arpeggios per added SMW score.
Rendered Game Over page verified against the source. Authored regressions cover
the drawing construction, partial coverage and cross-staff endpoints.

#### Explicit sustain-pedal symbols (2026-10-12, F21)

With established Maestro font, visible score articulation characters161/42
mean pedal down/release (official chart and Finale's Human Playback instructions).
Resolve them through the existing definition/assignment join, excluding shape
aliases, hidden copies and linked-part overrides. A text font's asterisk does
not become pedal release. No new byte field is guessed.

The93-file corpus has28 explicit symbols: Prelude16, Ending Theme10 and Sub
Castle2. Prelude's bass-staff starts at odd-bar beat0 and releases at even-bar
beat3.75. Ending's starts at53/55–58 and releases at54beat3,55–57beat3.5,58beat3;
some releases attach to treble layer2. Sub Castle starts on bass bar1beat0 and
releases on treble bar2beat0. Use exact event offsets including frame startTime,
tuplet scaling and grace timing; one linear voice scan prevents quadratic work
on hostile files with many assignments. Drawing offsets do not change timing.

Store `Measure.pedals` as timed start/stop/change events, retaining symbol versus
line appearance. A simultaneous explicit release/start on one staff becomes
change. Export standard pedal directions, sign=yes/line=no for these glyphs,
with damper-pedal sound instructions. Shared source instrument routing keeps
cross-staff starts/stops on one exported piano. No visible pedal marks are
invented for the six other MIDIs with Human Playback automatic sustain.

Actual MuseScore4.7.5 imports8/5/1 pedal spans respectively and exports controls
at their nominal first-pass positions (only small renderer tick delays). Its
Prelude MIDI repeats the512 note attacks over128quarters but emits only the
first16CC64 controls; reference and canonical route contain32. This repeat/export
limitation is recorded independently; do not unroll the written score or invent
extra signs. Authored tests cover frame offsets, chords, re-pedaling and fonts;
rendered Sub Castle and native cross-staff span endpoints were checked.

#### Dynamics assigned as articulations (2026-10-12, F22)

A visible score articAssign can place a dynamic character rather than an
ordinary note articulation. Resolve the decoded main font first and require
Maestro before using the established dynamic glyph registry. Shape definitions,
text-font letters and hidden/linked-part assignments remain separate. Convert
the recognized symbol to a timed Expression with readable marking and no
invented source category or default key velocity. Use the same linear exact
entry-offset scan as pedal directions, including frame starts and grace notes.

Simone's Theme has one such placement: Maestro P/character80, mp on the first
treble entry. The93-file before/after inventory changes exactly that one mp
count; ordinary expression dynamics are retained. Export a single dynamics/mp
direction for a chord, rather than an articulation named mp on each pitch.
Authored font/shape/scope/chord/offset tests pass and actual MuseScore4.7.5 imports
the first-note mp as a native Dynamic. No new byte range or playback value is
decoded by identifying this notation.

#### Font-specific sforzando variant (2026-10-12, R05)

The official [Maestro chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-maestro.htm)
identifies character83, `S`/Shift+s, as sforzando. Its linked
[glyph image](https://usermanuals.finalemusic.com/FinaleWin/Content/Resources/Images/characterSets/Maestro/Sforzando%20or%20Sforzato.png)
prints **sf**; character167, `§`, has a separate image printing **sfz**.
The inspected sf PNG has SHA256
`23998340ba65394379d0065e1e88b392d2376635d9429defabf554fc37a15c15`.
Resolve `S` to sf only when the actual decoded glyph run names Maestro. A
dynamic category, a description saying sforzando, an unknown font or another
music font cannot establish this character's appearance. Ordinary text S stays
text. No accent or MIDI-derived velocity is fabricated.

All105 current user-supplied files convert and pass the official MusicXML4.0
schema. Exactly three expression placements change: SM64 Main Theme bars22/24
and SMB3 Athletic Theme bar12. Actual MuseScore4.7.5 imports two and one native
sf dynamics respectively. The corpus now contains104 exact MUS/MIDI pairs,
no MIDI-only case and MUS-only Castlevania - Vampire Killer. These are notation
and import checks; the full playback audit remains separate.

#### Separate downward arpeggio arrows (2026-10-12, F23)

Corridors of Time entries1331/1340, upper bars5/25, each carry one glyph103
roll and a separate Maestro character224. The official Maestro chart calls224
a filled upside-down triangle; it has no inherent arpeggio meaning. The
original PDF shows it at the bottom of the wavy sign. The roll assignment has
horzOff=-42, vertOff=-24, vertAdd=-38; the triangle has horzOff=-67,
vertOff=-46. All105 files contain exactly these two eligible triangle placements.

Require one visible score roll and one actual Maestro triangle on the same
entry, both before the heads (negative horzOff), with the triangle below the
roll anchor. Shape/text-font/hidden/part variants, standalone triangles,
ambiguous multiple signs and missing positioning do not establish direction.
Append optional Arpeggio.direction, preserve it through cross-staff connections,
and emit standard arpeggiate direction=down on all seven covered notes. Partial
note coverage is never expanded into a cross-staff roll.

Actual MuseScore4.7.5 imports two native downward arpeggios; the rendered first
page was inspected. Both native MIDI rolls descend81,80,78,73,69,68,66, matching
the reference order. Native spread0.744quarter versus reference0.639quarter is
a renderer realization difference, not additional source notes or a tempo fix.
Authored direction/context/visibility/connection tests and all105 schema checks
pass. The MusicXML [arpeggiate reference](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/arpeggiate/)
distinguishes an explicit arrow from the plain sign's default upward roll.

#### Parenthetical noteheads and retained drawings (2026-10-12, F24)

Maestro characters40/41 are parentheses, not musical attacks. The expanded105
files have18 pairs across11 scores. Each definition uses xOffsetMain=-26/+26,
yOffsetMain=-21 and defVertPos=0. The published FCArticulationDef handle getters
and read-only released RGP Lua code anchor these additional fields:

| Field | 48-byte layout | 60-byte layout | Getter VM |
|---|---|---|---|
| signed xOffsetMain | +16 i16 | +18 i16 | 0x4c111e |
| signed yOffsetMain | +18 i16 | +20 i16 | 0x4c1102 |
| signed defVertPos | +20 i16 | +22 i16 | 0x4c10e6 |
| useTopNote | +10 u16 mask0x80 | same | 0x216ae8 |

These are glyph-handle adjustments; they do not by themselves establish the
automatically positioned chord note. The getters use object bases+0x38/+0x68
established above. The [primary model](https://github.com/openmusx/musxdom/blob/main/src/musx/dom/Others.h)
and its field map corroborate the names. Source assignment offsets remain the
independent signed fields already decoded from articAssign.

Event.parentheses retains both symbols and combined positioning adjustments in
staff spaces. A compact, vertically matched pair on a single pitched entry
establishes its notehead enclosure. Export notehead parentheses=yes with normal
heads, retaining pitch, rhythm, ties and playback. Actual MuseScore4.7.5 imports
all11 such enclosures. The Moon/Underwater/Hammer/Star Light, two Bubble Man,
Hyrule Castle entry1060, MEGALOVANIA entry2650, Spear and two Monster's Lair
placements use this path.

Seven placements require further drawing layout to establish exact attachment:
Dire Dire Docks entry8175 (wide multi-note span), Death Mountain438, Hyrule
Castle865 and MEGALOVANIA130/131/132/2129 (selected notes within chords). Their
glyphs and adjustments remain in IR and standard other-notation elements;
ScoreDiagnostic parenthesis-attachment identifies each, rather than guessing
whole-chord parentheses or deleting optional notes. Original MEGALOVANIA and
Death Mountain PDF pages confirm that the signs select individual chord notes.
These source drawings are retained, not claimed to be reconstructed page geometry.

MuseScore4.7.5 imports the fourteen retained SMuFL glyphs as articulations but
ignores their coordinates, producing misplaced signs. Its exact-revision
addArticulationToChord consumes placement/type/color, not position attributes;
this requires manual layout review. The eleven semantic notehead enclosures
render correctly. All105 XML files pass the official4.0 schema; authored tests
cover fonts, visibility, duplicates, signed era-specific offsets, unmatched
marks, chords, spans and invalid attachments. No MIDI notes or velocities are
changed to imply that parenthesized notes were omitted in playback.

#### First-page metronome text (2026-10-12, F14)

Numeric others194 contains packed24-byte pageTextAssign slots, keyed by page
assignment ID and incidence, not measure. Source Invincibility Theme page1 has
six slots: the half-note130 metronome is slot5, byte120, block97 -> blockText25.
Reading only the leading slot misses it. Published
[FCPageText getters](https://pdk.finalelua.com/class_f_c_page_text.html) and the
[primary page-assignment model](https://github.com/openmusx/musxdom/blob/main/src/musx/dom/Others.h)
establish the fields. Released RGP getters use block at object+0x38 as the
anchor: xdisp+2 signed i16 (VM1983aa), ydisp+4 signed i16 (199b0a), startPage+6
signed i16 (199e50), endPage+8 signed i16 (1998ee), flags+10 u16; annotation
mask0x80 means postIt/hidden (198be2). Preserve the remaining flags as source
attributes rather than guessing page alignment or odd/even behavior.

Normalize all complete slots with independent incidences and bounds checks.
Only visible score assignments explicitly keyed to page1 promote a metronome
header above the first musical measure. Require an established beat-symbol
font or explicit unit words/Unicode notes; arbitrary text-font h is not a half
note. Use the existing tempo-syntax and text/font joins. Expression.page retains
the source page, category stays empty, and typed playback=none distinguishes
printed page text from a playback expression. Playback preferences supply the
actual document rate. All other page assignments remain in the document;
later or repeated page headers cannot establish a measure position by themselves.

The105-file inventory recovers exactly one new header, Sonic Invincibility
Theme half130. Actual MuseScore4.7.5 prints it and stores260 quarter BPM,
agreeing with source playback and MIDI. Authored packed-slot/signed/hidden/font/
page/palette tests and all105 schema checks pass. This is a projection above
the first system, not a reconstruction of absolute page typography.

Simone's block46 resolves to blockText11, Met - 96. It is not one of that
file's decoded page-text or measure-expression placements. Definition11
instead resolves block15 to expression11, an unused fp glyph; identical raw
text numbers in different pools are not interchangeable. Numeric tag151
offset134 and detail1056 offset20 also contain46 but their role as a text
reference is unproven. Retain this as pending source-placement research rather
than placing an unused palette label. The explicit playback preference96 is
already retained independently.

#### Custom-line definition and text joins (2026-10-12, R02 foundation)

The expanded105-file inventory contains46 additional visible assigned lines:
nine dashed type10, nineteen solid type11, seventeen custom type29 and one
left-hooked dashed type32. Octave types4/5/20/21 are separate, already recovered.
Numeric SmartShape217 retains ssLineStyleID at+80 u16; the published
[SmartShape struct](https://pdk.finalelua.com/ff__smartshapes_8h_source.html)
and GetLineID VM2c8aa6 (object+0x88 relative to shapeType+0x38) establish it.
Definitions are a palette; neither a line definition nor its label places a span.

Numeric others222 supplies72-byte smartShapeCustomLine definitions. The
published FCCustomSmartLineDef and read-only released getters anchor two
layouts of equal total length, with object bases+0x38/+0x80. Constructor4f5ce8
sets loaded size0x48. The relevant fields are:

| Field | Legacy | Unicode era |
|---|---|---|
| line style0 solid/1 dashed/2 character | +0 i16 | same |
| character for character-style line | +2 u16 | +2 u32 |
| character font ID / size | +4/+6 i16 | +6/+8 i16 |
| line width for solid/dashed, Efix | +2 i16 | same |
| start/end cap0 none/1 preset/2 custom/3 hook | +14/+16 i16 | +16/+18 i16 |
| endpoint data, custom arrow ID | +18/+22 | +20/+24 |
| signed hook length, Efix | getter unsupported | +20/+24 i16 |
| five raw label IDs | +28,+30,...,+36 u16 | +30,+32,...,+38 u16 |

Evidence getter VMs: style2cf78e, character2d1190, font2d06c2, width2d0bc6,
start cap2d1aa4, hook2d1a76 and raw text2d037a. Unicode character fields here
are one little-endian32-bit field, unlike articulation definitions' two-word
character storage. The used wavy definition39 has character126, EngraverFontSet0,
size24 and no endpoint caps; source raw bytes and font chart corroborate it.

Spring Yard's NotePad banner has no parsed version year. A default legacy
choice misreads modern baseline-shift=-88 as a cap enum. For versionless files,
validate both complete layouts over the definition pool using published cap
values; select only a uniquely fitting layout. If both fit, retain an explicit
sourceLayout=unknown with the common line-style field. Never choose a label
reference merely because it matches a convenient text number. Authored tests
cover known eras, the NotePad case, ambiguous palettes and partial records.

Raw ^smartshape(N) text sections now decode bounded compiled commands through
the existing text decoder and normalize to smartShapeText, independently of
blockText/expression numbering. The published CreateTextString uses
tx_SmartShape; the [primary text model](https://github.com/openmusx/musxdom/blob/main/src/musx/dom/Texts.h)
corroborates smartShapeText. Unused Glissando, pedal and harmonic label palettes
remain unplaced. All105 production paths and schema checks pass after decoding
these records. Canonical span projection and custom endpoint graphics remain
the next R02 work; this foundation alone does not claim line export recovery.

#### Repeatable external-corpus verification (2026-10-12, stage7)

The opt-in make audit-corpus command uses canonical Score and separate analysis
attacks, not a parallel score representation. It hashes external inputs,
records exact stem pairing and each production stage, validates written-note
multiplicity/timing through IR to MusicXML, and optionally runs the official
schema and a supplied MuseScore executable. See [audit usage](CORPUS-AUDIT.md).
The local105/104 source snapshot has209 unchanged hashes, no MIDI-only files,
and Vampire Killer is MUS-only. All105 production/projection/schema paths pass;
all105 individual MuseScore4.7.5 processes produce native/PDF/MIDI artifacts
and exit0. A prior single-process105-score batch produced artifacts but aborted
with double-free during teardown; fresh per-case processes avoid treating that
batch exit as a passing check.

Comparison preserves raw residuals, source scope, contiguous tie chains,
silent notes, sounding ottavas and exact frame starts. Source-bound ornament
windows include hidden glissando anchors and cross-staff/end-bar endpoints.
Grace-chord/arpeggio timing contexts are separate from actual pitch coverage.
Triplet backbeat timing is a source-derived analysis model; it cannot reproduce
every Human Playback decision. Do not suppress swing on every tied note: that
probe regressed otherwise matched cases. Spring's straight-timed tied bass
offbeats therefore retain selective-swing candidate labels, alongside its
shorter reference replay. Reattack candidates and reference/source anomalies
remain reviewable rather than becoming invented notes or fake directions.

Expanded literal-route exceptions are also retained: Terra/MAP7/Death Mountain
have segno glyph assignments carrying jumpAbsolute target0, despite valid later
D.S. targets; Spear carries D.C. words with target0; Crash Man's always D.S. and
onPass2 To Coda eventually form a nonterminating literal route after the ending
Repeat From action. These are format-policy/source-reference investigations,
not proof that the written notes are corrupt. Do not convert target0 to measure1
or fit a substitute route from MIDI. The named raw source trace is
new-route-evidence.log in generated validation artifacts. Initial MIDI program/
bank/CC7/10 observations are recorded; their source field joins remain unproven.

#### Engraver half-notehead tremolo in the expanded corpus (2026-10-12, F17)

The added Battle to the Death score uses exactly the hidden-tuplet pair
construction already recovered for Maestro, but its default font0 is
EngraverFontSet. Bar1 bass entries1838/1839 have stable noteID1, noteheadMod
character250, consecutive beamed32nds and a hidden256-EDU tuplet referenced
to2048 EDU. The voice begins at2048 EDU; both metric durations remain1024 EDU.
The original PDF shows two open half heads with three tremolo strokes, and
the [official Engraver chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm)
independently identifies ALT+0250 as a half notehead. Extend only this evidenced
font gate, retaining the original hidden-tuplet/note-ID/adjacency gates and
unknown-font refusal. This recovers one additional paired tremolo without
altering its two pitches, frame start or sounded metric duration. Local trace:
new-case-tremolos.log, generated artifacts remain outside git.

#### Initial printed tempo versus independent playback (2026-10-12, R04/F14)

A first-beat display-only metronome now carries the independent document
default in its own MusicXML sound element. A separate measure-level sound
followed by an unsounded metronome let MuseScore infer the printed rate and
overwrite the default. This applies only when no active first-beat tempo
expression already establishes playback; later display-only metronomes do
not reset the piece to its initial default. The original printed beat/rate
survives. Authored quarter225/default100 imports in MuseScore4.7.5 as one
TempoText with printed225 and tempo1.666667 quarters/second; Sonic's first-page
half130 likewise retains quarter260 without a duplicate invisible tempo.

Source inspection corrects a previous assumption about 1UP, Get Treasure and
Uncover Secret: their first metronomes are active tempo expressions, not
playType=none. Source values225/100/100 contrast with paired MIDI100/120/120
and document defaults100/120/120. Preserve all three independent observations;
neither a default value that agrees with MIDI nor the importer behavior proves
that these active expressions should be disabled. Export the explicit source
rates, and flag reference/export provenance or still-unmapped playback policy
as unresolved. Dr Wily180/178 and Athletic150/152 are different: their explicit
source playback values explain those MIDIs, and actual native import retains
178/152 while printing180/150. The local tempo-source-check.log preserves the
complete typed IR trace. All105 MusicXML schema paths and authored tests pass.

#### Nonprinting articulation controls (2026-10-12, R01/R04)

Assigned Maestro character8 in Objection (161 placements) and character0 in
Athletic (two) are character definitions, not custom shapes or missing accent
glyphs. The independently decoded mainIsShape flag is clear in both. Their
screen-only flag is also clear: the absence of a printed symbol here follows
the character code, not an inferred hidden-shape instruction.

The released FCArticulationDef getters establish flag1+10 mask0100 as noPrint,
and flag2 at legacy+22/Unicode+24 has playArtic0040, attack-percent0010,
duration-percent0020 and velocity-percent0008. Signed top/bottom words occupy
legacy+36/+38 attack, +40/+42 duration and +44/+46 velocity; Unicode adds two
bytes to each offset. Pointer VMs4c1026/4c1066/4c1086/4c10a6 and percentage/
playback getters21bf3c/216bd6/218e22/21c9b0 independently anchor the map.
Normalize selected units using EnigmaXML start/dur/amp Top/Bot Note
Percent/Delta field names, retaining disabled definitions without activating
their data. Do not mistake a raw value85 in the velocity slots for duration85.

Objection's definition63 flags2=0060 selects duration75 percent on both ends
of a chord; Athletic's definition63 flags2=0048 selects velocity85 percent.
Its attack/duration values are zero. Canonical Event.articulation_playback
retains active assigned controls with explicit EDU/percent/key-velocity units,
including hidden/on-screen-only symbols. All printed articulation-derived
resolvers now honor noPrint independently. Diagnostics distinguish a
nonprinting glyph from the separate explicit manual playback controls.

The [Finale articulation manual](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/ht-articulations.htm)
states that manual articulation playback needs Human Playback disabled.
Consequently these fields cannot be imposed on this corpus's performance
MIDIs as literal note-off or velocity truth. Standard MusicXML attack/release
cannot preserve top/bottom interpolation, multiple-effect ordering and Human
Playback override policy together. Retain the values and an explicit
articulation-playback interchange diagnostic; export written symbols without
invented staccatos or altered metric durations. Actual MuseScore4.7.5 importer
does not read note attack/release attributes. Authored binary/unit/visibility/
inactive-palette tests pass, and all105 MusicXML schema paths remain valid.

#### Assigned line drawings and interchange limits (2026-10-12, R02)

Canonical `Part.lines` now carries every eligible type10/11/29/32 assignment:
exact whole-note measure offsets, source staff endpoints, active drawing
adjustments in staff spaces, solid/dashed/wavy style, endpoint caps, signed
hook direction and absolute hook length, endpoint labels and opaque custom
endpoint resource references. Only score assignments place lines; hidden,
part-only, unused palette and F05 stale records do not. Unknown font/layout or
entry/lyric attachment emits a specific diagnostic rather than an invented
metric span. Maestro and EngraverFontSet character126 are evidenced wavy-line
glyphs; the [Engraver chart](https://usermanuals.finalemusic.com/FinaleWin/Content/Finale/font-engraver.htm)
identifies Shift+grave as a trill extension, independently of the meaning of
the drawing that repeats it. Dreadful Fight's custom definition39 uses
EngraverFontSet0, not Maestro0.

Export paired standard MusicXML brackets with exact divisions, line-end/type,
hook end-length and relative endpoint geometry; offsets have sound=no. Reuse
numbers1–16 only after the previous document-order interval closes. Explicit
cross-staff endpoints join the corresponding staff-parts without inferring
shared playback identities. Reversed/missing/out-of-bar endpoints and excess
overlaps raise clear ExportError. Same-time drawings remain graphical; never
insert notes, lengthen a bar or turn a custom line into an octave, slur, pedal
controller or glissando merely from its style.

The supplied105-file inventory yields46 lines in17 scores. All105 XML paths
validate against MusicXML4.0, and normalized written pitches/durations/voices/
ties match the pre-line outputs. Authored tests cover signed Efix hooks,
non-grid offsets, source assignment gates, zero-time geometry, cross-staff
pairing, number reuse/overflow and custom-resource diagnostics. Actual
MuseScore4.7.5 imports on seven representative scores retain ordinary text
lines and hooks, but the importer does not read bracket relative-x/y. Thus
same-time hand brackets and other drawn geometry need manual layout. A custom
endpoint such as shape107 in Opening/Terra stays an opaque source reference
with line-endpoint-graphic diagnostics; the exported bracket omits the custom
change-pedal spike. Center/continuation labels, when present, also have an
explicit placement diagnostic. Unused pedal-text libraries place nothing.

MuseScore's primary bracket importer maps line-type=wavy to a Trill spanner
of PRALLPRALL_LINE type. This is a consumer interpretation, not new canonical
ornament meaning; Dreadful Fight's same-time slanted flourish needs manual
layout. These interchange limits do not justify fabricated playback controls.
Local evidence is r02-line-check.json and the original/native opening renders
in the generated validation directory, outside git.

#### Green Hill's written tie gap versus held MIDI (2026-10-12, R03)

Green Hill Zone upper staff1/layer2/bar26 has contiguous F4 entries776,929,777.
Their written durations are512,1024,1024 EDU. Source note IDs are1 throughout;
their flags are respectively start-only, end-only, start-and-end. Entry929 has
no onward tie start. The numeric detail pool has no score entry/note overrides
for any of these three entries. The production reader preserves those flags.

The original one-page PDF independently shows the incoming tie from the eighth
note to the following quarter and the later outgoing tie across the barline,
with no forward arc from the middle quarter to the next quarter. The paired
performance MIDI holds F4 through that written reattack, on both traversals.
This explains the two source-only attacks in the original comparison; it is
not evidence for an unread tie override or dropped flag. Preserve the written
notation and report this specific source/reference playback difference. Do not
fill unrelated unmatched tie starts/ends throughout the corpus or suppress
written notes merely to match this MIDI.

The local source-detail trace is green-hill-ties.log and the rendered original
PDF is green-hill-source.png in the generated validation directory. These
third-party score artifacts remain outside git. R03 requires no parser change.

The same SmartShape definitions carry phrase slurs. Solid types **0** (`slurDown`),
**1** (`slurUp`) and **15** (`slurAuto`) are documented by the published PDK
[SmartShape enums and structs](https://pdk.finalelua.com/ff__smartshapes_8h_source.html)
and corroborated by musxdom's
[normalized field map](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsOthers.cpp)
(inspected 2026-10-11). The entry-based flag **0x40000000** changes each endpoint's
32-bit union from EDU to **entry number**. Preserve that distinction: an entry
id is never a measure offset. Staff and measure still identify which placement
of that entry is intended. A slur may skip notes, cross barlines or begin/end
on a particular grace note without requiring any intermediate markers.

In the numeric `.mus` pool, **details tag 1064** is `smartShapeEntryMark`. Its
payload consists of **10-byte** assignment slots: `u16+0 shapeNum` followed by
eight bytes this adapter does not interpret. The published
`__EDTSmartShapeEntryMark` structure has this exact layout and uses ETF `Ex`.
The numeric tag is identified independently by all **174** local records:
every shape id resolves to a visible type 15 definition, and every entry key
is exactly one of that definition's two endpoint entries. Each of the 87 shapes
has both links, with no mismatches. As for other entry details, combine the
key's high-word `cmper1` and low-word `cmper2`; do not treat them as staff/measure.
Keep packed-slot incidence and `sourceInci` separately. Reject empty payloads
and partial slots before reading fields. The entry-detail tag map also includes
this record so inspection-report joins keep working. Historical corpus counts
for the earlier three known entry detail kinds are not remeasured here.

The PDK SmartShape structure also names its two signed note-id words at
**+76 / +78**, between the complete control-point adjustment and line-style
id. Normalize nonzero values as `startNoteID`/`endNoteID`, the corroborated
EnigmaXML names. Pitch-specific attachments require note-id resolution and are
excluded from the current entry-attached path instead of being moved onto a
chord's first pitch. All 87 local slurs have both ids zero and flag2 zero.
No new binary/plugin implementation is copied or executed; the shared endpoint
layout already has the independent getter evidence documented above.

`enigma/slurs.py` joins score measure **or entry** assignments once per shape;
definitions alone do not place notation. Exclude hidden, linked-part, custom,
lyric-based and non-entry-based shapes, and unrelated/dashed shape kinds. Exact
event indices are gathered in the existing IR build pass, including grace notes.
A supported endpoint must resolve to exactly one pitched event at its stated
staff and measure. Missing or ambiguous placements, malformed endpoint/note ids,
and equal/reversed spans raise `CorruptScoreError`. Cross-staff endpoints remain
unsupported rather than becoming shortened single-staff slurs.

Canonical `Part.slurs` holds complete immutable `Slur` spans, with
`SlurEndpoint(measure, voice, event_index)` for each tip. Event indices are
zero-based, while measure/voice retain their source numbers. This keeps several
graces and the following main note distinct even though all share one metric
onset. A None placement means automatic direction; explicit up/down shapes
carry above/below placement. EnigmaXML's explicit `dir=over|under` overrides
that default, while `automatic` retains it. These values are corroborated by
musxdom's
[common enum field map](https://github.com/openmusx/musxdom/blob/main/src/musx/factory/FieldPopulatorsCommon.cpp).
Malformed directions raise a clear error. Binary flag2 direction overrides are
not decoded; all local slurs have flag2 zero. These spans are independent of
`NoteTies` and do not introduce a sounding tie or change any written/metric duration.

MusicXML emits paired numbered
[`slur`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/slur/)
elements in the endpoint notes' `notations`, once per event even for chords.
Let the reader choose curve geometry and automatic direction. Explicit placement
also sets the corresponding over/under orientation. Allocate numbers in actual
measure/staff/voice/event XML order, closing before opening at a shared note;
the first serialized endpoint reserves a number and the second releases it.
This also permits a cross-voice stop appearing before its start in XML. Numbers
obey MusicXML's 1–16 document-overlap bound, independent of the IR's span count.
Staff projection preserves endpoints and numbers. Missing references, duplicate
measure/voice labels, rest endpoints, invalid placement, equal/reversed spans
and excess document overlaps raise `ExportError` without expanding supplied
indices into large allocations.

Local evidence: all **87 assigned visible automatic slurs** resolve, including
**25 cross-measure spans** and **seven grace endpoints**, with no cross-staff or
rest endpoints and no staff/measure mismatch. For the user's examples:

| Shape | Staff | Start entry and location | End entry and location |
| --- | --- | --- | --- |
| 42 | 1 | 166, m17 event 0 (G5) | 169, m17 event 2 (E5) |
| 43 | 1 | 170, m17 event 3 (D5) | 173, m19 event 0 (E5) |
| 44 | 1 | 183, m19 event 1 (E5) | 1269, m20 event 0 (E5) |
| 88 | 2 | 284, m17 event 0 | 291, m17 event 7 |
| 89 | 2 | 292, m18 event 0 | 299, m18 event 7 |
| 90 | 2 | 300, m19 event 0 | 303, m19 event 3 |
| 91 | 2 | 307, m19 grace event 4 | 305, m19 event 7 |

The original PDF's first two pages independently confirm these phrase
tips. The pre-change corrected MusicXML has no `slur` elements; its existing
short curves are `tied` notations. Source entry numbers need not increase with
musical time (see 307→305): use resolved event order, never raw id ordering.
Authored XML/binary/export regressions cover nonadjacent/cross-bar/grace spans,
mirrors, assignment kinds, hidden/linked/unused records, malformed input, chord
ties, nested/touching numbering, cross-voice serialization and staff projection.
The corrected local export now contains **174 paired slur endpoints**, all
verified against their source entry placements including both Finale layers.
Removing only these slurs and newly empty `notations` containers reproduces the
entire prior score tree and every note onset. All 928 pitches, ties, eight dynamics,
two hairpins, ten mordents, six arpeggio signs, one fermata and 24 grace flags are
unchanged. Original input and unrelated `uv.lock` hashes are unchanged.
Official MusicXML 4.0 schema validation succeeds; Verovio imports 87 MEI slurs and
draws 95 segments across three pages because cross-system spans split visually.
All three rendered pages are visually inspected, including the m17–19 phrases.
`make check` passes lint, formatting, strict typing and **1,755 tests** (seven
skipped), including **75 new authored regression cases**.
Automatic slur placement follows the reader's engraving style; source stems,
manual curve geometry and page layout are not reconstructed by this change.
No supplied score files become repository fixtures. The licensed corpus and
MuseScore runtime remain unavailable here.

### Explicit metronome markings

Assigned expression text can establish a metronome rate even when the legacy
`.mus` lacks a decoded category or `playType`. Scars of Time prints `q = 82` in
measure 1 and `Faster q = 112` in measure 20; the PDF and MIDI confirm both rates.
The definition's `value` is an untyped playback number, also used for dynamics,
so it is **not** used to infer tempo. The expression join and this distinction
are documented in `docs/formats/expressions-and-dynamics.md`.

`Expression.tempo` holds `Tempo(beat_unit, per_minute, dots, words)`. Beat units
and rates use exact `Fraction`s; `Expression.text` retains the original wording.
The reader recognizes one explicit whole/half/quarter/eighth beat-equals-number
mark, using named units, `w/h/q/e` or the supported Unicode note symbols, with
zero to three dots and a positive rate at most 1000. Ranges, note equivalences,
multiple markings, unsupported symbols and tempo words alone remain text.

MusicXML emits a [`metronome`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/metronome/)
marking and [`sound tempo`](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/sound/)
in quarter notes per minute: `per_minute * beat_unit * dot_multiplier * 4`.
Surrounding words such as `Faster` are emitted once; the printed equation is not
duplicated as words. The performance MIDI's expressive tempo changes remain outside
this explicit notation reading. No undecoded `playType` bits are guessed.

### Known format facts — lyrics

Enigma splits a lyric in two, and neither half is much use alone.

- **Text**: one blob per verse in the `texts` pool, syllabified with hyphens
  (`An-gels we have heard on high`). Tag `verse`, `chorus` or `section`, keyed by number.
- **Assignment**: an entry detail (`lyrDataVerse` and friends) carrying `lyricNumber` — which
  verse — and `syll`, a **1-based index into that verse's syllables**. Optionally `wext`, a word
  extension (the line under a held syllable).

Nothing stores the syllables themselves, so `enigma/lyrics.py` tokenises the verse — split on
whitespace, then each word on hyphens — and indexes it. Verified against the corpus: the syllables
land on consecutive entries in playing order, exactly as sung.

**`syllabic` is derived, not stored.** MusicXML needs `single`/`begin`/`middle`/`end`, and Enigma
records only hyphens: a hyphen after a syllable means the word continues, one before means it was
continued into. This is the part most likely to be subtly wrong — it produces output that looks
plausible and sings wrong — so it carries the most tests, including a mutation check that removing
the "previous syllable ended in a hyphen" test breaks `middle` and `end`.

Two cases are dropped rather than guessed at: an assignment whose index falls past the end of its
verse (a verse shortened after the notes were entered), and a lyric detail carrying only positioning.

**The two containers store this very differently, and produce identical output.** A `.musx` writes
one record per (entry, verse). A `.mus` packs every verse the entry sings into one record as
consecutive 20-byte groups (`lyricNumber` +0, `syll` +2, `wext` +8, details tag 1108) — and then
**repeats the whole record**, usually twice, so the adapter emits each (entry, verse) once. Its verse
text is ETF tagged text (`^verse(1)…^end`) in the text stream rather than a binary record. Over the
six same-content pairs whose `.musx` carries lyrics, all 1,794 events match exactly.

`plain_text` now strips both markup dialects: EnigmaXML's `^name(args)` and the binary
`^<opcode><4 bytes>` a `.mus` uses.

### Known format facts — EnigmaXML structure

Full reference and derivation: `docs/superpowers/specs/2026-07-22-enigma-document-design.md`.
Verified against all 401 corpus archives (`tests/enigma/test_document_corpus_sweep.py`).

- The `<finale>` root holds seven pools, always in this order when present: `header`, `mappings`,
  `options`, `others`, `details`, `entries`, `texts`. Any pool may be absent or empty; `parse_enigma`
  models an absent pool the same as an empty one.
- Records are recursive, not typed: `Record` has `tag`, `attrs` (all attributes, verbatim), `text`
  (the element's own direct text), and `fields` (child elements, keyed by local name — a scalar
  `str`, a nested `Record`, or a tuple of either when the tag repeats). A chord's notes are nested
  `note` fields inside an `entry` record — the same recursive rule reaches the musical core with no
  special-cased "note" type.
- Fields nest arbitrarily deep; the corpus and the fixtures both exercise nesting 4 levels deep
  (e.g. `others/widget/layerTwo/layerThree/leafValue`).
- `EnigmaDocument.version` is the **schema** version reported on the `<finale>` root (`"18.0"`
  across the entire corpus), not the writing application's version — that lives in
  `.musx`'s `NotationMetadata.xml`, read separately by `finale_file_parser.version`.
- The `texts` pool carries copyright, title, and composer text (`<fileInfo type="title">…`,
  `<expression>`, `<verse>`). Because of this, **no decoded corpus EnigmaXML is ever committed**;
  `tests/fixtures/enigma/*.xml` are hand-written synthetic documents with invented placeholder
  values, and `tests/enigma/test_fixtures.py` mechanically asserts no committed fixture contains a
  `fileInfo` element at all.
- **No fixed key set uniquely identifies a record** without also tracking `part`: `cmper=1` alone
  spans 54 distinct tags across the corpus, and `measSpec` additionally has per-`part` variants
  that share a `cmper` with the score-level record and with each other, distinguished only by the
  `part` attribute. Dropping any attribute to build a key would silently lose data (verified by
  mutation: removing `part` from the model fails a test). This is why the document model preserves
  every record uniformly (`Pool.of_tag` linear lookup, all attributes kept verbatim) as its
  baseline, with keyed lookup layered on top once the full key-attribute set per pool was mapped
  (below).

### Known format facts — keyed lookup

Full reference and derivation: `docs/superpowers/specs/2026-07-23-enigma-keyed-lookup-design.md`.
Verified against all 401 corpus archives — **3.1 million records, zero collisions**
(`tests/enigma/test_keyed_lookup_corpus_sweep.py`).

Five of the seven pools — `options`, `others`, `details`, `entries`, `texts` — are keyed
subclasses of `Pool` (`OptionsPool`, `OthersPool`, `DetailsPool`, `EntriesPool`, `TextsPool`) that
build an index at construction and add `get`/`all_with` (or `for_entry`) lookup on top of the
inherited `.records`/`.of_tag`. `header`/`mappings` stay plain `Pool` (with a `.record` singleton
convenience) — they hold exactly one record each, so there is nothing to key.

Each pool's full identity, measured exact and unique over the whole corpus:

| Pool | Identity | Records checked |
|---|---|---|
| `options` | tag alone (one record per option type) | 13,691 |
| `others` | tag + `cmper` + `inci` + `part` | 1,739,819 |
| `details` | tag + (`cmper1`+`cmper2` **or** `entnum`) + `inci` + `part` | 1,065,174 |
| `entries` | `entnum` (single tag `entry`) | 228,957 |
| `texts` | tag + `number` **xor** `type` | 67,438 |

- **`part` is Finale's linked-parts discriminant**: a score record (no `part` attribute) plus
  per-part variants (`part="1"`, `part="2"`, ...) share one `cmper` (or `cmper1`/`cmper2`, or
  `entnum`). `get(...)` with `part` omitted addresses the score record; passing `part` addresses
  that specific variant. `all_with(tag, cmper[, cmper2])` returns the whole linked set — score
  record plus every part variant, in document order — so nothing is dropped even though `get`
  itself returns a single record.
- **`get` returns the one exact `Record | None`** for a full identity — safe only because that
  identity is unique across all 3.1M corpus records. `inci` defaults to `0` (Finale's own default
  when the attribute is absent); key arguments normalize to `str` so `get(t, 1)` and `get(t, "1")`
  agree, matching how the model stores every attribute as a string.
- **A duplicate full identity raises `MalformedEnigmaError`** at index-build time, for any of the
  five keyed pools — the index build *is* the uniqueness check. The corpus has zero duplicates, so
  a duplicate identity in a real file would indicate a malformed document; the pool does not
  silently keep one of the colliding records.
- **Cross-pool link resolution — what a `cmper` on one record *refers to* on another pool — is not
  part of this slice.** `get`/`all_with` retrieve a record by its own identity only; following a
  reference to another pool's record is deferred (see Roadmap).

### Known format facts — entries and pitch

Full reference and derivation: `docs/eeppd.txt` (the Enigma Entry Pool description). Verified
against all 401 corpus archives (`tests/enigma/test_music_corpus_sweep.py`): every `entry` in the
corpus reads through `read_entry` without raising.

- `dura` is the entry's **written** note value in Enigma Duration Units (EDU); a whole note is
  4096. It decodes to a base power-of-two `NoteValue` plus a count of augmentation dots — the same
  decomposition notated on the page (e.g. `1536` is a dotted quarter: `1024 + 512`). **Tuplet
  scaling is a separate detail, not modelled here**: a tuplet's written `dura` is the undivided
  note value, not the sounded duration after the tuplet ratio is applied.
- An entry is a **rest** exactly when `numNotes == 0`; `read_entry` raises `MalformedEntryError` if
  `numNotes` disagrees with the actual number of nested `note` fields, so `is_rest ⟺ notes == ()`
  holds by construction rather than by convention.
- Pitch is **not** absolute in the record: `harmLev` is a diatonic displacement from the current
  key's tonic (0 at the tonic's octave, ±7 per octave), and `harmAlt` is an alteration relative to
  that key (0 natural, ±1 sharp/flat), not the accidental actually printed. Recovering an absolute
  spelled pitch (e.g. "F#4") needs the key in force at that point in the score — `harmLev`/`harmAlt`
  alone are key-independent. See `docs/eeppd.txt`'s Note Record section for the bit-level source of
  this fact.
- **This model stops at the cross-pool boundary.** `read_entry` only reads the `entries` pool's own
  fields; it does not resolve the key (which lives elsewhere, reached via
  `gfhold → frameSpec → measSpec` linkage, now done by `location.py` — see "Known format facts —
  score linkage" above and Roadmap) needed to spell a pitch absolutely, or the tuplet ratio needed
  to scale a written duration to its sounded length.

### Known format facts — score linkage

Full reference and derivation: `docs/superpowers/specs/2026-07-23-entry-location-design.md` and
`docs/superpowers/plans/2026-07-23-entry-location.md`. Verified against all 401 corpus archives
(`tests/enigma/test_location_corpus_sweep.py`): every entry in those archives is located exactly
once — no corpus `.musx` carries a mirror, which the legacy `.mus` cohort does (below).

- **An entry names no staff, measure, or key of its own.** Reaching them needs a chain across three
  pools: a `details` `gfhold` (`cmper1` = staff, `cmper2` = measure) holds up to four frame fields
  `frame1`..`frame4` — Finale's layers/voices; each present field is a `frameSpec` (`others`)
  `cmper`. A `frameSpec`'s `startEntry` begins the `entries` pool's own `next`-chain (each entry's
  `next` **attribute**, not a field) that walks forward to `endEntry`, and that chain *is* the
  entry's placement — the entry never carries its own staff/measure. An `others` `measSpec`
  (`cmper` = measure) carries the `keySig` (a nested `{key: <int>}` record) in force for that
  measure.
- **All four frame slots must be resolved**, not only `frame1` — 299 of 6,332 corpus `gfholds` carry
  `frame2`/`frame3`, and skipping them leaves layer-2+ entries unlocated. An absent, empty, or `"0"`
  frame slot is an unused layer, not a broken link — Finale usually omits it, but Enigma may also
  write `"0"`; either way it names no `frameSpec` and is skipped.
- **A frame `cmper` can resolve to more than one `frameSpec` *incidence*.** `others`' identity is
  `tag + cmper + inci + part`, and 73 of 67,558 corpus frame cmpers (20 of 401 files) carry two
  incidences — `inci="0"` and `inci="1"` — where exactly one carries `startEntry`/`endEntry` and
  the other has neither (only unrelated fields, e.g. `startTime`). `OthersPool.get` defaults to
  `inci=0`, which for these 73 is the *empty* incidence — resolving a frame must use
  `all_with(tag, cmper)` (every incidence sharing that cmper) and walk whichever one(s) actually
  carry a chain, not just the default. An incidence with neither `startEntry` nor `endEntry` is a
  legitimate empty layer; one with only one of the two is still malformed.
- **The key is per measure, and inherited**: not every measure carries a `keySig` (449 of 2,622
  omit it in the corpus survey) — a measure without one inherits the effective key of the prior
  measure, computed by walking measures in `cmper` order and carrying the last seen `keySig.key`
  forward (a measure before the first `keySig` defaults to `0`).
- **The key is exposed RAW (an `int`), not decoded — decoding it is a separate slice.** The
  standard scheme is fifths-style: a signed accidental count, e.g. `-1` = F major (one flat), `+2`
  = D major (two sharps). Decode hints and traps to carry into that slice: enharmonic equivalents
  (e.g. C# major vs. Db major) are **distinct** key values, not the same one spelled two ways; a
  raw signature alone does **not** fix major vs. minor (relative major/minor share a signature);
  and a transposing instrument's written key differs from concert pitch — the raw value is
  whatever is written for that staff/part, not necessarily concert.
- **An entry can be placed more than once, and that is legal — it is a *mirror*.** One staff
  displaying another's music is stored as a single entry span with two `frameSpec` records naming
  it and two `gfhold` records naming those frames. **Nothing in the file marks either placement as
  the copy**: the two `gfhold` records are ordinary, and the only sign is that their frames resolve
  to the same entries. Finale's editor has a direction — an engraver points one staff at another —
  but the stored file does not keep it, so `locate_entries` returns the placements as peers in
  frame-walk order and that order carries no meaning. `locate_entries` therefore returns
  `dict[int, tuple[EntryLocation, ...]]`. The **same** `(staff, measure, layer)` claimed twice is a
  different thing and is still malformed: several *distinct* places are a mirror, one place twice is
  a broken link. Corpus: 239 entries across 42 measures of one 2001-2005 `.mus` hold two placements
  each; none holds three. See `docs/DECISIONS.md`, "Mirror direction is not inferred".
- **This is the first cross-pool link resolution** — earlier slices (keyed lookup, typed entries)
  only retrieve a record by its own identity; `locate_entries` is the first to follow what a
  `cmper` on one record *refers to* on another pool. `MalformedScoreError` (distinct from
  `MalformedEnigmaError`) covers a broken chain: an entry no frame places (an orphan), a frame
  pointing at a missing `frameSpec`, a non-integer `keySig.key`/`startEntry`/`endEntry`, an entry
  placed twice at the same `(staff, measure, layer)`, a `next`-chain that exceeds a cycle guard, or
  an entry placed in more than 64 places — the guard on a file that names one long frame chain from
  many `gfhold` records, where the cycle guard bounds only a single walk. That cap is **per entry**,
  which bounds the document at `64 × entries` and also keeps each placement cheap: a placement is
  checked against the ones already made for its entry, so a budget one entry could absorb whole
  would make resolution quadratic in the file's size (measured: 1.70 MB of crafted input took 65.7 s
  to refuse under a whole-document total, 0.004 s per entry). The corpus maximum is 2.

### Known format facts — percussion mapping

`percussionNoteInfo` is a **149,533-row palette** present in all **401** archives; it is not score
usage. Actual use follows the resolver's five-hop linkage: `playbackRoute.cmper` identifies the
staff, `percMapRefID` selects that staff's map, and the map's assignments resolve through to the
percussion note information used by notes in that staff. `percussionNoteCode.noteID` is one-based;
its `inci` is exactly zero-based.

The aggregate sweep pins **605 used placements**: **597** resolve and **eight** remain explicit
unresolved code-13 assignments. All resolved `harmLev` values differ from the currently interpreted
pitch.

The older DCL palette is now typed independently. `^DL(map)` names a map,
`^DF(map,input)` carries one 10-byte mapping, and `^DN(map,input)` names that same input note. Every
one of the **18,647** `^DN` records has an exact `^DF` partner. The `^DF` key is an input note rather
than playback MIDI: among named entries they differ **3,717** times. Its first payload word is the
playback MIDI note and its second is staff position. Two further notehead values and the trailing
word remain raw because neither vendored specification names their order. The full DCL cohort holds
**1,282 maps** and **74,730 mapping rows**; `dcl_percussion_maps` reads the palette without claiming
that a score selects any of it. Text decoding follows the container cohort too: all **37**
big-endian DCL files are Mac-origin and all **102** little-endian files are Windows-origin, so map
and note names use Mac Roman and CP1252 respectively.

The cross-era boundary is equally important. Every `.musx` `percussionNoteInfo` map id has a
same-document `drumLibName` record — **8,403 map names in 401 documents** — but there is no
same-key note-name table. The 597 used appearances carry two distinct `percNoteType` values, both
outside MIDI's 0–127 range and neither equal to their note code. DCL map IDs also change meaning
between library versions, so joining unrelated files by a plausible numeric id would manufacture a
name. Notehead meaning, `.musx` drum naming, staff-to-map selection in DCL, IR consumption, output,
and `.mus` translation therefore remain deliberately deferred.

### Known format facts — key signatures

Full reference and derivation: `docs/superpowers/specs/2026-07-24-key-decode-design.md`. The
encoding is documented nowhere read; it was reverse-engineered from the corpus and verified against
all 401 archives (`tests/enigma/test_key_corpus_sweep.py`), decoded by `enigma/key.py`.

- **Encoding:** `key = (mode << 8) | (fifths & 0xFF)`. The **low byte, signed**, is `fifths` — the
  accidental count, sharps positive, flats negative, the MusicXML convention (`+2` = D major, `-1`
  = F major). The **high byte** is `mode`: `0` = major, `1` = minor.
- **Corroboration** (the encoding is inferred, so the evidence matters): all 13 distinct corpus raw
  values decompose to `mode ∈ {0,1}` and `fifths ∈ [-7,7]` with no remainder; `keySig` carries no
  field but `key`, so mode has nowhere to live but that integer; the scheme matches MusicXML, which
  Finale exports; and deriving the tonic from (fifths, mode) via the circle of fifths reproduces
  music theory for every value (`-3` major → E♭; raw `256` → A minor).
- **Inferred vs proven:** `mode = 1` → minor is **inferred**, not proven — no corpus file's key is
  independently known; the inference rests on the bit pattern, minor being the common second mode,
  and the high-byte-1 values being ordinary minor keys. The `±6`/`±7` enharmonic keys are modelled
  (the signed byte covers them, and `+6` = raw byte 6 vs `-6` = raw byte 250 stay distinct) but
  **unseen** — the corpus exercises only fifths `-5…+3`.
- **`decode_key` raises `UnsupportedKeyError`** on `mode ≥ 2` (a church mode or custom/linear key we
  have not reverse-engineered) or `fifths` outside `-7…+7`, including a negative raw value — rather
  than guess, since a wrong key would silently misspell every pitch that resolves through it. The
  corpus has 0 such values.

### Known format facts — the transposition octave

**The octave is baked into `harm_lev`, not stored separately.** Finale folds the octaves out of a
transposition into a residue in −4..+2 and folds the same octaves into every note's `harm_lev`. A
`.mus` records the residue with an unshifted `harm_lev`; a `.musx` records the full interval with a
`harm_lev` shifted to match, by exactly seven diatonic steps per octave — measured across 30,000+
notes with no exceptions. Either pairing determines the same written pitch, so **neither container
needs an octave field**.

That answers a question this project had recorded as a dead end. The octave genuinely is absent from
a `.mus` — no byte of `staffSpec` separates staves an octave apart, no field in any staff-keyed
record holds the interval or the octave count — but it is absent because nothing needs it, not
because it was lost.

`etfspec.pdf` anchors `harm_lev` absolutely — "the harmonic value 0 will always be the tonic of the
current key **in the octave from middle C to the C above**" — so `harm_lev` alone places the written
octave and a shifted value always needs undoing. `spell_note` adds
`written_octave_correction(interval)`: the folded octaves, returned, **for a downward
transposition**. An upward one (a xylophone, sounding an octave above what it reads) shows no fold;
that asymmetry rests on one instrument and is the weakest part of the rule.

Adjudicated against published written ranges rather than against Finale, since every corpus `.musx`
was produced by Finale *from* its `.mus`. **Each instrument is measured against its own range** —
lumping double bass and classical guitar, both interval 7, under one compromise range is what hid
the last error. Notes inside their instrument's published range go from **82.0% to 94.4%**: double
bass 69.8% → 99.7%, guitar 82.1% → 99.7%, baritone sax 7.3% → 100%, with trumpet, horn and
xylophone untouched.

Container octave-only differences fall **2,491 → 1**, and that one is a content difference between
the two files rather than a transposition fault. **The octave was never missing from a `.mus`.** See
`docs/formats/transposition-octave.md`.

### Known format facts — pitch spelling and transposition

Full reference and derivation: `docs/superpowers/specs/2026-07-24-pitch-spelling-design.md`. Turns
`decode_key` (tonic + fifths), `read_entry`'s `harm_lev`/`harm_alt`, and a staff's transposition into
an absolute spelled pitch (letter + accidental + octave), for both the **written** (what a player
reads) and **concert** (sounding) pitch. Implemented in `enigma/pitch.py`; verified against all 401
corpus archives, and against the 50,024 transposing-staff notes surveyed during design (every one
spells with 0 invariant violations — see below).

- **`harm_lev` is a diatonic scale degree** from the key's tonic, octaves included (`harm_lev = 0` is
  the tonic nearest middle C; `+7` is one octave up). **`harm_alt` is a chromatic alteration**
  relative to what the key signature already dictates for that letter (`0` = follow the key; e.g.
  F♮ in D major is `harm_lev = 2, harm_alt = −1`).
- **Spelling rule:** tonic letter + `harm_lev` → letter and octave (`LETTERS = "CDEFGAB"`, C-indexed
  so the octave boundary falls at C, as scientific pitch requires); the key's accidental for that
  letter (from the sharp order `F C G D A E B` or flat order `B E A D G C F`) + `harm_alt` →
  alteration.
- **Transposition is stored on `staffSpec.transposition.keysig`** as two signed integers:
  `interval` — diatonic steps the **written** pitch sits above concert (`0` = unison, `7` = an
  octave) — and `adjust` — the **written** key signature's shift on the circle of fifths (sharps
  positive). The written key is the concert key with `fifths += adjust` (mode unchanged, tonic
  re-derived). The concert pitch is the written pitch dropped `interval` diatonic steps and
  `T = ((7 · adjust) mod 12) + 12 · (interval ÷ 7)` semitones (a key-signature shift of `adjust`
  fifths moves the tonic `(7 · adjust) mod 12` semitones; the `12 · (interval ÷ 7)` term accounts
  for whole-octave transpositions). For a concert (non-transposing) staff (`interval = 0, adjust =
  0`) this is the identity.
- **Corroboration** (the `interval`/`adjust` decode is inferred, so the evidence matters): six
  distinct non-zero corpus signatures all reproduce a textbook instrument's transposition exactly —

  | `interval` | `adjust` | interval above concert | instrument |
  |---|---|---|---|
  | 1 | 2 | major 2nd (+2 sharps) | B♭ trumpet / clarinet |
  | 4 | 1 | perfect 5th (+1 sharp) | F horn |
  | 5 | 3 | major 6th (+3 sharps) | E♭ alto sax |
  | 8 | 2 | major 9th (+2 sharps) | B♭ tenor sax |
  | 12 | 3 | major 13th (+3 sharps) | E♭ baritone sax |
  | ±7 | 0 | octave (`noKeyOpt`) | bass / piccolo family |

  The octave rows (`interval = ±7, adjust = 0`) anchor `interval` as diatonic steps (7 = an octave)
  and `adjust` as a key shift that is 0 for a pure octave; "each added sharp is a perfect fifth" (a
  key shift of `adjust` fifths moves the tonic `(7 · adjust) mod 12` semitones) then reproduces every
  other row. The written-storage argument: `measSpec` carries a single **concert** key per measure
  (keyed by measure only, shared across every staff), so the written key is never stored directly —
  it must be derived by transposing the concert key, which is only meaningful if the stored
  `harm_lev`/`harm_alt` are the written pitch relative to the written key.
- **Inferred vs proven:** as with `mode = 1 ⇒ minor` in `decode_key`, **the instrument decode and the
  written-storage claim are inferred but strongly corroborated, not proven** — no corpus file's
  instrument or stored-pitch convention is independently known; the confidence rests on six distinct
  signatures all landing on real instruments, the octave anchor, the fifths-to-semitones law, and
  Finale's documented behaviour of storing written pitch.
- **`noKeyOpt` appears only on octave transpositions** (where `adjust = 0` already leaves the key
  signature unchanged) and **`setToClef` is display-only**; `read_transposition` does not consume
  either flag.

## Data flow

<!-- Describe the path of the core operation, input to output, naming the key types. -->

```
.mus  ──▶ zlib streams ──▶ pools ──────┐
                                       ├──▶ EnigmaDocument ──▶ build_score ──▶ IR ──▶ MusicXML
.musx ──▶ score.dat ──▶ EnigmaXML ─────┘
```

Both inputs converge **before** the IR, on `EnigmaDocument`. That is stronger than converging at the
IR: `locate_entries`, `read_entry`, `time_signatures`, `decode_key`, `spell_note` and `build_score`
are written once and read either container, so there is no second pipeline to keep in step and no
opportunity for the two to drift.

- `.musx`: `score_xml(path)` → `parse_enigma(xml)` → `EnigmaDocument`
- `.mus`: `read_mus_document(path)` → `EnigmaDocument`, translating the `.mus` pools into the same
  `Record`s (see "Known format facts — reading a `.mus` as an EnigmaDocument")

`read_document(path)` is the public facade over those two branches, using `detect_version(path)` to
choose by content. `read_score(path)` is `build_score(read_document(path))`. The lower-level
functions remain public for research and record-level work; application callers do not need to
compose them or know which container they received. Then `Score` → `to_musicxml(score)`. Key types
are named here as they are defined.
