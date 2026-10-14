"""Unit tests for the `.mus` -> `EnigmaDocument` adapter.

The three pool readers are stubbed, so these cover the translation itself: which
records are emitted, and the two places where *omitting* a field is the correct
translation rather than writing a zero.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma import mus_details
from finale_file_parser.enigma import mus_document as adapter
from finale_file_parser.enigma.articulations import articulations_by_entry
from finale_file_parser.enigma.clef import ClefSign, clef_definitions
from finale_file_parser.enigma.document import Record
from finale_file_parser.enigma.groups import staff_order
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_details import (
    TAG_ARTIC_ASSIGN,
    TAG_LYRIC_VERSE,
    TAG_SMART_SHAPE_ENTRY_MARK,
    TAG_TUPLET_DEF,
    MusDetailRecord,
)
from finale_file_parser.enigma.mus_document import read_mus_document
from finale_file_parser.enigma.mus_others import (
    OPTIONS_CMPER,
    TAG_ARTIC_DEF,
    TAG_CLEF_OPTIONS,
    TAG_STAFF_SPEC,
    TAG_TEXT_BLOCK,
    MusOther,
)
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.pitch import read_transposition
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.enigma.tuplet import tuplets_by_entry
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Arpeggio, Fermata

PATH = "unused.mus"
"""Every reader is stubbed, so no file is ever opened."""

FRAME_SPEC = 146
MEAS_SPEC = 176
GFHOLD = 1044


def meas_spec_payload(width: int, key: int, beats: int, divbeat: int) -> bytes:
    return b"".join(v.to_bytes(2, "little") for v in (width, key, beats, divbeat))


def gfhold_payload(clef: int, frame1: int, frame2: int = 0) -> bytes:
    return (
        clef.to_bytes(2, "little")
        + bytes(4)
        + frame1.to_bytes(2, "little")
        + frame2.to_bytes(2, "little")
        + bytes(10)
    )


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Install the three pool readers' returns, and the banner year, for one test."""

    def install(
        others: tuple[MusOther, ...] = (),
        details: tuple[MusDetailRecord, ...] = (),
        entries: tuple[Record, ...] = (),
        texts: tuple[Record, ...] = (),
        year: int | None = 2011,
        platform: str | None = "WIN",
    ) -> None:
        monkeypatch.setattr(adapter, "read_mus_others", lambda _p: others)
        monkeypatch.setattr(adapter, "read_mus_details", lambda _p: details)
        monkeypatch.setattr(adapter, "read_mus_entry_records", lambda _p: entries)
        monkeypatch.setattr(adapter, "_texts_records", lambda _p: list(texts))
        monkeypatch.setattr(adapter, "_banner_year", lambda _p: year)
        # Stubbed for the same reason as the year: it reads the banner off disk,
        # and these tests never open a file. It fixes the encoding a
        # `textExprDef` description is decoded with.
        monkeypatch.setattr(adapter, "_banner_platform", lambda _p: platform)

    return install


def clef_entry(stride: int, adjust: int, char: int, ydisp: int, shape: int = 0) -> bytes:
    """One clef-table entry in the layout the given stride implies."""
    offsets = adapter._CLEF_FIELD_OFFSETS[stride]
    entry = bytearray(stride)
    for name, value in (
        ("adjust", adjust),
        ("clefChar", char),
        ("clefYDisp", ydisp),
        ("shapeID", shape),
    ):
        at = offsets[name]
        entry[at : at + 2] = value.to_bytes(2, "little", signed=value < 0)
    return bytes(entry)


def test_translates_a_frame_spec(pools: Callable[..., None]) -> None:
    """A frame's own incidence is twelve bytes -- the pair, then four spare.
    Every one of the 10,465 corpus records is twelve or twenty-four."""
    pools(others=(MusOther(FRAME_SPEC, 3, 0, entry_pair(9, 10)),))
    record = read_mus_document(PATH).others.get("frameSpec", 3)
    assert record is not None
    assert (record.fields["startEntry"], record.fields["endEntry"]) == ("9", "10")


def test_translates_a_measure_s_key_and_beats(pools: Callable[..., None]) -> None:
    pools(others=(MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 253, 2, 1024)),))
    record = read_mus_document(PATH).others.get("measSpec", 1)
    assert record is not None
    key_sig = record.fields["keySig"]
    assert isinstance(key_sig, Record) and key_sig.fields["key"] == "253"
    assert (record.fields["beats"], record.fields["divbeat"]) == ("2", "1024")


def test_a_zero_key_becomes_no_key_signature_at_all(pools: Callable[..., None]) -> None:
    """`.mus` stores 0 where a `.musx` omits the element, and an absent key means
    "inherit the previous measure's". Writing `key="0"` instead would silently
    turn every inheriting measure into C major."""
    pools(others=(MusOther(MEAS_SPEC, 2, 0, meas_spec_payload(305, 0, 2, 1024)),))
    record = read_mus_document(PATH).others.get("measSpec", 2)
    assert record is not None
    assert "keySig" not in record.fields


def test_marks_a_part_variant_and_leaves_the_score_record_unmarked(
    pools: Callable[..., None],
) -> None:
    """Downstream modules select score records by the *absence* of `part`."""
    pools(
        others=(
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 253, 2, 1024)),
            MusOther(MEAS_SPEC, 1, 1, meas_spec_payload(600, 253, 2, 1024)),
        )
    )
    document = read_mus_document(PATH)
    score = document.others.get("measSpec", 1)
    variant = document.others.get("measSpec", 1, part=1)
    assert score is not None and "part" not in score.attrs
    assert variant is not None and variant.attrs["part"] == "1"


def test_translates_a_gfhold_with_two_layers(pools: Callable[..., None]) -> None:
    pools(details=(MusDetailRecord(GFHOLD, 2, 7, 0, gfhold_payload(3, 32, 33)),))
    record = read_mus_document(PATH).details.get("gfhold", 2, 7)
    assert record is not None
    assert (record.attrs["cmper1"], record.attrs["cmper2"]) == ("2", "7")
    assert (record.fields["clefID"], record.fields["frame1"]) == ("3", "32")
    assert record.fields["frame2"] == "33"


def test_an_empty_layer_slot_is_omitted(pools: Callable[..., None]) -> None:
    """A frame of 0 means the layer holds nothing. Emitting `frame2="0"` would
    send `locate_entries` looking for a frameSpec numbered 0."""
    pools(details=(MusDetailRecord(GFHOLD, 1, 1, 0, gfhold_payload(0, 32, 0)),))
    record = read_mus_document(PATH).details.get("gfhold", 1, 1)
    assert record is not None
    assert "frame2" not in record.fields


@pytest.mark.parametrize("layer", [3, 4])
def test_numeric_gfhold_preserves_higher_layers(pools: Callable[..., None], layer: int) -> None:
    payload = bytearray(gfhold_payload(3, 0))
    at = 6 + (layer - 1) * 2
    payload[at : at + 2] = (71).to_bytes(2, "little")
    pools(details=(MusDetailRecord(GFHOLD, 2, 7, 0, bytes(payload)),))
    record = read_mus_document(PATH).details.get("gfhold", 2, 7)
    assert record is not None
    assert record.fields == {"clefID": "3", f"frame{layer}": "71"}


@pytest.mark.parametrize("size", [0, 4, 6, 9, 10, 12, 13])
def test_numeric_gfhold_rejects_truncated_frame_arrays(
    pools: Callable[..., None], size: int
) -> None:
    pools(details=(MusDetailRecord(GFHOLD, 1, 1, 0, bytes(size)),))
    with pytest.raises(CorruptScoreError, match="truncated four-layer frame array"):
        read_mus_document(PATH)


@pytest.mark.parametrize("layer", [3, 4])
def test_higher_layer_music_reaches_ir_and_musicxml(pools: Callable[..., None], layer: int) -> None:
    payload = bytearray(gfhold_payload(0, 0))
    at = 6 + (layer - 1) * 2
    payload[at : at + 2] = (71).to_bytes(2, "little")
    pools(
        others=(
            MusOther(FRAME_SPEC, 71, 0, entry_pair(501, 501)),
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 0, 1, 1024)),
        ),
        details=(MusDetailRecord(GFHOLD, 1, 1, 0, bytes(payload)),),
        entries=(
            Record(
                "entry",
                {"entnum": "501", "prev": "0", "next": "0"},
                "",
                {
                    "dura": "1024",
                    "numNotes": "1",
                    "note": Record("note", {}, "", {"harmLev": "0", "harmAlt": "0"}),
                },
            ),
        ),
    )
    score = build_score(read_mus_document(PATH))
    voice = score.parts[0].measures[0].voices[0]
    assert voice.number == layer
    assert len(voice.events) == 1
    root = DET.fromstring(to_musicxml(score))
    assert root.findtext("part/measure/note/voice") == str(layer)
    assert root.findtext("part/measure/note/pitch/step") == "C"


def test_passes_entry_records_through(pools: Callable[..., None]) -> None:
    entry = Record(tag="entry", attrs={"entnum": "9"}, text="", fields={"dura": "1024"})
    pools(entries=(entry,))
    assert read_mus_document(PATH).entries.get(9) is entry


