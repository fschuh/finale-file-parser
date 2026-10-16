"""Unit tests for barline styles."""

from __future__ import annotations

import pytest

from finale_file_parser.enigma.barlines import barline_styles
from finale_file_parser.enigma.document import (
    DetailsPool,
    EnigmaDocument,
    EntriesPool,
    OptionsPool,
    OthersPool,
    Pool,
    Record,
    TextsPool,
)

EMPTY: tuple[Record, ...] = ()


def measure(number: int, style: str | None = None, *, part: str | None = None) -> Record:
    attrs = {"cmper": str(number)}
    if part is not None:
        attrs["part"] = part
    fields = {} if style is None else {"barline": style}
    return Record(tag="measSpec", attrs=attrs, text="", fields=fields)


def document(*others: Record) -> EnigmaDocument:
    return EnigmaDocument(
        version="test",
        header=Pool(records=EMPTY),
        mappings=Pool(records=EMPTY),
        options=OptionsPool(records=EMPTY),
        others=OthersPool(records=others),
        details=DetailsPool(records=EMPTY),
        entries=EntriesPool(records=EMPTY),
        texts=TextsPool(records=EMPTY),
    )


@pytest.mark.parametrize(
    ("name", "expected"), [("double", "light-light"), ("final", "light-heavy")]
)
def test_each_named_style_maps_to_its_musicxml_bar_style(name: str, expected: str) -> None:
    assert barline_styles(document(measure(4, name))) == {4: expected}


def test_an_ordinary_barline_needs_no_element() -> None:
    """`normal` is the default. Writing it out would put a `<bar-style>` on
    21,517 corpus measures and say nothing with any of them."""
    assert barline_styles(document(measure(1, "normal"), measure(2))) == {}


def test_an_unknown_style_is_ignored() -> None:
    assert barline_styles(document(measure(3, "dashed"))) == {}


def test_part_records_are_ignored() -> None:
    """A part can override a barline; honouring it would give the score a double
    bar it does not have."""
    doc = document(measure(5, "normal"), measure(5, "double", part="1"))
    assert barline_styles(doc) == {}


def _two_bar_score(last_spec: str = ""):  # type: ignore[no-untyped-def]
    from finale_file_parser.enigma.document import parse_enigma
    from finale_file_parser.enigma.to_ir import build_score

    entries = "".join(
        f'<entry entnum="{n}" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>'
        '<note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>'
        for n in (1, 2)
    )
    return build_score(
        parse_enigma(
            f"""<finale><others><staffSpec cmper="1"/>
          <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
          <measSpec cmper="2"><beats>4</beats><divbeat>1024</divbeat>{last_spec}</measSpec>
          <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
          <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>2</endEntry></frameSpec>
        </others><details>
          <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
          <gfhold cmper1="1" cmper2="2"><frame1>2</frame1></gfhold>
        </details><entries>{entries}</entries></finale>""".encode()
        )
    )


def test_the_last_bar_gets_finales_default_final_barline() -> None:
    measures = _two_bar_score().parts[0].measures
    assert [m.barline_style for m in measures] == [None, "light-heavy"]


def test_an_explicit_style_or_a_closing_repeat_keeps_the_last_bar() -> None:
    double = _two_bar_score("<barline>double</barline>").parts[0].measures
    assert double[-1].barline_style == "light-light"
    repeated = _two_bar_score("<bacRepBar/>").parts[0].measures
    assert repeated[-1].barline_style is None and repeated[-1].repeat_backward
