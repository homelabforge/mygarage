#!/usr/bin/env python3
"""Phase 3 unit-decision enumerator for the MyGarage frontend.

Re-runnable, takes no hand-picked file list. It walks every ``*.ts`` / ``*.tsx``
file under ``frontend/src`` (discovered, not enumerated) and reports every
lexical site where a unit decision is made.

Usage::

    python3 frontend/scripts/inventory.py [REPO_ROOT] [--json] [--prod-only]

REPO_ROOT defaults to the repository this file lives in.

Every filter rule applied is printed in the FILTERS block of the output so that
a reader can reproduce or widen it. Nothing is hand-excluded by filename.

R9 (2026-08-27): pass B used to run **only on lines that also mentioned a unit
morpheme**, so a bare conversion constant on a line with no unit word was
invisible to the whole script. It therefore missed a third ``1609.34`` at
``pages/ShopFinder.tsx`` while dutifully reporting the POIFinder and LeafletMap
copies, which made this enumerator the thirteenth floor-wearing-an-inventory's-
name in the units workstream, and the one written specifically to stop them.

The morpheme test is now an ANNOTATION, not a filter: every numeric literal in
every file is reported, and rows whose line carries a unit morpheme are tagged
``[CTX]``. Nothing that used to appear has disappeared; the signal that used to
gate the pass now only ranks it. The cost is a much larger pass-B section, which
is the honest price of removing a filter that was hiding real findings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# frontend/scripts/inventory.py -> frontend/scripts -> frontend -> repo root.
DEFAULT_ROOT = Path(__file__).resolve().parents[2]
SRC_REL = Path("frontend/src")
EXTS = {".ts", ".tsx"}


# --------------------------------------------------------------------------
# file discovery
# --------------------------------------------------------------------------
def discover(src: Path) -> list[Path]:
    """Return every TypeScript source file under ``src``, sorted, no exclusions."""
    return sorted(p for p in src.rglob("*") if p.suffix in EXTS and p.is_file())


def is_test(path: Path) -> bool:
    """True when the file is a test file (``__tests__`` dir or ``.test.``/``.spec.``)."""
    return "__tests__" in path.parts or ".test." in path.name or ".spec." in path.name


# --------------------------------------------------------------------------
# section 1: numeric conversion constants
# --------------------------------------------------------------------------
# Pass A: any decimal literal with >= 3 fractional digits. Chosen because every
# unit conversion factor in common use carries more precision than a UI
# constant (opacity, delay, percentage) ever does. Discovers factors nobody
# listed.
NUM_HI = re.compile(r"(?<![\w.$])(\d+\.\d{3,})(?![\w.])")

# Pass B: any numeric literal at all, ANYWHERE. Catches low-precision factors
# (25.4, 1.8, 9/5, 32, 1000) that pass A cannot see.
#
# R9: this pass used to be gated on UNIT_CONTEXT matching the SAME LINE, which
# made a bare `const METERS_PER_MILE = 1609.34` invisible. The gate is gone; the
# morpheme test survives only as the `[CTX]` annotation on each row.
#
# Lookbehind also rejects `,` `:` `#` `-` so that "9,999,999", "00:00", "#3B82F6"
# and Tailwind "grid-cols-1" do not manufacture phantom factors.
NUM_ANY = re.compile(r"(?<![\w.$,:#-])(\d+(?:\.\d+)?)(?![\w.])")
# Spans to ignore in pass B: Tailwind class soup is all numbers and no units.
CLASSNAME_RX = re.compile(r"""className=(?:"[^"]*"|'[^']*'|\{`[^`]*`\})""")
# Ranking signal only since R9, never a filter. A row whose line matches is
# tagged [CTX]; a row whose line does not is still reported.
UNIT_CONTEXT = re.compile(
    r"(?i)\b("
    r"mm|millimet\w*|cm|centimet\w*|inch\w*|"
    r"km|kilomet\w*|mile\w*|mi\b|"
    r"psi|kpa|bar|pascal|pressure|"
    r"gal|gallon\w*|lit(?:er|re)s?|quart\w*|"
    r"lb|lbs|pound\w*|kg|kilogram\w*|ounce\w*|"
    r"celsius|fahrenheit|temp\w*|"
    r"mpg|l100|consumption|economy|"
    r"nm|lbft|torque|"
    r"speed|kmh|mph|"
    r"tread|odometer|displacement|"
    r"imperial|metric|convert\w*|_TO_|feet|foot|meter\w*|metre\w*"
    r")\b"
)
# Pass B noise floor: literals that are structurally never conversion factors.
B_TRIVIAL = {"0", "1", "2", "3", "10", "100"}


