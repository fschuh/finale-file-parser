# Decisions

The log of decisions made and questions still open. **Standing rule: don't silently resolve an open
question in code — propose it here, get a decision, then build.** Newest entries at the top.

## Format

Each entry: a date, the decision or open question, and a one-line reason. Mark open items **OPEN**
and resolved ones **DECIDED**.

---

## 2026-10-14 — DECIDED: recover complete clef tables from unrecognized writers

The approved PDF-review P01 investigation found real NotePad clef tables
being skipped because the application banner supplies no supported year.
Read independently evidenced full eighteen-definition tables in their known
324/360-byte layouts while preserving known-era precedence. Partial unknown
layouts stay unresolved, score/part scope remains distinct, and no default
clefs or application versions are inferred from pitch or copyright text.
The canonical clef and MusicXML paths consume the recovered source table
unchanged. Evidence and allocation bounds are documented in ARCHITECTURE.md.

## 2026-10-11 — DECIDED: report wholly out-of-score shapes as stale source records

**Context.** Assigned shapes refer entirely to bars beyond the current score
in Spring Yard and Hurry Up, preventing export despite having no current notes
at either endpoint. The user approved quarantining verified stale references.

**Decision.** Keep raw records, attach typed diagnostics to canonical Score,
and omit only source-eligible shapes whose valid endpoints both lie beyond the
last real bar. Partially missing, malformed, reversed and zero-length supported
spans remain errors. Do not extend measures or clamp timings to accommodate a
stale drawing. Reuse this scope for subsequent octave/custom-line features.

## 2026-10-11 — DECIDED: keep same-event slur geometry separate from phrase timing

**Context.** Memories of Green contains a real incoming curve at its second
ending, drawn between distinct offsets attached to the same note. An ordinary
timed-slur invariant rejects it and prevents the whole score from exporting.

**Decision.** Extend canonical Slur with explicit graphical geometry, requiring
distinct drawing endpoints for the same-event case. Export standard positioned
slur notation while retaining every written note and playback tie unchanged.
Ordinary zero/reversed phrase spans remain errors. Document MuseScore4.7.5's
same-chord-to-l.v. conversion as an importer limitation; do not invent note
anchors or claim faithful display there. This fulfills the approved source
preservation path while exposing the specific renderer limit for user review.

## 2026-10-11 — DECIDED: preserve dormant legacy frames outside musical placement

**Context.** Reserved-template scope exposes active entry chains in stored
frames with no current gfhold assignment in Prelude, Simone and Dark World.
All four layer references must be decoded before making that determination.

**Decision.** Retain the raw database. The legacy adapter derives an unassigned
frame marker from complete entry references and absence of assignments in all
staff/layer/linked-part contexts. Musical placement validates those dormant
chains as ownership, while producing events only for assigned musical cells.
Raw location inspection stays strict; genuine frameless entries and malformed
chains still fail. This is consistent with the approved plan's scope/ownership
requirements and avoids classifying entries by their pitches or rhythms.

**Validation.** Authored unused/shared/higher-layer/linked-part/orphan cases;
75-file production sweep, with input hashes unchanged.

## 2026-10-11 — DECIDED: expand combined accent/staccato glyphs into existing articulations

**Context.** Scars' missing bass-clef accents are visible assignments of a
single glyph containing both an accent and a staccato dot. Finale's three
relevant font charts agree on characters 249 and 223 for the two variants.

**Decision.** Resolve either glyph to `("accent", "staccato")` in the existing
canonical event tuple, retaining source assignment order. Keep the public
single-component mapping unchanged. The existing MusicXML exporter emits
both elements once on a chord's principal note. Preserve visibility filtering
and binary duplicate-assignment handling; infer neither velocity nor timing
from the recovered marks.

**Consequence.** All 25 local composite marks regain both components without
changing notes or other notation. Shape glyphs and further combinations require
separate evidence. Manual coordinates and alternate-glyph placement remain
outside this semantic mapping. Evidence is in `docs/ARCHITECTURE.md`.

## 2026-10-11 — DECIDED: retain hairpin endpoint X adjustments independently of time

**Context.** The user approved recovering the m51 hairpin's source inset.
Its musical end is the barline, with a separate negative horizontal adjustment.
Moving that musical end to shorten the printed line would alter the crescendo.

**Decision.** Append exact staff-space `start_x_offset` / `end_x_offset` values
to canonical `Hairpin`, preserving existing constructor defaults. Normalize
active `endPtAdj` X values from Finale's 24 EVPUs per space, then emit MusicXML
`relative-x` in ten tenths per space. Preserve inactive source data without
applying it. Timing, divisions, pairing and note cursors remain independent.

**Consequence.** The XML carries the source inset for readers that support it.
MuseScore 4.7.5 revision `3654226` reads no hairpin X positioning in its importer;
this standard XML correction cannot itself change that build's displayed
endpoint. Do not change timing or add duplicate fake hairpins to compensate.
Vertical layout, source anchor contexts and system-break geometry remain
outside this horizontal-adjustment change. Evidence is in `docs/ARCHITECTURE.md`.

## 2026-10-11 — DECIDED: retain phrase slurs as complete spans between exact events

**Context.** The user requested missing slurs in Scars' bars 17–19 and approved
the recovery plan. Its 87 visible SmartShapes have explicit entry endpoints,
including 25 cross-measure spans and seven grace-note endpoints. These are
independent of per-pitch ties and cannot be recovered from note adjacency.

**Decision.** Append immutable `Slur` spans to canonical `Part`, using
`SlurEndpoint(measure, voice, event_index)` references. Gather entry placements
while building events, then resolve assigned visible preset entry-based solid
slurs against the endpoint's staff and measure. Preserve automatic direction or
an explicit up/down shape. Use the same normalized Enigma path for both formats.

**Consequence.** Exact event references distinguish graces at the same onset and
select the intended placement of a mirrored entry. MusicXML emits one start/stop
pair on the endpoint events' principal notes, with numbers allocated in actual
measure/staff/voice/event document order, independent of ties or playback. The
exporter validates spans and handles cross-voice stops serialized before starts.
It keeps the 1–16 overlap bound at export, not in the IR. No manual curve geometry
is guessed. Cross-staff spans, measure-based/custom/dashed slurs, pitch-specific
note-id attachments and older DCL shape layouts remain unsupported. Format and
assignment evidence is in `docs/ARCHITECTURE.md`.

## 2026-10-10 — DECIDED: preserve hairpins as exact spans on canonical staff-parts

**Context.** The user requested Scars' missing crescendo hairpins and approved
the implementation plan. Its SmartShape definitions and measure assignments
store kind, staff and exact endpoints; the adapter previously dropped them.
These markings span time and cannot be represented by a measure-start word.

**Decision.** Append immutable `Hairpin` spans to `Part`, with kind and start/end
measure numbers plus whole-note `Fraction` offsets. The part retains the source
staff identity. Resolve only assigned, visible preset measure-based crescendos
and diminuendos; exclude linked-part copies and unsupported attachment modes.
Keep the existing normalization and canonical `Score` pipeline for both formats.

**Consequence.** MusicXML emits paired numbered wedges below the staff, with
exact offsets and divisions that include endpoint denominators. Allocate/reuse
numbers in XML document order, including staff projection, so offsets and
overlapping spans survive cursor backups. Invalid positions and excess document
overlaps raise clear errors. This adds no guessed velocity curve or Finale
layout reconstruction. Omit optional wedge spreads and use the reader's style:
the user found MuseScore interprets the initial spread0 as overall zero height,
ignoring the stop's spread15. Its importer corroborates this behavior; schema
and Verovio validation alone did not detect it. Pairing/timing are unchanged.
Cross-staff endpoints, custom/entry/lyric-based shapes
and the older DCL shape encoding remain separate work; byte/API evidence and
validation are in `docs/ARCHITECTURE.md`.

## 2026-10-10 — DECIDED: recover source dynamics and honor hidden articulation assignments

**Context.** Scars' assigned dynamics were missing because its Finale-2012
UTF-16LE descriptions were truncated at a single zero byte. The final `sfz`
expression was unnamed, while two separate hidden accents were incorrectly
printed. The user approved the correction plan.

