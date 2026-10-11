"""Authored XML tests for source-driven, precisely positioned hairpin spans."""

from __future__ import annotations

from fractions import Fraction

import pytest

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.hairpins import hairpins_by_staff
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.ir import Hairpin


def _shape(
    *,
    kind: str = "cresc",
    attrs: str = "",
    flags: str = "",
    start_staff: str = "1",
    end_staff: str = "1",
    start_measure: str = "1",
    end_measure: str = "2",
    start_edu: str = "512",
    end_edu: str = "3072",
    start_adjustment: str = "",
    end_adjustment: str = "",
) -> str:
    return f"""
      <smartShape cmper="7"{attrs}>
        <shapeType>{kind}</shapeType>{flags}
        <startTermSeg><endPt>
          <inst>{start_staff}</inst><meas>{start_measure}</meas><edu>{start_edu}</edu>
        </endPt>{start_adjustment}</startTermSeg>
        <endTermSeg><endPt>
          <inst>{end_staff}</inst><meas>{end_measure}</meas><edu>{end_edu}</edu>
        </endPt>{end_adjustment}</endTermSeg>
      </smartShape>
    """


_MARK = '<smartShapeMeasMark cmper="1"><shapeNum>7</shapeNum></smartShapeMeasMark>'


def _document(shape: str = "", marks: str = _MARK) -> EnigmaDocument:
    # Independently authored whole-note pitches keep the IR pipeline executable;
    # measure 2 is silent and acquires its existing full-measure rest.
    return parse_enigma(
        f"""
      <finale><others>
        <staffSpec cmper="1"/><staffSpec cmper="2"/>
        <instUsed cmper="0" inci="0"><inst>1</inst></instUsed>
        <instUsed cmper="0" inci="1"><inst>2</inst></instUsed>
        <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
        <measSpec cmper="2"><beats>4</beats><divbeat>1024</divbeat></measSpec>
        <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
        <frameSpec cmper="2"><startEntry>2</startEntry><endEntry>2</endEntry></frameSpec>
        {shape}{marks}
      </others><details>
        <gfhold cmper1="1" cmper2="1"><frame1>1</frame1><clefID>0</clefID></gfhold>
        <gfhold cmper1="2" cmper2="1"><frame1>2</frame1><clefID>0</clefID></gfhold>
      </details><entries>
        <entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
          <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
        </entry>
        <entry entnum="2" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
          <note><harmLev>-7</harmLev><harmAlt>0</harmAlt></note>
        </entry>
      </entries></finale>
    """.encode()
    )


@pytest.mark.parametrize(("source", "kind"), [("cresc", "crescendo"), ("decresc", "diminuendo")])
def test_named_hairpins_preserve_fractional_positions_across_measures(
    source: str, kind: str
) -> None:
    assert hairpins_by_staff(_document(_shape(kind=source))) == {
        1: (Hairpin(kind, 1, Fraction(1, 8), 2, Fraction(3, 4)),)
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "slurAuto"},
        {"kind": "unknown"},
        {"attrs": ' part="1"'},
        {"flags": "<hidden/>"},
        {"flags": "<noPresetShape/>"},
        {"flags": "<entryBased/>"},
        {"flags": "<lyricBased/>"},
    ],
)
def test_other_or_unsupported_shapes_do_not_become_hairpins(kwargs: dict[str, str]) -> None:
    assert hairpins_by_staff(_document(_shape(**kwargs))) == {}


def test_definitions_without_score_measure_assignments_do_not_place_hairpins() -> None:
    assert hairpins_by_staff(_document(_shape(), marks="")) == {}
    linked = _MARK.replace('cmper="1"', 'cmper="1" part="1"')
    assert hairpins_by_staff(_document(_shape(), marks=linked)) == {}


def test_a_missing_definition_or_center_only_assignment_does_not_invent_a_span() -> None:
    assert hairpins_by_staff(_document()) == {}
    center = _MARK.replace("shapeNum", "centerShapeNum")
    assert hairpins_by_staff(_document(_shape(), marks=center)) == {}


def test_multiple_measure_marks_and_linked_part_copies_resolve_one_score_span() -> None:
    marks = _MARK + _MARK.replace('cmper="1"', 'cmper="2"')
    shapes = _shape() + _shape(attrs=' part="1"')
    assert hairpins_by_staff(_document(shapes, marks)) == {
        1: (Hairpin("crescendo", 1, Fraction(1, 8), 2, Fraction(3, 4)),)
    }


