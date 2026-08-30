#!/usr/bin/env bun
/**
 * The unit-audit manifest: a REVIEWED SNAPSHOT, digest-pinned, over a STATED
 * universe (plan 2026-08-28-units-phase3b, ruling R9).
 *
 * ★ WHAT THIS IS NOT, first, because five plan revisions got it wrong.
 *
 * This is NOT a completeness check and it cannot become one. The unit defects
 * in this codebase have no common lexical form: `formatVolume(units)` is
 * correct and `formatVolumePerDistance(units)` derives its distance half from
 * `units.volume`, and the two are CALL-SITE IDENTICAL; the fuel receipt preview
 * is an ordinary template string. Three separate revisions of the plan claimed a
 * mechanical artifact could certify their absence, and the claimed boundary
 * relocated three times before the answer turned out to be "stop claiming it".
 *
 * The exact sentence this file supports, and no stronger one:
 *
 *   all mechanically enumerated modules were dispositioned at this reviewed
 *   snapshot; these named scenarios pass
 *
 * ★ AND THE LIMIT OF THE DIGEST, stated here rather than in a plan nobody
 * reads at 3am. Binding a disposition to a content digest closes exactly one
 * hole: a name-set manifest cannot see unit behaviour ADDED to a module already
 * dispositioned `no unit behaviour`. Drop `` `${draft.liters} L` `` into such a
 * file and no parity check fires, because the name set did not change. With a
 * digest, that edit fails CI until somebody re-dispositions the row.
 *
 * A DIGEST FORCES EXPLICIT RE-ACKNOWLEDGEMENT. IT CANNOT PROVE THE QUALITY OF
 * THE REVIEW IT FORCES. `--update` will happily re-stamp every row in the file,
 * and no gate can tell a careful re-read from a keystroke. That is a real limit,
 * not a caveat: what this buys is that the re-acknowledgement is EXPLICIT and
 * appears in the diff, not that it is honest.
 *
 * ★ THE UNIVERSE IS STATED, NOT INFERRED. `validate-reachability.ts` walks
 * textual imports from `src/main.tsx`, so it cannot see the document that loads
 * `src/main.tsx`, nor anything served rather than imported:
 *
 *   - `index.html`, the entry document;
 *   - the service worker, registered by URL (`main.tsx`);
 *   - the non-English locale resources, loaded by HTTP URL template (`i18n.ts`);
 *   - `offline.html` and `manifest.json`, which `sw.js` precaches by name.
 *
 * The locale bundles are not academic. The settings screen tells a
 * `{volume:'L', distance:'mi', pressure:'psi'}` user "Using metric units:
 * liters, kilometers, L/100km, °C, bar, kg, Nm" in SIX languages, and nothing
 * in the walker would have said those files existed.
 *
 * So the universe is: every file `validate-reachability.ts` recognises, PLUS the
 * entry document, PLUS everything shipped under `public/`. Anything outside that
 * is out of scope BY STATEMENT rather than by accident. `walkGraph` is imported
 * from that gate rather than reimplemented here, because two copies of a walk
 * are two answers to "what is the universe" the first time one of them changes.
 *
 * ★ AND WHAT THE DIGEST STILL DID NOT PIN, which a review found by mutating this
 * file's subject rather than this file: the digest pins CONTENT, and nothing
 * pinned the CONCLUSION. Downgrade every row to `no unit behaviour`, delete
 * every finding, touch no source file, and the first version of this gate
 * printed the permitted sentence and exited 0. The findings are the work list
 * tasks 2 through 7 consume, so the cheapest path to a green row was to erase
 * the finding rather than repair the file. Two rules close it:
 *
 *   [baseline]   `units.baseline.json` is a second, independently maintained
 *                record of the same work for the 26 files the gate can see.
 *                The two must agree, so an erasure in one fails against the
 *                other.
 *   [weakened]   a row whose digest is UNCHANGED may not lower its disposition
 *                or lose a finding. A repair moves the digest; an erasure does
 *                not. Residual, stated rather than implied: this pins that a
 *                conclusion changed FOR A REASON, never that the reason was
 *                good.
 *
 * ★ AND THE TWO DO NOT REACH EQUALLY FAR, which belongs here and not only in a
 * report. Only findings that MIRROR the units gate baseline
 * (`<kind> xN (units gate baseline)`) are held by both.
 *
 * ★ AND SINCE PLAN 3b TASK 8 THERE ARE NONE, which is a real reduction in what
 * this file can catch and is stated here rather than left to be inferred from a
 * zero in the summary. The flip emptied `units.baseline.json`, so no row has a
 * counterpart in it to be checked against; every finding below now rests on
 * `[weakened]` alone. What survives of the cross-check is `baseline.invented`,
 * which is the direction that still has teeth: no row may claim a units gate
 * finding, because the gate has none. The summary line at the bottom measures
 * the split on every run rather than asserting it.
 *
 * Every PROSE finding,
 * which is most of the ones a human wrote, rests on `[weakened]` alone, and
 * `[weakened]` compares against the last COMMITTED manifest: erase one and
 * commit it in the same step and a local run has nothing to compare against.
 * What catches that is CI passing `--against-ref <merge-base>`, and that job is
 * advisory. The split is PRINTED on every successful run rather than written
 * down here, because a number in prose goes stale and this one moves every time
 * a task closes a finding.
 *
 * Usage:
 *   bun run scripts/validate-units-manifest.ts              # gate
 *   bun run scripts/validate-units-manifest.ts --update     # re-stamp digests
 *   bun run scripts/validate-units-manifest.ts --report     # disposition summary
 *   bun run scripts/validate-units-manifest.ts --root <dir> # another tree (selftest)
 *   bun run scripts/validate-units-manifest.ts --manifest <p>
 *   bun run scripts/validate-units-manifest.ts --baseline <p>
 *   bun run scripts/validate-units-manifest.ts --against-ref <ref>   # default HEAD
 *   bun run scripts/validate-units-manifest.ts --against-file <p>
 * Exit code: 1 on any parity, schema, digest, baseline or weakening failure.
 */

