"""Independently authored score and palette octave-line assignments."""

from fractions import Fraction

import pytest

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.octaves import octaves_by_staff
from finale_file_parser.ir import OctaveShift


def _xml(kind: str, flags: str = "", end: str = "3072") -> bytes:
    return f"""<finale><others>
      <smartShape cmper="9"><shapeType>{kind}</shapeType>{flags}
        <startTermSeg><endPt><inst>2</inst><meas>3</meas><edu>512</edu></endPt></startTermSeg>
        <endTermSeg><endPt><inst>2</inst><meas>3</meas><edu>{end}</edu></endPt></endTermSeg>
      </smartShape>
      <smartShapeMeasMark cmper="3"><shapeNum>9</shapeNum></smartShapeMeasMark>
    </others></finale>""".encode()


@pytest.mark.parametrize(("kind", "octaves"), [("4", -1), ("5", 1), ("20", -2), ("21", 2)])
def test_standard_source_kinds_preserve_staff_and_exact_endpoints(kind: str, octaves: int) -> None:
    assert octaves_by_staff(parse_enigma(_xml(kind))) == {
        2: (OctaveShift(octaves, 3, Fraction(1, 8), 3, Fraction(3, 4)),)
    }


@pytest.mark.parametrize("flag", ["hidden", "entryBased", "lyricBased", "noPresetShape"])
def test_nonvisible_or_unsupported_lines_do_not_shift_notes(flag: str) -> None:
    assert octaves_by_staff(parse_enigma(_xml("5", f"<{flag}/>"))) == {}


def test_palette_linked_part_and_quarantined_shapes_are_not_score_spans() -> None:
    source = _xml("4")
    assert octaves_by_staff(parse_enigma(source), ignored_shapes={9}) == {}
    assert octaves_by_staff(parse_enigma(source.replace(b'cmper="3"', b'cmper="3" part="1"'))) == {}
    assert octaves_by_staff(parse_enigma(source.replace(b'cmper="9"', b'cmper="9" part="1"'))) == {}


def test_a_single_attack_span_is_valid_but_a_reversed_span_is_not() -> None:
    span = octaves_by_staff(parse_enigma(_xml("4", end="512")))[2][0]
    assert span.contains(3, Fraction(1, 8))
    assert not span.contains(3, Fraction(1, 4))
    with pytest.raises(CorruptScoreError, match="reversed octave"):
        octaves_by_staff(parse_enigma(_xml("4", end="511")))


@pytest.mark.parametrize("end", ["-1", "2147483648", "bad"])
def test_hostile_endpoint_values_raise(end: str) -> None:
    with pytest.raises(CorruptScoreError, match="invalid endTermSeg position"):
        octaves_by_staff(parse_enigma(_xml("4", end=end)))
