#!/usr/bin/env python3
"""Make each of mutation_harness.py's guards fail ON PURPOSE, plus a control.

A guard that has never fired is a guard nobody has tested. Round 1's harness had
one that could not fire at all, so this file exists before any real mutation is
scored.

★ The fixtures are OWNED BY THIS FILE, not borrowed from production source.
The first version patched an `odometer_km: toCanonicalKm(..., system)` line in
`DEFRecordForm.tsx`, and Task 3d then DELETED that line -- so the PATTERN guard
began firing first and the COMPILES guard, the one that exists to fix round 1's
actual defect, silently stopped being exercised. A gate's own self-test must not
depend on code the gate's subject is free to delete. Everything below is created
and removed by this script, so no change to the repo can rot it.

The baseline is DERIVED by running the suite once with the fixtures in place,
for the same reason: the previous version took a hardcoded 1792 on the command
line, which was already stale by the time the fixtures changed.
"""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "harness", Path(__file__).parent / "mutation_harness.py"
)
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

# Fixtures this script owns outright.
FIX_SRC = H.FRONTEND / "src/__selftest_fixture__.ts"
FIX_TEST = H.FRONTEND / "src/__tests__/__selftest_fixture__.test.ts"

FIX_SRC_BODY = """/** Fixture owned by scratchpad selftest.py. Created and deleted per run. */
export const SELFTEST_ALPHA = 1
export const SELFTEST_BETA = 2
export function selftestSum(): number {
  return SELFTEST_ALPHA + SELFTEST_BETA
}
"""

FIX_TEST_BODY = """import { describe, it, expect } from 'vitest'
import { SELFTEST_ALPHA, selftestSum } from '../__selftest_fixture__'

describe('selftest fixture', () => {
  it('alpha is one', () => { expect(SELFTEST_ALPHA).toBe(1) })
  it('sums to three', () => { expect(selftestSum()).toBe(3) })
})
"""


def main() -> int:
    FIX_SRC.write_text(FIX_SRC_BODY)
    FIX_TEST.write_text(FIX_TEST_BODY)
    failures: list[str] = []
    try:
        _, base, _ = H.run_suite()
        print(f"derived baseline with fixtures in place: {base}\n")
        if base == 0:
            print("cannot derive a baseline; aborting")
            return 1

        cases = [
            # 1. PATTERN: text that occurs zero times.
            ("SELF-PATTERN-0", FIX_SRC, "NOT_IN_THE_FIXTURE", "x", "PATTERN occurs 0"),
            # 2. PATTERN: text that occurs more than once.
            (
                "SELF-PATTERN-2",
                FIX_SRC,
                "SELFTEST_ALPHA",
                "SELFTEST_ALPHA",
                "PATTERN occurs",
            ),
            # 3. COMPILES: round 1's actual defect, a replacement that drops the
            #    opening of a call and leaves a dangling paren.
            (
                "SELF-SYNTAX",
                FIX_SRC,
                "  return SELFTEST_ALPHA + SELFTEST_BETA",
                "  return (SELFTEST_ALPHA +",
                "DOES NOT COMPILE",
            ),
            # 4. TOTAL: a module-scope throw. Syntactically valid and it
            #    type-checks, so it passes guards 1-3 and only the total pin can
            #    catch it. A RENAME was tried first and was a BAD probe: it kills
            #    tests while the total holds, because vitest still collects the
            #    files. The hazard is a suite that did not run the same tests.
            (
                "SELF-TOTAL",
                FIX_TEST,
                "describe('selftest fixture', () => {",
                "throw new Error('SELFTEST')\ndescribe('selftest fixture', () => {",
                "TOTAL",
            ),
        ]

        for mid, path, old, new, expect in cases:
            try:
                r = H.score(mid, path, old, new, base)
                failures.append(
                    f"{mid}: guard did NOT fire, scored {r['failed']}/{r['total']}"
                )
                print(f"{mid}: *** GUARD DID NOT FIRE *** {r['failed']}/{r['total']}")
            except H.MutantError as exc:
                got = str(exc)
                ok = expect in got
                print(f"{mid}: {'fired' if ok else '*** WRONG GUARD ***'} -> {got}")
                if not ok:
                    failures.append(f"{mid}: expected {expect!r}, got {got!r}")

        # 5. POSITIVE CONTROL. Guards that always fire are as useless as guards
        #    that never do, so one genuine mutant must score cleanly: it has to
        #    compile, run the full baseline, and kill exactly the fixture test
        #    that asserts the value it changes.
        try:
            r = H.score(
                "SELF-VALID",
                FIX_SRC,
                "export const SELFTEST_ALPHA = 1",
                "export const SELFTEST_ALPHA = 99",
                base,
            )
            ok = r["failed"] == 2 and r["total"] == base
            print(
                f"SELF-VALID: {'scored cleanly' if ok else '*** UNEXPECTED ***'} -> "
                f"{r['failed']} killed of {r['total']}"
            )
            if not ok:
                failures.append(f"SELF-VALID: expected 2 killed of {base}, got {r}")
        except H.MutantError as exc:
            print(f"SELF-VALID: *** GUARD FIRED ON A VALID MUTANT *** {exc}")
            failures.append(f"SELF-VALID: {exc}")
    finally:
        FIX_SRC.unlink(missing_ok=True)
        FIX_TEST.unlink(missing_ok=True)

    print()
    if failures:
        print("SELFTEST: FAILURES")
        for f in failures:
            print("  " + f)
        return 1
    print("SELFTEST: ALL FOUR GUARDS FIRED, AND A VALID MUTANT SCORED CLEANLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