**Decision.** Decode descriptions using the banner's evidenced encoding era,
with aligned terminators and explicit malformed-input errors. Keep the existing
`Expression` IR and MusicXML exporter. Grade names suffice for level dynamics;
otherwise ambiguous attack names require their documented glyph when font
markup is unresolved. Maestro glyph167 plus `sforzato` establishes `sfz`.
Normalize assignment visibility, retain it in source records, and exclude hidden
and linked-part assignments consistently from all articulation-derived notation.
Include visibility in binary-assignment deduplication so visible copies survive.

**Consequence.** The eight source dynamics print correctly and bar59 retains
its visible staccatos plus `sfz`, with no invented accents. Ordinary visible
accents keep their meaning. Playback values remain source data without guessed
performance curves. No parallel score model or hidden-playback notation is
added to the IR. Byte/glyph evidence is in `docs/ARCHITECTURE.md`.

## 2026-10-10 — DECIDED: retain arpeggio connections in the IR and project connected staves at export

**Context.** The user requested missing arpeggio signs from Scars of Time. Six
assigned plain glyphs were already normalized but had no resolver or exporter.
Its opening sign spans both staves; a note-only glyph mapping would shorten it
to the upper chord. MusicXML expresses connected staff rolls inside one part,
while the reader's canonical `Score` currently has one part per staff.

**Decision.** Append `Event.arpeggios` using immutable `Arpeggio` objects. Keep
the reader's existing staff-parts, and record a shared connection and staff ids
only where the assignment's documented vertical-copy endpoint covers one
complete simultaneous lower chord in a two-staff brace with known geometry.
The XML exporter projects explicitly connected consecutive staff-parts into
one multi-staff part. A brace alone never causes merging or a new arpeggio.

**Consequence.** Every chord pitch receives a real `<arpeggiate>` notation;
shared numbers preserve connected rolls, and independent simultaneous rolls
remain separate. Staff attributes, voice identities, cursor timing, directions,
barlines and outer groups survive the projection. Source pitches, written and
metric durations stay intact. No exact Finale roll timing, arrow glyph, manual
shape or broader span policy is inferred. The byte evidence and local/synthetic
validation are recorded in `docs/ARCHITECTURE.md`.

## 2026-08-20 — DECIDED: PDF export goes through svglib, behind an optional extra

`finale-parser convert --format pdf` writes an engraved score as PDF. The route is
`Score` -> MusicXML -> Verovio SVG -> svglib/reportlab -> PDF, and the last step is an optional
install extra: `pip install finale-file-parser[pdf]`. Without it the command exits with a message
naming the extra.

Reason: **Verovio cannot write PDF.** Its toolkit renders SVG, MIDI, PAE and a timemap and nothing
else, so a converter is unavoidable. Writing one here was considered and rejected on evidence: one
page of a corpus score carries 70 `<use>` elements resolving into `<defs>`, `<text>` with a
`font-family`, a `<style>` block and eight `<ellipse>`s, so a faithful converter means implementing
`use` resolution, CSS and font embedding.

The three candidates were measured rather than compared on their documentation, and the measurement
reversed the expected order. CairoSVG needs a native `libcairo`; WeasyPrint is *not* pure Python as
its reputation suggests — it dropped cairo but still needs Pango, HarfBuzz and fontconfig through
cffi. Both fail to import on a stock arm64 macOS with no system packages. svglib + reportlab, the
candidate expected to be weakest on `<use>` and CSS, renders the notation faithfully with no
warnings and no system libraries.

**Licence.** svglib is **LGPL-3.0** and reportlab is BSD. This adds no new *class* of obligation:
the project already depends on Verovio under LGPL-3.0 and documents the boundary the same way in
`THIRD-PARTY-NOTICES.md`. Neither is vendored; both are ordinary imported packages. Making it an
extra keeps the obligation off anyone who never asks for a PDF.

Consequence: `export/pdf.py` sets its own engraving options rather than reusing the report's. The
report crops each page to its content (`adjustPageHeight`), which turns a one-system score into an
8.8 x 3.0 inch strip; print sets a real page size, which also makes every page share one viewBox so
a multi-page score prints at a single scale. Verovio's default footer is suppressed, as the report
already suppresses it.

## 2026-07-22 — DECIDED: cipher parameters taken as facts from MIT-licensed source

The `score.dat` cipher — seed `0x28006D45`, the BSD `rand()` LCG, the
`(upper + upper // 255)` output function, and the 128 KiB keystream reset — was read from
denigma's source (MIT), which credits Deguerre for the discovery. The implementation here is
written independently; the parameters are not.

Reason: the earlier decision was to use published *documentation* as reference and write
implementations independently. That proved insufficient — the transform is documented nowhere in
prose, only in code. An algorithm choice and a seed value are facts rather than creative
expression, and MIT would permit outright porting with attribution in any case.

Consequence: attribution to both denigma and Deguerre is required in `docs/REFERENCES.md` and in
`enigma/crypt.py`. `docs/formats/score-dat.md` records precisely what this project derived from the
corpus and what it did not.

## 2026-07-22 — DECIDED: one provenance type for both formats

`ProvenanceStamp` (renamed from `MusStamp`) carries date, application, and platform for both `.mus`
and `.musx`, plus `modified_by` and `app_version` which only `.musx` fills. `MusxDetail.platform`
was removed — platform now lives on each stamp, matching `.mus`'s rule that both stamps must not be
assumed to agree.

Reason: the formats recorded the same facts and the code modelled them twice, one module apart —
`.musx` discarded its dates entirely and collapsed two platforms into one field. Breaking the
published type was cheap at 0.0.1 and would only get more expensive.

`appRegion` is deliberately not modelled: `US` in all 802 corpus blocks, so it carries no
information yet.

## 2026-07-22 — DECIDED: both `.mus` and `.musx` are in scope

Settled by what shipped: `detect_version` handles both, `.mus` banner parsing and provenance stamps
are done, and `.musx` has a full container reader. Reason: the corpus is 238 `.mus` and 401 `.musx`
— dropping either would abandon a third of real files.

## 2026-07-22 — DECIDED: use community reverse-engineering as reference, not as source

Published community documentation (e.g. the MIT-licensed EnigmaXML documentation) may be read as a
reference for what the format is; implementations are written independently rather than ported.
Reason: keeps provenance simple while not re-deriving what is already public. Licenses of known
sources are recorded in `docs/REFERENCES.md`.

## 2026-07-21 — DECIDED: one module owns archive access

`container/` owns opening, validating, and reading `.musx` archives. `version/musx.py` is a client.
Reason: the two had parallel implementations of the same zip-safety logic, which can drift; a
single owner means one place to harden.

## 2026-07-21 — DECIDED: reject unsafe member names, allow unknown ones

The container reader raises only on genuinely dangerous names (absolute, `..` segments,
backslashes, control characters). A merely *unfamiliar* name is surfaced as data. Reason: rejecting
unrecognised archives would contradict the principle that unknown variants stay inspectable, and
would make a new Finale member name break version detection outright. The fixture generator keeps a
strict allowlist, because we control what gets committed.

## 2026-07-21 — DECIDED: container fixtures carry structure only

Committed `.musx` fixtures harvest member names, order, compression method and declared lengths
from the corpus, and regenerate every payload. Reason: `score.dat` is the musical work and the
corpus also embeds `graphics/*.jpg` which may be licensed artwork. Payload bytes never leave the
gitignored corpus.

## 2026-07-21 — DECIDED: version detection precedes record parsing

Version is detected from headers/metadata before any record parsing, and both formats are covered.
Whether each version needs *distinct record-parsing logic* remains unknown — that question opens
once record parsing begins.

## 2026-07-21 — DECIDED: defusedxml for all XML parsing

`.musx` metadata is attacker-controlled XML, and stdlib `ElementTree` is vulnerable to
entity-expansion and external-entity attacks. All XML parsing uses **`defusedxml`** — the project's
first runtime dependency. Reason: hand-hardening the stdlib parser is easy to get subtly wrong and
easy to regress.

## 2026-07-20 — DECIDED: output data model — internal IR, MusicXML as the first exporter

