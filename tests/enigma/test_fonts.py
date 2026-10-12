"""Authored music/text registries verify literal glyph context, not filename rules."""

import pytest

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.expressions import expressions_by_measure
from finale_file_parser.enigma.fonts import text_runs
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import MusOther


def _document(markup: str, *, name: str = "Maestro", desc: str = "Imported from MusicXML") -> bytes:
    return f"""<finale><others>
      <fontName cmper="0"><name>{name}</name></fontName>
      <fontName cmper="17"><name>Times New Roman</name></fontName>
      <textExprDef cmper="2"><descStr>{desc}</descStr></textExprDef>
      <measExprAssign cmper="3"><staffAssign>1</staffAssign>
        <textExprID>2</textExprID></measExprAssign>
    </others><texts><expression number="2">{markup}</expression></texts></finale>""".encode()


@pytest.mark.parametrize(
    ("glyph", "marking"), [("P", "mp"), ("F", "mf"), ("Ä", "ff"), ("p", "p"), ("f", "f")]
)
@pytest.mark.parametrize("opcode", ["85", "A5"])
def test_compiled_font_reference_recovers_a_named_music_dynamic(
    glyph: str, marking: str, opcode: str
) -> None:
    doc = parse_enigma(_document(f"^legacycmd({opcode},01010101){glyph}"))
    assert expressions_by_measure(doc)[1, 3][0].marking == marking


def test_the_same_letter_in_a_text_or_unknown_font_stays_ordinary_text() -> None:
    for name in ["Times New Roman", "Unknown Music Font"]:
        doc = parse_enigma(_document("^legacycmd(A5,01010101)F", name=name))
        expression = expressions_by_measure(doc)[1, 3][0]
        assert (expression.text, expression.marking) == ("F", None)


def test_mixed_runs_and_later_font_changes_control_the_printed_glyph() -> None:
    # 01 01 02 02 denotes hexadecimal 0011, font 17, not font 1.
    markup = "^legacycmd(A5,01010101)^legacycmd(85,01010202)F"
    doc = parse_enigma(_document(markup))
    assert text_runs(doc, markup)[0].name == "Times New Roman"
    assert expressions_by_measure(doc)[1, 3][0].marking is None
    markup = "^fontMus(0)f^fontTxt(17) label"
    doc = parse_enigma(_document(markup))
    assert [run.is_music for run in text_runs(doc, markup)] == [True, False]
    assert expressions_by_measure(doc)[1, 3][0].marking is None


def test_a_later_text_font_without_literal_content_does_not_erase_the_glyph_context() -> None:
    doc = parse_enigma(_document("^fontMus(0)P^fontTxt(17)"))
    assert expressions_by_measure(doc)[1, 3][0].marking == "mp"


def test_existing_named_empty_text_dynamics_still_resolve_without_a_font() -> None:
    doc = parse_enigma(_document("", desc="pianissimo (velocity = 36)"))
    assert expressions_by_measure(doc)[1, 3][0].marking == "pp"


@pytest.mark.parametrize("arguments", ["010101", "01010001", "01011101", "zz"])
def test_malformed_compiled_font_parameters_raise_a_clear_error(arguments: str) -> None:
    doc = parse_enigma(_document(f"^legacycmd(85,{arguments})F"))
    with pytest.raises(CorruptScoreError, match="compiled font command"):
        expressions_by_measure(doc)


def test_font_registry_name_is_read_from_the_bounded_numeric_payload() -> None:
    record = MusOther(144, 17, 0, bytes(12) + b"Authored Font\0")
    (font,) = _others_records((record,), "cp1252")
    assert font.attrs == {"cmper": "17"}
    assert font.fields == {"name": "Authored Font"}


def test_a_short_font_registry_record_is_rejected() -> None:
    with pytest.raises(CorruptScoreError, match="fontName: truncated"):
        _others_records((MusOther(144, 1, 0, bytes(12)),), "cp1252")