def scan_constants(files: list[Path], src: Path) -> dict:
    hi: list[dict] = []
    lo: list[dict] = []
    for path in files:
        rel = str(path.relative_to(src.parent.parent))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            for m in NUM_HI.finditer(line):
                hi.append(
                    {
                        "file": rel,
                        "line": i,
                        "value": m.group(1),
                        "text": stripped,
                        "test": is_test(path),
                    }
                )
            # R9: no UNIT_CONTEXT gate. Every literal is reported; the morpheme
            # test only tags the row.
            skip = [(m.start(), m.end()) for m in CLASSNAME_RX.finditer(line)]
            ctx = bool(UNIT_CONTEXT.search(line))
            for m in NUM_ANY.finditer(line):
                v = m.group(1)
                if v in B_TRIVIAL:
                    continue
                if any(a <= m.start() < b for a, b in skip):
                    continue
                if NUM_HI.fullmatch(v):  # already in pass A
                    continue
                lo.append(
                    {
                        "file": rel,
                        "line": i,
                        "value": v,
                        "text": stripped,
                        "test": is_test(path),
                        "unit_context": ctx,
                    }
                )
    return {"pass_a_high_precision": hi, "pass_b_unit_context": lo}


# --------------------------------------------------------------------------
# section 2: imperial branching
# --------------------------------------------------------------------------
PATTERNS_BRANCH = {
    "isImperial_declaration": re.compile(
        r"\b(?:const|let|var)\s+isImperial\b|isImperial\s*[:=]\s*(?!=)"
    ),
    "isImperial_ternary": re.compile(r"\bisImperial\s*\?"),
    "isImperial_other": re.compile(r"\bisImperial\b"),
    "system_eq_imperial_ternary": re.compile(r"system\s*===\s*'imperial'\s*\?"),
    "system_eq_imperial_all": re.compile(r"system\s*===\s*'imperial'"),
    "system_neq_imperial": re.compile(r"system\s*!==\s*'imperial'"),
    "eq_imperial_any_lhs": re.compile(r"===\s*'imperial'"),
    "neq_imperial_any_lhs": re.compile(r"!==\s*'imperial'"),
    "eq_metric_any_lhs": re.compile(r"===\s*'metric'"),
    "neq_metric_any_lhs": re.compile(r"!==\s*'metric'"),
    "unit_preference_literal": re.compile(
        r"unit_preference|unitPreference|unitSystem|UnitSystem"
    ),
}


def scan_lines(files: list[Path], src: Path, patterns: dict) -> dict:
    out: dict[str, list[dict]] = {k: [] for k in patterns}
    for path in files:
        rel = str(path.relative_to(src.parent.parent))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for name, rx in patterns.items():
                n = len(rx.findall(line))
                if n:
                    out[name].append(
                        {
                            "file": rel,
                            "line": i,
                            "n": n,
                            "text": line.strip(),
                            "test": is_test(path),
                        }
                    )
    return out


