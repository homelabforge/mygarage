#!/usr/bin/env python3
"""Capture Home Assistant README screenshots via the ha-integration-screenshots skill."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SKILL_SCRIPT = (
    Path.home()
    / ".cursor/skills/ha-integration-screenshots/scripts/capture_ha_screenshots.py"
)
REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if not SKILL_SCRIPT.is_file():
        print(
            f"Skill script not found: {SKILL_SCRIPT}\n"
            "Install the ha-integration-screenshots skill under ~/.cursor/skills/.",
            file=sys.stderr,
        )
        return 1
    return subprocess.call(
        [sys.executable, str(SKILL_SCRIPT), "--repo-root", str(REPO_ROOT), *sys.argv[1:]],
    )


if __name__ == "__main__":
    raise SystemExit(main())
