"""Recover per-note enharmonic flips and respell the notes they mark.

Finale stores a note's "Enharmonic Respell" as a flag on its notehead
modification (detail 1058, ``FCNoteheadMod.EnharmonicFlip``), not in the note's
own harmonic level. The note keeps its default spelling in the entry and is drawn
with the other spelling, so the flag has to be applied for the written pitch to
match the printed page.
"""

from collections import defaultdict
from dataclasses import replace

from finale_file_parser.enigma.document import EnigmaDocument, field_int
from finale_file_parser.enigma.models import CorruptScoreError
from finale_file_parser.enigma.music import read_entry
from finale_file_parser.enigma.pitch import SpelledPitch

_LETTERS = "CDEFGAB"
_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def enharmonic_notes_by_entry(document: EnigmaDocument) -> dict[int, frozenset[int]]:
    """Chord indices of the flipped notes, by entry; linked-part records place nothing."""
    result: dict[int, set[int]] = defaultdict(set)
    for record in document.details.of_tag("noteheadMod"):
        if "part" in record.attrs or "enharmonic" not in record.fields:
            continue
        entnum = field_int(record.attrs.get("entnum"))
        if entnum is None:
            raise CorruptScoreError("notehead modification has an invalid entry")
        entry = document.entries.get(entnum)
        if entry is None:
            continue
        note_id = field_int(record.fields.get("noteID"))
        indices = [i for i, n in enumerate(read_entry(entry).notes) if n.note_id == note_id]
        if note_id is None or note_id <= 0 or len(indices) != 1:
            raise CorruptScoreError("notehead modification has an invalid or ambiguous note ID")
        result[entnum].add(indices[0])
    return {entnum: frozenset(indices) for entnum, indices in result.items()}


def flip_enharmonic(pitch: SpelledPitch) -> SpelledPitch:
    """The same sounding pitch under the neighbouring letter.

    A sharpened note moves to the letter above (C#4 -> Db4), a flattened one to
    the letter below (Bb3 -> A#3). A natural moves toward the nearer letter --
    the one a semitone away (E -> Fb, F -> E#, B -> Cb, C -> B#); a natural with
    a whole tone on both sides (D, G, A) moves up to a double flat, as Finale's
    flip does with its default spelling tables.
    """
    index = _LETTERS.index(pitch.letter)
    if pitch.alteration > 0:
        step = 1
    elif pitch.alteration < 0:
        step = -1
    else:
        step = -1 if pitch.letter in "CF" else 1
    target = index + step
    letter = _LETTERS[target % 7]
    octave = pitch.octave + target // 7
    midi = 12 * pitch.octave + _SEMITONE[pitch.letter] + pitch.alteration
    alteration = midi - (12 * octave + _SEMITONE[letter])
    return replace(pitch, letter=letter, alteration=alteration, octave=octave)
