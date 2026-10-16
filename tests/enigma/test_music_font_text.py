"""Note glyphs in text fonts; fixtures authored for this project."""

from fractions import Fraction

import pytest

from finale_file_parser.enigma.expressions import _framed
from finale_file_parser.enigma.fonts import FontRun, readable_text
from finale_file_parser.ir import Expression


@pytest.mark.parametrize(
    "runs,expected",
    [
        ((FontRun("ŒÂ = Œ Ç‰", "MaestroTimes", False),), "♫ = ♩ ³♪"),
        ((FontRun("(Ó.=Œ)", "MaestroTimes", False),), "(\U0001d15e.=♩)"),
        ((FontRun("qd = 51", "EngraverTextT", False),), "♩. = 51"),
        (
            (
                FontRun("Swing ", "Times New Roman", False),
                FontRun("e", "EngraverTextT", False),
                FontRun("'s", "Times New Roman", False),
            ),
            "Swing ♪'s",
        ),
        (
            (FontRun("Swing ", "Times New Roman", False), FontRun("e", "Maestro", True)),
            "Swing ♪",
        ),
        # A run standing alone in a music font is a glyph read elsewhere (forte).
        ((FontRun("f", "Maestro", True),), "f"),
        ((FontRun("sub. ", "Times New Roman", False), FontRun("p", "Maestro", True)), "sub. p"),
    ],
)
def test_note_glyphs_read_as_note_symbols(runs: tuple[FontRun, ...], expected: str) -> None:
    assert readable_text(runs) == expected


def test_an_empty_parenthesis_frame_folds_around_its_glyph() -> None:
    frame = Expression("(      )", "", offset=Fraction(1, 2))
    caesura = Expression("//", "", offset=Fraction(3, 4))
    other = Expression("dolce", "")
    assert _framed((other, frame, caesura)) == (
        other,
        Expression("(//)", "", offset=Fraction(3, 4)),
    )
    assert _framed((frame,)) == (frame,)