import { createHash } from 'crypto'
import { execFileSync } from 'child_process'
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'fs'
import { dirname, join, relative, sep } from 'path'
import { ROOT } from './translation-utils'
import { walkGraph } from './validate-reachability'

const DEFAULT_MANIFEST = join(ROOT, 'scripts', 'units.manifest.json')

/**
 * Runtime roots the import walker cannot reach.
 *
 * ★ THE RULE HAS NO SEMANTIC STEP, AND THAT IS THE SECOND REVISION OF IT.
 * The first version named `public/sw.js` and enumerated `public/locales`, which
 * is what R9 described. A review then found the universe was itself a floor in
 * the shape of the previous nineteen: `index.html`, `public/offline.html` and
 * `public/manifest.json` are all shipped and user-facing, `sw.js` precaches two
 * of them by name, and none of the three was in scope. No unit text in them
 * today, so no live defect, but they were out by OMISSION rather than by
 * statement, and that distinction is the whole of R9's closing sentence.
 *
 * So the rule is now mechanical: the entry document, plus EVERY file under
 * `public/`, with no extension filter. That deliberately includes the two PNG
 * icons. Filtering to "files that can carry text" would put a judgement back in
 * the middle of the universe, and a judgement is the thing that relocates: an
 * SVG carries text, a JSON does, a `.txt` does, and the next person's list will
 * not match this one's. A binary asset costs one cheap re-acknowledgement on the
 * rare day it changes, which is a better trade than a filter nobody can audit.
 */
const ENTRY_DOCUMENT = 'index.html'
const PUBLIC_DIR = 'public'

/**
 * Who repairs a recorded finding. An ENUM, not free text.
 *
 * The first version of this manifest put the owner inside the finding string,
 * and 47 rows produced twelve different spellings of it ("task 6", "tasks 4, 6
 * and 7", "task 2 (R1 composition)", "task 6, jointly with ..."). Tasks 2
 * through 7 consume this list as their work list, so a spelling nobody greps
 * for is an orphaned work item, and prose cannot be checked.
 *
 * `deferred` is a real member rather than an escape hatch: some recorded
 * observations are genuinely outside this phase, and a row that says so
 * explicitly is better than one that invents an owner to satisfy a schema.
 */
const OWNERS = new Set([
  'task 2',
  'task 3',
  'task 4',
  'task 5',
  'task 6',
  // ★ Added when task 6 closed, and the reason is the enum working rather than
  // the enum bending. Task 6 finished holding 23 rows, so "task 6" stopped
  // naming anybody who would act on them; the fuel-economy and fuel-rate family
  // moved to 6b and the price family to task 7. Widening the enum is the
  // sanctioned way to add an owner precisely because it is a CODE change in the
  // diff, where free text produced twelve spellings across 47 rows.
  'task 6b',
  'task 7',
  'task 8',
  'task 9',
  'phase 4',
  'deferred',
])

/** The dispositions a row may carry. Anything else fails. */
const DISPOSITIONS = new Set([
  /** Reviewed; unit behaviour present. Carries `tests`, `findings`, or both. */
  'audited',
  /** Reviewed; the module makes no unit decision and renders no unit-bearing quantity. */
  'no unit behaviour',
  /** Unit behaviour present and deliberately outside the conversion contract. */
  'domain exemption',
  /** Reviewed; correctness cannot be established at this layer. `reason` says what would settle it. */
  'unverifiable',
])

/**
 * The manifest's on-disk format, carried in the file AND in this constant.
 *
 * ★ WHY A VERSION AT ALL, and it is not decoration. `[weakened]` forbids a row's
 * findings from shrinking while its digest holds still, which is right for an
 * erasure and WRONG for a format migration: moving 47 rows' owner text out of
 * `findings` into an `owners` array shrank findings on 47 unchanged files, so
 * the rule would have failed on its own introduction. That was handled by
 * ordering the commits, which worked locally and left an undocumented
 * dependency on push granularity: a single push of both commits makes the CI
 * merge base the PRE-migration commit and the advisory job goes red on the very
 * change that introduces the rule.
 *
 * So a format migration is now exempt BY CONSTRUCTION rather than by discipline:
 * bump this constant and the file's `schemaVersion` together, and the drift
 * check announces a migration instead of reporting phantom weakenings.
 *
 * ★ It is deliberately a TWO-FILE change. The constant lives in code and the
 * version lives in data, and they must agree or the gate refuses to run. Bumping
 * it to dodge a guard is therefore a code change in the diff, held to the same
 * "explicit re-acknowledgement" standard as re-stamping a digest, rather than a
 * free escape hatch anybody can reach by editing JSON.
 */
