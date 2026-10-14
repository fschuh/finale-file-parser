"""Original custom-ending labels and hostile text authored here, licensed MIT."""

from dataclasses import replace
from fractions import Fraction

import pytest
from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import TAG_REPEAT_ENDING_TEXT, MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml
from finale_file_parser.ir import Ending, Event, Measure, Part, Pitch, Score, TimeSignature, Voice


def _document(label: str = "1.", *, part: bool = False) -> bytes:
    scope = ' part="1"' if part else ""
    return f'''<finale><others><staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat><barEnding/><bacRepBar/></measSpec>
      <repeatEndingStart cmper="1"/>
      <repeatPassList cmper="1"><act>1</act><act>3</act></repeatPassList>
      <repeatEndingText cmper="1"{scope}><rptText>{label}</rptText></repeatEndingText>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold></details>
    <entries><entry entnum="1" prev="0" next="0"><dura>4096</dura><numNotes>1</numNotes>
      <isValid/><isNote/><note id="1"><harmLev>0</harmLev><harmAlt>0</harmAlt></note>
    </entry></entries></finale>'''.encode()


@pytest.mark.parametrize("label", ["1.", "last time", ""])
def test_explicit_label_keeps_playback_passes_independently(label: str) -> None:
    score = build_score(parse_enigma(_document(label)))
    endings = score.parts[0].measures[0].endings
    assert [(e.numbers, e.type, e.text) for e in endings] == [
        ((1, 3), "start", label),
        ((1, 3), "stop", label),
    ]
    nodes = ET.fromstring(to_musicxml(score)).findall(".//ending")
    assert [n.get("number") for n in nodes] == ["1,3", "1,3"]
    assert [(n.text or "") for n in nodes] == [label, label]


def test_linked_part_label_does_not_override_score_default() -> None:
    score = build_score(parse_enigma(_document("parts only", part=True)))
    assert score.parts[0].measures[0].endings[0].text is None
    assert ET.fromstring(to_musicxml(score)).findtext(".//ending") == "1., 3."


def test_label_uses_scalar_text_instead_of_stringifying_a_nested_record() -> None:
    with pytest.raises(CorruptScoreError, match="repeatEndingText.*scalar"):
        build_score(parse_enigma(_document("<unexpected/>")))


@pytest.mark.parametrize("year", [2011, 2012, None])
def test_numeric_label_is_aligned_unicode_and_retains_measure_scope(year: int | None) -> None:
    payload = "é reprise\0".encode("utf-16-le") + bytes(8)
    record = _others_records(
        (MusOther(TAG_REPEAT_ENDING_TEXT, 7, 0, payload),), "cp1252", year=year
    )[0]
    assert record.tag == "repeatEndingText" and record.attrs == {"cmper": "7"}
    assert record.fields == {"rptText": "é reprise"}
    override = _others_records(
        (MusOther(TAG_REPEAT_ENDING_TEXT, 7, 2, payload),), "cp1252", year=year
    )[0]
    assert override.attrs == {"cmper": "7", "part": "2"}


@pytest.mark.parametrize("payload", [b"a", b"\x00\xd8", b"\x01\x00", b"\xff\xff"])
def test_malformed_label_fails_clearly(payload: bytes) -> None:
    with pytest.raises(CorruptScoreError, match="repeatEndingText"):
        _others_records((MusOther(TAG_REPEAT_ENDING_TEXT, 1, 0, payload),), "cp1252")


def _native_score() -> Score:
    """Three original bars with different printed labels and playable pass lists."""
    event = Event(Fraction(1), Fraction(1), (Pitch("C", 4, 0),))
    measure = Measure(1, (Voice(1, (event,)),), time=TimeSignature(4, 4))
    return Score(
        (
            Part(
                "P1",
                "Authored",
                (
                    replace(measure, repeat_forward=True),
                    replace(
                        measure,
                        number=2,
                        repeat_backward=True,
                        repeat_passes=4,
                        endings=(Ending((1, 3), "start", "1."), Ending((1, 3), "stop", "1.")),
                    ),
                    replace(
                        measure,
                        number=3,
                        endings=(
                            Ending((2, 4), "start", "2."),
                            Ending((2, 4), "discontinue", "2."),
                        ),
                    ),
                ),
            ),
        )
    )