Parsing produces a project-internal **intermediate representation (IR)**; output formats are
exporters layered on top, with **MusicXML** as the first. Every supported input converges on the
same IR (`.mus` directly; `.musx` via EnigmaXML), so format-specific quirks stay in the readers and
never leak into the exporters. Reason: multiple inputs and a likely-growing set of outputs make a
hub-and-spoke shape cheaper than coupling any reader to any writer.

Consequence: MusicXML's expressive limits must not constrain the IR. If Finale represents something
MusicXML cannot, the IR keeps it and the exporter drops it — the loss happens at the edge, on the
way out, and is documented there.

## 2026-07-20 — DECIDED: scope includes a desktop frontend

Beyond the parser library, the project will ship a **desktop application** providing (a) a hex
viewer that decodes binary entries and displays their structure values, and (b) a rendering of the
corresponding notation. Reason: reverse-engineering an undocumented format is far faster when you
can see bytes and the notation they produce side by side — the viewer is a research instrument, not
just a deliverable.

Consequence: the library must stay independently usable and must not take a GUI dependency. See the
open question on GUI framework and repo layout.

**Update, 2026-08-04:** (a), the hex viewer, shipped — not as part of a desktop application, as an
HTML report instead. See the 2026-08-04 entry below for why, and `docs/ARCHITECTURE.md`'s overview
for the current shape.

**Update, 2026-08-15:** (b), notation rendering, also shipped in that report. Verovio engraves the
shared `Score` in the Music tab; see the 2026-08-15 entry below. No GUI framework, separate package,
or repository split was needed.

## 2026-07-20 — DECIDED: third-party reference documents are vendored into `docs/` under fair use

Four out-of-print reference documents are committed to `docs/` (the ETF specification, the 1996
Enigma Entry Pool document, the Cahill thesis, and the LilyPond ETF notes). All are cited with
author, original URL, and archive URL in `docs/REFERENCES.md`.

Owner's determination: these works are **no longer accessible through their original channels**,
are of value to other researchers, and are reproduced here for **research and scholarship** under
fair use. All works are properly attributed. **The project will comply promptly with any takedown
request** from a rights holder.

Consequence for future sessions: do not remove these files as a "licensing cleanup" — this is a
settled decision, not an oversight. Any *new* vendored document must meet the same bar: out of
print, properly cited with original and archive URLs, and added to `REFERENCES.md` at the same time
as the file.

## 2026-07-20 — DECIDED: toolchain

Python managed with **uv**; **ruff** for lint + format; **mypy --strict** for types; **pytest** for
tests. One toolchain, declared in the project manifest and `CLAUDE.md`, run through `make`. Reason:
a single enforced toolchain removes a class of back-and-forth and keeps every session consistent.

## 2026-07-20 — DECIDED: license posture

**MIT** — confirmed by the owner, matching the `LICENSE` file already in the repo. Reason: a
permissive license suits a format-interoperability library that other tools need to embed freely.

## Open questions

<!-- Add architectural forks here as they arise, each with a recommended default and "owner to
     confirm". Move to a DECIDED entry above once resolved. -->
- **OPEN — does each detected version need distinct record-parsing logic?** Version detection
  itself is DECIDED (see above) and covers both `.mus` and `.musx`. What remains unknown is whether
  the record layouts inside a given version differ enough to require separate parsing paths per
  version, or whether one parser can cover the range. Opens once record parsing begins.
- **OPEN — `.musx` major-version-to-year mapping.** The `major` field (15/16/17/18) has no
  established mapping to Finale's marketing years (2009/2011/2012/2014...), and nothing in the
  corpus bridges the two schemes. See `docs/ARCHITECTURE.md`.

## 2026-07-24 — DECIDED: port zlib's `contrib/blast` for legacy `.mus` payloads

**Context.** `.mus` files from Finale 2001-2005 (139 of the 238 corpus files) store their payload as a
PKWARE DCL ("implode") stream. No Python stdlib module reads this format, and no maintained pure-Python
implementation was found.

**Decision.** Port Mark Adler's `blast.c` (zlib `contrib/blast`) to Python as
`enigma/blast.py`, rather than shelling out to a tool or adding a dependency.

**Licensing.** `contrib/blast` is under the **zlib License**, which permits use and modification
provided the origin is not misrepresented and altered versions are marked as such. The module docstring
states plainly that it is a port of Adler's work, and `docs/REFERENCES.md` records the attribution —
the same treatment already given to denigma/Deguerre for the `score.dat` cipher.

**Why not a dependency.** The format is small and stable (the tables are fixed constants), the port is
~150 lines, and it must enforce this project's own allocation caps on untrusted input, which a
third-party library would not.

**Consequence.** `read_mus_payload()` decodes 238 of 238 corpus files. Correctness rests on the
upstream test vector rather than on our own reimplementation being self-consistent.


## 2026-07-27 — DECIDED: parts follow the instrument list, not the staff number

**Context.** `build_score` ordered parts by staff number. A `.musx` records the score's real staff
layout in `instUsed`, one record per slot, and that order is **not** always ascending: 10 of 401
corpus documents list staves in an order their numbers do not follow. Those scores exported with
their parts down the page in the wrong places — silently, since every part was still present. It
also forced 8 staff groups to be dropped as non-contiguous.

**Decision.** Order parts by `staff_order(document)`. A staff carrying music but holding no slot in
the list keeps a place after the listed ones rather than being dropped.

**Consequence.** 10 documents change part order; 388 do not. All 79 same-content pairs keep identical
part order across containers, because a `.mus` has no instrument-list record and falls back to
numeric order, and no paired document is one of the 10. Staff groups rise from 201 to 209 — every
group previously dropped for non-contiguity now survives.

- **RESOLVED 2026-07-27 — staff 32767 is not a part.** See the entry below.


## 2026-07-27 — DECIDED: staff 32767 is a reserved staff and is not exported

**Context.** Every one of the 401 corpus documents declares a staff numbered 32767 — 0x7FFF, the same
sentinel the format uses for "to the end" in `staffGroup.endMeas`. It has its own `staffSpec`, a
`gfhold` per measure, and real entries, so it is not a phantom of our reading, and it was exported as
a part named "Staff 32767" in every file this project produced.

**Evidence that it is not part of the score.** Each of these was measured over the whole corpus:

- it is **never** in the score's instrument list (0 of 401) — and `instUsed` is precisely the layout
  of the staves a score shows;
- it is **never** named by a staff group (0 of 401);
- its `staffSpec` is a template, not a description of a part: 401 documents hold only **two** distinct
  bodies, all with the same fixed `instUuid`, a one-line `customStaff`, and clefs, key signatures,
  measure numbers, repeats and repeat barlines all hidden;
- 376 of 398 give it a single repeated pitch, always in layer 1, and none carries a lyric;
- its entries are **disjoint** from every real staff in all 401 documents, so it is not an alias or a
  wildcard for one;
- it is the **only** staff in the corpus absent from the instrument list, so excluding it excludes
  nothing else.

**Decision.** `build_score` does not make a part for it. The exclusion is by staff id rather than by
"absent from the instrument list", because a `.mus` has no instrument-list record — excluding it only
where a list exists would drop the staff from `.musx` and keep it in `.mus`, and the two containers
would then disagree on every score. All 93 buildable `.mus` documents carry the same staff.

**What is deliberately not claimed.** What Finale uses it for. A hidden one-line staff of repeated
quarter notes fits a click track, a rhythmic-notation staff, or a chord-symbol carrier, and the
corpus does not decide between them. The decision rests only on it not being part of the score.

**Consequence.** No `Score` loses all its parts. Beams fall 84,620 → 84,593 (27 of them were on this
staff); articulations, lyrics and staff groups are unchanged.

- **RESOLVED 2026-07-27 — parts have gaps where a staff is empty.** Fixed; see the entry below. Was: `build_score` makes a measure only where a staff
  has entries, so a staff silent through a measure gets no `Measure` at all and its part's measure
  list skips a number. The reserved staff was hiding how much of this there is: it covered 1,375
  measures across 162 documents that no real staff occupies — typically measures 1 and 2 of a score
  whose real staves start at 3. Four of those carry a repeat barline that now has no part to be drawn
  on, which is why the repeat sweep counts 107 forward and 119 backward against a pool holding 109
  and 121. The fix is to emit a full-measure rest where a part is silent, which is its own slice.