const MANIFEST_SCHEMA_VERSION = 2

interface Manifest {
  schemaVersion: number
  rows: ManifestRow[]
}

interface ManifestRow {
  path: string
  disposition: string
  digest: string
  reason?: string
  tests?: string[]
  findings?: string[]
  owners?: string[]
}

/**
 * One failure, identified by the RULE that produced it.
 *
 * ★ WHY A RULE ID AND NOT JUST A TAG, which is the second revision of this type.
 * The tags were already load bearing: R9 requires the "edit a `no unit
 * behaviour` module" mutation to fail SPECIFICALLY on the digest mismatch, and
 * a bare exit code cannot tell that from "something is wrong". But a review
 * then deleted each rule one at a time and found THREE that survived, every one
 * of them masked by a SIBLING RULE EMITTING THE SAME TAG: delete the
 * disposition-rank half of `weakened` and the finding-dropped half still says
 * `weakened`; delete "a `no unit behaviour` row may not carry a finding" and
 * "a finding must name an owner" still says `schema`.
 *
 * The instance of that shape had already been found once, for M-O, and fixed as
 * an instance. This is the class: every rule now carries an id, every probe in
 * `units_manifest_selftest.py` asserts the exact RULE set, and a sweep deletes
 * each rule in turn and requires it to flip a named probe. A rule whose removal
 * changes nothing is untested, whatever its siblings emit.
 */
type Rule =
  | 'unlisted'
  | 'orphan'
  | 'duplicate'
  | 'schema.no-path'
  | 'schema.disposition'
  | 'schema.reason'
  | 'schema.evidence'
  | 'schema.nub-finding'
  | 'schema.test-missing'
  | 'schema.finding-unowned'
  | 'schema.owner-idle'
  | 'schema.owner-enum'
  | 'digest'
  | 'baseline.not-audited'
  | 'baseline.counts'
  | 'baseline.invented'
  | 'weakened.rank'
  | 'weakened.finding'

interface Failure {
  rule: Rule
  path: string
  detail: string
}

/**
 * How much work a disposition claims. Only the ORDER matters.
 *
 * `audited` is the only one that carries an obligation, so dropping to any other
 * is a weakening. `unverifiable` and `domain exemption` rank together because
 * both still assert that unit behaviour is present; `no unit behaviour` asserts
 * there is nothing here at all, which is the cheapest thing a row can say and
 * therefore the one an erasure reaches for.
 */
const DISPOSITION_RANK: Readonly<Record<string, number>> = {
  audited: 3,
  unverifiable: 2,
  'domain exemption': 2,
  'no unit behaviour': 1,
}

/** The shape a finding takes when it mirrors a `units.baseline.json` entry. */
const BASELINE_FINDING = /^([a-z-]+) x(\d+) \(units gate baseline\)$/

interface BaselineEntry {
  file: string
  kind: string
  count: number
}

function sha256(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

/** POSIX-style relative path, so a manifest is the same on every platform. */
function rel(root: string, absolute: string): string {
  return relative(root, absolute).split(sep).join('/')
}

/** Every file shipped under `public/`, recursively. No filter, by design. */
function shippedPublicFiles(root: string): string[] {
  const base = join(root, PUBLIC_DIR)
  if (!existsSync(base)) {
    throw new Error(
      `${PUBLIC_DIR}/ does not exist under ${root}. Everything shipped there is a ` +
        'named part of this manifest\'s universe, and a universe that silently loses ' +
        'a part is the failure this file exists to prevent. Refusing to run.',
    )
  }
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir).sort()) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) walk(full)
      else out.push(rel(root, full))
    }
  }
  walk(base)
  if (out.length === 0) {
    throw new Error(`nothing found under ${PUBLIC_DIR}/. See above: refusing to run.`)
  }
  return out
}

/** The stated universe: walker-recognised files plus the named runtime roots. */
export function universeOf(root: string): string[] {
  const walker = [...walkGraph(root)].map((f) => rel(root, f))
  if (walker.length === 0) {
    throw new Error(
      `the reachability walker recognised nothing under ${root}. Every row would ` +
        'read as an orphan and an empty manifest would pass. Refusing to run.',
    )
  }
  if (!existsSync(join(root, ENTRY_DOCUMENT))) {
    throw new Error(
      `${ENTRY_DOCUMENT} is missing. It is the document that loads the module graph, ` +
        'so the walker starts one level below it and can never see it, and dropping ' +
        'it here would shrink the universe silently. Refusing to run.',
    )
  }
  return [
    ...new Set([...walker, ENTRY_DOCUMENT, ...shippedPublicFiles(root)]),
  ].sort()
}

/** Parse a manifest in either format. A bare array is the pre-version shape. */
function parseManifest(raw: string): Manifest {
  const parsed: unknown = JSON.parse(raw)
  if (Array.isArray(parsed)) return { schemaVersion: 1, rows: parsed as ManifestRow[] }
  const obj = parsed as Partial<Manifest>
  if (typeof obj?.schemaVersion !== 'number' || !Array.isArray(obj.rows)) {
    throw new Error('not a units manifest: expected { schemaVersion, rows }.')
  }
  return { schemaVersion: obj.schemaVersion, rows: obj.rows }
}

