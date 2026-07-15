#!/usr/bin/env bun
/**
 * i18n usage validation — checks CODE against the English reference.
 *
 * validate-translations.ts checks each language AGAINST English, so English is
 * its reference and a key missing from English itself is invisible to it. The
 * vitest mock is `t: (key) => key`, so component tests can't see it either.
 * Between those two blind spots, `t('installPrompt.title')` shipped with the
 * key absent from every locale file and rendered raw to users.
 *
 * This script closes that gap: every literal `t('...')` in src/ must resolve to
 * a key in src/locales/en/<namespace>.json.
 *
 * Usage: bun run scripts/validate-i18n-usage.ts
 * Exit code: 1 if any used key is missing from English. Unlike a missing
 * translation (which falls back to English), a key missing from English has no
 * fallback — i18next renders the raw key. It is always a bug, so it blocks.
 */

import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative } from 'path'
import { EN_DIR, ROOT, discoverNamespaces, flattenKeys, loadJson } from './translation-utils'

/** i18n.ts sets defaultNS: 'common' — a bare useTranslation() resolves there. */
const DEFAULT_NS = 'common'

const SRC = join(ROOT, 'src')
const SKIP_DIRS = new Set(['__tests__', 'locales', 'node_modules'])

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (!SKIP_DIRS.has(entry)) out.push(...walk(full))
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

/** Namespaces a file binds via useTranslation('x') / useTranslation(['x','y']) / useTranslation(). */
function namespacesFor(text: string): string[] {
  const found = new Set<string>()
  for (const m of text.matchAll(/useTranslation\(\s*'([^']+)'/g)) found.add(m[1])
  for (const m of text.matchAll(/useTranslation\(\s*\[([^\]]+)\]/g)) {
    for (const q of m[1].matchAll(/'([^']+)'/g)) found.add(q[1])
  }
  if (/useTranslation\(\s*\)/.test(text)) found.add(DEFAULT_NS)
  return [...found]
}

const namespaces = discoverNamespaces()
const englishKeys = new Map<string, Set<string>>()
for (const ns of namespaces) {
  englishKeys.set(ns, new Set(flattenKeys(loadJson(join(EN_DIR, `${ns}.json`)))))
}

interface Violation {
  file: string
  line: number
  key: string
  searched: string[]
}

const violations: Violation[] = []

for (const file of walk(SRC)) {
  const text = readFileSync(file, 'utf-8')
  const bound = namespacesFor(text)
  if (bound.length === 0) continue

  // Literal t('key') / t('key', { ... }) only. Template literals are dynamic and
  // every one in the codebase carries a defaultValue, so they can't render raw.
  for (const m of text.matchAll(/\bt\(\s*'([^']+)'\s*(,\s*\{[^}]*\})?\s*\)/g)) {
    const [, rawKey, opts = ''] = m
    if (opts.includes('defaultValue')) continue

    let key = rawKey
    let searched = bound
    if (rawKey.includes(':')) {
      const [ns, ...rest] = rawKey.split(':')
      key = rest.join(':')
      searched = [ns]
    }

    if (searched.some(ns => englishKeys.get(ns)?.has(key))) continue

    violations.push({
      file: relative(ROOT, file),
      line: text.slice(0, m.index).split('\n').length,
      key: rawKey,
      searched,
    })
  }
}

if (violations.length > 0) {
  console.log(`✗ ${violations.length} translation key(s) used in code but missing from English:\n`)
  for (const v of violations) {
    console.log(`  ${v.file}:${v.line}`)
    console.log(`    t('${v.key}') — not in ${v.searched.map(n => `${n}.json`).join(' or ')}`)
  }
  console.log('\nThese render as the raw key to users — English has no fallback.')
  console.log(`Add them to ${relative(ROOT, EN_DIR)}/<namespace>.json.`)
  process.exit(1)
}

console.log('✓ All translation keys used in code exist in English.')
process.exit(0)