## 2026-07-27 — DECIDED: every part gets every measure, silent bars included

**Context.** `build_score` made a `Measure` only where a staff had entries, so a part silent through
a bar skipped it and its measure numbering jumped. **6,362 measures were missing across 420 of 731
corpus parts** — 57% of parts. The output stayed well-formed, which is why it went unnoticed: a
reader meeting a gap in the numbering cannot tell a silent bar from a lost one.

**Decision.** A part covers every measure of the score, and a bar it rests through carries one
full-measure rest.

Three pieces make that work:

- **The measure list comes from `measSpec`**, not from where the music is. It runs 1..N with no gaps
  in all 398 buildable corpus documents and nothing sounds outside it. Using the measures that hold
  entries loses every bar in which the whole ensemble rests.
- **The key comes from the measure** (`effective_keys`, promoted to public), not from the staff's
  notes — so a part silent through the opening bars is not reported as being in C major there.
- **Clefs carry forward.** `clefs_by_measure` reads `gfhold`, and a measure a staff rests through has
  no `gfhold` at all; without carrying the last one forward a part loses its clef the moment it falls
  silent and re-announces it on returning. Before the first `gfhold`, the staff's `defaultClef`
  applies.

**Why a measure rest is its own thing.** `Event.is_measure_rest` is not "a rest that happens to last
a whole note": it is written as one symbol centred in the bar and its length follows the time
signature, so a 3/4 measure rest lasts 3/4 and has **no note value at all**. MusicXML spells that
`<rest measure="yes"/>` with a duration and no `<type>` — and asking `_note_type` for the type of a
3/4 event raises, which is the check that the two stay in step.

**Consequence.** All 398 documents now give every part the same contiguous 1..N measure list, with
6,362 measure rests. This also restores the 4 repeat barlines that reached no part after the
reserved-staff exclusion, so the repeat sweep matches the pool exactly again.

Carrying clefs forward cut the `.mus`/`.musx` clef disagreement from 22 measures to **10**, without
touching the clef reading itself: half of those 22 were one container having a `gfhold` where the
other did not, rather than the two disagreeing about a clef.


## 2026-07-28 — RESOLVED: the transposition octave is not missing from a `.mus`

**Context.** The project recorded that a `.mus` cannot supply a transposing staff's octave, and that
2,491 written pitches were therefore an octave wrong. The first half is now proven exhaustively; the
second was the wrong conclusion drawn from it.

**Finding.** The octave is **baked into every note's `harm_lev`**. Finale folds the octaves out of a
transposition into a residue in −4..+2 and folds the same octaves into `harm_lev`; the two are a
matched pair. A `.mus` stores the residue with an unshifted `harm_lev`, a `.musx` the full interval
with a `harm_lev` shifted to match. Measured across 30,000+ notes, the delta is exactly seven
diatonic steps per octave, with no exceptions. **Neither container needs an octave field**, which is
how Finale displays a `.mus` correctly.

Undoing the fold on the `.musx` side takes the containers from 27,931 identical / 2,493 octave-only
to **30,423 identical / 1 octave-only**.

**Decision.** Document it; change no code yet. Reconciling the two containers does not say which
frame is the true written pitch, and the obvious external check — where notes land on the staff —
cannot adjudicate: four candidate models each fit some intervals and none fits all, and a
transposing instrument has its own tessitura, so the non-transposing baseline is not a fair
comparison for the staves in question. Changing it would move the octave of every transposing staff
in the output.

See `docs/formats/transposition-octave.md` for the full evidence and for what would settle it.

- **RESOLVED 2026-07-28 — which octave frame is the true written pitch?** Both, depending on the
  residue. The independent witness turned out not to need a new file: the interval values identify
  the instruments (B♭ trumpet, F horn, E♭ alto/tenor/baritone sax, double bass, xylophone), and each
  has a published written range that owes nothing to Finale. `spell_note` undoes the fold for every
  **downward** transposition; an upward one shows no fold. Measuring each instrument against **its
  own** published range — not a compromise range shared by two instruments, which hid an error for
  a while — notes inside range go **82.0% → 94.4%**: baritone sax 7.3% → 100%, double bass
  69.8% → 99.7%, guitar 82.1% → 99.7%. Container octave-only differences **2,491 → 1**, and that
  one is a content difference between the files. The octave was never missing from a `.mus`.

## 2026-07-29 — CORRECTED: a 2001–2005 `.mus` payload is four labelled pools, not one stream

**What was recorded.** That the DCL era "packs every pool into one stream with no known
delimiters", so `read_mus_others`, `read_mus_details` and `read_mus_entries` raised for those files
by design. It appeared in three module docstrings, `docs/ARCHITECTURE.md` and the roadmap.

**What is true.** The payload is a chain of four DCL records from `0x200` to the last byte of the
file, each `[u16 kind][u32 length, header included][u32 checksum][DCL stream]`, with `kind` naming
the pool — 15 others, 16 details, 17 entries, 18 text. All 139 corpus documents tile exactly. The
DCL era **labels its pools**, which the zlib era does not.

The old fixed offset `0x20A` is `0x200` plus one ten-byte header, which is why decoding there always
worked. It returned the first pool of four — the `others` pool, about a quarter of the file — and
reported success, so the payload sweep counted 139/139 as decoding while three quarters of every one
of those files, including every note, went unread.

**Two things this changes about the public API.**

- `read_mus_payload` now returns the whole payload for a DCL-era file rather than its first pool. It
  is the same function doing what its name always claimed; the number it returns is roughly 4× larger.
- `read_mus_pools` is added and `read_mus_streams` kept as `[pool.data for pool in ...]`. A `MusPool`
  carries the container's own `kind` and the document's `byte_order`, because both are facts the file
  states and neither should be re-derived by guessing. `kind` is `None` for the zlib era, where the
  container genuinely says nothing and a reader must walk a pool to know what it is.

**Byte order is per document** — 102 little-endian (Windows), 37 big-endian (Mac) — and governs every
field in every pool. It is read off the first record's kind, which is 15 exactly one way round, so
the byte-order test and the "is there a container here" test are the same test.

**What this does not do.** These files still do not build a `Score`. The `others`/`details` pools are
a different record encoding from the 2011 era's — fixed 16-byte rows carrying ETF's two-character
tags — and decoding the fields inside those rows is unstarted. Both walks are pinned as accepting
0 of 139 so that a future change cannot start half-reading them silently. See
`docs/formats/mus-dcl-container.md`.

**The process lesson, and it is the same one as the codec false negatives.** "139/139 decode" was
measured on the thing that was implemented, not on the thing that exists. A decoder that returns
*something* for every file is not evidence that it returns *everything*; nothing checked the decoded
size against the file, and a 4× shortfall went unnoticed for a week.

## 2026-07-29 — DECIDED: an entry no frame reaches is dead pool space, and is discarded

**The `.mus` entry pool is a live database, not a list of the music.** A `.mus` is written in place,
so an entry deleted in Finale keeps its 38-byte slot until the file is compacted. The pool therefore
holds the current music *and* whatever earlier music has not yet been overwritten. The frames say
which is which. The 2001–2005 reader now emits only the entries some frame reaches, and 5,302
unreached entries across 16 documents are dropped at the container edge.

**Why this is not a convenient reading of an inconvenient failure.** 4,675 of the 5,302 (88%) are
exact duplicates of passages the frames *do* reach, matched as whole `next`-chains rather than
entry-by-entry — sequence identity, which coincidence in tonal music does not produce. One document
keeps entries 1–858 as a stale copy of the live 859–1717, 824 identical field for field. The other
12% are in three documents whose frames reach nothing at all.

**What it buys**: 118 → 129 of 139 documents build, 55,463 → 66,847 pitches (+20%), and the
malformed count falls 16 → 2. The two that remain are a genuinely double-claimed entry and a gfhold
placing entries in a measure that defines no key.

**What it costs, and how that is paid for.** The orphan check in `locate_entries` is what caught the
four-layer frame bug the day before; pruning would silence it for this era. So it is left untouched —
it still fires for `.musx` and for 2011 `.mus` — and the discard is pinned instead. The sweep asserts
that the reader discards exactly 4,946 entries, a number that **may only fall**. A reader that
stopped reaching music would discard *more*: reverting `_FRAME_LAYERS` from 4 to 2 pushes it to
6,004 and fails the pin, where the build counts alone would only have got quieter. The detector moved
from a per-document exception to a corpus-level quantity; it did not go away.

