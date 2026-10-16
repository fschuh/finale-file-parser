"""Page-one title blocks; fixtures authored for this project."""

from defusedxml import ElementTree as ET

from finale_file_parser.enigma.document import EnigmaDocument, parse_enigma
from finale_file_parser.enigma.header import page_header
from finale_file_parser.enigma.to_ir import build_score
from finale_file_parser.export.musicxml import to_musicxml


def _document(blocks: list[tuple[str, int, int]], info: dict[str, str]) -> EnigmaDocument:
    others = "".join(
        f'<textBlock cmper="{n}"><textID>{n}</textID><textTag>block</textTag></textBlock>'
        f'<pageTextAssign cmper="1" inci="{n}" sourceFlags="{flags}"><block>{n}</block>'
        f"<ydisp>{y}</ydisp><startPage>1</startPage><endPage>1</endPage></pageTextAssign>"
        for n, (_, flags, y) in enumerate(blocks, start=1)
    )
    texts = "".join(
        f'<blockText number="{n}">{markup}</blockText>'
        for n, (markup, _, _) in enumerate(blocks, start=1)
    ) + "".join(f'<fileInfo type="{k}">{v}</fileInfo>' for k, v in info.items())
    return parse_enigma(
        f"""<finale><others>{others}
      <staffSpec cmper="1"/>
      <measSpec cmper="1"><beats>4</beats><divbeat>1024</divbeat></measSpec>
    </others><texts>{texts}</texts></finale>""".encode()
    )


def test_inserts_take_file_info_and_literal_words_around_them_are_kept() -> None:
    doc = _document(
        [
            ("^legacycmd(99,)&quot;", 40, 0),
            ("^legacycmd(8A,) Masato Nakamura", 20, -200),
            ("^legacycmd(A3,)", 40, -130),
            ("^legacycmd(A2,)\n&amp; Static", 20, -260),
        ],
        {
            "title": '"Spring Yard Zone',
            "composer": "Composed by",
            "subtitle": "Sonic the Hedgehog",
            "arranger": "Arranged by Maelstrom",
        },
    )
    assert page_header(doc) == {
        "title": '"Spring Yard Zone"',
        "subtitle": "Sonic the Hedgehog",
        "composer": "Composed by Masato Nakamura",
        "arranger": "Arranged by Maelstrom\n& Static",
    }


def test_printed_literal_text_overrides_template_placeholders() -> None:
    doc = _document(
        [
            ('^legacycmd(86,01010209)"Fillmore (Act-1)"', 40, 0),
            ("^legacycmd(86,0101010d)ActRaiser", 40, -148),
            ("Composition by Yuzo Koshiro", 276, 3454),
            ("Arrangement by Atcero", 276, 3386),
            ("Enix, Quintet © 1990\nhttps://www.NinSheetMusic.org/", 296, 0),
            ("~ A word to the performer ~", 0, -2554),
        ],
        {"title": '"Title"', "composer": "Composition by Composer", "subtitle": "Game"},
    )
    assert page_header(doc) == {
        "title": '"Fillmore (Act-1)"',
        "subtitle": "ActRaiser",
        "composer": "Composition by Yuzo Koshiro",
        "arranger": "Arrangement by Atcero",
        "copyright": "Enix, Quintet © 1990\nhttps://www.NinSheetMusic.org/",
    }


def test_file_info_fills_roles_the_page_does_not_print() -> None:
    doc = _document([], {"title": "Chocobo", "composer": "Composed by Nobuo Uematsu"})
    assert page_header(doc) == {"title": "Chocobo", "composer": "Composed by Nobuo Uematsu"}


def test_the_header_reaches_identification_and_placed_credits() -> None:
    doc = _document(
        [("^legacycmd(99,)\nMega Man 2", 40, 0), ("^legacycmd(8B,)", 296, 0)],
        {
            "title": '"Air Man Stage"',
            "copyright": "Capcom © 1988",
            "composer": "Composed by Takashi Tateishi",
            "arranger": "Arranged by LeviR.star",
        },
    )
    root = ET.fromstring(to_musicxml(build_score(doc)))
    assert root.findtext("work/work-title") == '"Air Man Stage"'
    creators = {c.get("type"): c.text for c in root.iter("creator")}
    assert creators == {
        "composer": "Composed by Takashi Tateishi",
        "arranger": "Arranged by LeviR.star",
    }
    assert root.findtext("identification/rights") == "Capcom © 1988"
    credits = {
        tuple(t.text for t in c.findall("credit-type")): c.findtext("credit-words")
        for c in root.iter("credit")
    }
    assert credits == {
        ("title",): '"Air Man Stage"',
        ("subtitle",): "Mega Man 2",
        ("composer", "arranger"): "Composed by Takashi Tateishi\nArranged by LeviR.star",
        ("rights",): "Capcom © 1988",
    }
    assert all(w.get("default-y") for w in root.iter("credit-words"))
    assert root.find("defaults/page-layout/page-height") is not None


def test_page_placed_performance_notes_are_kept_apart_from_the_title_block() -> None:
    from finale_file_parser.enigma.header import page_notes

    doc = _document(
        [
            ("^legacycmd(99,)", 40, 0),
            ("Optional: Echo the\r\nsecond eighth", 256, 1947),
            ("Arranged by Sam Waetford", 256, 1800),
        ],
        {"title": '"Memories of Green"'},
    )
    assert page_notes(doc) == ((1, "Optional: Echo the second eighth"),)
    assert page_header(doc)["arranger"] == "Arranged by Sam Waetford"