function loadManifest(path: string): Manifest {
  let raw: string
  try {
    raw = readFileSync(path, 'utf-8')
  } catch {
    throw new Error(`units manifest missing at ${path}. Run --update to seed it.`)
  }
  let manifest: Manifest
  try {
    manifest = parseManifest(raw)
  } catch (err) {
    throw new Error(`${path}: ${(err as Error).message}`, { cause: err })
  }
  if (manifest.schemaVersion !== MANIFEST_SCHEMA_VERSION) {
    throw new Error(
      `${path} is schema version ${manifest.schemaVersion}, this checker is ` +
        `${MANIFEST_SCHEMA_VERSION}. The two must agree, so a format migration is a ` +
        'change to both the data and the code and is visible in the diff. Refusing to run.',
    )
  }
  return manifest
}

/**
 * The gate's own work list, keyed as the manifest records it.
 *
 * ★ WHY THIS CROSS-CHECK EXISTS, and it is the review finding this file was
 * weakest on. The digest pins CONTENT. Nothing pinned the CONCLUSION. A reviewer
 * downgraded all 83 non-trivial rows to `no unit behaviour` and deleted every
 * finding, touched not one source file, and this gate printed
 * "all 382 enumerated module(s) dispositioned at this reviewed snapshot" and
 * exited 0. The findings are what tasks 2 through 7 consume, so the cheapest
 * path to a green row was to erase the finding rather than repair the file.
 *
 * For the 26 files the gate can see, `units.baseline.json` is an independent
 * record of the same work, maintained by a different program. Requiring the two
 * to agree costs nothing (they already did, exactly, across every per-kind
 * count) and means an erased finding fails here instead of passing quietly.
 */
function baselineWork(path: string): Map<string, Map<string, number>> {
  let raw: string
  try {
    raw = readFileSync(path, 'utf-8')
  } catch {
    throw new Error(
      `units baseline missing at ${path}. It is the second, independently maintained ` +
        'record of the same work list, and without it a deleted finding is invisible. ' +
        'Refusing to run. Pass --baseline to point at another one.',
    )
  }
  const entries = JSON.parse(raw) as BaselineEntry[]
  const work = new Map<string, Map<string, number>>()
  for (const e of entries) {
    const kinds = work.get(e.file) ?? new Map<string, number>()
    kinds.set(e.kind, (kinds.get(e.kind) ?? 0) + e.count)
    work.set(e.file, kinds)
  }
  return work
}

/** What a row's findings claim about the gate baseline, parsed back out. */
function claimedWork(row: ManifestRow): Map<string, number> {
  const claimed = new Map<string, number>()
  for (const finding of row.findings ?? []) {
    const m = BASELINE_FINDING.exec(finding)
    if (m) claimed.set(m[1], (claimed.get(m[1]) ?? 0) + Number(m[2]))
  }
  return claimed
}

function sameCounts(a: Map<string, number>, b: Map<string, number>): boolean {
  if (a.size !== b.size) return false
  for (const [k, v] of a) if (b.get(k) !== v) return false
  return true
}

function describe(counts: Map<string, number>): string {
  return counts.size === 0
    ? 'nothing'
    : [...counts]
        .sort()
        .map(([k, n]) => `${k} x${n}`)
        .join(', ')
}

/**
 * The previous manifest, from a git ref or a file.
 *
 * Returns null when it cannot be read at all: no git, no such ref, or the
 * manifest not yet committed. The caller REPORTS that rather than passing
 * quietly, because "the drift check did not run" and "the drift check found
 * nothing" are different sentences and only one of them is evidence.
 */