**A document whose frames reach no entry at all is refused, not pruned to nothing.** Three files are
like this. Pruning turned them from "rejected for orphans" into "builds a `Score` with no parts", and
every aggregate total stayed green, because a document contributing nothing changes no sum. The
per-document assertion caught it — the same trap as the blank scores three days ago, in a third
costume. The rule that keeps catching it: **a sweep that only adds things up cannot see a document
that adds up to nothing.**

## 2026-07-29 — RESOLVED: a 2011 `.mus` staff layout order is others tag 159

A `.musx` lists its staves in the order the score lays them out, which is not always ascending.
`enigma.groups.staff_order` reads that from `instUsed`; the `.mus` reader had no equivalent and fell
back to numeric order. Both this file's predecessor entries and the code itself recorded the reason as
**unidentifiable**: "every paired document numbers its slots and staves alike, so no pair
distinguishes a right guess from a wrong one."

That was false, and worth understanding why it was believed. Two paired documents *do* lay five
staves out as 1 2 5 3 4 and 5 1 2 3 4. They were reaching no paired sweep, because pairing chose a
`.musx` for a stem by directory-walk order and the candidate it happened to pick for those two
failed the same-music filter. **The corpus had the evidence the whole time; the test harness was
discarding it.** Fixing the pairing rule surfaced it, and identifying the record took one afternoon
after that.

**The record**: others tag 159, keyed by instrument list (`cmper` 0 is the score's, exactly as a
`.musx` keys its own). The payload is an array of **24-byte slots, one per staff**, each opening with
the staff number as a u16.

**Why 24 and not a coincidence.** In all **95** paired documents the record's length is exactly
`24 x` the staff count, and the u16 at each slot start reproduces the `.musx` layout order in all 95
— including both permuted documents. Length agreeing with staff count in every document is the part
a wrong tag would not survive; a five-element sequence that merely fits is easy to find, and looking
for one first produced a page of coincidences. The other 22 bytes of a slot are not decoded, because
the layout order does not need them.

**Confirmation from the other direction**: once the order is read, those two documents agree with
their `.musx` on structure, measure attributes, rhythm and tuplets exactly, having previously
differed only in part sequence.

**Not extended to 2001–2005.** That era carries an ETF `^Iu` row which is very likely the same
record, but the whole DCL cohort has no paired `.musx` anywhere, so there is nothing to check a slot
layout against. It keeps the numeric fallback, and `UNTRANSLATED` says so.

**The process lesson, and it is a new one.** A gap can be documented as unresolvable when what is
actually true is that the test harness cannot see the evidence. The claim "no pair distinguishes a
right guess" was a statement about the corpus, but it was only ever measured through the pairing
code — and that code was silently dropping the distinguishing pairs. **Before recording that
evidence does not exist, check that the thing which looked for it could have found it.**

## 2026-07-29 — RETRACTED: "the `.mus` staff-name id is not arithmetic"

`docs/formats/mus-staff-names.md` recorded that the id at `staffSpec` +30 cannot reach a text block
by arithmetic. That is withdrawn. Both grounds for it were artefacts of how the corpus was being
read.

The first was "only one document resolves two names, so within-document constancy is vacuous — and
that one document's delta varies." Five documents resolve two or three names. They were reaching no
paired sweep because pairing chose a `.musx` per filename stem by directory-walk order and picked, for
those five, a candidate that failed the same-music filter. In all five the delta is constant
(70, 71, 71, 71, 69), and the blocks it selects hold the right names in the right order —
`1st/2nd/3rd Violin`, `Oboe / English Horn / Clarinet in B♭` — which arithmetic alone would not give.

The second was "across documents the delta ranges 63–87." That was computed across two different id
spaces. The `.mus` id and the `.musx` `textBlock` cmper agree for only 25 of 83 named staves: a
re-saved `.musx` renumbers its text blocks, so it says `fullName` 2 where the `.mus` says 93.

**What remains is one unknown, not a missing record**: the per-document base. One anchor per document
would resolve every name in it. Also confirmed on the way: the `.musx`'s `textID` *is* the `.mus`
stream-3 block number, so the containers agree on block numbering even where they disagree on ids.

**This is the second gap in two days that turned out to be a harness artefact**, after the staff
layout order (tag 159) the same day. Both were recorded as "the corpus cannot distinguish this", and
in both cases the corpus could — the code that looked was dropping the evidence. The count of
documents able to test the relation is now itself pinned, so the same silence cannot recur unnoticed.

The gap is still open: a `.mus` still exports positional part names. What changed is that the reason
written down for it is no longer false.

## 2026-07-30 — FIXED: a breve and a dotted whole are note values

`duration_from_edu` refused any duration over 4096 EDU, which cost two corpus documents. Two
distinct defects hid behind one symptom.

**The range check tested the total, not the base.** A dotted whole is 6144 EDU, and it was rejected
for being "larger than a whole note" — but *every* dotted note exceeds its own base, so the limit was
never the right thing to test the total against. The check now bounds the base value.

**A breve was not in the model.** 8192 EDU, two whole notes, and ordinary notation in early music —
the corpus document that needed it is a Renaissance motet. `NoteValue` gained it, and the MusicXML
exporter with it: its note-type table is keyed by the denominator of the written value as a fraction
of a whole note, which quietly assumes every note value is a whole note or shorter. A breve is 2/1,
the one exception, so it is handled explicitly rather than by extending the table.

Nothing longer is added. A longa would be next and no corpus document carries one, so there is
nothing to check a guess at it against — the same rule that keeps `final` barlines unread.

**Effect**: 129 → 131 of 139 DCL documents build, 66,847 → 68,530 pitches, and the `.mus` export
audit rises 222 → 224 with every invariant unchanged. The DCL entry-pool sweep now reads all 139
pools rather than 137.

**Worth noting about the pin that caught it.** `EXPECTED_DURATION_FAILURES` was set to 2 with the
docstring "pinned here so that fixing it shows up as this number falling to 0". It did exactly that.
A known gap recorded as a number, rather than as a comment, is what makes closing it visible.

## 2026-08-04 — DECIDED: the hex-viewer half of the desktop frontend ships as an HTML report, not a GUI

The 2026-07-20 entry above scoped a **desktop application** with a hex viewer and a notation
renderer. The hex viewer half is now built, and it is not a desktop application: `finale-parser
inspect --report` writes one self-contained HTML file (`src/finale_file_parser/report/`) showing the
stage ladder, the score and document summaries, every decoded record, and the raw bytes. Full design:
`docs/superpowers/specs/2026-08-04-diagnostic-frontend-design.md`.

**Why an HTML report over a GUI, now that the choice is real rather than deferred:**

- **No GUI or web dependency.** At the time, the library depended on `defusedxml` alone; a GUI
  toolkit or web framework would have been a dependency taken on for one read-only viewer. Verovio
  later became the second runtime dependency for notation engraving, without changing this choice of
  HTML over a GUI.
- **Works offline.** No server, no port, nothing to run beside opening a file.
- **Archivable beside the converted output.** One file, the same way `score.musicxml` is one file —
  it can sit next to a conversion in the same archive rather than needing an application installed to
  reopen it.
- **Crosses a legal boundary a `.mus`/`.musx` file cannot.** A user who cannot legally send this
  project their score — it may be copyrighted, or under a license that forbids redistribution — can
  still send the report: it is generated *from* the file, not the file itself, and is useful for
  diagnosing a parser failure without transmitting the protected work.

Consequence: the 2026-07-20 entry's "must not take a GUI dependency" constraint is satisfied by
construction, not by discipline — there is no GUI toolkit anywhere in the dependency graph. This
initially left notation rendering open; the 2026-08-15 Verovio decision below resolved it inside the
same report.

## Mirror direction is not inferred

**Decided 2026-08-10.** A Finale mirror stores one entry span, two `frameSpec`
records naming it, and two `gfhold` records naming those frames. Nothing marks
either placement as the original and the other as the copy.

