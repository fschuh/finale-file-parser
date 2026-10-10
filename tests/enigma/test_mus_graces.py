"""Authored preference rows cover both legacy adapters through MusicXML export."""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

import pytest
from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import OptionsPool, Record, parse_enigma
from finale_file_parser.enigma.mus_document import _options_records, _rows_options
from finale_file_parser.enigma.mus_others import (
    OPTIONS_CMPER,
    TAG_CLEF_OPTIONS,
    TAG_GRACE_SLASH_OPTIONS,
    MusOther,
)
from finale_file_parser.enigma.mus_payload import ByteOrder
from finale_file_parser.enigma.mus_rows import MusRowRecord, MusRows
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml

Layout = Literal["zlib", "dcl-little", "dcl-big"]


def _options(payload: bytes, layout: Layout, *, cmper: int = OPTIONS_CMPER) -> list[Record]:
    if layout == "zlib":
        return _options_records((MusOther(TAG_GRACE_SLASH_OPTIONS, cmper, 0, payload),), 2011)
    order: ByteOrder = "little" if layout == "dcl-little" else "big"
    return _rows_options(
        MusRows(
            others={("44", cmper): MusRowRecord("44", cmper, payload=payload, incidences=1)},
            byte_order=order,
        )
    )


def _payload(value: int, layout: Layout) -> bytes:
    order: ByteOrder = "big" if layout == "dcl-big" else "little"
    # Neighbors are deliberately nonzero: word 4 alone controls the slash.
    return b"".join(word.to_bytes(2, order) for word in (1, 2, 3, 4, value, 6))


@pytest.mark.parametrize("layout", ["zlib", "dcl-little", "dcl-big"])
@pytest.mark.parametrize("value", [0, 1, 0x100, 0xFFFF])
def test_the_mapped_preference_word_reaches_ir_and_export(value: int, layout: Layout) -> None:
    options = _options(_payload(value, layout), layout)
    assert len(options) == 1 and options[0].tag == "graceNoteOptions"
    assert ("slashFlaggedGraceNotes" in options[0].fields) is bool(value)
    document = parse_enigma(b"""
      <finale>
        <others>
          <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
          <frameSpec cmper="10"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>
        </others>
        <details><gfhold cmper1="1" cmper2="1"><frame1>10</frame1></gfhold></details>
        <entries>
          <entry entnum="1" prev="0" next="2">
            <dura>512</dura><numNotes>1</numNotes><graceNote/>
            <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
          </entry>
          <entry entnum="2" prev="1" next="0">
            <dura>1024</dura><numNotes>1</numNotes>
            <note><harmLev>2</harmLev><harmAlt>0</harmAlt></note>
          </entry>
        </entries>
      </finale>
    """)
    document.options = OptionsPool(records=tuple(options))
    score = build_score(document)
    grace, main = score.parts[0].measures[0].voices[0].events
    assert grace.grace_slash is bool(value) and grace.duration == 0
    assert main.duration == Fraction(1, 4) and main.grace_slash is None
    root = DET.fromstring(to_musicxml(score))
    element = root.find(".//grace")
    assert element is not None and element.attrib == {"slash": "yes" if value else "no"}


@pytest.mark.parametrize("layout", ["zlib", "dcl-little", "dcl-big"])
@pytest.mark.parametrize("length", [0, 8, 10, 11, 13, 24])
def test_an_unsupported_preference_layout_does_not_invent_a_setting(
    length: int, layout: Layout
) -> None:
    assert _options(bytes([1]) * length, layout) == []


@pytest.mark.parametrize("layout", ["zlib", "dcl-little", "dcl-big"])
def test_the_same_tag_with_another_comparator_is_not_a_preference(layout: Layout) -> None:
    assert _options(_payload(1, layout), layout, cmper=1) == []


def test_a_linked_part_preference_does_not_change_the_score() -> None:
    records = (MusOther(TAG_GRACE_SLASH_OPTIONS, OPTIONS_CMPER, 1, _payload(1, "zlib")),)
    assert _options_records(records, 2011) == []


def test_the_slash_layout_does_not_depend_on_the_clef_table_era() -> None:
    records = (MusOther(TAG_GRACE_SLASH_OPTIONS, OPTIONS_CMPER, 0, _payload(1, "zlib")),)
    options = _options_records(records, None)
    assert len(options) == 1 and "slashFlaggedGraceNotes" in options[0].fields


@pytest.mark.parametrize("layout", ["zlib", "dcl-little", "dcl-big"])
@pytest.mark.parametrize("clef_length", [0, 17, 18])
def test_grace_and_clef_options_are_translated_independently(
    layout: Layout, clef_length: int
) -> None:
    slash = _payload(1, layout)
    clef = bytes(clef_length)
    if layout == "zlib":
        options = _options_records(
            (
                MusOther(TAG_CLEF_OPTIONS, OPTIONS_CMPER, 0, clef),
                MusOther(TAG_GRACE_SLASH_OPTIONS, OPTIONS_CMPER, 0, slash),
            ),
            2011,
        )
    else:
        order: ByteOrder = "little" if layout == "dcl-little" else "big"
        options = _rows_options(
            MusRows(
                others={
                    ("95", OPTIONS_CMPER): MusRowRecord("95", OPTIONS_CMPER, payload=clef),
                    ("44", OPTIONS_CMPER): MusRowRecord("44", OPTIONS_CMPER, payload=slash),
                },
                byte_order=order,
            )
        )
    assert [record.tag for record in options] == ["graceNoteOptions"] + (
        ["clefOptions"] if clef_length == 18 else []
    )
