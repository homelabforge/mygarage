#!/usr/bin/env python3
"""Mutation harness that proves each mutant is a real mutant before scoring it.

Round 1's harness scored a mutant that did not PARSE as a clean survivor: it
read vitest's `Tests  no tests` as zero failures. The rule derived from that was
never mechanised, and `recheck2.py`'s `assert names or failed == 0` was vacuous
-- it passes in exactly the case it was meant to catch (names empty AND
failed == 0). These three checks CAN fire, and each one is exercised on purpose
by `selftest.py` before any real mutation runs:

  1. PATTERN  the search text occurs exactly once
  2. COMPILES `tsc --noEmit` reports no SYNTAX error for the mutated file
  3. TOTAL    the run reports a nonzero test total, and it equals the baseline

Check 3 is what makes a zero meaningful: `failed == 0` is only "no test catches
this" when `total == BASELINE`. Any other total is an error, not a survivor.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# frontend/scripts/mutation_harness.py -> frontend/scripts -> frontend -> root.
REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"

# Syntax-level diagnostics. A TYPE error is a legitimate mutant (vitest
# transpiles without checking); a SYNTAX error means the mutant never ran.
SYNTAX_CODES = (
    "TS1002",
    "TS1003",
    "TS1005",
    "TS1109",
    "TS1128",
    "TS1131",
    "TS1136",
    "TS1381",
    "TS1382",
)

FAIL_RX = re.compile(r"^\s*× (.+?)(?: \d+ms)?$")
TOTAL_RX = re.compile(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed \((\d+)\)")


class MutantError(RuntimeError):
    """The mutant is not a valid experiment, so its result means nothing."""


def compiles(path: Path) -> tuple[bool, str]:
    """True when tsc reports no SYNTAX error. Type errors are allowed."""
    p = subprocess.run(
        ["bunx", "tsc", "--noEmit"], cwd=FRONTEND, capture_output=True, text=True
    )
    out = p.stdout + p.stderr
    for line in out.splitlines():
        if any(code in line for code in SYNTAX_CODES):
            return False, line.strip()
    return True, ""


def run_suite() -> tuple[int, int, list[str]]:
    """Return (failed, total, failing test names) from a full vitest run."""
    p = subprocess.run(
        ["bunx", "vitest", "run", "--reporter=verbose"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
    )
    out = p.stdout + p.stderr
    names = sorted(
        {
            m.group(1).strip()
            for m in (FAIL_RX.match(ln) for ln in out.splitlines())
            if m
        }
    )
    failed = total = 0
    for line in out.splitlines():
        m = TOTAL_RX.search(line)
        if m:
            failed = int(m.group(1) or 0)
            total = int(m.group(3))
    return failed, total, names


def score(mid: str, path: Path, old: str, new: str, baseline: int) -> dict:
    """Apply one mutation, verify it is a real mutant, score it, restore."""
    src = path.read_text()
    n = src.count(old)
    if n != 1:
        raise MutantError(f"{mid}: PATTERN occurs {n} times, expected exactly 1")
    path.write_text(src.replace(old, new))
    try:
        ok, diag = compiles(path)
        if not ok:
            raise MutantError(f"{mid}: DOES NOT COMPILE ({diag})")
        failed, total, names = run_suite()
        if total == 0:
            raise MutantError(f"{mid}: TOTAL is 0, the suite did not run")
        if total != baseline:
            raise MutantError(f"{mid}: TOTAL {total} != baseline {baseline}")
    finally:
        path.write_text(src)
    return {"failed": failed, "total": total, "names": names}


def main(mutations: list[tuple[str, Path, str, str]], baseline: int, log: Path) -> int:
    results: dict[str, dict] = {}
    with log.open("w") as fh:
        for mid, path, old, new in mutations:
            try:
                r = score(mid, path, old, new, baseline)
            except MutantError as exc:
                print(f"{mid}: ERROR {exc}", flush=True)
                fh.write(f"\n===== {mid}: ERROR {exc} =====\n")
                results[mid] = {"error": str(exc)}
                continue
            results[mid] = r
            fh.write(
                f"\n===== {mid}: {r['failed']} killed (total {r['total']}) =====\n"
            )
            for nm in r["names"]:
                fh.write(f"  {nm}\n")
            fh.flush()
            print(f"{mid}: {r['failed']} killed of {r['total']}", flush=True)
    log.with_suffix(".json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