`locate_entries` therefore returns the placements as **peers**, in frame-walk
order, and the order carries no meaning. Direction could only be inferred — from
the lower frame `cmper`, or from `gfhold` order — and neither is evidence.

This costs nothing: a mirrored passage stays identifiable as an entry whose
location tuple holds more than one member, so "is this staff independent music
or a duplicate?" remains answerable without inventing an answer to "which came
first?".

**Reopen if** a field carrying mirror direction or a per-mirror transposition is
identified, at which point the offset in `UNTRANSLATED` closes too.

## A record's own text is evidence, and its own tier

**Decided 2026-08-14.** The tag catalogue kept three tiers apart because
conflating them is how a lead becomes a fact: `decoded` (payload read and
checked against a paired `.musx`), `documented` (the vendor named it), and
`matched` (its key sequence matches a named record's, which establishes shape
and not meaning).

None of the three fits a record whose payload contains the words
`D.C. al Fine`. That is not a pairing, not a vendor document, and not an
inference — the file says what the record is for, and the only judgement is
reading it. Such names now carry a fourth tier, `labelled`, quoting the text
found and counting the documents carrying it.

Two reasons it earns its own tier rather than being folded into an existing one:

- **It is stronger than `matched` and differently sourced from `documented`.**
  Recording `^FN` as "matched" would understate it; as "documented" would claim
  a source that does not exist.
- **It establishes what a record *holds*, and nothing about where its fields
  sit.** A `labelled` name must never imply a payload layout. `layout_for` still
  returns nothing for all seven, and a test pins that.

This matters most for the 2001–2005 era, which has **no paired `.musx` anywhere
in this corpus**, so `decoded` is unreachable there by the method that earned it
elsewhere. Reading payload text is the strongest evidence that cohort can offer.

Consequence: the `UNTRANSLATED` entry claiming the corpus held no evidence for
the text-repeat tag was wrong, and is corrected. It had reasoned only about
paired documents and never searched the DCL cohort, where 1,253 `^RT` records
across 137 documents carry the text verbatim. The earlier 411/38 measurement
was another incomplete cohort: a lowercase-only glob omitted 101 `.MUS` files.

**Reopen if** a `labelled` name is ever contradicted by a decoded payload, which
would mean the words in a record describe something other than the record.

## 2026-08-15 — DECIDED: Verovio engraves the score, as a runtime dependency

**Owner's decision**, chosen over a hand-drawn SVG renderer that would have taken no dependency.

The report's Music tab showed a tree of parts, measures and events. That is what the parser
*found*; it is not the form in which "did this file read correctly?" is actually asked. A wrong
clef, a passage a step sharp, or a rhythm that does not add up is obvious at a glance on a staff
and invisible in a list of pitch names. The tab now shows the engraved score above the tree.

**Why not hand-drawn.** This project draws its own staves in `scripts/format_spec/`, so the
precedent existed and the option was real. It was rejected because notation that is subtly wrong
because the *renderer* is wrong is worse than no notation at all: a reader cannot tell which half
to distrust, and the entire value of this pane is trusting what it shows.

**What it costs.**

- **A runtime dependency, where there was one.** `dependencies` was `defusedxml` alone; it is now
  `defusedxml` and `verovio`.
- **LGPL-3.0, where this project is MIT.** Verovio is imported as a separate package and never
  vendored or statically linked, so this project's own licence is unchanged and MIT code may depend
  on an LGPL library. A redistributor bundling both into one artifact does take on the LGPL's
  obligations for the Verovio part. `THIRD-PARTY-NOTICES.md` states this.
- **Report size.** A page is 208 KB of SVG at the corpus median and the largest scores reach 5.2 MB
  across twenty pages. Pages are taken in order up to `MAX_NOTATION_BYTES` (2 MB) and the number
  omitted is stated on the page, following the same measured-and-reported pattern as the JSON
  budget.
- **Time.** Median 0.04 s per document, worst observed 0.18 s: about 35 seconds across the corpus
  sweep, which the split gate absorbs.

**What it does not cost.** The report is still one self-contained file that works offline. Verovio
draws every glyph as a path and references no external font, image or stylesheet — verified on the
corpus, not assumed.

**The library still parses without it in every sense that matters**: engraving is a ladder stage
run with `halt=False`, so a document Verovio cannot lay out still produces a report with its music
tree, its records and its ladder, and the stage says what happened.

**Reopen if** the dependency becomes a problem for a consumer who wants the parser without it, at
which point the answer is an optional extra and a fallback message rather than a different engraver.

## 2026-08-17 — DECIDED: two functions form the stable reader facade

**Context.** Both containers already converge on `EnigmaDocument`, but an application caller had
to know the format-specific composition: `score_xml` then `parse_enigma` for `.musx`, or
`read_mus_document` for `.mus`, followed by `build_score`. The CLI duplicated that dispatch and
chose from the filename suffix even though version detection already identifies the family from
the file contents.

**Decision.** `read_document(path)` detects the family from content and returns the shared
`EnigmaDocument`; `read_score(path)` adds `build_score` and returns the IR. These two package-root
functions are the small application-facing facade. They preserve existing exceptions rather than
wrapping them, and the lower-level readers remain public for format research and record-level use.

**Consequence.** Ordinary callers and the CLI no longer know which parser branch a file needs, and
a valid file with a misleading suffix still reaches the correct reader. The facade deliberately
does not include export or file-writing policy: `to_musicxml` remains a separate edge operation.

## 2026-10-08 — DECIDED: preserve individual ties and explicit performance notation in the IR

**Context.** The approved Scars of Time investigation found that an event-wide tie
flag was copied to every chord pitch, while upper mordents and explicit printed
metronome rates were omitted. All ordinary source attacks matched the performance
MIDI; replacing notated durations with expressive MIDI note lengths would discard
the source notation.

**Decision.** Extend the existing canonical IR with `NoteTies`, `Ornament` and
`Tempo`. `Event.note_ties` is aligned with pitches and takes precedence during
export. Retain `tie_start`/`tie_end` as aggregate summaries for compatibility, and
retain their previous export behavior for authored events without individual
flags. Preserve unmatched source ties. Ornaments stay attached to events rather
than becoming additional written notes. `Expression.tempo` structures an explicit
printed beat/rate while `Expression.text` retains the full source wording.

**Consequence.** Both containers keep using one reader-to-IR-to-export path.
Support the upper mordent at legacy glyph 109 with cross-font chart evidence and
the local PDF/MIDI comparison; leave unknown glyphs unmapped. Infer no tempo from
an untyped expression `value` or an undecoded legacy `playType`. Export explicit
metronome notation and a correctly scaled quarter-note playback rate, leaving
expressive performance timing to the consuming application. Existing callers
using event-wide ties or plain expression text retain their behavior.

## 2026-10-08 — DECIDED: fermatas are event notation with no inferred hold duration

**Context.** The user requested fermata export after the local investigation
confirmed an assigned above-note fermata in a trailing 20-byte `.mus` articulation
group. Its absence involved both losing that group and having no IR/export support.

**Decision.** Extend the canonical IR with an immutable `Fermata` carrying the
normal symbol's orientation, and append `Event.fermatas` without changing existing
positional fields. Resolve the two legacy glyphs documented consistently across
Maestro, Engraver and Broadway Copyist, using only assigned score definitions.
Export the symbol once per event in MusicXML note notations, including rests.

**Consequence.** The same resolver serves normalized `.mus` and `.musx` documents.
Packed `.mus` assignments receive unique identities and retain source-row metadata
for inspection links. Written and metric durations stay unchanged. Finale's Human
Playback stretching is not a fixed fermata duration and is not reconstructed from
the MIDI. Additional shapes and automatic alternate-glyph placement require their
own format evidence.

## 2026-10-10 — DECIDED: preserve source grace slashes after resolving beaming

**Context.** The local Scars of Time PDF has twenty slashed single graces, while
the previous reader/IR/export wrote bare `<grace/>`. MuseScore imports those
single eighths as long appoggiaturas. The user approved tracing and preserving
Finale's global and individual slash settings with "proceed". Published PDK
definitions and read-only inspection of released RGP Lua 0.79 establish the
legacy option and flag locations; the evidence is in `docs/ARCHITECTURE.md`.