def test_tagged_file_info_reaches_the_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """The numeric kinds in a `.mus` text stream name bibliographic fields.

    This catches dropping the sections or mapping any of 1, 2 and 3 to the
    wrong Enigma `fileInfo.type`. The unknown kind proves the adapter does not
    invent a meaning for a number the paired corpus has not established.
    """
    stream = (
        b"^fileInfo(1)Legacy title^end"
        b"^fileInfo(2)Jos\xe9 Composer^end"
        b"^fileInfo(3)Copyright notice^end"
        b"^fileInfo(9)Unknown metadata^end"
    )
    monkeypatch.setattr(adapter, "read_mus_others", lambda _p: ())
    monkeypatch.setattr(adapter, "read_mus_details", lambda _p: ())
    monkeypatch.setattr(adapter, "read_mus_entry_records", lambda _p: ())
    monkeypatch.setattr(adapter, "read_mus_streams", lambda _p: [b"", b"", b"", stream])
    monkeypatch.setattr(adapter, "_banner_year", lambda _p: 2011)
    monkeypatch.setattr(adapter, "_banner_platform", lambda _p: "WIN")

    score = build_score(read_mus_document(PATH))

    assert score.title == "Legacy title"
    assert score.composer == "Jos\N{LATIN SMALL LETTER E WITH ACUTE} Composer"
    assert score.metadata == {"copyright": "Copyright notice"}


def test_skips_record_types_it_cannot_translate(pools: Callable[..., None]) -> None:
    """An undecoded payload is left out, never guessed at."""
    # 140 is fretboardSymbol and 1043 fretboard: both identified by key
    # sequence only, so neither is translated.
    pools(
        others=(MusOther(140, 1, 0, bytes(84)),),
        details=(MusDetailRecord(1043, 1, 1, 0, bytes(40)),),
    )
    document = read_mus_document(PATH)
    assert document.others.records == ()
    assert document.details.records == ()


def test_skips_a_payload_too_short_for_its_fields(pools: Callable[..., None]) -> None:
    pools(
        others=(MusOther(FRAME_SPEC, 3, 0, b"\x09\x00"),),
    )
    document = read_mus_document(PATH)
    assert document.others.records == ()
    assert document.details.records == ()


@pytest.mark.parametrize(("year", "stride"), [(2011, 18), (2012, 20)])
def test_translates_the_clef_table_in_either_era_layout(
    pools: Callable[..., None], year: int, stride: int
) -> None:
    """2012 moved `clefYDisp` and `shapeID`; the banner year picks the layout."""
    payload = clef_entry(stride, -10, 38, -6) + clef_entry(stride, 2, 63, -2)
    pools(others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, payload),), year=year)
    table = clef_definitions(read_mus_document(PATH))
    assert len(table) == 2
    assert (table[0].clef_char, table[0].adjust, table[0].y_displacement) == (38, -10, -6)
    assert (table[1].clef_char, table[1].adjust, table[1].y_displacement) == (63, 2, -2)


def test_a_shape_clef_keeps_its_shape_id(pools: Callable[..., None]) -> None:
    pools(
        others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 0, 0, shape=50)),)
    )
    table = clef_definitions(read_mus_document(PATH))
    assert (table[0].shape_id, table[0].clef_char) == (50, None)
    assert table[0].sign is ClefSign.SHAPE


def test_a_zero_clef_char_becomes_an_absent_field(pools: Callable[..., None]) -> None:
    """Absent means "there is no character"; `clefChar="0"` would be a real
    character, and `Clef.sign` must report UNKNOWN rather than inventing one."""
    pools(others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 0, -6)),))
    table = clef_definitions(read_mus_document(PATH))
    assert table[0].clef_char is None
    assert table[0].sign is ClefSign.UNKNOWN


def test_skips_a_clef_table_that_is_not_a_whole_number_of_entries(
    pools: Callable[..., None],
) -> None:
    """A mis-strided table would yield plausible wrong clefs, so emit none."""
    pools(others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 38, -6)[:-3]),))
    assert clef_definitions(read_mus_document(PATH)) == {}


def test_skips_a_partial_clef_table_when_the_era_is_unknown(pools: Callable[..., None]) -> None:
    """Only complete eighteen-definition tables establish an unknown writer's layout."""
    pools(
        others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 38, -6)),),
        year=None,
    )
    assert clef_definitions(read_mus_document(PATH)) == {}


@pytest.mark.parametrize("stride", [18, 20])
@pytest.mark.parametrize("year", [None, 2006])
def test_complete_clef_table_survives_an_unrecognized_writer(
    pools: Callable[..., None], stride: int, year: int | None
) -> None:
    """Authored C4 on a bass staff tests the table-to-IR-to-XML path.

    The fixture is original test data under the repository's MIT license;
    no external score or binary table is copied.
    """
    defs = [clef_entry(stride, -10, 38, -6) for _ in range(18)]
    defs[3] = clef_entry(stride, 2, 63, -2)
    defs[16] = clef_entry(stride, -10, 0, 0, shape=9)
    pools(
        year=year,
        others=(
            MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, b"".join(defs)),
            MusOther(FRAME_SPEC, 1, 0, entry_pair(1, 1)),
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(200, 0, 1, 1024)),
            MusOther(MEAS_SPEC, 2, 0, meas_spec_payload(200, 0, 1, 1024)),
        ),
        details=(MusDetailRecord(GFHOLD, 1, 1, 0, gfhold_payload(3, 1)),),
        entries=(
            Record(
                "entry",
                {"entnum": "1", "prev": "0", "next": "0"},
                "",
                {
                    "dura": "1024",
                    "numNotes": "1",
                    "note": Record("note", {}, "", {"harmLev": "0", "harmAlt": "0"}),
                },
            ),
        ),
    )
    document = read_mus_document(PATH)
    table = clef_definitions(document)
    assert len(table) == 18
    assert table[3].sign is ClefSign.F
    assert table[3].adjust == 2
    assert table[16].shape_id == 9
    score = build_score(document)
    assert [(m.clef_sign, m.clef_line) for m in score.parts[0].measures] == [
        ("F", 4),
        (None, None),
    ]
    assert score.parts[0].measures[1].voices[0].events[0].is_measure_rest
    xml = DET.fromstring(to_musicxml(score))
    assert xml.findtext("part/measure/attributes/clef/sign") == "F"
    assert xml.findtext("part/measure/note/pitch/step") == "C"


def test_linked_part_clef_table_does_not_override_the_score(pools: Callable[..., None]) -> None:
    pools(
        others=(
            MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 1, clef_entry(18, 2, 63, -2)),
            MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 38, -6)),
        )
    )
    assert clef_definitions(read_mus_document(PATH))[0].sign is ClefSign.G


def test_clef_table_allocation_is_bounded(pools: Callable[..., None]) -> None:
    pools(others=(MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef_entry(18, -10, 38, -6) * 257),))
    with pytest.raises(CorruptScoreError, match="clef table exceeds"):
        read_mus_document(PATH)


def tuplet_payload(sym_num: int, sym_dur: int, ref_num: int, ref_dur: int) -> bytes:
    return b"".join(v.to_bytes(2, "little") for v in (sym_num, sym_dur, ref_num, ref_dur)) + bytes(
        22
    )


def test_translates_a_tuplet_and_keys_it_by_entry(pools: Callable[..., None]) -> None:
    """A detail hanging off an entry packs the 32-bit entnum into the two key
    fields, high word first."""
    pools(details=(MusDetailRecord(TAG_TUPLET_DEF, 1, 4660, 0, tuplet_payload(3, 512, 2, 512)),))
    record = mus_details.entry_key(MusDetailRecord(TAG_TUPLET_DEF, 1, 4660, 0, b""))
    assert record == 70196
    tuplets = tuplets_by_entry(read_mus_document(PATH))
    assert list(tuplets) == [70196]
    assert tuplets[70196][0].ratio == Fraction(2, 3)


def test_a_tuplet_ratio_is_not_inverted(pools: Callable[..., None]) -> None:
    """Every corpus tuplet is 3:2, so nothing in the data distinguishes
    `symbolicNum` from `refNum`. A 5:4 case would come out 4/5 if the pairs were
    swapped, and 5/4 if not."""
    pools(details=(MusDetailRecord(TAG_TUPLET_DEF, 0, 9, 0, tuplet_payload(5, 256, 4, 256)),))
    assert tuplets_by_entry(read_mus_document(PATH))[9][0].ratio == Fraction(4, 5)


def test_skips_a_tuplet_payload_too_short_for_its_fields(pools: Callable[..., None]) -> None:
    pools(details=(MusDetailRecord(TAG_TUPLET_DEF, 0, 9, 0, b"\x03\x00"),))
    assert tuplets_by_entry(read_mus_document(PATH)) == {}


def staff_spec_payload(transposition: int) -> bytes:
    payload = bytearray(84)
    payload[20:22] = transposition.to_bytes(2, "little")
    return bytes(payload)


