#!/usr/bin/env bun
/**
 * Translation source records: which English each translation was accepted
 * against, so an English edit shows up as a stale translation.
 *
 * Usage:
 *   bun run i18n:stamp                                   summary, writes nothing
 *   bun run i18n:stamp --list stale|unrecorded|draft de  one language's work list
 *   bun run i18n:stamp --accept de --base <ref>          every UNRECORDED key in de
 *   bun run i18n:stamp --accept de:vehicles:fuelList.title --base <ref>
 *                                                        one key, whatever its state
 *
 * --base is the English the translation was made against, read with git show.
 * For a contributor PR that's its merge-base with main, so a key English moved
 * after the PR branched stays stale instead of getting certified against the
 * new wording. It defaults to HEAD, which is right for your own edits.
 *
 * Bulk accept skips stale keys (clear those one at a time, or retranslate) and
 * copies of English (approve one on purpose with a per-key accept, which
 * writes "="). Accepting a draft drops its draft mark. Records for keys that
 * no longer exist are dropped whenever a language is written.
 */

import { spawnSync } from 'child_process'
import { join } from 'path'
import {
  PROJECT_ROOT,
  SOURCES_DIR,
  acceptRecords,
  analyzeLocale,
  discoverLanguages,
  discoverNamespaces,
  expectedKeys,
  flattenKeys,
  getNestedValue,
  loadEnglishData,
  loadJson,
  loadSourceRecords,
  pruneRecords,
  writeJson,
  LOCALES_DIR,
  type AcceptEntry,
} from './translation-utils'

const EN_PATH = (ns: string): string => `frontend/src/locales/en/${ns}.json`

/** English as of a git ref, plural sets expanded for `lang`: ns:key to value. */
function englishAt(ref: string, lang: string, namespaces: readonly string[]): Map<string, unknown> {
  const out = new Map<string, unknown>()
  for (const ns of namespaces) {
    const res = spawnSync('git', ['show', `${ref}:${EN_PATH(ns)}`], { cwd: PROJECT_ROOT, encoding: 'utf-8' })
    if (res.status !== 0) continue
    const data = JSON.parse(res.stdout) as Record<string, unknown>
    const keys = flattenKeys(data)
    const values = new Map(keys.map(k => [k, getNestedValue(data, k)]))
    for (const { key, enValue } of expectedKeys(keys, values, lang)) out.set(`${ns}:${key}`, enValue)
  }
  return out
}

function acceptLanguage(lang: string, keys: string[] | 'bulk', ref: string): void {
  const namespaces = discoverNamespaces()
  const english = loadEnglishData(namespaces)
  const base = englishAt(ref, lang, namespaces)

  // What this language expects today, in English order, for pruning and output order.
  const order: string[] = []
  const values = new Map<string, unknown>()
  for (const ns of namespaces) {
    const data = loadJson(join(LOCALES_DIR, lang, `${ns}.json`))
    for (const { key } of expectedKeys(english.keysByNamespace.get(ns)!, english.valuesByNamespace.get(ns)!, lang)) {
      order.push(`${ns}:${key}`)
      const value = getNestedValue(data, key)
      if (value !== undefined && value !== '') values.set(`${ns}:${key}`, value)
    }
  }

  const wanted = keys === 'bulk' ? [...values.keys()] : keys
  const entries: AcceptEntry[] = []
  for (const nsKey of wanted) {
    if (!values.has(nsKey) || !base.has(nsKey)) {
      if (keys !== 'bulk') {
        console.error(`✗ ${lang}:${nsKey}: ${values.has(nsKey) ? `not in English at ${ref}` : 'no translation to accept'}`)
        process.exit(1)
      }
      continue
    }
    entries.push({ nsKey, enBase: base.get(nsKey), value: values.get(nsKey) })
  }

  const before = loadSourceRecords(lang)
  const after = pruneRecords(acceptRecords(before, entries, keys === 'bulk' ? 'bulk' : 'key'), new Set(order))
  const sorted = Object.fromEntries(order.filter(k => k in after).map(k => [k, after[k]]))
  writeJson(join(SOURCES_DIR, `${lang}.json`), sorted)
  const changed = order.filter(k => before[k] !== after[k]).length
  const dropped = Object.keys(before).filter(k => !(k in after)).length
  console.log(`[${lang}] ${changed} record(s) written against ${ref}, ${dropped} dropped`)
}

function main(): void {
  const args = process.argv.slice(2)
  const ref = args.includes('--base') ? args[args.indexOf('--base') + 1] : 'HEAD'

  if (args.includes('--accept')) {
    const specs = args.slice(args.indexOf('--accept') + 1).filter((a, i, all) => !a.startsWith('--') && all[i - 1] !== '--base')
    const byLang = new Map<string, string[] | 'bulk'>()
    for (const spec of specs) {
      const [lang, ...rest] = spec.split(':')
      if (rest.length === 0) byLang.set(lang, 'bulk')
      else if (byLang.get(lang) !== 'bulk') byLang.set(lang, [...((byLang.get(lang) as string[]) ?? []), rest.join(':')])
    }
    const known = new Set(discoverLanguages())
    for (const [lang, keys] of byLang) {
      if (!known.has(lang)) {
        console.error(`✗ unknown language: ${lang}`)
        process.exit(1)
      }
      acceptLanguage(lang, keys, ref)
    }
    return
  }

  const namespaces = discoverNamespaces()
  const english = loadEnglishData(namespaces)

  if (args.includes('--list')) {
    const [state, lang] = args.slice(args.indexOf('--list') + 1)
    for (const i of analyzeLocale(lang, namespaces, english).issues) {
      if (i.type === state) console.log(`${i.namespace}:${i.key}`)
    }
    return
  }

  for (const lang of discoverLanguages()) {
    const counts = { stale: 0, unrecorded: 0, draft: 0 }
    for (const i of analyzeLocale(lang, namespaces, english).issues) {
      if (i.type in counts) counts[i.type as keyof typeof counts]++
    }
    console.log(`[${lang}] stale ${counts.stale}, unrecorded ${counts.unrecorded}, draft ${counts.draft}`)
  }
}

if (import.meta.main) main()
