"""Actual metric division, not a printed tempo unit, establishes swing subdivision."""

from fractions import Fraction

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.expressions import expressions_by_measure


def test_a_typed_swing_expression_uses_half_the_actual_metric_division() -> None:
    doc = parse_enigma(b"""<finale><others>
      <measSpec cmper="1"><beats>4</beats><divbeat>512</divbeat></measSpec>
      <textExprDef cmper="1"><playType>swing</playType><value>1024</value></textExprDef>
      <measExprAssign cmper="1"><staffAssign>-1</staffAssign>
        <textExprID>1</textExprID></measExprAssign>
    </others><texts><expression number="1">Swing</expression></texts></finale>""")
    expression = expressions_by_measure(doc)[-1, 1][0]
    assert expression.playback is not None
    assert expression.playback.beat_unit == Fraction(1, 16)