# --------------------------------------------------------------------------
# section 3: imports of the unit modules
# --------------------------------------------------------------------------
# Keyed by the LAST TWO path segments so that `utils/units` and `types/units`
# (two different modules whose basename is identical) never merge into one count.
# ★ THIS LIST AND `SYMBOL_RX` BELOW ARE TWO HALVES OF ONE INVENTORY AND MUST MOVE
# TOGETHER. Fix round 1 of phase 3b task 5 caught them out of step: `SYMBOL_RX`
# gained `seedUnitField` and `canonicalFromUnitField` when the deleted binary
# helpers came out of it, but `utils/unitFormat`, the module that DECLARES both,
# was never added here. The symbol scan and the module scan then disagreed about
# which files matter, which is the quieter half of the same failure the deleted
# helpers were: a count that looks complete because each half was measured
# honestly on its own.
UNIT_MODULES = [
    "utils/units",
    "types/units",
    "utils/telemetryUnits",
    "utils/supplyUnits",
    "utils/decimalSafe",
    "utils/unitFormat",
    # `utils/gallonStandardStore` sat here until phase 4 task 5 deleted the
    # module. Removed rather than kept: a name left in this list after its
    # module is gone cannot match anything, so it does not inflate a count, but
    # it does make the list read as an inventory of what exists when it is
    # really an inventory of what was once looked for.
    "hooks/useUnitPreference",
    "utils/formatUtils",
]
IMPORT_RX = re.compile(r"""^\s*(?:import|export)\b[^\n]*?from\s+['"]([^'"]+)['"]""")
SYMBOL_RX = re.compile(
    # `toCanonicalKm`, `toCanonicalKg` and `toCanonicalMeters` were listed here
    # until phase 3b task 5 deleted them under ruling R8, and `toCanonicalLiters`
    # and the exported `priceToCanonical` until task 7 did the same to them under
    # R4. A name kept in this alternation after its symbol is gone cannot match
    # anything, so it does not inflate a count, but it does make the list read as
    # an inventory of what exists when it is really an inventory of what was once
    # looked for. The pair that replaced them, `seedPriceField` and
    # `canonicalFromPriceField`, is listed instead, beside the quantity pair.
    r"\b(UnitFormatter|UnitConverter|useUnitPreference|convertTelemetryValue|priceToDisplay|toLitersWirePrecision|seedUnitField|canonicalFromUnitField|seedPriceField|canonicalFromPriceField|canonicalToDisplay|displayToCanonical|supplyUnitLabel)\b"
)


def _resolve_module(spec: str, importer: Path, src: Path) -> str:
    """Resolve an import specifier to a `dir/name` key relative to frontend/src.

    Relative specifiers are resolved against the importing file's directory and
    `@/` against `src`, so `./units` inside `utils/` and `../utils/units` and
    `@/utils/units` all collapse to the same key. Bare package specifiers are
    returned unchanged (they never match UNIT_MODULES).
    """
    if spec.startswith("@/"):
        target = (src / spec[2:]).resolve()
    elif spec.startswith("."):
        target = (importer.parent / spec).resolve()
    else:
        return spec
    try:
        rel = target.relative_to(src)
    except ValueError:
        return spec
    return "/".join(rel.parts[-2:]) if len(rel.parts) >= 2 else str(rel)


def scan_imports(files: list[Path], src: Path) -> dict:
    imports: dict[str, list[dict]] = defaultdict(list)
    symbols: dict[str, list[dict]] = defaultdict(list)
    for path in files:
        rel = str(path.relative_to(src.parent.parent))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = IMPORT_RX.match(line)
            if m:
                spec = m.group(1)
                base = _resolve_module(spec, path, src)
                if base in UNIT_MODULES:
                    imports[base].append(
                        {
                            "file": rel,
                            "line": i,
                            "spec": spec,
                            "text": line.strip(),
                            "test": is_test(path),
                        }
                    )
            for s in SYMBOL_RX.findall(line):
                symbols[s].append(
                    {
                        "file": rel,
                        "line": i,
                        "text": line.strip(),
                        "test": is_test(path),
                    }
                )
    return {"by_module": dict(imports), "by_symbol": dict(symbols)}


# --------------------------------------------------------------------------
# section 4: hardcoded unit labels
# --------------------------------------------------------------------------
# Any quoted or template-embedded token whose *whole* content matches a
# unit-label shape. Discovered by shape, not by a supplied list.
UNIT_LABEL_SHAPE = re.compile(
    r"""^(?:
        PSI|psi|kPa|kpa|KPA|bar|Bar|
        mm|cm|m|in|inch|inches|ft|feet|
        km|mi|mile|miles|kilometers|kilometres|
        L|l|mL|ml|gal|gals|gallon|gallons|qt|quart|quarts|
        kg|lb|lbs|g|oz|
        MPG|mpg|km/L|km/l|L/100km|l/100km|L/100\ km|MPGe|
        C|F|°C|°F|
        Nm|N·m|lb-ft|lbft|lb\ ft|ft-lb|
        mph|km/h|kmh|kph|rpm|RPM|
        \$/L|\$/gal|\$/km|\$/mi|
        %|V|s|hr|h
    )$""",
    re.X,
)
QUOTED_RX = re.compile(r"""'([^'\\\n]{1,12})'|"([^"\\\n]{1,12})\"""")
# ` ... ${x} mm` and `${x} km` style template suffixes
TEMPLATE_UNIT_RX = re.compile(r"\}\s?([A-Za-z°/$%]{1,8})(?=`|\s|\})")
# JSX text node immediately after an expression: {expr} mm<
JSX_TAIL_RX = re.compile(r"\}\s?([A-Za-z°/%]{1,8})\s*(?:<|\{)")
# i18n interpolation carrying a unit value
I18N_UNIT_RX = re.compile(
    r"\bt\(\s*['\"][^'\"]+['\"]\s*,\s*\{[^}]*\b(unit|units)\b\s*:"
)


