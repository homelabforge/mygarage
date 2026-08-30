#!/usr/bin/env bun
/**
 * Every sentence in the repo's Markdown that makes a claim about units.
 *
 * ★ WHY A TOOL FOR PROSE. `docs/UNIT_CONVERSION.md` described a DIFFERENT
 * APPLICATION: a two-system model storing Imperial units, with a schema
 * (`mileage INTEGER -- Stored in miles`, `gallons REAL`) that has not existed
 * since `6f04e53` made storage metric-canonical. The repo is public, so a
 * contributor greps that file and builds the wrong thing. It had been fixed
 * "surgically" twice, and both times the fix was a floor, because both times
 * the claims were picked by hand out of 434 lines.
 *
 * ★ SO THE PICKING IS MECHANICAL AND THE JUDGING IS NOT. This prints every
 * line matching a claim vocabulary, with its file and line number, and says
 * nothing about whether the claim is true: verifying one against the code is a
 * human's job, and a tool that pretended otherwise would be one people learn
 * to override. What it guarantees is that no line matching the vocabulary goes
 * UNSEEN, which is the failure mode both surgical passes hit.
 *
 * ★ IT SCANS EVERY MARKDOWN FILE IN THE REPO, not one document. A claim about
 * Imperial storage is exactly as wrong in `README.md` as in
 * `docs/UNIT_CONVERSION.md`, and scoping a scanner to the file you already
 * suspect is how the second file goes unnoticed. Fenced code blocks are
 * scanned too and LABELLED as code, because the false schema was inside one.
 *
 * Usage:
 *   bun run scripts/enumerate-doc-unit-claims.ts             # every file
 *   bun run scripts/enumerate-doc-unit-claims.ts docs/X.md   # one file
 *   bun run scripts/enumerate-doc-unit-claims.ts --json
 * Exit code: 0 always. A measuring instrument, not a gate.
 */

import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import { ROOT } from './translation-utils'

/** The repository root: `frontend/scripts` -> `frontend` -> the repo. */
const REPO = join(ROOT, '..')

/**
 * Directories never walked, and why.
 *
 * Dependencies, build output and virtualenvs are not this repo's prose. Every
 * DOT-directory is excluded for a different reason: `.superpowers/` and
 * `.claude/` hold task briefs and reports, which are records of what was true
 * at a moment rather than claims about the code as it stands. Including them
 * put 2,800 lines of history in front of the 200 that a contributor actually
 * greps, which is how a real finding gets missed. `.github/` templates come
 * back in only if somebody puts a unit claim in one, so they stay out too.
 */
const SKIP_DIRS = new Set(['node_modules', 'dist', 'build', '.venv', 'coverage'])

/** Whether a directory entry is a dot-directory. See `SKIP_DIRS`. */
function isHidden(entry: string): boolean {
  return entry.startsWith('.')
}

/**
 * The claim vocabulary, grouped so a reader can see WHY a line was pulled.
 *
 * ★ Each group is a kind of assertion this workstream has found wrong in prose,
 * not a keyword somebody liked. `storage` catches "stored in miles";
 * `canonicality` catches the word this repo uses for the thing that inverted;
 * `system` catches the two-system framing that per-quantity units replaced;
 * `backend` catches claims about where conversion happens; `schema` catches
 * DDL and column names, which is the form the false claim took last time.
 *
 * Deliberately over-broad. A tool for finding claims you have to judge should
 * over-report: a false positive costs one line of reading, and a miss costs
 * another contributor building the wrong thing.
 */
const VOCABULARY: readonly { group: string; pattern: RegExp }[] = [
  { group: 'storage', pattern: /\b(stored?|stores|storage|persist(s|ed)?)\b/i },
  { group: 'canonicality', pattern: /\bcanonical\b/i },
  { group: 'system', pattern: /\b(imperial|metric)\b/i },
  { group: 'backend', pattern: /\b(backend|API|endpoint|server[- ]side)\b/ },
  {
    group: 'schema',
    pattern:
      /\b(CREATE TABLE|ALTER TABLE|INTEGER|REAL|NUMERIC|VARCHAR|column|table|mileage|gallons?|liters?|litres?|_km\b|_kg\b|kpa|l_per_100km)\b/i,
  },
  { group: 'unit-name', pattern: /\b(MPG|L\/100km|PSI|km\/h|mph|lb-ft|Nm|kPa)\b/ },
]