@pytest.mark.parametrize(
    ("stored", "adjust"),
    [(0x0000, 0), (0x0101, 1), (0x0042, 2), (0x0F83, 3)],
)
def test_reads_the_transposition_key_alteration(
    pools: Callable[..., None], stored: int, adjust: int
) -> None:
    """The alteration is the low nibble; the upper bits are something else and
    are deliberately not interpreted."""
    pools(others=(MusOther(TAG_STAFF_SPEC, 1, 0, staff_spec_payload(stored)),))
    record = read_mus_document(PATH).others.get("staffSpec", 1)
    assert record is not None
    assert read_transposition(record).adjust == adjust


def test_a_negative_alteration_is_sign_and_magnitude(pools: Callable[..., None]) -> None:
    """Bit 3 is the sign, not a two's-complement sign: `0x9` reads as -1 rather
    than the -7 two's complement would give.

    **This convention is borrowed, and the vendored specification does not
    state it.** Both `eeppd.txt` and `etfspec.pdf` say only that the alteration
    occupies "the low order nybble (four bits) as a signed quantity" -- the same
    sentence in both, since the two documents carry the same TCD text -- and
    they name no encoding. Read as two's complement, which is how "signed" in
    four bits ordinarily reads, `0x9` would be -7.

    Sign-and-magnitude is this project's own finding, and it was measured
    somewhere else: on note alterations in the entry pool, where the corpus
    contradicts the two's-complement reading. See
    `tests/enigma/test_mus_entries.py::test_alteration_is_sign_and_magnitude`.

    Applying it *here*, to a `staffSpec` transposition, is an assumption. Every
    corpus value in this field is positive, so nothing in the corpus
    distinguishes the two encodings for `staffSpec` -- this test pins the
    behaviour the reader has, and names the evidence it does not have.
    """
    pools(others=(MusOther(TAG_STAFF_SPEC, 1, 0, staff_spec_payload(0x0009)),))
    record = read_mus_document(PATH).others.get("staffSpec", 1)
    assert record is not None
    assert read_transposition(record).adjust == -1


def test_the_transposition_interval_is_left_absent(pools: Callable[..., None]) -> None:
    """The `.mus` does not store it. Absent reads as 0, which is right for the
    written pitch and wrong for the concert pitch -- see UNTRANSLATED."""
    pools(others=(MusOther(TAG_STAFF_SPEC, 1, 0, staff_spec_payload(0x0042)),))
    record = read_mus_document(PATH).others.get("staffSpec", 1)
    assert record is not None
    assert read_transposition(record).interval == 0


def test_a_concert_staff_gets_no_transposition_record(pools: Callable[..., None]) -> None:
    pools(others=(MusOther(TAG_STAFF_SPEC, 1, 0, staff_spec_payload(0)),))
    record = read_mus_document(PATH).others.get("staffSpec", 1)
    assert record is not None
    assert "transposition" not in record.fields


@pytest.mark.parametrize("order", ["little", "big"])
def test_stored_default_clef_is_separate_from_the_transposition_clef(order: ByteOrder) -> None:
    """Original scalar fields; no source music or external file bytes."""
    payload = bytearray(84)
    payload[12:14] = (0x8003).to_bytes(2, order)
    fields = adapter._staff_spec(bytes(payload), order)
    assert fields["defaultClef"] == "3"
    payload[12:14] = (0x8000).to_bytes(2, order)
    assert "defaultClef" not in adapter._staff_spec(bytes(payload), order)


def test_literal_gfhold_zero_overrides_the_staff_default_and_can_switch_back(
    pools: Callable[..., None],
) -> None:
    from finale_file_parser.enigma.clef import clefs_by_measure, default_clefs

    payload = bytearray(staff_spec_payload(0))
    payload[12:14] = (0x0303).to_bytes(2, "little")
    pools(
        others=(MusOther(TAG_STAFF_SPEC, 2, 0, bytes(payload)),),
        details=tuple(
            MusDetailRecord(GFHOLD, 2, measure, 0, gfhold_payload(clef, 0))
            for measure, clef in ((1, 3), (2, 0), (3, 3))
        ),
    )
    doc = read_mus_document(PATH)
    assert default_clefs(doc) == {2: 3}
    assert clefs_by_measure(doc) == {(2, 1): 3, (2, 2): 0, (2, 3): 3}


def lyric_payload(*groups: tuple[int, int, bool]) -> bytes:
    """A lyrDataVerse payload: one 20-byte group per verse."""
    out = bytearray()
    for number, syll, extend in groups:
        block = bytearray(20)
        block[0:2] = number.to_bytes(2, "little")
        block[2:4] = syll.to_bytes(2, "little")
        block[8:10] = (1 if extend else 0).to_bytes(2, "little")
        out += block
    return bytes(out)


def test_one_mus_lyric_record_becomes_one_record_per_verse(
    pools: Callable[..., None],
) -> None:
    """A `.mus` packs every verse into one record; a `.musx` writes one each.
    Splitting here is what lets one lyrics module read both."""
    pools(
        details=(
            MusDetailRecord(TAG_LYRIC_VERSE, 0, 9, 0, lyric_payload((1, 3, False), (2, 4, True))),
        )
    )
    found = read_mus_document(PATH).details.of_tag("lyrDataVerse")
    assert [(r.attrs["entnum"], r.fields["lyricNumber"], r.fields["syll"]) for r in found] == [
        ("9", "1", "3"),
        ("9", "2", "4"),
    ]
    assert "wext" not in found[0].fields
    assert "wext" in found[1].fields


def test_a_repeated_lyric_assignment_is_emitted_once(pools: Callable[..., None]) -> None:
    """A `.mus` repeats an entry's assignments, usually as two identical
    records. Emitting both would sing every syllable twice."""
    payload = lyric_payload((1, 3, False))
    pools(
        details=(
            MusDetailRecord(TAG_LYRIC_VERSE, 0, 9, 0, payload),
            MusDetailRecord(TAG_LYRIC_VERSE, 0, 9, 0, payload),
        )
    )
    assert len(read_mus_document(PATH).details.of_tag("lyrDataVerse")) == 1


def test_an_empty_verse_slot_is_skipped(pools: Callable[..., None]) -> None:
    pools(details=(MusDetailRecord(TAG_LYRIC_VERSE, 0, 9, 0, lyric_payload((0, 0, False))),))
    assert read_mus_document(PATH).details.of_tag("lyrDataVerse") == ()


def artic_def_payload(character: int, *, length: int = 48) -> bytes:
    payload = bytearray(length)
    offset = 0 if length == 48 else 2
    payload[offset : offset + 2] = character.to_bytes(2, "little")
    return bytes(payload)


@pytest.mark.parametrize("length", [48, 60])
def test_an_articulation_definition_reads_in_either_era_layout(
    pools: Callable[..., None], length: int
) -> None:
    """2012 puts two bytes ahead of the character, as it does for clefs."""
    pools(
        others=(MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(46, length=length)),),
        details=(
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, (1).to_bytes(2, "little") + bytes(18)),
        ),
    )
    assert articulations_by_entry(read_mus_document(PATH)) == {9: ("staccato",)}


@pytest.mark.parametrize("length", [48, 60])
def test_articulation_symbol_handle_positions_and_note_anchor_are_signed_and_era_specific(
    pools: Callable[..., None], length: int
) -> None:
    payload = bytearray(artic_def_payload(40, length=length))
    base = 2 if length == 60 else 0
    for at, value in ((16, -26), (18, -21), (20, 7)):
        payload[base + at : base + at + 2] = value.to_bytes(2, "little", signed=True)
    payload[10:12] = (0x80).to_bytes(2, "little")
    pools(others=(MusOther(TAG_ARTIC_DEF, 1, 0, bytes(payload)),))
    record = read_mus_document(PATH).others.get("articDef", 1)
    assert record is not None
    assert record.fields["xOffsetMain"] == "-26"
    assert record.fields["yOffsetMain"] == "-21"
    assert record.fields["defVertPos"] == "7"
    assert "useTopNote" in record.fields


def test_packed_page_text_assignments_keep_the_later_slot_and_signed_positions(
    pools: Callable[..., None],
) -> None:
    def slot(block: int, hidden: bool) -> bytes:
        words = (block, -38, -267, 1, 1, 0x80 if hidden else 0)
        return b"".join(v.to_bytes(2, "little", signed=True) for v in words) + bytes(12)

    pools(others=(MusOther(194, 1, 0, slot(7, True) + slot(97, False)),))
    rows = read_mus_document(PATH).others.of_tag("pageTextAssign")
    assert [r.fields["block"] for r in rows] == ["7", "97"]
    assert [r.attrs["inci"] for r in rows] == ["0", "1"]
    assert "postIt" in rows[0].fields and "postIt" not in rows[1].fields
    assert rows[1].fields["xdisp"] == "-38" and rows[1].fields["ydisp"] == "-267"


@pytest.mark.parametrize("length", [0, 23, 25])
def test_partial_page_text_slots_are_rejected(pools: Callable[..., None], length: int) -> None:
    pools(others=(MusOther(194, 1, 0, bytes(length)),))
    with pytest.raises(CorruptScoreError, match="pageTextAssign"):
        read_mus_document(PATH)


