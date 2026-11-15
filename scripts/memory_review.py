"""Review and retire memories written by episode summaries before v0.58.0.

    python scripts/memory_review.py export            # write the review sheet (reads only)
    python scripts/memory_review.py plan              # show what apply would change
    python scripts/memory_review.py apply --yes       # back up, then expire the rows marked "expire"
    python scripts/memory_review.py restore AUDIT.json

Nothing is deleted. See docs/core/renaissance-memory.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import memory_review  # noqa: E402

DEFAULT_DIR = ROOT / "storage" / "audit" / "memory-review"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--file", type=Path, default=DEFAULT_DIR / "review.csv")
    export.add_argument("--default", choices=sorted(memory_review.ACTIONS), default="expire")
    export.add_argument("--overwrite", action="store_true")
    for name in ("plan", "apply"):
        command = commands.add_parser(name)
        command.add_argument("--file", type=Path, default=DEFAULT_DIR / "review.csv")
    commands.choices["apply"].add_argument("--yes", action="store_true", help="required to change the database")
    commands.add_parser("restore").add_argument("audit", type=Path)
    args = parser.parse_args()

    if args.command == "export":
        if args.file.exists() and not args.overwrite:
            print(f"{args.file} already exists. Pass --overwrite to replace your edits.", file=sys.stderr)
            return 2
        result = memory_review.export(args.file, default_action=args.default)
    elif args.command == "plan":
        planned = memory_review.plan(args.file)
        result = {key: len(value) for key, value in planned.items()}
    elif args.command == "apply":
        if not args.yes:
            print("Nothing changed. Run `plan` first, then pass --yes.", file=sys.stderr)
            return 2
        applied = memory_review.apply(args.file, DEFAULT_DIR)
        result = {key: (len(value) if isinstance(value, list) else value) for key, value in applied.items()}
    else:
        result = memory_review.restore(args.audit)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
