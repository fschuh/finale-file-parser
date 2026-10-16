"""Original authored C/D score layouts, licensed under the repository MIT license."""

from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def test_a_resting_active_staff_survives_ir_and_musicxml() -> None:
    document = parse_enigma(b"""
    <finale version="18.0">
      <options><clefOptions>
        <clefDef><clefChar>38</clefChar><adjust>-10</adjust></clefDef>
        <clefDef><clefChar>63</clefChar><adjust>2</adjust></clefDef>
      </clefOptions></options>
      <others>
        <instUsed cmper="0" inci="0"><inst>1</inst></instUsed>
        <instUsed cmper="0" inci="1"><inst>2</inst></instUsed>
        <staffSpec cmper="1"/>
        <staffSpec cmper="2"><defaultClef>1</defaultClef></staffSpec>
        <staffSpec cmper="3"/>
        <staffSpec cmper="32767"/>
        <measSpec cmper="1"><beats>2</beats><divbeat>1024</divbeat></measSpec>
        <measSpec cmper="2"><beats>2</beats><divbeat>1024</divbeat></measSpec>
        <frameSpec cmper="1"><startEntry>1</startEntry><endEntry>2</endEntry></frameSpec>
      </others>
      <details>
        <gfhold cmper1="1" cmper2="1"><frame1>1</frame1></gfhold>
        <staffGroup cmper1="0" cmper2="1"><startInst>1</startInst><endInst>2</endInst>
          <bracket><id>3</id></bracket><groupBarlineStyle>group</groupBarlineStyle>
        </staffGroup>
      </details>
      <entries>
        <entry entnum="1" prev="0" next="2"><dura>1024</dura><numNotes>1</numNotes>
          <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>
        <entry entnum="2" prev="1" next="0"><dura>1024</dura><numNotes>1</numNotes>
          <note><harmLev>1</harmLev><harmAlt>0</harmAlt></note></entry>
      </entries>
    </finale>
    """)
    score = build_score(document)
    assert [p.id for p in score.parts] == ["P1", "P2"]
    assert score.groups[0].part_ids == ("P1", "P2")
    bass = score.parts[1]
    assert (bass.measures[0].clef_sign, bass.measures[0].clef_line) == ("F", 4)
    assert [m.number for m in bass.measures] == [1, 2]
    assert all(m.voices[0].events[0].is_measure_rest for m in bass.measures)
    root = ET.fromstring(to_musicxml(score))
    # The piano brace joins the staves; the resting bass is staff 2 of the part.
    assert len(root.findall("part")) == 1
    assert root.findtext("part/measure/attributes/clef[@number='2']/sign") == "F"
    rests = [n for n in root.iter("note") if n.find("rest[@measure='yes']") is not None]
    assert [n.findtext("staff") for n in rests].count("2") == 2
    assert [
        n.findtext("pitch/step") for n in root.findall(".//note") if n.find("pitch") is not None
    ] == ["C", "D"]