@pytest.mark.parametrize("year", [2011, 2012])
def test_custom_line_fonts_caps_and_raw_text_references_use_the_complete_era_layout(
    pools: Callable[..., None], year: int
) -> None:
    modern = year >= 2012
    payload = bytearray(72)
    payload[0:2] = (2).to_bytes(2, "little")
    payload[2 : 6 if modern else 4] = (126).to_bytes(4 if modern else 2, "little")
    font_at, cap_at, text_at = (6, 16, 30) if modern else (4, 14, 28)
    payload[font_at : font_at + 2] = (7).to_bytes(2, "little")
    payload[font_at + 2 : font_at + 4] = (24).to_bytes(2, "little")
    payload[cap_at : cap_at + 2] = (3).to_bytes(2, "little")
    payload[text_at : text_at + 2] = (17).to_bytes(2, "little")
    if modern:
        payload[20:22] = (-1536).to_bytes(2, "little", signed=True)
    pools(year=year, others=(MusOther(222, 11, 0, bytes(payload)),))
    line = read_mus_document(PATH).others.get("smartShapeCustomLine", 11)
    assert line is not None
    parameters = line.fields["charParams"]
    assert isinstance(parameters, Record)
    assert parameters.fields == {"lineChar": "126", "fontID": "7", "fontSize": "24"}
    assert line.fields["lineCapStartType"] == "hook"
    assert line.fields["leftStartRawTextID"] == "17"
    if modern:
        assert line.fields["lineCapStartHookLength"] == "-1536"


def test_unknown_banner_uses_only_a_uniquely_validated_line_definition_layout(
    pools: Callable[..., None],
) -> None:
    glyph = bytearray(72)
    glyph[0:2] = (2).to_bytes(2, "little")
    glyph[2:6] = (126).to_bytes(4, "little")
    glyph[8:10] = (24).to_bytes(2, "little")
    # The modern baseline-shift field is not a valid legacy line-cap enum.
    glyph[14:16] = (-88).to_bytes(2, "little", signed=True)
    solid = bytearray(72)
    solid[16:20] = (3).to_bytes(2, "little") * 2
    solid[20:22] = (1536).to_bytes(2, "little")
    pools(year=None, others=(MusOther(222, 1, 0, bytes(glyph)), MusOther(222, 6, 0, bytes(solid))))
    doc = read_mus_document(PATH)
    line = doc.others.get("smartShapeCustomLine", 6)
    assert line is not None and line.fields["lineCapStartType"] == "hook"
    assert line.fields["lineCapEndType"] == "hook"


def test_ambiguous_versionless_line_definitions_retain_an_explicit_unknown_layout(
    pools: Callable[..., None],
) -> None:
    pools(year=None, others=(MusOther(222, 1, 0, bytes(72)),))
    line = read_mus_document(PATH).others.get("smartShapeCustomLine", 1)
    assert line is not None and line.attrs["sourceLayout"] == "unknown"
    assert line.fields == {"lineStyle": "solid"}


@pytest.mark.parametrize("length", [0, 71, 73])
def test_partial_custom_line_definitions_raise_clear_errors(
    pools: Callable[..., None], length: int
) -> None:
    pools(others=(MusOther(222, 1, 0, bytes(length)),))
    with pytest.raises(CorruptScoreError, match="smartShapeCustomLine"):
        read_mus_document(PATH)


def test_a_repeated_articulation_assignment_is_emitted_once(
    pools: Callable[..., None],
) -> None:
    """A `.mus` repeats an assignment on 23 corpus entries; no `.musx` ever
    assigns the same articDef twice, so a repeat would print the mark twice."""
    payload = (1).to_bytes(2, "little") + bytes(18)
    pools(
        others=(MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(62)),),
        details=(
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, payload),
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, payload),
        ),
    )
    assert articulations_by_entry(read_mus_document(PATH)) == {9: ("accent",)}


def test_two_different_articulations_on_one_entry_both_survive(
    pools: Callable[..., None],
) -> None:
    pools(
        others=(
            MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(46)),
            MusOther(TAG_ARTIC_DEF, 2, 0, artic_def_payload(62)),
        ),
        details=(
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, (1).to_bytes(2, "little") + bytes(18)),
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, (2).to_bytes(2, "little") + bytes(18)),
        ),
    )
    assert articulations_by_entry(read_mus_document(PATH)) == {9: ("staccato", "accent")}


def artic_assign_payload(*definitions: int) -> bytes:
    """Authored 20-byte assignment groups, with uninterpreted bytes left empty."""
    return b"".join(definition.to_bytes(2, "little") + bytes(18) for definition in definitions)


@pytest.mark.parametrize("character", [249, 223])
@pytest.mark.parametrize("length", [48, 60])
def test_binary_combined_articulation_exports_both_marks_once_on_its_chord(
    pools: Callable[..., None], character: int, length: int
) -> None:
    """Authored C/E then D quarters exercise the entire join in both era layouts."""
    notes = tuple(
        Record(tag="note", attrs={}, text="", fields={"harmLev": str(level), "harmAlt": "0"})
        for level in (0, 2)
    )
    hidden_accent = bytearray(artic_assign_payload(2))
    hidden_accent[10:12] = b"\x01\x00"
    pools(
        year=2011 if length == 48 else 2012,
        others=(
            MusOther(FRAME_SPEC, 3, 0, entry_pair(9, 10)),
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 0, 2, 1024)),
            MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(character, length=length)),
            MusOther(TAG_ARTIC_DEF, 2, 0, artic_def_payload(62, length=length)),
        ),
        details=(
            MusDetailRecord(GFHOLD, 1, 1, 0, gfhold_payload(0, 3)),
            MusDetailRecord(
                TAG_ARTIC_ASSIGN,
                0,
                9,
                0,
                artic_assign_payload(1) + bytes(hidden_accent) + artic_assign_payload(1),
            ),
        ),
        entries=(
            Record(
                tag="entry",
                attrs={"entnum": "9", "prev": "0", "next": "10"},
                text="",
                fields={"dura": "1024", "numNotes": "2", "note": notes},
            ),
            Record(
                tag="entry",
                attrs={"entnum": "10", "prev": "9", "next": "0"},
                text="",
                fields={
                    "dura": "1024",
                    "numNotes": "1",
                    "note": Record(
                        tag="note", attrs={}, text="", fields={"harmLev": "1", "harmAlt": "0"}
                    ),
                },
            ),
        ),
    )
    score = build_score(read_mus_document(PATH))
    first, following = score.parts[0].measures[0].voices[0].events
    assert first.articulations == ("accent", "staccato")
    assert following.articulations == ()
    assert (first.duration, following.duration) == (Fraction(1, 4), Fraction(1, 4))
    root = DET.fromstring(to_musicxml(score))
    exported = root.findall(".//note")
    assert [n.findtext("pitch/step") for n in exported] == ["C", "E", "D"]
    assert [n.findtext("duration") for n in exported] == ["1", "1", "1"]
    assert exported[1].find("chord") is not None
    marks = exported[0].find("notations/articulations")
    assert marks is not None and [mark.tag for mark in marks] == ["accent", "staccato"]
    assert len(root.findall(".//accent")) == len(root.findall(".//staccato")) == 1
    assert all(n.find("notations/articulations") is None for n in exported[1:])


def test_a_packed_assignment_preserves_the_second_definition(
    pools: Callable[..., None],
) -> None:
    pools(details=(MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, artic_assign_payload(1, 2)),))
    assignments = read_mus_document(PATH).details.of_tag("articAssign")
    assert [record.fields["articDef"] for record in assignments] == ["1", "2"]


def test_packed_assignment_visibility_uses_only_bit_zero_in_each_group(
    pools: Callable[..., None],
) -> None:
    payload = bytearray(artic_assign_payload(1, 2, 3, 4, 5))
    for offset, flags in enumerate((0, 1, 2, 3, 0x8000)):
        start = offset * 20 + 10
        payload[start : start + 2] = flags.to_bytes(2, "little")
    pools(details=(MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 4, bytes(payload)),))
    assignments = read_mus_document(PATH).details.of_tag("articAssign")
    assert ["hide" in record.fields for record in assignments] == [False, True, False, True, False]
    assert [record.attrs["sourceInci"] for record in assignments] == ["4"] * 5


@pytest.mark.parametrize("hidden_first", [False, True])
def test_a_hidden_duplicate_does_not_swallow_a_visible_assignment(
    pools: Callable[..., None], hidden_first: bool
) -> None:
    visible = artic_assign_payload(1)
    hidden = bytearray(visible)
    hidden[10:12] = b"\x01\x00"
    groups = (bytes(hidden), visible) if hidden_first else (visible, bytes(hidden))
    pools(
        others=(MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(62)),),
        details=(
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, b"".join(groups)),
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, b"".join(reversed(groups))),
        ),
    )
    document = read_mus_document(PATH)
    assignments = document.details.of_tag("articAssign")
    assert len(assignments) == 2
    assert {"hide" in record.fields for record in assignments} == {False, True}
    assert [record.attrs["inci"] for record in assignments] == ["0", "1"]
    assert [record.attrs["sourceInci"] for record in assignments] == ["0", "0"]
    assert articulations_by_entry(document) == {9: ("accent",)}


