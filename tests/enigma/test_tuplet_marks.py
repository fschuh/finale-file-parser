"""Tuplet counts and notations; fixtures authored for this project."""

from fractions import Fraction

from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.enigma.tuplet import EntryChain, Tuplet, tuplet_positions
from finale_file_parser.export.musicxml import _tuplet_notations, to_musicxml
from finale_file_parser.ir import Beam, Event, Pitch, TupletMark


def _document(count: int, dura: int, tuplet: str, beam: bool = True) -> EnigmaDocument:
    entries = "".join(
        f'<entry entnum="{n}" prev="{n - 1}" next="{n + 1 if n < count else 0}">'
        f"<dura>{dura}</dura><numNotes>1</numNotes>"
        f"{'<beam/>' if beam and n == 1 else ''}"
        f'<note id="1"><harmLev>{n}</harmLev><harmAlt>0</harmAlt></note></entry>'
        for n in range(1, count + 1)
    )
    return parse_enigma(
        f"""<finale><others>
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>{count}</endEntry></frameSpec>
    </others><details><gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>{tuplet}
    </details><entries>{entries}</entries></finale>""".encode()
    )


SEXTUPLET = (
    '<tupletDef entnum="1"><symbolicNum>6</symbolicNum><symbolicDur>256</symbolicDur>'
    "<refNum>1</refNum><refDur>1024</refDur><numberStyle>1</numberStyle></tupletDef>"
)


def test_a_sextuplet_keeps_its_six_in_the_time_of_four() -> None:
    root = ET.fromstring(to_musicxml(build_score(_document(6, 256, SEXTUPLET))))
    notes = root.findall(".//note")
    assert {
        (n.findtext("time-modification/actual-notes"), n.findtext("time-modification/normal-notes"))
        for n in notes
    } == {("6", "4")}
    marks = [
        [(t.get("type"), t.get("bracket"), t.get("show-number")) for t in n.iter("tuplet")]
        for n in notes
    ]
    assert marks[0] == [("start", "no", "actual")] and marks[-1] == [("stop", "no", "actual")]
    assert all(m == [] for m in marks[1:-1])


def test_a_hidden_number_is_written_as_none() -> None:
    hidden = SEXTUPLET.replace("<numberStyle>1</numberStyle>", "<numberStyle>0</numberStyle>")
    root = ET.fromstring(to_musicxml(build_score(_document(6, 256, hidden))))
    assert {t.get("show-number") for t in root.iter("tuplet")} == {"none"}


def test_positions_open_on_the_defining_entry_and_close_when_the_span_is_used() -> None:
    triplet = Tuplet(3, 512, 2, 512)
    chain = EntryChain(order=(1, 2, 3, 4), written_edu={1: 512, 2: 512, 3: 512, 4: 512})
    positions = tuplet_positions(chain, {1: (triplet,)})
    assert positions == {
        1: ((triplet, True, False),),
        2: ((triplet, False, False),),
        3: ((triplet, False, True),),
    }


def test_unbeamed_tuplets_are_bracketed_and_beamed_ones_are_not() -> None:
    def note(start: bool, stop: bool, beam: str | None) -> Event:
        return Event(
            Fraction(1, 6),
            Fraction(1, 4),
            (Pitch("C", 4, 0),),
            tuplet_ratio=Fraction(2, 3),
            tuplets=(TupletMark(3, 2, Fraction(1, 4), start=start, stop=stop),),
            beams=(Beam(1, beam),) if beam else (),
        )

    unbeamed = (note(True, False, None), note(False, False, None), note(False, True, None))
    assert _tuplet_notations(unbeamed) == {
        0: (("start", 1, True, "actual"),),
        2: (("stop", 1, True, "actual"),),
    }
    beamed = (note(True, False, "begin"), note(False, False, "continue"), note(False, True, "end"))
    assert _tuplet_notations(beamed)[0] == (("start", 1, False, "actual"),)


def test_a_grace_note_has_no_time_modification() -> None:
    graced = parse_enigma(
        b"<finale><others><staffSpec cmper='1'/>"
        b"<measSpec cmper='1'><beats>1</beats><divbeat>1024</divbeat></measSpec>"
        b"<frameSpec cmper='1'><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>"
        b"</others><details><gfhold cmper1='1' cmper2='1'><frame1>1</frame1></gfhold>"
        b"</details><entries>"
        b"<entry entnum='1' prev='0' next='2'><dura>512</dura><numNotes>1</numNotes>"
        b"<graceNote/><note id='1'><harmLev>1</harmLev><harmAlt>0</harmAlt></note></entry>"
        b"<entry entnum='2' prev='1' next='0'><dura>1024</dura><numNotes>1</numNotes>"
        b"<note id='1'><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>"
        b"</entries></finale>"
    )
    root = ET.fromstring(to_musicxml(build_score(graced)))
    assert root.find(".//note/grace") is not None
    assert root.find(".//time-modification") is None