function previousManifest(
  ref: string | null,
  file: string | null,
  manifestPath: string,
): { manifest: Manifest; from: string } | null {
  // ★ An EMPTY previous manifest is not a comparison. Every other degraded path
  // (missing file, unparseable JSON, a ref git does not know, no repository, no
  // git at all) already returned null and printed the warning; a file holding
  // `[]` slipped through and printed the affirmative "no conclusion weakened"
  // clause, which is the one thing a degraded path must never do. Nothing can
  // weaken against nothing, so saying nothing did is vacuously true and reads
  // as evidence.
  const accept = (raw: string, from: string): { manifest: Manifest; from: string } | null => {
    let manifest: Manifest
    try {
      manifest = parseManifest(raw)
    } catch {
      return null
    }
    return manifest.rows.length === 0 ? null : { manifest, from }
  }
  if (file !== null) {
    try {
      return accept(readFileSync(file, 'utf-8'), file)
    } catch {
      return null
    }
  }
  if (ref === null) return null
  const dir = dirname(manifestPath)
  try {
    const top = execFileSync('git', ['rev-parse', '--show-toplevel'], {
      cwd: dir,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    const relPath = relative(top, manifestPath).split(sep).join('/')
    const text = execFileSync('git', ['show', `${ref}:${relPath}`], {
      cwd: dir,
      encoding: 'utf-8',
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return accept(text, `${ref}:${relPath}`)
  } catch {
    return null
  }
}

/** Digest to row, but only for digests that appear exactly once. */
function uniqueByDigest(rows: ManifestRow[]): Map<string, ManifestRow> {
  const seen = new Map<string, ManifestRow | null>()
  for (const row of rows) seen.set(row.digest, seen.has(row.digest) ? null : row)
  const unique = new Map<string, ManifestRow>()
  for (const [digest, row] of seen) if (row !== null) unique.set(digest, row)
  return unique
}

/**
 * Conclusions may only weaken alongside a content change.
 *
 * ★ The rule, and the reason it is shaped this way: a LEGITIMATE downgrade always
 * arrives with a content change, because you fixed the file, so its digest moved.
 * An erasure touches only the manifest. So a row whose digest is unchanged may
 * not lower its disposition or lose a finding.
 *
 * ★ AND THE RESIDUAL, stated rather than implied: this pins that a conclusion
 * changed FOR A REASON. It cannot pin that the reason was good. Someone who
 * genuinely re-concludes without touching the file must record the new
 * conclusion in the file, which is a content change and shows up in the diff,
 * and that is the most this mechanism can ask for.
 */
function conclusionDrift(before: ManifestRow[], after: ManifestRow[]): Failure[] {
  const failures: Failure[] = []
  const old = new Map(before.map((r) => [r.path, r]))

  // ★ PATH IS NOT THE IDENTITY. Keying drift on path alone let a RENAME launder
  // a conclusion: move a file with its bytes untouched, give the new path a
  // clean row, delete the old one, and the gate exited 0 with no tags while
  // printing "no conclusion weakened". Parity is satisfied (both paths are
  // accounted for), the digest is satisfied (the content never changed), and
  // the finding is simply gone.
  //
  // So a row whose path vanished is looked up by DIGEST instead. Only when the
  // digest is unique on BOTH sides: identical files are ordinary (four empty
  // `nav.json` bundles would collide), and a wrong pairing invents a weakening
  // that never happened, which is a worse failure than missing one. Fail-open
  // on the PAIRING, never on the rule.
  const survivingPaths = new Set(after.map((r) => r.path))
  const uniqueBefore = uniqueByDigest(before.filter((r) => !survivingPaths.has(r.path)))
  const previousPaths = new Set(before.map((r) => r.path))
  const uniqueAfter = uniqueByDigest(after.filter((r) => !previousPaths.has(r.path)))

  for (const row of after) {
    let was = old.get(row.path)
    if (was === undefined && uniqueAfter.get(row.digest)?.path === row.path) {
      was = uniqueBefore.get(row.digest)
    }
    if (was === undefined || was.digest !== row.digest) continue
    const rankBefore = DISPOSITION_RANK[was.disposition] ?? 0
    const rankAfter = DISPOSITION_RANK[row.disposition] ?? 0
    if (rankAfter < rankBefore) {
      failures.push({
        rule: 'weakened.rank',
        path: row.path,
        detail:
          `disposition dropped from ${was.disposition} to ${row.disposition} while the ` +
          `file did not change${was.path === row.path ? '' : ` (renamed from ${was.path})`}. ` +
          'A repair moves the digest; an erasure does not.',
      })
    }
    const kept = new Set(row.findings ?? [])
    for (const finding of was.findings ?? []) {
      if (!kept.has(finding)) {
        failures.push({
          rule: 'weakened.finding',
          path: row.path,
          detail:
            `dropped a recorded finding while the file did not change: ` +
            `${JSON.stringify(finding.slice(0, 90))}. Repair the file, or record the new ` +
            'conclusion in it so the digest moves with the claim.',
        })
      }
    }
  }
  return failures
}

/**
 * Everything wrong with the manifest, as tagged failures.
 *
 * Deliberately returns ALL of them rather than the first: this gate's own
 * mutation tests assert on the exact SET of tags that fired, and a checker that
 * short-circuits on the first problem cannot distinguish "the digest caught it"
 * from "parity caught it and the digest was never reached".
 */
export function checkManifest(
  root: string,
  rows: ManifestRow[],
  baselinePath: string,
): Failure[] {
  const failures: Failure[] = []

  const seen = new Set<string>()
  for (const row of rows) {
    if (typeof row?.path !== 'string' || row.path.length === 0) {
      // Spelled across four lines like every other emission on purpose: the
      // sweep in `units_manifest_selftest.py` disables a rule by finding its
      // own `failures.push({` / `rule: '<id>',` pair, and a one-line spelling
      // was unreachable to that anchor. It was the one rule of eighteen with no
      // deletion mutation, while the harness said "each rule in turn".
      failures.push({
        rule: 'schema.no-path',
        path: '<row>',
        detail: 'row has no `path`',
      })
      continue
    }
    if (seen.has(row.path)) {
      failures.push({
        rule: 'duplicate',
        path: row.path,
        detail: 'listed more than once, so one row\'s disposition hides the other',
      })
    }
    seen.add(row.path)
  }

  const universe = new Set(universeOf(root))
  for (const path of [...universe].sort()) {
    if (!seen.has(path)) {
      failures.push({
        rule: 'unlisted',
        path,
        detail: 'in the universe but not dispositioned',
      })
    }
  }
  for (const path of [...seen].sort()) {
    if (!universe.has(path)) {
      failures.push({
        rule: 'orphan',
        path,
        detail: 'dispositioned but no longer in the universe',
      })
    }
  }

  for (const row of rows) {
    if (typeof row?.path !== 'string' || row.path.length === 0) continue
    const where = row.path
    if (!DISPOSITIONS.has(row.disposition)) {
      failures.push({
        rule: 'schema.disposition',
        path: where,
        detail: `disposition ${JSON.stringify(row.disposition)} is not one of ${[...DISPOSITIONS].join(', ')}`,
      })
    }
    const reason = (row.reason ?? '').trim()
    const tests = row.tests ?? []
    const findings = row.findings ?? []
    const owners = row.owners ?? []
    // A finding with no owner is a work item nobody is holding; an owner with no
    // finding is a name attached to no work. Both directions, because only
    // checking one of them leaves the other free.
    if (findings.length > 0 && owners.length === 0) {
      failures.push({
        rule: 'schema.finding-unowned',
        path: where,
        detail: 'records findings but names no owner, so nothing holds the work item',
      })
    }
    if (owners.length > 0 && findings.length === 0) {
      failures.push({
        rule: 'schema.owner-idle',
        path: where,
        detail: 'names an owner but records no finding for them to repair',
      })
    }
    for (const owner of owners) {
      if (!OWNERS.has(owner)) {
        failures.push({
          rule: 'schema.owner-enum',
          path: where,
          detail:
            `owner ${JSON.stringify(owner)} is not one of ${[...OWNERS].join(', ')}. ` +
            'Free-text owners produced twelve spellings across 47 rows, and a spelling ' +
            'nobody greps for is an orphaned work item.',
        })
      }
    }
    if ((row.disposition === 'domain exemption' || row.disposition === 'unverifiable') && !reason) {
      failures.push({
        rule: 'schema.reason',
        path: where,
        detail:
          row.disposition === 'unverifiable'
            ? 'unverifiable rows must state what would MAKE them verifiable'
            : 'a domain exemption must state the reason it is exempt',
      })
    }
    if (row.disposition === 'audited' && tests.length === 0 && findings.length === 0) {
      failures.push({
        rule: 'schema.evidence',
        path: where,
        detail:
          'an audited row must name the tests that cover it or the findings still ' +
          'open against it. A bare "audited" is an assertion nothing can fail.',
      })
    }
    // ★ A test id that names no file is the QUIET failure mode, and this repo
    // has already learned it once: `units_gate_selftest.py`'s scope proof
    // checks the same thing about ESLint exemption paths, because "a typo that
    // silently un-exempts a file fails loudly; a typo that names nothing at all
    // is the quiet one". An `audited` row is allowed to rest on `tests`, so a
    // `tests` entry pointing at a renamed or deleted file is a row resting on
    // nothing while still reading as covered.
    for (const test of tests) {
      if (!existsSync(join(root, 'src', test))) {
        failures.push({
          rule: 'schema.test-missing',
          path: where,
          detail:
            `names a test that does not exist: src/${test}. A row that rests on a ` +
            'test id nobody can run is a row resting on nothing.',
        })
      }
    }
    if (row.disposition === 'no unit behaviour' && findings.length > 0) {
      failures.push({
        rule: 'schema.nub-finding',
        path: where,
        detail: 'a row with no unit behaviour cannot also record a unit finding',
      })
    }
    if (!universe.has(where)) continue
    const actual = sha256(join(root, where))
    if (row.digest !== actual) {
      failures.push({
        rule: 'digest',
        path: where,
        detail:
          `digest ${String(row.digest).slice(0, 12)} recorded, ${actual.slice(0, 12)} on disk. ` +
          `Re-review this file and re-stamp it: its disposition (${row.disposition}) was ` +
          'made against different content.',
      })
    }
  }

  // The independent record of the same work, both directions.
  const work = baselineWork(baselinePath)
  const byPath = new Map(rows.filter((r) => typeof r?.path === 'string').map((r) => [r.path, r]))
  for (const [file, kinds] of [...work].sort()) {
    const row = byPath.get(file)
    if (row === undefined) continue // parity already reported it
    if (row.disposition !== 'audited') {
      failures.push({
        rule: 'baseline.not-audited',
        path: file,
        detail:
          `the units gate baselines ${describe(kinds)} here, so this row cannot be ` +
          `${row.disposition}. Shrink the baseline by fixing the file, not the manifest.`,
      })
      continue
    }
    const claimed = claimedWork(row)
    if (!sameCounts(claimed, kinds)) {
      failures.push({
        rule: 'baseline.counts',
        path: file,
        detail: `records ${describe(claimed)}; the units gate baselines ${describe(kinds)}.`,
      })
    }
  }
  for (const row of rows) {
    if (typeof row?.path !== 'string') continue
    const claimed = claimedWork(row)
    if (claimed.size > 0 && !work.has(row.path)) {
      failures.push({
        rule: 'baseline.invented',
        path: row.path,
        detail: `records ${describe(claimed)} but the units gate baselines nothing here.`,
      })
    }
  }

  return failures
}

function seed(root: string, rows: ManifestRow[]): ManifestRow[] {
  const byPath = new Map(rows.map((r) => [r.path, r]))
  return universeOf(root).map((path) => {
    const existing = byPath.get(path)
    const row: ManifestRow = {
      path,
      // A NEW file gets an empty disposition on purpose. `--update` re-stamps
      // digests, which is a re-acknowledgement a human can at least be asked
      // about; it must never INVENT a disposition, or seeding the manifest
      // would be the same keystroke as auditing the tree.
      disposition: existing?.disposition ?? '',
      digest: sha256(join(root, path)),
    }
    if (existing?.reason) row.reason = existing.reason
    if (existing?.tests?.length) row.tests = existing.tests
    if (existing?.findings?.length) row.findings = existing.findings
    // ★ `owners` was added to the row schema and NOT added here, so `--update`
    // silently dropped all 50 of them and the next run reported 50 schema
    // failures. That is nastier than its size: `--update` is the documented
    // remedy for a [digest] failure, and the natural way to clear the schema
    // errors it then causes is to delete the findings, which [weakened] holds
    // shut. The remedy led into a trap the guard kept closed.
    //
    // The round-trip probe in units_manifest_selftest.py is the real fix: it
    // asserts `--update` is a FIXED POINT on a fully dispositioned manifest, so
    // the next field somebody forgets fails there rather than in production.
    if (existing?.owners?.length) row.owners = existing.owners
    return row
  })
}

function report(rows: ManifestRow[]): void {
  const counts = new Map<string, number>()
  for (const r of rows) counts.set(r.disposition, (counts.get(r.disposition) ?? 0) + 1)
  console.log(`\n${rows.length} row(s) in the unit-audit manifest:\n`)
  for (const [disposition, n] of [...counts].sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(n).padStart(4)}  ${disposition || '<undispositioned>'}`)
  }
  const open = rows.filter((r) => (r.findings ?? []).length > 0)
  console.log(`\n${open.length} row(s) carrying recorded findings:\n`)
  for (const r of open.sort((a, b) => a.path.localeCompare(b.path))) {
    console.log(`  ${r.path}`)
    for (const f of r.findings ?? []) console.log(`      ${f}`)
  }
  const unverifiable = rows.filter((r) => r.disposition === 'unverifiable')
  console.log(`\n${unverifiable.length} unverifiable row(s):\n`)
  for (const r of unverifiable.sort((a, b) => a.path.localeCompare(b.path))) {
    console.log(`  ${r.path}\n      ${r.reason ?? ''}`)
  }
  console.log('')
}

function main(): void {
  const argv = process.argv.slice(2)
  const args = new Set(argv)
  const rootIdx = argv.indexOf('--root')
  const root = rootIdx === -1 ? ROOT : (argv[rootIdx + 1] ?? ROOT)
  const manifestIdx = argv.indexOf('--manifest')
  const manifestPath =
    manifestIdx === -1 ? DEFAULT_MANIFEST : (argv[manifestIdx + 1] ?? DEFAULT_MANIFEST)

  if (args.has('--update')) {
    let existing: ManifestRow[]
    try {
      existing = loadManifest(manifestPath).rows
    } catch {
      // No manifest yet, or an unreadable one. Seeding from nothing is the
      // bootstrap case; every row it writes is undispositioned and fails.
      existing = []
    }
    const before = new Map(existing.map((r) => [r.path, r.digest]))
    const rows = seed(root, existing)
    writeFileSync(
      manifestPath,
      `${JSON.stringify({ schemaVersion: MANIFEST_SCHEMA_VERSION, rows }, null, 1)}\n`,
    )
    const restamped = rows.filter((r) => before.has(r.path) && before.get(r.path) !== r.digest)
    const added = rows.filter((r) => !before.has(r.path))
    console.log(`✓ units manifest written: ${rows.length} row(s)`)
    if (added.length > 0) {
      console.log(`  ${added.length} new row(s), each UNDISPOSITIONED and failing until reviewed:`)
      for (const r of added) console.log(`      ${r.path}`)
    }
    if (restamped.length > 0) {
      console.log(
        `  ${restamped.length} digest(s) re-stamped. Each one is a claim that you ` +
          're-read the file and the disposition still holds:',
      )
      for (const r of restamped) console.log(`      ${r.path}`)
    }
    return
  }

  const baselineIdx = argv.indexOf('--baseline')
  const baselinePath =
    baselineIdx === -1
      ? join(root, 'scripts', 'units.baseline.json')
      : (argv[baselineIdx + 1] ?? join(root, 'scripts', 'units.baseline.json'))

  // Conclusion drift, against the last committed manifest by default. A worker
  // erasing a finding locally fails before they can commit it; CI passes the
  // merge base so the same erasure fails on the pull request.
  const againstFileIdx = argv.indexOf('--against-file')
  const againstRefIdx = argv.indexOf('--against-ref')
  const againstFile = againstFileIdx === -1 ? null : (argv[againstFileIdx + 1] ?? null)
  const againstRef =
    againstFile !== null
      ? null
      : againstRefIdx === -1
        ? 'HEAD'
        : (argv[againstRefIdx + 1] ?? 'HEAD')

  const manifest = loadManifest(manifestPath)
  const rows = manifest.rows
  if (args.has('--report')) report(rows)
  const failures = checkManifest(root, rows, baselinePath)

  // Said out loud, every run. "The drift check did not run" and "the drift check
  // found nothing" are different sentences and only one of them is evidence.
  const previous = previousManifest(againstRef, againstFile, manifestPath)
  let comparedAgainst: string | null = null
  if (previous === null) {
    console.log(
      `  (conclusion drift NOT checked: no usable previous manifest at ` +
        `${againstFile ?? againstRef ?? '<none>'})`,
    )
  } else if (previous.manifest.schemaVersion !== manifest.schemaVersion) {
    // ★ A FORMAT MIGRATION STANDS DOWN THE FINDING HALF, NOT THE WHOLE
    // DIRECTION. Moving 47 rows' owner text out of the finding string and into
    // an `owners` array legitimately shrinks `findings` on files that never
    // changed, so `weakened.finding` has to yield to it. Nothing about moving a
    // field between columns LOWERS A DISPOSITION, though, and skipping both
    // halves turned a version bump into a blanket amnesty: bump the version in
    // the same commit that downgrades every row and this printed a reassuring
    // sentence. Measured by forcing the real owner migration through the check:
    // 49 `weakened.finding` and 0 `weakened.rank`, so keeping rank live costs a
    // genuine migration nothing.
    const rank = conclusionDrift(previous.manifest.rows, rows).filter(
      (f) => f.rule === 'weakened.rank',
    )
    failures.push(...rank)
    console.log(
      `  (erased-finding drift NOT checked: ${previous.from} is schema version ` +
        `${previous.manifest.schemaVersion} and this manifest is ` +
        `${manifest.schemaVersion}. A format migration moves fields between ` +
        'columns, which is not a conclusion getting cheaper. Disposition drift WAS ' +
        'checked across the bump, because a migration never lowers one.)',
    )
  } else {
    comparedAgainst = previous.from
    failures.push(...conclusionDrift(previous.manifest.rows, rows))
  }

  if (failures.length > 0) {
    const byRule = new Map<Rule, Failure[]>()
    for (const f of failures) byRule.set(f.rule, [...(byRule.get(f.rule) ?? []), f])
    console.error(`\n✗ ${failures.length} unit-manifest failure(s):\n`)
    for (const [rule, group] of [...byRule].sort()) {
      for (const f of group) console.error(`  [${rule}]  ${f.path}\n      ${f.detail}`)
    }
    console.error(
      '\nThe manifest is a REVIEWED SNAPSHOT over a stated universe, not a\n' +
        'completeness proof. Each row says what a human concluded about one file\n' +
        'and pins that conclusion to the content it was made against.\n\n' +
        '  [unlisted]   a file entered the universe. Review it and add a row.\n' +
        '  [orphan]     a row outlived its file. Delete the row.\n' +
        '  [duplicate]  two rows for one path: one disposition hides the other.\n' +
        '  [schema.*]   a row claims something it does not back up. The suffix\n' +
        '               names WHICH rule, because three rules once survived\n' +
        '               deletion by hiding behind a sibling with the same tag.\n' +
        '  [baseline.*] the manifest and units.baseline.json disagree about the\n' +
        '               same work. They are maintained by different programs on\n' +
        '               purpose, so a finding erased in one still fails here.\n' +
        '  [weakened.*] a conclusion got cheaper while the file stayed the same,\n' +
        '               under the same path or under a rename.\n' +
        '               A repair moves the digest; an erasure does not. This\n' +
        '               pins that a conclusion changed FOR A REASON, never that\n' +
        '               the reason was good.\n' +
        '  [digest]     the file changed under a disposition made against older\n' +
        '               content. Re-read it, then `--update` to re-stamp. That\n' +
        '               re-stamp is an explicit re-acknowledgement; it is NOT\n' +
        '               evidence the re-read happened.\n',
    )
    process.exit(1)
  }

  // The residual, MEASURED on every run rather than asserted in a comment. See
  // the module docstring: the two erasure defences do not reach equally far, and
  // which findings each one covers changes as tasks close them.
  let mirrored = 0
  let prose = 0
  const mirroredRows = new Set<string>()
  const proseRows = new Set<string>()
  for (const row of rows) {
    for (const finding of row.findings ?? []) {
      if (BASELINE_FINDING.test(finding)) {
        mirrored += 1
        mirroredRows.add(row.path)
      } else {
        prose += 1
        proseRows.add(row.path)
      }
    }
  }

  const counts = new Map<string, number>()
  for (const r of rows) counts.set(r.disposition, (counts.get(r.disposition) ?? 0) + 1)
  const summary = [...counts]
    .sort((a, b) => b[1] - a[1])
    .map(([d, n]) => `${n} ${d}`)
    .join(', ')
  console.log(
    `✓ units manifest: all ${rows.length} enumerated module(s) dispositioned at this ` +
      `reviewed snapshot (${summary})` +
      `${comparedAgainst === null ? '' : `, no conclusion weakened against ${comparedAgainst}`}.`,
  )
  console.log(
    `  (${mirrored} finding(s) on ${mirroredRows.size} row(s) mirror the units gate ` +
      `baseline and are held by two mechanisms; ${prose} on ${proseRows.size} row(s) are ` +
      'prose and rest on the drift rule alone, so erasing one and committing it in the ' +
      'same step is caught only by the merge-base run.)',
  )
}

if (import.meta.main) main()
