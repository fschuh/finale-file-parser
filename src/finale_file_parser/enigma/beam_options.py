"""The evidenced document beam settings, separate from stored group boundaries."""

from finale_file_parser.enigma.beams import RestBeams
from finale_file_parser.enigma.document import EnigmaDocument


def rest_beams(document: EnigmaDocument) -> RestBeams | None:
    for record in document.options.of_tag("beamOptions"):
        if "part" not in record.attrs:
            return RestBeams(
                extend_edges="incEdgeRestsInBeamGroups" in record.fields,
                extend_secondary="extendSecBeamsOverRests" in record.fields,
            )
    return None