**Decision.** Append optional `Event.grace_slash` to the existing canonical IR.
Normalize the global setting to the same `graceNoteOptions` field for both
containers, and preserve the individual extended flag. Resolve the displayed
slash after grouping grace beams separately from ordinary beams: only flagged,
unbeamed graces can be slashed, enabled globally or individually. Export a known
style using MusicXML `slash="yes|no"`; leave unknown style unspecified.

**Consequence.** Source-driven regeneration restores all twenty slashes and
keeps the four beamed graces unslashed, without score-specific rules or altered
metric durations. Authored synthetic regressions cover both legacy byte orders,
XML input, global/individual settings, malformed layouts and beam separation.
The original local score remains an investigation input, not a cleared fixture.

## 2026-10-10 — OPEN: grace playback duration and Human Playback interchange

The preference map also identifies the legacy grace playback duration; Scars
stores 128 EDU. It is not propagated through the IR or exported in this change.
The inspected MuseScore importer reads steal-time attributes for placement but
does not retain their percentages for duration. Restoring the source slashes
changes its grace classification but does not recreate Finale's measured
77–80 ms performance automatically. A policy for optional performance timing,
including player compatibility and Human Playback behavior, remains open.

## 2026-10-11 — DECIDED: exact expression attachment in the canonical IR

Append default-zero `Expression.offset`, a signed Fraction in whole-note units.
It preserves `measExprAssign.horzEduOff` (4096 EDU per whole note) independently
from EVPU drawing adjustments. Negative and measure-end attachments remain valid;
malformed or out-of-signed-32-bit values raise a clear input error. Export directions
at cursor zero with an exact MusicXML offset, including sound, without moving notes.
Include the offset denominator in divisions and preserve it through score-wide and
connected-staff placement. Duplicate score/staff assignments must also agree in time.
This fixes ActRaiser's bar-8 mf at 1536 EDU without changing its velocity policy.

## 2026-10-11 — DECIDED: timed clefs on the existing Measure

Append `Measure.clef_changes`, containing immutable `ClefChange(offset, sign,
line, visible)` objects. Offsets use the IR's whole-note units. Source change
lists include their initial clef at zero; literal measure-start clefs continue
to use the existing fields. Carry the final effective clef into following bars
and use the event-time clef for arpeggio geometry. Pitches remain key-relative
and are unaffected. MusicXML forwards/backup place attributes at exact times
before serializing voices, including changes during sustained notes; projected
staves retain every timed attribute with the correct staff number.

## 2026-10-11 — DECIDED: preserve abbreviated staff names in Part

Append default-empty `Part.abbreviation` alongside the existing full `name`.
The name resolver already recovers both strings, but the IR previously dropped
the abbreviated staff label before export. Group labels remain on `PartGroup`;
recovering a group name does not rename each staff or merge its instrument.
MusicXML emits a staff's abbreviation with its score-part, or the group label
when an existing connected-arpeggio projection produces a combined part.
Appending the field preserves existing positional Part construction.

## 2026-10-11 — DECIDED: source octave spans preserve written pitches

Append `Part.octave_shifts` containing signed one/two-octave displacements with
exact inclusive source endpoints. Keep canonical Event pitches written. Export
performed pitch octaves once alongside MusicXML octave-shift directions; do not
rewrite the IR or multiply this displacement by staff transposition. Source
point spans cover their attack and graces. Translate inclusive attack endpoints
to a stop after that attack for standard XML interval semantics. Reject ambiguous
overlapping source octave spans until their combined meaning is evidenced; the
current 50 active corpus records do not overlap. Preserve stale records in the
raw document and its existing diagnostic rather than extending the score.

## 2026-10-11 — DECIDED: tempo equivalents and ranges retain their printed meaning

Append optional `Tempo.upper_per_minute` and `Tempo.equivalents`. Consistent
explicit equivalents export both metronome units and one quarter-note rate.
Ranges export their two printed bounds; absent separately typed source playback
data, they do not select a single sound tempo. Resolve legacy beat and dot glyphs
from active font runs before parsing. Keep expression text intact and require
actual assignment evidence before promoting page/header text to timed notation.

## 2026-10-12 — DECIDED: retain repeat rules independently from written barlines

Append `Measure.repeat_playback` for explicit destination, trigger, pass count
and reset policy. Keep existing written repeat/ending fields. A bounded pure
traversal over canonical Score retains encounter counts per backward repeat;
an outer jump resets only counters with an explicit source reset flag. It never
uses a MIDI-derived route or expands the written score into performed notes.
Ordinary MusicXML barlines retain their standard after-jump flag outside endings;
arbitrary Finale actions and playback-control stops require separate source and
importer evidence before additional playback instructions are emitted.

## 2026-10-12 — DECIDED: typed document playback preferences

Append `Score.playback` with exact beat/rate, swing amount, base velocity and
playback-control range/mode/pass fields. These are independent of printed marks
and do not alter notes or replace the canonical score. Export an established
default tempo as sound-only when there is no explicit initial metronome; retain
control range/mode rather than blindly cutting a whole-score export to the UI
selection. Unknown ignore/reset/expression-mode toggles remain an evidence gate.
Use the documented high-word-first conversion for split EDU controls.

## 2026-10-12 — DECIDED: printed expressions and typed playback are independent

Append `Expression.playback` with kind, signed value, optional beat unit and pass
condition. Preserve the old untyped value for compatibility but never export it
as velocity. Export scalar tempo/key-velocity only where source type and valid
absolute meaning are established; keep print tempo unchanged. Explicit "none"
does not imply a printed rate is active. Nonabsolute/zero source controls stay
in canonical data and structured diagnostics rather than failing the whole
score or changing their type to match a performance MIDI.

## 2026-10-12 — DECIDED: preserve standard source swing despite importer limits

Represent typed swing amounts and their actual metric subdivisions without
rewriting written rhythms. Export established zero/standard-triplet values with
MusicXML straight or first=2/second=1, retaining scope and pass conditions.
Intermediate source amounts stay an evidence gate rather than using a fitted
MIDI ratio. Keep standards-compliant export despite the verified MuseScore 4.7.5
ratio conversion bug; record the renderer limitation and native control result
in review evidence instead of encoding a false ratio for every other importer.

## 2026-10-12 — DECIDED: navigation text does not define source playback

Append `Measure.navigation` with placed text/sign, font-established kind,
mark identity, visibility and typed source repeat rule. Preserve optional,
hidden and malformed-destination controls without assigning them a guessed
D.C./D.S. action from their words. Keep the words-only helper for compatibility.
Traverse canonical rules with independent encounters and completed ending state;
advance 1,3/2,4 lists through navigation jumps without replaying ordinary consumed
1/2 endings. Retain invalid source targets as diagnostics and bounded traversal
errors, independently of whether their notation can still be exported.

Use standard MusicXML signs, sound destinations and pass conditions. Keep sound
measure-level for al Fine/Coda instructions so MuseScore can import the complete
printed instruction; its embedded-sound classifier discards that qualifier.
Document other importer policy limits rather than changing source ending labels
or synthesizing duplicated notation to reproduce a performance route.

## 2026-10-12 — DECIDED: silent source events retain independent notation

Append Event.playback/visible with backward-compatible true defaults and expose
the same state on typed Entry. Decode source noPlayback/ignore independently;
keep metric time, pitches, ties and span anchors. Export disabled pitched events
as standard full-size silent cues, retaining visual ties while omitting prohibited
sounding ties. Preserve hidden sounding notes as sounding, and silent visible
notes as visible. A standard cue-size default of100 complements type size=full
so MuseScore's importer retains the source's normal note size. This follows
source flags and MusicXML semantics; MIDI does not decide which notes to silence.

## 2026-10-12 — DECIDED: articulation characters and shapes are separate

Normalize fontMain/sizeMain and explicit mainIsShape/mainShape for evidenced
48/60-byte numeric definitions. Combine modern Unicode words rather than assuming
the first word is padding. Resolve font identity through the score registry.
Reject shape definitions in all character-based semantic resolvers, including
normalized MUSX, rather than interpreting a shape ID or stale character as a
fermata/accent. Unsupported layouts remain unguessed; new extended glyph mappings
must establish their font context before introducing visible notation.
# 2026-10-12: preserve the principal note of a chord ornament