def test_a_fermata_in_a_packed_mus_assignment_reaches_musicxml(
    pools: Callable[..., None],
) -> None:
    """An authored C/E chord exercises the binary adapter -> IR -> XML path."""
    notes = tuple(
        Record(tag="note", attrs={}, text="", fields={"harmLev": str(level), "harmAlt": "0"})
        for level in (0, 2)
    )
    entry = Record(
        tag="entry",
        attrs={"entnum": "9", "prev": "0", "next": "0"},
        text="",
        fields={"dura": "1024", "numNotes": "2", "note": notes},
    )
    pools(
        others=(
            MusOther(FRAME_SPEC, 3, 0, entry_pair(9, 9)),
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 0, 1, 1024)),
            MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(103)),
            MusOther(TAG_ARTIC_DEF, 2, 0, artic_def_payload(85, length=60)),
        ),
        details=(
            MusDetailRecord(GFHOLD, 1, 1, 0, gfhold_payload(0, 3)),
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, artic_assign_payload(1, 2)),
        ),
        entries=(entry,),
    )
    score = build_score(read_mus_document(PATH))
    event = score.parts[0].measures[0].voices[0].events[0]
    assert event.fermatas == (Fermata(),)
    assert event.arpeggios == (Arpeggio(),)
    root = DET.fromstring(to_musicxml(score))
    assert len(root.findall(".//fermata[@type='upright']")) == 1
    assert len(root.findall(".//arpeggiate")) == 2
    assert [note.findtext("pitch/step") for note in root.findall(".//note")] == ["C", "E"]


def test_packed_and_separate_assignments_keep_unique_identities_and_source_rows(
    pools: Callable[..., None],
) -> None:
    """Separate score records continue the packed group's logical incidences."""
    pools(
        details=(
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, artic_assign_payload(1, 2, 1)),
            MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, artic_assign_payload(2, 3)),
        )
    )
    document = read_mus_document(PATH)
    assignments = document.details.of_tag("articAssign")
    assert [record.fields["articDef"] for record in assignments] == ["1", "2", "3"]
    assert [record.attrs["inci"] for record in assignments] == ["0", "1", "2"]
    assert [record.attrs["sourceInci"] for record in assignments] == ["0", "0", "0"]
    for incidence, assignment in zip((0, 1, 2), assignments, strict=True):
        assert document.details.for_entry("articAssign", 9, incidence) is assignment


def test_packed_assignment_positions_use_signed_words_in_each_group(
    pools: Callable[..., None],
) -> None:
    first = b"".join(
        value.to_bytes(2, "little", signed=True) for value in (1, -18, 0, -20, -240)
    ) + bytes(10)
    second = b"".join(
        value.to_bytes(2, "little", signed=True) for value in (2, 5, 24, 30, 48)
    ) + bytes(10)
    pools(details=(MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, first + second),))
    assignments = read_mus_document(PATH).details.of_tag("articAssign")
    assert [record.fields for record in assignments] == [
        {"articDef": "1", "horzOff": "-18", "horzAdd": "0", "vertOff": "-20", "vertAdd": "-240"},
        {"articDef": "2", "horzOff": "5", "horzAdd": "24", "vertOff": "30", "vertAdd": "48"},
    ]


@pytest.mark.parametrize("length", [0, 1, 2, 19, 21, 39, 41])
def test_an_incomplete_articulation_assignment_group_is_rejected(
    pools: Callable[..., None], length: int
) -> None:
    pools(details=(MusDetailRecord(TAG_ARTIC_ASSIGN, 0, 9, 0, bytes(length)),))
    with pytest.raises(CorruptScoreError, match="articAssign.*20-byte"):
        read_mus_document(PATH)


def test_an_articulation_definition_of_unknown_length_is_skipped(
    pools: Callable[..., None],
) -> None:
    pools(others=(MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(46)[:30]),))
    assert read_mus_document(PATH).others.of_tag("articDef") == ()


def test_reports_what_it_does_not_translate() -> None:
    """`UNTRANSLATED` is the module's contract with its callers; an empty tuple
    would claim full fidelity."""
    assert adapter.UNTRANSLATED
    assert all(isinstance(gap, str) and gap for gap in adapter.UNTRANSLATED)


REPEAT_BACK = 203
REPEAT_ENDING_START = 204
REPEAT_PASS_LIST = 206


def meas_spec_with_flags(flags: int) -> bytes:
    """A `measSpec` long enough to carry the flags byte at +10."""
    return meas_spec_payload(305, 0, 2, 1024) + bytes(2) + bytes([flags]) + bytes(15)


@pytest.mark.parametrize(
    ("flags", "expected"),
    [(0x02, "barEnding"), (0x04, "bacRepBar"), (0x08, "forRepBar")],
)
def test_the_repeat_barline_flags_are_read(
    pools: Callable[..., None], flags: int, expected: str
) -> None:
    """All three live in one byte at +10, on adjacent bits."""
    pools(others=(MusOther(MEAS_SPEC, 4, 0, meas_spec_with_flags(flags)),))
    record = read_mus_document(PATH).others.get("measSpec", 4)
    assert record is not None
    assert expected in record.fields


def test_the_barline_style_nibble_is_not_mistaken_for_a_repeat(
    pools: Callable[..., None],
) -> None:
    """The same byte's high nibble is the barline style -- 0x10 normal, 0x20
    double. Reading the byte as a whole, or masking it loosely, would turn every
    ordinary barline into a repeat."""
    pools(others=(MusOther(MEAS_SPEC, 5, 0, meas_spec_with_flags(0x10)),))
    record = read_mus_document(PATH).others.get("measSpec", 5)
    assert record is not None
    assert not {"forRepBar", "bacRepBar", "barEnding"} & set(record.fields)


def test_a_measure_spec_too_short_for_the_flags_byte_keeps_its_other_fields(
    pools: Callable[..., None],
) -> None:
    pools(others=(MusOther(MEAS_SPEC, 6, 0, meas_spec_payload(305, 0, 2, 1024)),))
    record = read_mus_document(PATH).others.get("measSpec", 6)
    assert record is not None
    assert record.fields["beats"] == "2"


def test_translates_a_backward_repeat_s_total_passes(pools: Callable[..., None]) -> None:
    pools(others=(MusOther(REPEAT_BACK, 8, 0, bytes(2) + (3).to_bytes(2, "little") + bytes(20)),))
    record = read_mus_document(PATH).others.get("repeatBack", 8)
    assert record is not None
    assert record.fields["actuate"] == "3"


def test_a_zero_total_passes_becomes_no_field_at_all(pools: Callable[..., None]) -> None:
    """Same omission convention as `measSpec.key`: a `.musx` writes nothing
    where the value is the default, and the `.mus` stores 0 there."""
    pools(others=(MusOther(REPEAT_BACK, 9, 0, bytes(24)),))
    record = read_mus_document(PATH).others.get("repeatBack", 9)
    assert record is not None
    assert "actuate" not in record.fields


def test_translates_an_ending_start_and_its_pass_number(pools: Callable[..., None]) -> None:
    pools(
        others=(
            MusOther(REPEAT_ENDING_START, 21, 0, bytes(24)),
            MusOther(REPEAT_PASS_LIST, 21, 0, (2).to_bytes(2, "little") + bytes(10)),
        )
    )
    document = read_mus_document(PATH)
    assert document.others.get("repeatEndingStart", 21) is not None
    passes = document.others.get("repeatPassList", 21)
    assert passes is not None and passes.fields["act"] == "2"


STAFF_GROUP = 1057


def staff_group_payload(
    start: int,
    end: int,
    *,
    full_id: int = 0,
    bracket: int = 3,
    barline: bool = False,
) -> bytes:
    """A 40-byte `staffGroup`, in the field order etfspec.pdf documents."""
    out = bytearray(40)
    for offset, value in ((0, start), (2, end), (4, full_id), (10, bracket)):
        out[offset : offset + 2] = value.to_bytes(2, "little")
    if barline:
        out[21] |= 0x04
    return bytes(out)


def test_translates_a_staff_group(pools: Callable[..., None]) -> None:
    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 1, 0, staff_group_payload(2, 3, bracket=6)),))
    record = read_mus_document(PATH).details.get("staffGroup", 0, 1)
    assert record is not None
    assert (record.fields["startInst"], record.fields["endInst"]) == ("2", "3")
    bracket = record.fields["bracket"]
    assert isinstance(bracket, Record) and bracket.fields["id"] == "6"


def test_the_group_barline_bit_is_read(pools: Callable[..., None]) -> None:
    """0x0400 of the flag word at +20 -- the bit etfspec.pdf's worked example
    sets and glosses as "barline through all staves"."""
    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 1, 0, staff_group_payload(1, 2, barline=True)),))
    record = read_mus_document(PATH).details.get("staffGroup", 0, 1)
    assert record is not None
    assert record.fields["groupBarlineStyle"] == "group"


