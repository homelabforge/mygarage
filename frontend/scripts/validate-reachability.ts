#!/usr/bin/env bun
/**
 * Unreachable-module detection — dead source files, found by walking imports.
 *
 * Why this sits alongside the i18n validators: twelve components had become
 * unreachable over time, and successive i18n passes kept translating them,
 * because a hardcoded string in a dead file looks exactly like one in a live
 * file. That inflated every language's missing-key count with strings no user
 * could ever see. Dead code is the blind spot the other three gates share.
 *
 * Reachability, not "who imports this". A grep for importers gives the wrong
 * answer for transitive death: AttachmentPreview had two importers and looked
 * alive, but both of them were themselves unreachable. Only a walk from the
 * real entry point can tell the difference.
 *
 * Tests are deliberately NOT entry points. A component whose only surviving
 * importer is its own test file is dead product code with a test keeping it
 * warm — that is the state two of the twelve were in, and treating tests as
 * roots would have hidden both.
 *
 * This is a clean-room gate, not a baseline one: it went in at zero
 * unreachable files, so any new finding is a genuine regression.
 *
 * Usage:
 *   bun run scripts/validate-reachability.ts
 * Exit code: 1 if any source file is unreachable from an entry point.
 */

import { readdirSync, readFileSync, statSync, existsSync } from 'fs'
import { join, dirname, resolve, relative } from 'path'
import { ROOT } from './translation-utils'

const SRC = join(ROOT, 'src')

/** Real roots. index.html loads main.tsx; everything else hangs off it. */
const ENTRIES = ['src/main.tsx']

/**
 * Files that are genuinely unreferenced but must not fail the gate — ambient
 * declarations, or a future second entry point (a service worker, say) that
 * something outside the module graph loads. Keep this list short and justified;
 * an entry here is a claim that nothing imports the file ON PURPOSE.
 */
const ALLOWLIST = new Set<string>([])

const EXTS = ['.tsx', '.ts', '/index.tsx', '/index.ts']

function resolveImport(spec: string, fromFile: string): string | null {
  let base: string
  if (spec.startsWith('@/')) base = join(SRC, spec.slice(2))
  else if (spec.startsWith('.')) base = resolve(dirname(fromFile), spec)
  else return null // bare package specifier — node_modules, not our graph
  for (const e of ['', ...EXTS]) {
    const p = base + e
    if (existsSync(p) && statSync(p).isFile()) return p
  }
  return null
}

/** Static imports, re-exports, and dynamic import() — lazy routes use the last. */
function specifiersOf(source: string): string[] {
  const out: string[] = []
  const patterns = [
    /(?:import|export)[\s\S]*?from\s*['"]([^'"]+)['"]/g,
    /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g,
    /import\s+['"]([^'"]+)['"]/g,
  ]
  for (const re of patterns) {
    for (const m of source.matchAll(re)) out.push(m[1])
  }
  return out
}

function walkGraph(): Set<string> {
  const reachable = new Set<string>()
  const queue = ENTRIES.map((e) => join(ROOT, e))
  while (queue.length) {
    const file = queue.pop()!
    if (reachable.has(file)) continue
    reachable.add(file)
    let source: string
    try {
      source = readFileSync(file, 'utf-8')
    } catch {
      continue
    }
    for (const spec of specifiersOf(source)) {
      const target = resolveImport(spec, file)
      if (target && !reachable.has(target)) queue.push(target)
    }
  }
  return reachable
}

function allSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      allSourceFiles(full, out)
    } else if (
      (entry.endsWith('.tsx') || entry.endsWith('.ts')) &&
      !entry.endsWith('.test.tsx') &&
      !entry.endsWith('.test.ts') &&
      !entry.endsWith('.d.ts')
    ) {
      out.push(full)
    }
  }
  return out
}

function main(): void {
  for (const e of ENTRIES) {
    if (!existsSync(join(ROOT, e))) {
      console.error(`✗ entry point ${e} does not exist — update ENTRIES`)
      process.exit(1)
    }
  }

  const reachable = walkGraph()
  const dead = allSourceFiles(SRC)
    .filter((f) => !reachable.has(f))
    .filter((f) => !ALLOWLIST.has(relative(ROOT, f)))

  if (dead.length > 0) {
    console.error(`\n✗ ${dead.length} unreachable source file(s):\n`)
    let lines = 0
    for (const f of dead.sort()) {
      const n = readFileSync(f, 'utf-8').split('\n').length
      lines += n
      console.error(`  ${String(n).padStart(4)} lines  ${relative(ROOT, f)}`)
    }
    console.error(
      `\n${lines} lines unreachable from ${ENTRIES.join(', ')}.\n` +
        'Delete them, or wire them up. If a file is unreferenced on purpose\n' +
        '(a second entry point loaded outside the module graph), add it to\n' +
        'ALLOWLIST in this script with a comment saying why.\n\n' +
        'Before deleting: check whether its tests cover behaviour that still\n' +
        'exists on a live component, and port those rather than dropping them.\n',
    )
    process.exit(1)
  }

  console.log(`✓ No unreachable source files (${reachable.size} reachable).`)
}

main()