def scan_labels(files: list[Path], src: Path) -> dict:
    quoted: list[dict] = []
    template: list[dict] = []
    jsx: list[dict] = []
    i18n: list[dict] = []
    for path in files:
        rel = str(path.relative_to(src.parent.parent))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            for m in QUOTED_RX.finditer(line):
                tok = m.group(1) if m.group(1) is not None else m.group(2)
                if tok and UNIT_LABEL_SHAPE.match(tok):
                    quoted.append(
                        {
                            "file": rel,
                            "line": i,
                            "token": tok,
                            "text": s,
                            "test": is_test(path),
                        }
                    )
            for m in TEMPLATE_UNIT_RX.finditer(line):
                if UNIT_LABEL_SHAPE.match(m.group(1)):
                    template.append(
                        {
                            "file": rel,
                            "line": i,
                            "token": m.group(1),
                            "text": s,
                            "test": is_test(path),
                        }
                    )
            for m in JSX_TAIL_RX.finditer(line):
                if UNIT_LABEL_SHAPE.match(m.group(1)):
                    jsx.append(
                        {
                            "file": rel,
                            "line": i,
                            "token": m.group(1),
                            "text": s,
                            "test": is_test(path),
                        }
                    )
            if I18N_UNIT_RX.search(line):
                i18n.append({"file": rel, "line": i, "text": s, "test": is_test(path)})
    return {
        "quoted": quoted,
        "template_suffix": template,
        "jsx_tail": jsx,
        "i18n_unit_interp": i18n,
    }


# --------------------------------------------------------------------------
# section 5: unit-bearing identifiers crossing the boundary
# --------------------------------------------------------------------------
SUFFIX_RX = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*)_(km|kpa|kPa|mm|cm|l|liters|litres|c|f|psi|kg|lbs|mi|miles|nm|bar|ml|gal|kwh|percent|hours|per_unit)\b"
)
CAMEL_RX = re.compile(
    r"\b([a-z][A-Za-z0-9]*)(Km|Kpa|KPa|Mm|Psi|Kg|Lbs|Liters|Litres|Miles|Nm|Bar|Mph|Kmh|L100km)\b"
)
BARE_RX = re.compile(
    r"\b(liters|litres|gallons|price_per_unit|pricePerUnit|tread_depth_mm|treadDepthMm|mileage|odometer_reading|odometerReading)\b"
)