def test_a_group_without_the_barline_bit_says_nothing(pools: Callable[..., None]) -> None:
    """The flag word carries more than this one bit, so the byte has to be
    masked rather than tested whole -- ETF's own example reads 0x0440, two bits
    set, of which only 0x0400 is the barline."""
    other_bits = bytearray(staff_group_payload(1, 2))
    other_bits[21] = 0x08
    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 1, 0, bytes(other_bits)),))
    record = read_mus_document(PATH).details.get("staffGroup", 0, 1)
    assert record is not None
    assert "groupBarlineStyle" not in record.fields


def test_a_zero_name_id_becomes_no_field_at_all(pools: Callable[..., None]) -> None:
    """Same omission convention as `measSpec.key`: 0 means "no name"."""
    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 1, 0, staff_group_payload(1, 2, full_id=0)),))
    record = read_mus_document(PATH).details.get("staffGroup", 0, 1)
    assert record is not None
    assert "fullID" not in record.fields

    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 2, 0, staff_group_payload(1, 2, full_id=99)),))
    named = read_mus_document(PATH).details.get("staffGroup", 0, 2)
    assert named is not None
    assert named.fields["fullID"] == "99"


def test_skips_a_group_payload_too_short_for_its_fields(pools: Callable[..., None]) -> None:
    pools(details=(MusDetailRecord(STAFF_GROUP, 0, 1, 0, bytes(8)),))
    assert read_mus_document(PATH).details.get("staffGroup", 0, 1) is None


@pytest.mark.parametrize(("nibble", "expected"), [(1, "normal"), (2, "double")])
def test_the_barline_style_nibble_is_read(
    pools: Callable[..., None], nibble: int, expected: str
) -> None:
    """The high nibble of the same flags byte the repeat bits live in."""
    pools(others=(MusOther(MEAS_SPEC, 7, 0, meas_spec_with_flags(nibble << 4)),))
    record = read_mus_document(PATH).others.get("measSpec", 7)
    assert record is not None
    assert record.fields["barline"] == expected


def test_an_unknown_barline_nibble_is_not_guessed_at(pools: Callable[..., None]) -> None:
    """Nibble 3 would be the obvious reading of `final`, and it does not occur
    once in 4,427 measures across 99 corpus `.mus` documents -- so there is
    nothing to check a guess against, and a wrong one puts the wrong bar at the
    end of a piece."""
    pools(others=(MusOther(MEAS_SPEC, 8, 0, meas_spec_with_flags(3 << 4)),))
    record = read_mus_document(PATH).others.get("measSpec", 8)
    assert record is not None
    assert "barline" not in record.fields


def test_the_barline_nibble_does_not_disturb_the_repeat_bits(
    pools: Callable[..., None],
) -> None:
    """They share a byte: reading the style off the whole byte, or the flags
    off the whole byte, breaks the other."""
    pools(others=(MusOther(MEAS_SPEC, 9, 0, meas_spec_with_flags((2 << 4) | 0x08)),))
    record = read_mus_document(PATH).others.get("measSpec", 9)
    assert record is not None
    assert record.fields["barline"] == "double"
    assert "forRepBar" in record.fields


def entry_record(entnum: int, prev: int = 0, next_: int = 0) -> Record:
    """An entry carrying only the chain links `_live_entries` walks."""
    return Record(
        tag="entry",
        attrs={"entnum": str(entnum), "prev": str(prev), "next": str(next_)},
        text="",
        fields={},
    )


def gfhold_record(*frames: int) -> Record:
    return Record(
        tag="gfhold",
        attrs={"cmper1": "1", "cmper2": "1"},
        text="",
        fields={f"frame{i + 1}": str(f) for i, f in enumerate(frames) if f},
    )


def test_an_entry_no_frame_reaches_is_dropped_as_dead_pool_space() -> None:
    """A `.mus` entry pool is a live database: entries deleted in Finale stay in
    it until the file is compacted, so the frames -- not the pool -- say what the
    music is."""
    entries = (entry_record(1, next_=2), entry_record(2, prev=1), entry_record(9))
    live = adapter._live_entries(entries, {7: (1, 2, None)}, [gfhold_record(7)])
    assert [r.attrs["entnum"] for r in live] == ["1", "2"]


def test_a_dead_entry_between_two_live_ones_does_not_break_the_chain() -> None:
    """Dead slots are not always a block at one end of the pool."""
    entries = (entry_record(1, next_=3), entry_record(2), entry_record(3, prev=1))
    live = adapter._live_entries(entries, {7: (1, 3, None)}, [gfhold_record(7)])
    assert [r.attrs["entnum"] for r in live] == ["1", "3"]


def test_every_layer_of_a_gfhold_keeps_its_music() -> None:
    """Reading fewer layer slots than a gfhold names would silently discard the
    rest as dead -- the failure this pruning could otherwise hide."""
    entries = tuple(entry_record(n) for n in range(1, 5))
    frames: dict[int, tuple[int, int, int | None]] = {
        1: (1, 1, None),
        2: (2, 2, None),
        3: (3, 3, None),
        4: (4, 4, None),
    }
    live = adapter._live_entries(entries, frames, [gfhold_record(1, 2, 3, 4)])
    assert [r.attrs["entnum"] for r in live] == ["1", "2", "3", "4"]


def test_a_chain_that_never_meets_its_end_entry_stops_at_the_pool_edge() -> None:
    """A `next` of 0 ends the walk: a frame whose endEntry is unreachable must
    not spin, and must not claim the whole pool."""
    entries = (entry_record(1, next_=0), entry_record(5))
    live = adapter._live_entries(entries, {7: (1, 99, None)}, [gfhold_record(7)])
    assert [r.attrs["entnum"] for r in live] == ["1"]


def test_a_cyclic_chain_terminates() -> None:
    """Hostile input: two entries pointing at each other, and an endEntry never
    reached."""
    entries = (entry_record(1, next_=2), entry_record(2, next_=1))
    live = adapter._live_entries(entries, {7: (1, 99, None)}, [gfhold_record(7)])
    assert [r.attrs["entnum"] for r in live] == ["1", "2"]


def pass_list_payload(*passes: int) -> bytes:
    """A `repeatPassList` payload: a u16 array, zero-terminated."""
    return b"".join(p.to_bytes(2, "little") for p in passes) + bytes(12)


def test_an_ending_taken_on_two_passes_keeps_both(pools: Callable[..., None]) -> None:
    """A "1., 2." ending stores both passes.

    Reading only the first at +0 turns it into a "1." ending -- the same notes
    with a different repeat structure. The `.musx` reader already treats `act` as
    possibly-a-tuple for exactly this case; the `.mus` side did not.
    """
    pools(others=(MusOther(REPEAT_PASS_LIST, 30, 0, pass_list_payload(1, 2)),))
    record = read_mus_document(PATH).others.get("repeatPassList", 30)
    assert record is not None
    assert record.fields["act"] == ("1", "2")


def test_an_ending_taken_on_one_pass_stays_a_single_act(pools: Callable[..., None]) -> None:
    """One pass keeps the scalar shape the `.musx` reader also produces."""
    pools(others=(MusOther(REPEAT_PASS_LIST, 31, 0, pass_list_payload(1)),))
    record = read_mus_document(PATH).others.get("repeatPassList", 31)
    assert record is not None
    assert record.fields["act"] == "1"


def test_a_zero_ends_the_pass_list(pools: Callable[..., None]) -> None:
    """The array is zero-terminated, so trailing padding is not a pass."""
    pools(others=(MusOther(REPEAT_PASS_LIST, 32, 0, pass_list_payload(1, 2, 0, 7)),))
    record = read_mus_document(PATH).others.get("repeatPassList", 32)
    assert record is not None
    assert record.fields["act"] == ("1", "2")


INST_USED = 159
_SLOT = 24


def inst_used_payload(*staves: int) -> bytes:
    """An `instUsed` payload: one 24-byte slot per staff, staff number first."""
    return b"".join(s.to_bytes(2, "little") + bytes(_SLOT - 2) for s in staves)


def test_the_score_staff_list_becomes_one_inst_used_record_per_slot(
    pools: Callable[..., None],
) -> None:
    """`groups.staff_order` reads one record per slot, keyed by `inci`."""
    pools(others=(MusOther(INST_USED, 0, 0, inst_used_payload(1, 2, 3)),))
    records = read_mus_document(PATH).others.of_tag("instUsed")
    assert [r.attrs["inci"] for r in records] == ["0", "1", "2"]
    assert [r.fields["inst"] for r in records] == ["1", "2", "3"]


def test_staff_geometry_reads_signed_32_bit_distances_per_slot(
    pools: Callable[..., None],
) -> None:
    payload = bytearray(inst_used_payload(1, 2, 3))
    for index, distance in enumerate((0, -240, -70000)):
        payload[index * _SLOT + 8 : index * _SLOT + 12] = distance.to_bytes(
            4, "little", signed=True
        )
    pools(others=(MusOther(INST_USED, 0, 0, bytes(payload)),))
    assert [
        record.fields["distFromTop"] for record in read_mus_document(PATH).others.of_tag("instUsed")
    ] == ["0", "-240", "-70000"]


