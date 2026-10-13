"""Run through make audit-corpus; external inputs are never modified."""

import argparse
from pathlib import Path

from .runner import AuditOptions, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--musescore", type=Path)
    args = parser.parse_args()
    try:
        result = audit(AuditOptions(args.root, args.output, args.schema, args.musescore))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Audit failed: {error}\n")
    rows = result["cases"]
    assert isinstance(rows, list)
    return int(any("failure" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
