"""An authored pickup voice keeps silence as position, not extra written music."""

from fractions import Fraction

from defusedxml import ElementTree as DET

from finale_file_parser.enigma.document import parse_enigma
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def test_delayed_eighth_and_independent_whole_rest_reach_musicxml() -> None:
    raw = b"""<finale version="18.0" xmlns="http://www.makemusic.com/2012/finale">
      <others>
        <frameSpec cmper="10" inci="0"><startTime>3584</startTime></frameSpec>
        <frameSpec cmper="10" inci="1"><startEntry>1</startEntry><endEntry>1</endEntry></frameSpec>
        <frameSpec cmper="11"><startEntry>2</startEntry><endEntry>2</endEntry></frameSpec>
        <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
      </others><details>
        <gfhold cmper1="1" cmper2="1"><frame1>10</frame1><frame2>11</frame2></gfhold>
      </details><entries>
        <entry entnum="1" prev="0" next="0"><dura>512</dura><numNotes>1</numNotes>
          <note><harmLev>0</harmLev><harmAlt>0</harmAlt></note></entry>
        <entry entnum="2" prev="0" next="0"><dura>4096</dura><numNotes>0</numNotes></entry>
      </entries>
    </finale>"""
    score = build_score(parse_enigma(raw))
    first, second = score.parts[0].measures[0].voices
    assert first.start_offset == Fraction(7, 8) and second.start_offset == 0
    assert len(first.events) == 1 and first.events[0].written_duration == Fraction(1, 8)
    root = DET.fromstring(to_musicxml(score))
    assert root.findtext("part/measure/forward/duration") == "7"
    assert root.findtext("part/measure/backup/duration") == "8"
    assert root.findtext("part/measure/note/type") == "eighth"
    assert len(root.findall("part/measure/note")) == 2
