"""Run PETIT Develop ACP initialize diagnostics on the host PC (no login/prompt)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.develop_acp import available, diagnose  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["all", "codex", "antigravity_cli", "claude_code"], default="all")
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args()
    providers = [x["provider"] for x in available()] if args.provider == "all" else [args.provider]
    results = [diagnose(p, timeout=args.timeout) for p in providers]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(x["diagnostic"] in {"initialized", "acp_not_enabled"} for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