def test_a_staff_list_that_is_not_ascending_keeps_its_order(
    pools: Callable[..., None],
) -> None:
    """The whole point: sorting would give the same answer for every ascending
    document and the wrong one for these. Two corpus documents lay five staves
    out this way, and they are the only evidence this record could be identified
    from."""
    pools(others=(MusOther(INST_USED, 0, 0, inst_used_payload(1, 2, 5, 3, 4)),))
    document = read_mus_document(PATH)
    assert [r.fields["inst"] for r in document.others.of_tag("instUsed")] == [
        "1",
        "2",
        "5",
        "3",
        "4",
    ]
    assert staff_order(document) == (1, 2, 5, 3, 4)


def test_a_part_instrument_list_is_marked_as_a_part_variant(
    pools: Callable[..., None],
) -> None:
    """`staff_order` skips part variants; a list read as the score's would order
    the score by a part's staves."""
    pools(others=(MusOther(INST_USED, 0, 1, inst_used_payload(3, 1)),))
    records = read_mus_document(PATH).others.of_tag("instUsed")
    assert records and all("part" in r.attrs for r in records)


def test_a_staff_list_payload_that_is_not_whole_slots_is_skipped(
    pools: Callable[..., None],
) -> None:
    """Hostile input: a trailing partial slot must not read past the payload."""
    pools(others=(MusOther(INST_USED, 0, 0, inst_used_payload(1, 2)[:-3]),))
    assert [r.fields["inst"] for r in read_mus_document(PATH).others.of_tag("instUsed")] == ["1"]


def entry_pair(start: int, end: int) -> bytes:
    return start.to_bytes(4, "little") + end.to_bytes(4, "little") + bytes(4)


def start_time_row(edu: int) -> bytes:
    """A `startTime` incidence: the block that precedes the entry pair."""
    return edu.to_bytes(4, "little") + bytes(4) + bytes(2) + (2048).to_bytes(2, "little")


def test_a_frame_with_no_start_time_keeps_its_entry_pair_first() -> None:
    """One incidence: the pair is the whole record."""
    assert adapter._frame_span(entry_pair(9, 12), 1, "little") == (9, 12, None)


def test_a_frame_with_a_start_time_takes_the_pair_from_the_last_incidence() -> None:
    """Two incidences: `startTime` comes first and the entry pair follows.

    The reader used to try +0 then +12 and keep whichever named entries the pool
    held -- a fallback that could say which worked, never which was right.
    """
    payload = start_time_row(3072) + entry_pair(9, 12)
    assert adapter._frame_span(payload, 2, "little") == (9, 12, 3072)


def test_a_zero_start_time_is_not_written_out() -> None:
    """The same omit-the-default convention as `measSpec.key` and `gfhold.clefID`."""
    payload = start_time_row(0) + entry_pair(9, 12)
    assert adapter._frame_span(payload, 2, "little") == (9, 12, None)


def test_a_frame_payload_too_short_for_its_incidence_count_is_refused() -> None:
    """Hostile input: the incidence count must not index past the payload."""
    assert adapter._frame_span(entry_pair(9, 12)[:6], 1, "little") is None
    assert adapter._frame_span(entry_pair(9, 12), 2, "little") is None


def meas_spec_be(width: int, key: int, beats: int, divbeat: int, flags: int) -> bytes:
    """A big-endian `measSpec`, flags in the low byte of the u16 at +10."""
    head = b"".join(v.to_bytes(2, "big") for v in (width, key, beats, divbeat))
    return head + bytes(2) + (flags).to_bytes(2, "big") + bytes(14)


def test_the_flags_byte_follows_the_documents_byte_order() -> None:
    """It is the low byte of a u16, so it moves with the byte order.

    Reading payload[10] unconditionally takes the *high* byte in a big-endian
    file. Every one of the 37 big-endian DCL documents was reading its barline
    style and repeat flags from the wrong byte -- the corpus shows nibble {1, 2}
    at +11 there, exactly the distribution little-endian files show at +10.
    """
    fields = adapter._meas_spec(meas_spec_be(305, 0, 4, 1024, (2 << 4) | 0x08), "big")
    assert fields["barline"] == "double"
    assert "forRepBar" in fields


def test_the_flags_byte_is_unmoved_in_a_little_endian_document() -> None:
    """The other half of the same claim: the fix must not shift the 102."""
    fields = adapter._meas_spec(meas_spec_with_flags((2 << 4) | 0x08), "little")
    assert fields["barline"] == "double"
    assert "forRepBar" in fields


def test_a_2011_frame_with_a_start_time_takes_the_pair_from_the_last_incidence(
    pools: Callable[..., None],
) -> None:
    """The same shape as a 2001-2005 frame, and it was only fixed there.

    A `frameSpec` carrying a `startTime` is 24 bytes: the start time block, then
    the entry pair. Reading +0 unconditionally takes the start time as the pair,
    which is why four corpus documents raised "chain references missing entry
    3584" -- 3584 EDU being a start time, not an entry number.
    """
    payload = start_time_row(3584) + entry_pair(129, 140)
    pools(others=(MusOther(FRAME_SPEC, 7, 0, payload),))
    record = read_mus_document(PATH).others.get("frameSpec", 7)
    assert record is not None
    assert (record.fields["startEntry"], record.fields["endEntry"]) == ("129", "140")
    assert record.fields["startTime"] == "3584"


def test_a_2011_frame_without_a_start_time_is_unchanged(
    pools: Callable[..., None],
) -> None:
    """10,450 of the 10,465 corpus records are this shape; the fix must not move
    them."""
    pools(others=(MusOther(FRAME_SPEC, 8, 0, entry_pair(9, 12)),))
    record = read_mus_document(PATH).others.get("frameSpec", 8)
    assert record is not None
    assert (record.fields["startEntry"], record.fields["endEntry"]) == ("9", "12")
    assert "startTime" not in record.fields


TEXT_EXPR_DEF = 241
MEAS_EXPR_ASSIGN = 177


def text_expr_def_payload(
    *, text_id: int, value: int, description: bytes, terminator: bytes = b"\x00"
) -> bytes:
    payload = bytearray(36 + len(description) + len(terminator))
    payload[0:2] = text_id.to_bytes(2, "little")
    payload[4:6] = value.to_bytes(2, "little")
    payload[36 : 36 + len(description)] = description
    payload[36 + len(description) :] = terminator
    return bytes(payload)


def expression_text_block_payload(text_id: int) -> bytes:
    """Authored text-block reference to the expression text pool."""
    payload = bytearray(26)
    payload[:4] = text_id.to_bytes(4, "little")
    payload[24:26] = (2006).to_bytes(2, "little")
    return bytes(payload)


def meas_expr_assign_slot(*, expr_id: int, staff: int, flags: int = 0x02) -> bytes:
    slot = bytearray(24)
    slot[0:2] = expr_id.to_bytes(2, "little")
    slot[8:10] = staff.to_bytes(2, "little", signed=True)
    slot[11] = flags
    return bytes(slot)


def test_a_mus_expression_definition_carries_its_value_and_description(
    pools: Callable[..., None],
) -> None:
    """The description is what names a dynamic in a `.mus`: the container has no
    `^fontMus` markup and its category is not decoded."""
    pools(
        others=(
            MusOther(
                tag=TEXT_EXPR_DEF,
                cmper=4,
                part=0,
                payload=text_expr_def_payload(
                    text_id=17, value=88, description=b"forte (velocity = 88)"
                ),
            ),
        )
    )
    (record,) = [r for r in read_mus_document(PATH).others.records if r.tag == "textExprDef"]
    assert record.attrs == {"cmper": "4"}
    assert record.fields["value"] == "88"
    assert record.fields["descStr"] == "forte (velocity = 88)"
    assert record.fields["textIDKey"] == "17"
    assert "categoryID" not in record.fields, "not identified, so it must not be invented"


def test_a_definition_with_no_playback_level_omits_the_field(pools: Callable[..., None]) -> None:
    """Zero is how the record writes "no level"; the `.musx` omits the field, and
    `expressions` reads absent as None rather than as a velocity of nought."""
    pools(
        others=(
            MusOther(
                tag=TEXT_EXPR_DEF,
                cmper=11,
                part=0,
                payload=text_expr_def_payload(text_id=24, value=0, description=b"forte piano"),
            ),
        )
    )
    (record,) = [r for r in read_mus_document(PATH).others.records if r.tag == "textExprDef"]
    assert "value" not in record.fields
    assert record.fields["descStr"] == "forte piano"