def test_an_omitted_default_edu_is_zero_and_a_barline_endpoint_is_retained() -> None:
    shape = _shape(start_edu="0", end_measure="1", end_edu="4096")
    shape = shape.replace("<edu>0</edu>", "")
    assert hairpins_by_staff(_document(shape)) == {
        1: (Hairpin("crescendo", 1, Fraction(0), 1, Fraction(1)),)
    }


def test_cross_staff_shapes_are_not_misattributed_to_the_start_staff() -> None:
    assert hairpins_by_staff(_document(_shape(end_staff="2"))) == {}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_staff": "0"},
        {"end_staff": "-1"},
        {"start_measure": "nonsense"},
        {"end_measure": "0"},
        {"start_edu": "-1"},
        {"end_edu": "2147483648"},
        {"start_edu": "nonsense"},
    ],
)
def test_malformed_recognized_positions_raise_a_clear_error(kwargs: dict[str, str]) -> None:
    with pytest.raises(CorruptScoreError, match="invalid .* position"):
        hairpins_by_staff(_document(_shape(**kwargs)))


def test_missing_termination_points_and_entry_numbers_are_not_read_as_edu() -> None:
    with pytest.raises(CorruptScoreError, match="missing startTermSeg.endPt"):
        hairpins_by_staff(_document(_shape().replace("startTermSeg", "unknownSeg")))
    with pytest.raises(CorruptScoreError, match="invalid .* position"):
        hairpins_by_staff(_document(_shape().replace("<edu>512</edu>", "<entryNum>512</entryNum>")))


@pytest.mark.parametrize(("measure", "edu"), [("1", "512"), ("1", "0")])
def test_zero_length_and_reversed_spans_raise_a_clear_error(measure: str, edu: str) -> None:
    with pytest.raises(CorruptScoreError, match="end must follow"):
        hairpins_by_staff(_document(_shape(end_measure=measure, end_edu=edu)))


def test_ir_retains_staff_identity_and_spans_over_silent_measures() -> None:
    document = _document(_shape(start_staff="2", end_staff="2"))
    score = build_score(document)
    assert score.parts[0].hairpins == ()
    assert score.parts[1].hairpins == (Hairpin("crescendo", 1, Fraction(1, 8), 2, Fraction(3, 4)),)
    assert score.parts[1].measures[1].voices[0].events[0].is_measure_rest
    assert tuple(part.measures for part in score.parts) == tuple(
        part.measures for part in build_score(_document(marks="")).parts
    )


def test_active_horizontal_adjustments_keep_exact_space_units_and_metric_endpoints() -> None:
    shape = _shape(
        start_adjustment="<endPtAdj><on/><x>12</x><y>-144</y></endPtAdj>",
        end_adjustment="<endPtAdj><on/><x>-37</x><y>-144</y></endPtAdj>",
    )
    assert hairpins_by_staff(_document(shape)) == {
        1: (
            Hairpin(
                "crescendo", 1, Fraction(1, 8), 2, Fraction(3, 4), Fraction(1, 2), Fraction(-37, 24)
            ),
        )
    }
    assert tuple(part.measures for part in build_score(_document(shape)).parts) == tuple(
        part.measures for part in build_score(_document(_shape())).parts
    )


def test_inactive_and_omitted_horizontal_adjustments_leave_layout_automatic() -> None:
    shape = _shape(
        start_adjustment="<endPtAdj><x>120</x></endPtAdj>",
        end_adjustment="<endPtAdj><on/><y>-144</y></endPtAdj>",
    )
    assert hairpins_by_staff(_document(shape)) == hairpins_by_staff(_document(_shape()))


@pytest.mark.parametrize("value", ["nonsense", "1.5", "", "2147483648", "-2147483649"])
def test_malformed_active_horizontal_adjustments_fail_clearly(value: str) -> None:
    shape = _shape(end_adjustment=f"<endPtAdj><on/><x>{value}</x></endPtAdj>")
    with pytest.raises(CorruptScoreError, match="invalid endTermSeg horizontal adjustment"):
        hairpins_by_staff(_document(shape))


def test_malformed_adjustment_container_does_not_become_automatic_layout() -> None:
    with pytest.raises(CorruptScoreError, match="invalid endTermSeg.endPtAdj"):
        hairpins_by_staff(_document(_shape(end_adjustment="<endPtAdj>bad</endPtAdj>")))
