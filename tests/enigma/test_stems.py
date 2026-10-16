"""Original two-layer fixtures authored for this project; licensed MIT."""

from fractions import Fraction

from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.mus_document import _others_records
from finale_file_parser.enigma.mus_others import MusOther
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import _voice_order, to_musicxml
from finale_file_parser.ir import Event, Measure, NoteTies, Pitch, Voice

LAYERS = (
    '<layerAtts cmper="0"><freezeLayer/><upStems/></layerAtts>'
    '<layerAtts cmper="1"><freezeLayer/></layerAtts>'
)


def _entry(entnum: int, prev: int, nxt: int, harm: int, flags: str = "", dura: int = 2048) -> str:
    return (
        f'<entry entnum="{entnum}" prev="{prev}" next="{nxt}"><dura>{dura}</dura>'
        f'<numNotes>1</numNotes>{flags}<note id="1"><harmLev>{harm}</harmLev>'
        "<harmAlt>0</harmAlt></note></entry>"
    )


def _document(layer1: str, layer2: str = "", layers: str = LAYERS) -> EnigmaDocument:
    frames = '<frameSpec cmper="1"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>'
    gfhold = "<frame1>1</frame1>"
    if layer2:
        frames += (
            '<frameSpec cmper="2"><startEntry>3</startEntry><endEntry>4</endEntry></frameSpec>'
        )
        gfhold += "<frame2>2</frame2>"
    return parse_enigma(
        f"""<finale><others>{layers}
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>{frames}
    </others><details><gfhold cmper1="1" cmper2="1">{gfhold}</gfhold></details>
    <entries>{layer1}{layer2}</entries></finale>""".encode()
    )


def _stems(document: EnigmaDocument) -> list[str | None]:
    root = ET.fromstring(to_musicxml(build_score(document)))
    return [n.findtext("stem") for n in root.iter("note")]


LOW = _entry(1, 0, 2, -2) + _entry(2, 1, 0, -2)
HIGH = _entry(3, 0, 4, 5) + _entry(4, 3, 0, 5)


def test_a_lone_layer_leaves_its_stems_to_the_reader() -> None:
    assert _stems(_document(LOW)) == [None, None]


def test_frozen_layers_fix_stems_only_while_another_layer_has_notes() -> None:
    assert _stems(_document(LOW, HIGH)) == ["up", "up", "down", "down"]


def test_a_hand_frozen_entry_overrides_its_layer() -> None:
    low = _entry(1, 0, 2, -2, "<freezeStem/>") + _entry(2, 1, 0, -2)
    high = _entry(3, 0, 4, 5, "<freezeStem/><upStem/>") + _entry(4, 3, 0, 5)
    # Layer 1: frozen down, then its layer's up; layer 2: frozen up, then down.
    assert _stems(_document(low, high)) == ["down", "up", "up", "down"]


def test_a_beam_group_takes_its_first_frozen_direction() -> None:
    eighths = _entry(3, 0, 4, 5, "<freezeStem/><upStem/>", dura=512) + _entry(4, 3, 0, 6, dura=512)
    stems = _stems(_document(LOW, eighths))
    assert stems[:2] == ["up", "up"]


def test_unfrozen_layer_settings_fix_nothing() -> None:
    assert _stems(_document(LOW, HIGH, layers="")) == [None] * 4


def test_higher_layer_is_written_as_voice_one() -> None:
    root = ET.fromstring(to_musicxml(build_score(_document(LOW, HIGH))))
    voices = [(n.findtext("pitch/octave"), n.findtext("voice")) for n in root.iter("note")]
    assert voices == [("3", "2"), ("3", "2"), ("4", "1"), ("4", "1")]


def test_voice_order_keeps_numbers_when_a_tie_crosses_the_barline() -> None:
    low = Event(Fraction(1), Fraction(1), (Pitch("C", 4, 0),))
    high = Event(Fraction(1), Fraction(1), (Pitch("C", 5, 0),))
    tied = Event(Fraction(1), Fraction(1), (Pitch("C", 5, 0),), note_ties=(NoteTies(stop=True),))
    assert _voice_order(Measure(1, (Voice(1, (low,)), Voice(2, (high,))))) == {1: 2, 2: 1}
    assert _voice_order(Measure(1, (Voice(1, (low,)), Voice(2, (tied,))))) == {}


def test_mus_layer_settings_decode_freeze_and_direction() -> None:
    records = _others_records(
        (
            MusOther(163, 0, 0, bytes.fromhex("06000000000000000000807f")),
            MusOther(163, 1, 0, bytes.fromhex("faff0000000000000000807b")),
            MusOther(163, 2, 0, bytes.fromhex("000000000000000000000030")),
        ),
        "cp1252",
    )
    fields = [r.fields for r in records if r.tag == "layerAtts"]
    assert fields == [
        {"restOffset": "6", "freezeLayer": "", "upStems": ""},
        {"restOffset": "-6", "freezeLayer": ""},
        {"restOffset": "0"},
    ]
