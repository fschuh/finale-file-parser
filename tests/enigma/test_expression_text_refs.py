"""Authored references distinguish legacy raw IDs from normalized MUSX IDs."""

from fractions import Fraction

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, OthersPool, Record, parse_enigma
from finale_file_parser.enigma.expressions import expressions_by_measure


def _document(
    *,
    legacy: bool = True,
    resolved: bool = True,
    blank: bool = False,
    description: str = "",
    pool: str = "expression",
) -> EnigmaDocument:
    reference = "<textBlockID>37</textBlockID>" if legacy else ""
    block = (
        '<textBlock cmper="37"><textID>83</textID><textTag>' + pool + "</textTag></textBlock>"
        if resolved
        else ""
    )
    actual_tag = "blockText" if pool == "block" else "expression"
    body = "" if blank else "h = 90"
    raw = f"""<finale version="18.0" xmlns="http://www.makemusic.com/2012/finale">
      <others>
        <textExprDef cmper="8"><textIDKey>37</textIDKey>{reference}
          <descStr>{description}</descStr></textExprDef>
        {block}
        <measExprAssign cmper="2"><textExprID>8</textExprID><staffAssign>1</staffAssign>
          <horzEduOff>512</horzEduOff></measExprAssign>
      </others>
      <texts><expression number="8">q = 200</expression>
        <{actual_tag} number="83">{body}</{actual_tag}></texts>
    </finale>"""
    return parse_enigma(raw.encode())


@pytest.mark.parametrize("pool", ["expression", "block"])
def test_legacy_definition_block_and_raw_text_ids_are_independent(pool: str) -> None:
    doc = _document(pool=pool)
    (expression,) = expressions_by_measure(doc)[1, 2]
    assert expression.text == "h = 90"
    assert expression.offset == Fraction(1, 8)
    assert expression.tempo is not None and expression.tempo.beat_unit == Fraction(1, 2)
    assert expression.tempo.per_minute == 90
    raw = doc.texts.get("expression", 8)
    assert raw is not None and raw.text == "q = 200"  # raw pool is unchanged


def test_normalized_musx_keeps_its_existing_definition_number_convention() -> None:
    (expression,) = expressions_by_measure(_document(legacy=False))[1, 2]
    assert expression.text == "q = 200"
    assert expression.tempo is not None and expression.tempo.per_minute == 200


@pytest.mark.parametrize("resolved,blank", [(False, False), (True, True)])
def test_missing_or_empty_legacy_text_cannot_fall_back_to_the_wrong_number(
    resolved: bool,
    blank: bool,
) -> None:
    assert expressions_by_measure(_document(resolved=resolved, blank=blank)) == {}


def test_an_empty_copied_dynamic_still_uses_its_naming_description() -> None:
    doc = _document(blank=True, description="piano (velocity = 49) (Copy)")
    (expression,) = expressions_by_measure(doc)[1, 2]
    assert expression.marking == "p"
    assert expression.text == "" and expression.tempo is None


def test_crossed_raw_ids_do_not_depend_on_definition_iteration_order() -> None:
    doc = _document()
    existing = list(doc.others.records)
    existing.extend(
        (
            Record("textExprDef", {"cmper": "83"}, "", {"textBlockID": "38"}),
            Record("textBlock", {"cmper": "38"}, "", {"textID": "8", "textTag": "expression"}),
            Record(
                "measExprAssign",
                {"cmper": "2", "inci": "1"},
                "",
                {"textExprID": "83", "staffAssign": "1"},
            ),
        )
    )
    doc.others = OthersPool(tuple(existing))
    assert [expression.text for expression in expressions_by_measure(doc)[1, 2]] == [
        "h = 90",
        "q = 200",
    ]