@pytest.mark.parametrize(
    "description",
    ["pianissimo (velocity = 36)", "mezzo piano (velocity = 62)", "sforzato", "演奏 a一 🎼"],
)
def test_unicode_expression_descriptions_use_complete_code_units(
    pools: Callable[..., None], description: str
) -> None:
    pools(
        year=2012,
        others=(
            MusOther(
                TEXT_EXPR_DEF,
                1,
                0,
                text_expr_def_payload(
                    text_id=14,
                    value=0,
                    description=description.encode("utf-16-le"),
                    terminator=b"\x00\x00",
                ),
            ),
        ),
    )
    record = read_mus_document(PATH).others.get("textExprDef", 1)
    assert record is not None and record.fields["descStr"] == description


@pytest.mark.parametrize("raw", [b"\x70", b"\x00\xd8", b"\x00\xdc", b"\x00\xd8a\x00"])
def test_malformed_unicode_expression_descriptions_raise_a_clear_error(
    pools: Callable[..., None], raw: bytes
) -> None:
    pools(
        year=2012,
        others=(
            MusOther(
                TEXT_EXPR_DEF,
                1,
                0,
                text_expr_def_payload(
                    text_id=14,
                    value=0,
                    description=raw,
                    terminator=b"",
                ),
            ),
        ),
    )
    with pytest.raises(CorruptScoreError, match="textExprDef.*UTF-16LE description"):
        read_mus_document(PATH)


@pytest.mark.parametrize("tail", [b"", b"\x00\x00\xff"])
def test_a_unicode_description_is_bounded_by_its_record_or_aligned_terminator(
    pools: Callable[..., None], tail: bytes
) -> None:
    pools(
        year=2012,
        others=(
            MusOther(
                TEXT_EXPR_DEF,
                1,
                0,
                text_expr_def_payload(
                    text_id=14,
                    value=0,
                    description="Pedal".encode("utf-16-le") + tail,
                    terminator=b"",
                ),
            ),
        ),
    )
    record = read_mus_document(PATH).others.get("textExprDef", 1)
    assert record is not None and record.fields["descStr"] == "Pedal"


@pytest.mark.parametrize(
    ("description", "glyph", "marking"),
    [
        ("pianissimo", "¹", "pp"),
        ("mezzo piano", "P", "mp"),
        ("mezzo forte", "F", "mf"),
        ("forte", "f", "f"),
        ("sforzato", "§", "sfz"),
    ],
)
def test_a_unicode_dynamic_and_hidden_accent_reach_musicxml_correctly(
    pools: Callable[..., None], description: str, glyph: str, marking: str
) -> None:
    """An authored C/E chord tests binary definitions, visibility and the join."""
    hidden_accent = bytearray(artic_assign_payload(2))
    hidden_accent[10:12] = b"\x01\x00"
    notes = tuple(
        Record(tag="note", attrs={}, text="", fields={"harmLev": str(level), "harmAlt": "0"})
        for level in (0, 2)
    )
    entry = Record(
        tag="entry",
        attrs={"entnum": "9", "prev": "0", "next": "0"},
        text="",
        fields={"dura": "1024", "numNotes": "2", "note": notes},
    )
    pools(
        year=2012,
        others=(
            MusOther(FRAME_SPEC, 3, 0, entry_pair(9, 9)),
            MusOther(MEAS_SPEC, 1, 0, meas_spec_payload(305, 0, 1, 1024)),
            MusOther(TAG_ARTIC_DEF, 1, 0, artic_def_payload(46, length=60)),
            MusOther(TAG_ARTIC_DEF, 2, 0, artic_def_payload(62, length=60)),
            MusOther(
                TEXT_EXPR_DEF,
                1,
                0,
                text_expr_def_payload(
                    text_id=14,
                    value=21,
                    description=description.encode("utf-16-le"),
                    terminator=b"\x00\x00",
                ),
            ),
            MusOther(MEAS_EXPR_ASSIGN, 1, 0, meas_expr_assign_slot(expr_id=1, staff=1)),
            MusOther(TAG_TEXT_BLOCK, 14, 0, expression_text_block_payload(27)),
        ),
        details=(
            MusDetailRecord(GFHOLD, 1, 1, 0, gfhold_payload(0, 3)),
            MusDetailRecord(
                TAG_ARTIC_ASSIGN, 0, 9, 0, artic_assign_payload(1) + bytes(hidden_accent)
            ),
        ),
        entries=(entry,),
        # The same binary markup dialect, applied to authored music.
        texts=(
            Record(
                tag="expression",
                attrs={"number": "27"},
                text="^¥\x01\x01\x01\x01" + glyph,
                fields={},
            ),
        ),
    )
    score = build_score(read_mus_document(PATH))
    measure = score.parts[0].measures[0]
    assert measure.expressions[0].marking == marking
    assert measure.expressions[0].velocity == 21
    assert measure.voices[0].events[0].articulations == ("staccato",)
    root = DET.fromstring(to_musicxml(score))
    assert len(root.findall(f".//dynamics/{marking}")) == 1
    assert len(root.findall(".//staccato")) == 1
    assert not root.findall(".//accent")
    assert not root.findall(".//sound[@dynamics]")
    assert [n.findtext("pitch/step") for n in root.findall(".//note")] == ["C", "E"]
    assert [n.findtext("duration") for n in root.findall(".//note")] == ["1", "1"]


def test_two_markings_in_one_measure_become_two_assignments(pools: Callable[..., None]) -> None:
    """The payload is an array of 24-byte slots. Reading only the first would
    lose the second marking in any measure that carries two."""
    pools(
        others=(
            MusOther(
                tag=MEAS_EXPR_ASSIGN,
                cmper=9,
                part=0,
                payload=meas_expr_assign_slot(expr_id=4, staff=1)
                + meas_expr_assign_slot(expr_id=7, staff=2),
            ),
        )
    )
    found = [r for r in read_mus_document(PATH).others.records if r.tag == "measExprAssign"]
    assert [(r.attrs["inci"], r.fields["textExprID"], r.fields["staffAssign"]) for r in found] == [
        ("0", "4", "1"),
        ("1", "7", "2"),
    ]


def test_a_shape_assignment_is_not_read_as_an_expression(pools: Callable[..., None]) -> None:
    """Its id names a drawn shape, so emitting it as a `textExprID` places
    whatever definition happens to share that number -- 44 spurious markings
    across the paired corpus before the flag at +11 was found."""
    pools(
        others=(
            MusOther(
                tag=MEAS_EXPR_ASSIGN,
                cmper=3,
                part=0,
                payload=meas_expr_assign_slot(expr_id=4, staff=1, flags=0x20),
            ),
        )
    )
    assert [r for r in read_mus_document(PATH).others.records if r.tag == "measExprAssign"] == []


def test_a_staff_list_assignment_keeps_its_negative_staff(pools: Callable[..., None]) -> None:
    """-1 is a sentinel, not a staff, and it must survive the read as one: the
    downstream sweep counts how many markings it costs."""
    pools(
        others=(
            MusOther(
                tag=MEAS_EXPR_ASSIGN,
                cmper=1,
                part=0,
                payload=meas_expr_assign_slot(expr_id=72, staff=-1),
            ),
        )
    )
    (record,) = [r for r in read_mus_document(PATH).others.records if r.tag == "measExprAssign"]
    assert record.fields["staffAssign"] == "-1"


def test_every_entry_keyed_detail_this_adapter_emits_is_in_the_tag_map() -> None:
    """`ENTRY_DETAIL_TAGS` is what lets the report join a detail record back to
    the raw row it was read from (`report.model`). The join is silent when it
    misses -- a reference simply stops being clickable -- so a fourth
    entry-keyed detail added here without a map entry would break the feature
    with nothing to show for it.

    Read off this module's own source rather than off a corpus document: a tag
    the adapter emits only for a document this machine does not have would
    otherwise slip through. Every `Record(...)` built with an `entnum`
    attribute must have a name the map knows.
    """
    source = Path(inspect.getsourcefile(adapter) or "").read_text(encoding="utf-8")
    emitted = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != "Record":
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        attrs = keywords.get("attrs")
        if not isinstance(attrs, ast.Dict):
            continue
        names = {k.value for k in attrs.keys if isinstance(k, ast.Constant)}
        tag = keywords.get("tag")
        if "entnum" in names and isinstance(tag, ast.Constant):
            emitted.add(tag.value)
        elif (
            "entnum" in names and isinstance(tag, ast.Subscript) and isinstance(tag.value, ast.Dict)
        ):
            emitted.update(
                value.value for value in tag.value.values if isinstance(value, ast.Constant)
            )

    assert emitted == set(mus_details.ENTRY_DETAIL_TAGS)


def test_the_tag_map_names_the_raw_tags_the_adapter_reads() -> None:
    """The other half: each name maps to the numeric tag whose branch emits it."""
    assert mus_details.ENTRY_DETAIL_TAGS == {
        "articAssign": TAG_ARTIC_ASSIGN,
        "tupletDef": TAG_TUPLET_DEF,
        "lyrDataVerse": TAG_LYRIC_VERSE,
        "smartShapeEntryMark": TAG_SMART_SHAPE_ENTRY_MARK,
        "beamExtUp": 1021,
        "beamExtDown": 1022,
        "noteheadMod": 1058,
        "crossStaff": 1036,
    }
