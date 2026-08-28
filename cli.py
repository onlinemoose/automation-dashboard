"""Run this capability in isolation, straight from a terminal.

    uv run python cli.py --input examples/sample.txt
    echo "some text" | uv run python cli.py

The point of this file: prove the module is useful on its own, with no
other module present.
"""

from __future__ import annotations

import argparse
import sys

from capability import Input, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input",
        type=argparse.FileType("r"),
        default=sys.stdin,
        help="input file (default: read stdin)",
    )
    parser.add_argument(
        "--emphasis",
        action="append",
        default=[],
        metavar="POINT",
        help="a point to emphasise (repeatable)",
    )
    args = parser.parse_args()

    data = Input(text=args.input.read(), emphasis=args.emphasis)
    output = run(data)

    sys.stdout.write(output.result)
    sys.stdout.write("\n")
    if output.rationale:
        sys.stderr.write(f"---\n{output.rationale}\n")


if __name__ == "__main__":
    main()