/** One line that makes, or looks like it makes, a claim about units. */
interface Claim {
  file: string
  line: number
  /** Which vocabulary groups matched. */
  groups: string[]
  /** True when the line is inside a fenced code block. */
  inCode: boolean
  text: string
}

/**
 * POSIX-style path relative to the repository root.
 *
 * @param absolute An absolute path inside the tree.
 * @returns The relative path, with forward slashes on every platform.
 */
function rel(absolute: string): string {
  return relative(REPO, absolute).split(sep).join('/')
}

/**
 * Every Markdown file in the repository.
 *
 * @param dir The directory to walk.
 * @param out The accumulator.
 * @returns Absolute paths, sorted per directory.
 */
function markdownFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir).sort()) {
    if (SKIP_DIRS.has(entry) || isHidden(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) markdownFiles(full, out)
    else if (entry.endsWith('.md')) out.push(full)
  }
  return out
}

/**
 * Scan one file for claim-bearing lines.
 *
 * @param path The file to scan.
 * @returns One entry per matching line, and the file's total line count.
 */
function scan(path: string): { claims: Claim[]; lines: number } {
  const lines = readFileSync(path, 'utf-8').split('\n')
  const claims: Claim[] = []
  let inCode = false
  lines.forEach((text, i) => {
    if (/^\s*```/.test(text)) {
      inCode = !inCode
      return
    }
    if (text.trim() === '') return
    const groups = VOCABULARY.filter(({ pattern }) => pattern.test(text)).map((v) => v.group)
    if (groups.length > 0) {
      claims.push({ file: rel(path), line: i + 1, groups, inCode, text: text.trim() })
    }
  })
  return { claims, lines: lines.length }
}

function main(): void {
  const args = process.argv.slice(2).filter((a) => a !== '--json')
  const files =
    args.length > 0 ? args.map((a) => join(REPO, a)) : markdownFiles(REPO)

  const perFile = files.map((path) => ({ path, ...scan(path) }))
  const total = perFile.reduce((n, f) => n + f.claims.length, 0)

  if (process.argv.includes('--json')) {
    console.log(
      JSON.stringify(
        {
          vocabulary: VOCABULARY.map((v) => ({ group: v.group, pattern: String(v.pattern) })),
          files: perFile.map((f) => ({ file: rel(f.path), lines: f.lines, claims: f.claims })),
        },
        null,
        1,
      ),
    )
    return
  }

  console.log('\nSCOPE: every line of every .md in the repository, minus node_modules, dist,')
  console.log('  build, .venv, coverage and every DOT-directory (.superpowers and .claude are')
  console.log('  task history, not documentation), matched against a unit-claim vocabulary.')
  console.log('  CANDIDATES, not verdicts: whether a claim is TRUE is checked against the')
  console.log('  code by hand. The guarantee is that no matching line goes unseen.\n')
  console.log('  vocabulary:')
  for (const { group, pattern } of VOCABULARY) {
    console.log(`    ${group.padEnd(14)} ${String(pattern)}`)
  }
  console.log(`\n  ${files.length} file(s), ${total} claim-bearing line(s):\n`)
  for (const f of perFile) {
    if (f.claims.length === 0) continue
    console.log(`  ${String(f.claims.length).padStart(4)} / ${String(f.lines).padStart(4)} lines  ${rel(f.path)}`)
  }
  console.log('')
  for (const f of perFile) {
    if (f.claims.length === 0) continue
    console.log(`  ── ${rel(f.path)} ──`)
    for (const c of f.claims) {
      console.log(`  :${String(c.line).padEnd(5)} ${c.inCode ? '[code]' : '[prose]'} <${c.groups.join(' ')}>`)
      console.log(`      ${c.text.slice(0, 150)}`)
    }
    console.log('')
  }
}

main()