def scan_fields(files: list[Path], src: Path) -> dict:
    suffix = Counter()
    suffix_sites: dict[str, list[str]] = defaultdict(list)
    camel = Counter()
    camel_sites: dict[str, list[str]] = defaultdict(list)
    bare = Counter()
    for path in files:
        rel = str(path.relative_to(src.parent.parent))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in SUFFIX_RX.finditer(line):
                key = f"{m.group(1)}_{m.group(2)}"
                suffix[key] += 1
                if len(suffix_sites[key]) < 500:
                    suffix_sites[key].append(f"{rel}:{i}")
            for m in CAMEL_RX.finditer(line):
                key = m.group(1) + m.group(2)
                camel[key] += 1
                if len(camel_sites[key]) < 500:
                    camel_sites[key].append(f"{rel}:{i}")
            for m in BARE_RX.finditer(line):
                bare[m.group(1)] += 1
    return {
        "snake_suffix": {
            "counts": dict(suffix.most_common()),
            "sites": dict(suffix_sites),
        },
        "camel_suffix": {
            "counts": dict(camel.most_common()),
            "sites": dict(camel_sites),
        },
        "bare_names": dict(bare.most_common()),
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def hr(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def dump_rows(rows: list[dict], key: str | None = None, show_text: bool = True) -> None:
    for r in rows:
        tag = " [TEST]" if r.get("test") else ""
        # R9: pass-B rows carry the unit-morpheme signal as a tag rather than
        # having been filtered out by it.
        if r.get("unit_context"):
            tag += " [CTX]"
        extra = f"  {r[key]}" if key else ""
        txt = f"  |  {r['text']}" if show_text else ""
        print(f"  {r['file']}:{r['line']}{extra}{tag}{txt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(DEFAULT_ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--prod-only", action="store_true", help="drop rows in test files")
    args = ap.parse_args()

    root = Path(args.root)
    src = root / SRC_REL
    if not src.is_dir():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 2

    files = discover(src)
    if args.prod_only:
        files = [f for f in files if not is_test(f)]
    prod = [f for f in files if not is_test(f)]

    result = {
        "root": str(root),
        "files_total": len(files),
        "files_production": len(prod),
        "files_test": len(files) - len(prod),
        "constants": scan_constants(files, src),
        "branching": scan_lines(files, src, PATTERNS_BRANCH),
        "imports": scan_imports(files, src),
        "labels": scan_labels(files, src),
        "fields": scan_fields(files, src),
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("MyGarage frontend unit-decision inventory")
    print(f"root            : {root}")
    print(f"scanned         : {src}  (**/*.ts, **/*.tsx, recursive, no exclusions)")
    print(
        f"files           : {result['files_total']} total "
        f"({result['files_production']} production, {result['files_test']} test)"
    )
    print()
    print("FILTERS APPLIED (all of them, so any number here is reproducible):")
    print(
        "  S1 pass A : decimal literals with >= 3 fractional digits. No context filter."
    )
    print("  S1 pass B : any numeric literal ANYWHERE (R9: the UNIT_CONTEXT gate is")
    print("              gone; a matching line is only tagged [CTX]), minus literals")
    print(
        f"              in {sorted(B_TRIVIAL)} and minus anything pass A already has."
    )
    print("  S2        : regex per row, counted per-occurrence (n) not per-line.")
    print("  S3        : `import ... from '<path>'` whose basename is one of")
    print(f"              {UNIT_MODULES}; plus bare symbol occurrences.")
    print(
        "  S4        : quoted tokens <= 12 chars whose WHOLE content matches a unit-label"
    )
    print("              shape; template `${x} UNIT` suffixes; JSX `{x} UNIT<` tails;")
    print("              t(key, { unit: ... }) interpolations.")
    print(
        "  S5        : identifiers with a unit suffix (snake or camel) + a bare-name list."
    )
    print("  Test files are INCLUDED and tagged [TEST]; per-section counts give both.")

    # ---- section 1
    hi = result["constants"]["pass_a_high_precision"]
    lo = result["constants"]["pass_b_unit_context"]
    hr("S1. NUMERIC CONVERSION CONSTANTS -- pass A (>= 3 fractional digits)")
    byval = Counter(r["value"] for r in hi)
    print(
        f"  occurrences: {len(hi)}  (production {sum(1 for r in hi if not r['test'])}, "
        f"test {sum(1 for r in hi if r['test'])})"
    )
    byval_prod = Counter(r["value"] for r in hi if not r["test"])
    print(
        f"  distinct values: {len(byval)}  (in >=1 production file: {len(byval_prod)})"
    )
    print()
    print("  PRODUCTION-ONLY value histogram -- this is the phase-3 work list:")
    for val, n in sorted(byval_prod.items(), key=lambda kv: (-kv[1], kv[0])):
        fl = sorted({r["file"] for r in hi if r["value"] == val and not r["test"]})
        print(f"    {val:<16} x{n:<3} {', '.join(fl)}")
    print()
    print("  ALL sites, grouped by value:")
    for val, n in sorted(byval.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  --- {val}  ({n} occurrence{'s' if n != 1 else ''})")
        dump_rows([r for r in hi if r["value"] == val])
    hr("S1. NUMERIC CONVERSION CONSTANTS -- pass B (any literal, anywhere)")
    byval_b = Counter(r["value"] for r in lo)
    print(
        f"  occurrences: {len(lo)}  (production {sum(1 for r in lo if not r['test'])}, "
        f"test {sum(1 for r in lo if r['test'])})"
    )
    print(f"  distinct values: {len(byval_b)}")
    ctx_n = sum(1 for r in lo if r["unit_context"])
    print(
        f"  of those, on a line carrying a unit morpheme: {ctx_n} "
        f"(the pre-R9 pass reported ONLY these)"
    )
    print()
    print("  PRODUCTION-ONLY value histogram (fractional literals first -- an integer")
    print("  is rarely a conversion factor, but none are hidden, only ordered later):")
    byval_b_prod = Counter(r["value"] for r in lo if not r["test"])
    for val, n in sorted(
        byval_b_prod.items(), key=lambda kv: ("." not in kv[0], -kv[1], kv[0])
    ):
        fl = sorted({r["file"] for r in lo if r["value"] == val and not r["test"]})
        print(f"    {val:<16} x{n:<3} {', '.join(fl)}")
    print()
    print("  ALL sites, grouped by value:")
    for val, n in sorted(byval_b.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  --- {val}  ({n})")
        dump_rows([r for r in lo if r["value"] == val])

    # ---- section 2
    hr("S2. IMPERIAL BRANCHING")
    for name, rows in result["branching"].items():
        total = sum(r["n"] for r in rows)
        prod_n = sum(r["n"] for r in rows if not r["test"])
        nfiles = len({r["file"] for r in rows})
        print()
        print(
            f"  === {name}: {total} occurrences across {nfiles} files "
            f"(production {prod_n}, test {total - prod_n})"
        )
        if name == "unit_preference_literal":
            fc = Counter(r["file"] for r in rows)
            for f, c in sorted(fc.items()):
                print(f"    {f}: {c} lines")
            continue
        dump_rows(rows)

    # ---- section 3
    hr("S3. IMPORTS OF UNIT MODULES")
    for mod in UNIT_MODULES:
        rows = result["imports"]["by_module"].get(mod, [])
        print()
        print(
            f"  === '{mod}': {len(rows)} importers "
            f"(production {sum(1 for r in rows if not r['test'])})"
        )
        dump_rows(rows, show_text=True)
    print()
    print("  --- symbol occurrences (not import lines) ---")
    for sym, rows in sorted(result["imports"]["by_symbol"].items()):
        nf = len({r["file"] for r in rows})
        print(
            f"  {sym}: {len(rows)} occurrences in {nf} files "
            f"(production {sum(1 for r in rows if not r['test'])})"
        )
    print()
    for sym, rows in sorted(result["imports"]["by_symbol"].items()):
        print(f"  === {sym}")
        dump_rows(rows)

    # ---- section 4
    hr("S4. HARDCODED UNIT LABELS")
    for kind, rows in result["labels"].items():
        print()
        print(
            f"  === {kind}: {len(rows)} occurrences in {len({r['file'] for r in rows})} files "
            f"(production {sum(1 for r in rows if not r['test'])})"
        )
        if kind != "i18n_unit_interp":
            tc = Counter(r["token"] for r in rows)
            tp = Counter(r["token"] for r in rows if not r["test"])
            print(
                f"      tokens (all) : {dict(sorted(tc.items(), key=lambda kv: (-kv[1], kv[0])))}"
            )
            print(
                f"      tokens (prod): {dict(sorted(tp.items(), key=lambda kv: (-kv[1], kv[0])))}"
            )
        dump_rows(rows)

    # ---- section 5
    hr("S5. UNIT-BEARING IDENTIFIERS")
    for kind in ("snake_suffix", "camel_suffix"):
        blk = result["fields"][kind]
        print()
        print(
            f"  === {kind}: {len(blk['counts'])} distinct names, "
            f"{sum(blk['counts'].values())} occurrences"
        )
        for name, n in blk["counts"].items():
            sites = blk["sites"][name]
            nf = len({s.rsplit(":", 1)[0] for s in sites})
            print(f"    {name}: {n} occurrences in {nf} files")
    print()
    print(f"  === bare_names: {result['fields']['bare_names']}")
    print()
    print("  --- full site list, snake_suffix ---")
    for name, sites in sorted(result["fields"]["snake_suffix"]["sites"].items()):
        print(f"  {name}:")
        for s in sites:
            print(f"    {s}")
    print()
    print("  --- full site list, camel_suffix ---")
    for name, sites in sorted(result["fields"]["camel_suffix"]["sites"].items()):
        print(f"  {name}:")
        for s in sites:
            print(f"    {s}")

    # ---- section 6: per-file density (production files only)
    hr("S6. PER-FILE UNIT-DECISION DENSITY (production files only)")
    density: Counter = Counter()
    for r in hi + lo:
        if not r["test"]:
            density[r["file"]] += 1
    for rows in result["branching"].values():
        for r in rows:
            if not r["test"]:
                density[r["file"]] += r["n"]
    for kind in ("quoted", "template_suffix", "jsx_tail", "i18n_unit_interp"):
        for r in result["labels"][kind]:
            if not r["test"]:
                density[r["file"]] += 1
    print(
        "  (sum of S1A + S1B + S2 + S4 hits per file; a ranking, not a work estimate)"
    )
    print(f"  files with >=1 hit: {len(density)}")
    for f, n in density.most_common():
        loc = len((root / f).read_text(encoding="utf-8").splitlines())
        print(f"    {n:>5}  ({loc:>5} loc)  {f}")

    hr("HEADLINE COUNTS")
    b = result["branching"]
    print(f"  files scanned                          : {result['files_total']}")
    print(
        f"  S1A high-precision constants           : {len(hi)} occurrences, {len(byval)} distinct values"
    )
    print(
        f"  S1B unit-context low-precision numbers : {len(lo)} occurrences, {len(byval_b)} distinct"
    )
    print(
        f"  isImperial (all)                       : {sum(r['n'] for r in b['isImperial_other'])} in "
        f"{len({r['file'] for r in b['isImperial_other']})} files"
    )
    print(
        f"  isImperial ?  (ternary)                : {sum(r['n'] for r in b['isImperial_ternary'])} in "
        f"{len({r['file'] for r in b['isImperial_ternary']})} files"
    )
    print(
        f"  system === 'imperial' (all)            : {sum(r['n'] for r in b['system_eq_imperial_all'])} in "
        f"{len({r['file'] for r in b['system_eq_imperial_all']})} files"
    )
    print(
        f"  system === 'imperial' ? (ternary)      : {sum(r['n'] for r in b['system_eq_imperial_ternary'])} in "
        f"{len({r['file'] for r in b['system_eq_imperial_ternary']})} files"
    )
    print(
        f"  system !== 'imperial'                  : {sum(r['n'] for r in b['system_neq_imperial'])}"
    )
    print(
        f"  === 'imperial' (any LHS)               : {sum(r['n'] for r in b['eq_imperial_any_lhs'])} in "
        f"{len({r['file'] for r in b['eq_imperial_any_lhs']})} files"
    )
    print(
        f"  !== 'imperial' (any LHS)               : {sum(r['n'] for r in b['neq_imperial_any_lhs'])}"
    )
    print(
        f"  === 'metric' (any LHS)                 : {sum(r['n'] for r in b['eq_metric_any_lhs'])} in "
        f"{len({r['file'] for r in b['eq_metric_any_lhs']})} files"
    )
    print(
        f"  !== 'metric' (any LHS)                 : {sum(r['n'] for r in b['neq_metric_any_lhs'])}"
    )
    for mod in UNIT_MODULES:
        rows = result["imports"]["by_module"].get(mod, [])
        print(
            f"  importers of '{mod}'".ljust(41)
            + f": {len({r['file'] for r in rows})} files, {len(rows)} import stmts"
        )
    lb = result["labels"]
    print(
        f"  hardcoded unit labels (quoted)         : {len(lb['quoted'])} in "
        f"{len({r['file'] for r in lb['quoted']})} files"
    )
    print(
        f"  hardcoded unit labels (template tail)  : {len(lb['template_suffix'])} in "
        f"{len({r['file'] for r in lb['template_suffix']})} files"
    )
    print(
        f"  hardcoded unit labels (JSX tail)       : {len(lb['jsx_tail'])} in "
        f"{len({r['file'] for r in lb['jsx_tail']})} files"
    )
    print(
        f"  t(key, {{unit: ...}}) interpolations     : {len(lb['i18n_unit_interp'])} in "
        f"{len({r['file'] for r in lb['i18n_unit_interp']})} files"
    )
    print(
        f"  unit-suffixed snake identifiers        : {len(result['fields']['snake_suffix']['counts'])} distinct"
    )
    print(
        f"  unit-suffixed camel identifiers        : {len(result['fields']['camel_suffix']['counts'])} distinct"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