Append `Ornament.pitch_index` to the canonical IR. Above-chord trills select the
upper written note following Finale's documented Human Playback semantics, and
their auxiliary interval is derived from that note's key. Export once on the
corresponding MusicXML note. Preserve written chord structure and durations.
MuseScore4.7.5 attaches imported ornaments to the whole chord and can trill all
its pitches; report that renderer limitation instead of changing the score to
match one consumer's playback. Human Playback's ornament speed/acceleration is
also a performance realization, not a source notation correction.

# 2026-10-12: retain inverted marcato in the existing articulation vocabulary

Add `strong-accent-down` to the existing string articulation representation;
it means inverted marcato and exports to `strong-accent type="down"`. This keeps
the established component expansion for combined marks and avoids discarding
their orientation. Unknown-font and blank-character definitions are excluded.

# 2026-10-12: keep auxiliary accidentals independent of the main pitch

Append `Ornament.auxiliary_alteration` as an optional explicit alteration of the
natural auxiliary. Preserve both that printed sign and the derived interval;
an explicit natural is different from absence. Resolve only unique same-entry,
music-font small signs positioned above an ornament. Export a standard ornament
accidental-mark without changing the written pitch or generating MIDI notes.

# 2026-10-12: normalize Finale's tremolo display construction into a musical pair

Represent two-note tremolos as `Part.tremolos` with exact event endpoints and
stroke count. Recover only hidden two-note stretched tuplets corroborated by
detached beam extensions or half-notehead overrides. Replace their artificial
short written values with the true tremolo values; keep the exact sounded time.
Export standard start/stop ornaments and their required time modification.
Source ornament/tremolo performance attacks are not inserted into the written
score, and Human Playback's cadence is not encoded as a fabricated tempo curve.

# 2026-10-12: resolve individual-note spans through source IDs

Keep source note IDs in decoded `Note` data, then resolve them to canonical
`NoteEndpoint(event,pitch_index)` values. Add `Part.glissandi` using those exact
attachments and source appearance/geometry. Keep silent or hidden pitched
anchors and do not synthesize a glissando's MIDI realization as written notes.
Source IDs are not array indices; unresolved or duplicate matches are errors.
Part-local spans support cross-voice attachments; cross-staff glissandi currently
raise a clear format limitation instead of being silently dropped.

# 2026-10-12: use explicit source routing to share an exported instrument

Append instrument identity/play/solo to Voice and shared identity to Part.
Normalize source staffPlayData, keeping its routing IDs distinct from MIDI
programs/channels and its velocity-control fields distinct from key velocity.
Adjacent staves with one explicit identity export as one multi-staff MusicXML
instrument. This permits cross-staff pedal controls to act on the same piano;
staff names or a brace alone are insufficient evidence. Keep disabled/solo
notation intact and suppress only its sounding attacks.

# 2026-10-12: extend pitch spans across staves and recognize drawn arpeggios

Allow NoteEndpoint to name another staff-part. Export explicit glissando
connections in one staff bundle with globally paired numbers, retaining source
voice instrument identities independently. Same-chord type25 wavy drawings
before the noteheads are arpeggios when distinct pitch endpoints establish their
extent, corroborated by Game Over/Swimming source PDFs. Keep exact pitch coverage
on Arpeggio; the drawing's endpoint order does not establish roll direction.
This resolves the cross-staff limitation recorded in the initial F18 decision.

# 2026-10-12: preserve explicit pedal commands separately from automatic sustain

Add timed symbol/line `Measure.pedals` to canonical IR. Resolve explicit
music-font signs at exact entry offsets and export standard pedal directions
plus damper-pedal sound instructions. A same-offset release/start is a change.
Shared source routing supplies instrument scope across staves. Automatic
Human Playback sustain does not authorize manufacturing printed pedal signs;
MuseScore's missing repeated MIDI pedal controls do not authorize score unrolling.

# 2026-10-12: retain explicit arpeggio arrows through staff projection

Append optional up/down direction to Arpeggio, with None preserving the plain
sign and its default upward roll. Recognize Corridors' separately drawn
Maestro down triangle only with an unambiguous positioned roll assignment;
the glyph alone is not a roll. Preserve direction when connecting staves and
export the standard arpeggiate direction attribute. Different native/reference
roll speeds remain performance realizations, without inserted notes or tempo
changes derived from MIDI.

# 2026-10-12: distinguish parenthetical noteheads from unresolved glyph drawings

Retain positioned parentheses on canonical Event, with an optional established
pitch index. Compact pairs on single notes use standard notehead parentheses.
Chord-note and wide-span placements retain their glyphs/adjustments and a source
diagnostic until Finale automatic drawing layout can resolve their attachment.
Do not parenthesize every pitch, suppress optional notes, or fabricate playback
from MIDI. Standard other-notation preserves the remaining symbols; MuseScore's
importer treats them as articulations and ignores coordinates, so those seven
placements require manual review. This is an explicit F24 format/import limit.

# 2026-10-12: project explicitly assigned first-page metronomes as display headers

Decode page-text assignments in the normalized document, retaining their page
IDs and coordinates. Promote visible first-page metronomes to score-wide
Expression with page=1 above the first musical measure, using existing tempo
syntax and font evidence. Such text has no expression playback; document
preferences remain independent. Unassigned labels, repeated/later-page text
and ambiguous font letters do not establish tempo or rhythmic placement.

# 2026-10-12: retain assigned line drawings without inferring performance semantics

Append `Part.lines` using canonical `LineSpan` with metric endpoints separate
from drawing geometry. Export ordinary drawings as standard bracket directions;
preserve opaque custom endpoint references and diagnose unsupported glyph,
attachment and label-placement cases. Neither a custom pedal-like drawing nor
a repeated wavy glyph establishes a controller or ornament playback instruction.
Source geometry survives even when MuseScore ignores its positioning or maps
the wavy style to a trill line. No notes or durations are manufactured to make
zero-time drawings visible in one importer.

# 2026-10-12: keep articulation playback controls separate from written notation

Append explicit assigned top/bottom attack, duration and velocity adjustments
to canonical Event, with their source units and references. Symbol visibility
does not disable those controls. Honor noPrint in printed symbol resolvers,
and diagnose nonprinting music-font characters without guessing a visible mark.
Do not apply manual articulation data as if it were Finale Human Playback's
rendered performance. Keep controls in IR and report the MusicXML realization
limit rather than changing written note lengths or synthesizing MIDI velocities.

# 2026-10-12: attach initial display-only tempo to its independent source default

Put the document's default playback rate in the same first-beat MusicXML
direction as a metronome that has no tempo playback. This keeps printed and
performed rates distinct through MuseScore import. Do not override active
source expressions with a MIDI-matching document default, and do not reset
later display-only marks to the initial tempo.

# 2026-10-12: distinguish corpus pipeline coverage from performance equivalence

Provide an opt-in external audit through make, with input hashes, exact pairing,
written-note projection, explicit source-route failures and raw MIDI residuals.
Keep contextual ornament/unison labels separate from candidate reattacks and
unexplained events. Never fit routes, globally collapse unisons, compare human
note-off durations as notation or synthesize controls to produce a perfect
match. Record native process status alongside fresh artifacts; use individual
MuseScore processes after the demonstrated batch teardown failure.

# 2026-10-12: OPEN — remaining legacy playback routing and reference provenance

The complete user-corpus audit records initial MIDI programs/banks and CC7/10,
but the legacy field joins/function flags for those controls are not independently
established. Numeric136 is an executable-shape palette and149 is fretInst;
neither supplies a program merely because a small payload word matches a MIDI
number. Numeric21412-byte records and channelPlayData124 remain research leads.
Released InstrumentDef getters prove virtual-channel/perc-map fields in their
API structure, not an unsupported bank/program interpretation of another word.
Do not emit MIDI-derived programs, pan, volume or per-note velocities as source.

Active 1UP225/Treasure100/Uncover100 tempo expressions disagree with the paired
MIDIs100/120/120 and agree differently with source defaults. Literal navigation
sentinels/counters in five expanded cases also need policy/provenance evidence.
These discrepancies and the documented graphical interchange limits remain
explicit review items; a schema/import pass does not close them.

