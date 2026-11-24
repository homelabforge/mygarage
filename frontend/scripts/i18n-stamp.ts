#!/usr/bin/env bun
/**
 * Translation source records: which English each translation was accepted
 * against, so an English edit shows up as a stale translation.
 *
 * Usage:
 *   bun run i18n:stamp                                   summary, writes nothing
 *   bun run i18n:stamp --list stale|unrecorded|draft de  one language's work list
 *   bun run i18n:stamp --accept de --base <ref>          UNRECORDED de keys changed since <ref>
 *   bun run i18n:stamp --accept de:vehicles:fuelList.title --base <ref>
 *                                                        one key, whatever its state
 *   bun run i18n:stamp --accept-drafts de [ns:key ...]   approve de's drafts, all or the listed ones
 *   bun run i18n:stamp --draft-stale de [ns:key ...]     re-date de's stale keys as drafts, all or the listed ones
 *
 * --base is the English the translation was made against, read with git show.
 * For a contributor PR that's its merge-base with main, so a key English moved
 * after the PR branched stays stale instead of getting certified against the
 * new wording. It defaults to HEAD, which is right for your own edits.
 *
 * Bulk accept only looks at keys whose translation changed since --base, so
 * it can't certify an older unrecorded translation the PR never touched (those
 * get listed instead). It skips stale keys (clear those one at a time, or
 * retranslate), drafts, and copies of English (approve one on purpose with a
 * per-key accept, which writes "="). Accepting a draft drops its draft mark.
 * --draft-stale is for when English moved but someone checked the old
 * translation still fits: it records the key against today's English as a
 * draft, so it stays visible until a native speaker accepts it. "Stale" is
 * exactly what --list stale shows. Records for keys that no longer exist are
 * dropped whenever a language is written. Nothing is written until every language and ref checks out.
 */

import { spawnSync, type SpawnSyncReturns } from 'child_process'
import { existsSync } from 'fs'
import { join, relative, sep } from 'path'
import {
  EN_DIR,
  PROJECT_ROOT,
  SOURCES_DIR,
  acceptRecords,
  analyzeLocale,
  hash8,
  discoverLanguages,
  discoverNamespaces,
  expectedKeys,
  flattenKeys,
  getNestedValue,
  loadEnglishData,
  loadJson,
  loadSourceRecords,
  pruneRecords,
  recordState,
  sourceState,
  writeJson,
  LOCALES_DIR,
  type AcceptEntry,
} from './translation-utils'

const USAGE = `Usage:
  bun run i18n:stamp
  bun run i18n:stamp --list stale|unrecorded|draft <lang>
  bun run i18n:stamp --accept <lang> [--base <ref>]
  bun run i18n:stamp --accept <lang>:<ns>:<key> [...] [--base <ref>]
  bun run i18n:stamp --accept-drafts <lang> [<ns>:<key> ...]
  bun run i18n:stamp --draft-stale <lang> [<ns>:<key> ...]`

const LIST_STATES = ['stale', 'unrecorded', 'draft']

function fail(message: string, usage = false): never {
  console.error(`✗ ${message}`)
  if (usage) console.error(USAGE)
  process.exit(1)
}

// git wants the path from the repo root with forward slashes
const repoPath = (path: string): string => relative(PROJECT_ROOT, path).split(sep).join('/')

function git(args: string[]): SpawnSyncReturns<string> {
  return spawnSync('git', args, { cwd: PROJECT_ROOT, encoding: 'utf-8' })
}

/** The commit a ref names, or null when it names none. */
function resolveCommit(ref: string): string | null {
  const res = git(['rev-parse', '--verify', '--quiet', `${ref}^{commit}`])
  return res.status === 0 ? res.stdout.trim() : null
}

/**
 * A JSON file as of a commit, or null when the commit doesn't have it. Any
 * other git failure exits, so a broken repo can't read as "file absent".
 */
function jsonAt(commit: string, path: string): Record<string, unknown> | null {
  const ls = git(['ls-tree', '--name-only', commit, '--', repoPath(path)])
  if (ls.status !== 0) fail(`git ls-tree ${commit} ${repoPath(path)}: ${ls.stderr.trim()}`)
  if (ls.stdout.trim() === '') return null
  const show = git(['show', `${commit}:${repoPath(path)}`])
  if (show.status !== 0) fail(`git show ${commit}:${repoPath(path)}: ${show.stderr.trim()}`)
  return JSON.parse(show.stdout) as Record<string, unknown>
}

/** English as of a commit, plural sets expanded for `lang`: ns:key to value. */
function englishAt(commit: string, lang: string, namespaces: readonly string[]): Map<string, unknown> {
  const out = new Map<string, unknown>()
  for (const ns of namespaces) {
    const data = jsonAt(commit, join(EN_DIR, `${ns}.json`))
    if (data === null) continue
    const keys = flattenKeys(data)
    const values = new Map(keys.map(k => [k, getNestedValue(data, k)]))
    for (const { key, enValue } of expectedKeys(keys, values, lang)) out.set(`${ns}:${key}`, enValue)
  }
  return out
}

interface Row {
  ns: string
  key: string
  nsKey: string
  /** Today's English. */
  enValue: unknown
  /** The working-tree translation; undefined when missing or empty. */
  value: unknown
}

/** What this language expects today, in English order, with its current values. */
function currentRows(lang: string, namespaces: readonly string[]): Row[] {
  const english = loadEnglishData([...namespaces])
  const rows: Row[] = []
  for (const ns of namespaces) {
    const path = join(LOCALES_DIR, lang, `${ns}.json`)
    const data = existsSync(path) ? loadJson(path) : {}
    for (const { key, enValue } of expectedKeys(english.keysByNamespace.get(ns)!, english.valuesByNamespace.get(ns)!, lang)) {
      const value = getNestedValue(data, key)
      rows.push({ ns, key, nsKey: `${ns}:${key}`, enValue, value: value === '' ? undefined : value })
    }
  }
  return rows
}

/** Keys whose translation differs from the base's; a namespace file the base lacked counts as all changed. */
function changedSince(commit: string, lang: string, namespaces: readonly string[], rows: readonly Row[]): Set<string> {
  const changed = new Set<string>()
  for (const ns of namespaces) {
    const was = jsonAt(commit, join(LOCALES_DIR, lang, `${ns}.json`))
    for (const r of rows) {
      if (r.ns !== ns || r.value === undefined) continue
      const before = was === null ? undefined : getNestedValue(was, r.key)
      if (JSON.stringify(before) !== JSON.stringify(r.value)) changed.add(r.nsKey)
    }
  }
  return changed
}

interface Plan {
  lang: string
  records: Record<string, string>
  lines: string[]
}

/** Prune, put records in English order, and count what moved. */
function finishPlan(rows: readonly Row[], before: Record<string, string>, after: Record<string, string>): {
  records: Record<string, string>
  changed: number
  dropped: number
} {
  const pruned = pruneRecords(after, new Set(rows.map(r => r.nsKey)))
  return {
    records: Object.fromEntries(rows.filter(r => r.nsKey in pruned).map(r => [r.nsKey, pruned[r.nsKey]])),
    changed: rows.filter(r => before[r.nsKey] !== pruned[r.nsKey]).length,
    dropped: Object.keys(before).filter(k => !(k in pruned)).length,
  }
}

// asks acceptRecords itself, so this can't drift from what bulk would record
const bulkWouldRecord = (records: Record<string, string>, e: AcceptEntry): boolean =>
  acceptRecords(records, [e], 'bulk')[e.nsKey] !== records[e.nsKey]

function planAccept(lang: string, keys: string[] | 'bulk', ref: string, commit: string): Plan {
  const namespaces = discoverNamespaces()
  const rows = currentRows(lang, namespaces)
  const byKey = new Map(rows.map(r => [r.nsKey, r]))
  const base = englishAt(commit, lang, namespaces)
  const before = loadSourceRecords(lang)
  const lines: string[] = []

  const entries: AcceptEntry[] = []
  if (keys === 'bulk') {
    const changed = changedSince(commit, lang, namespaces, rows)
    const unchanged: string[] = []
    const notInBase: string[] = []
    for (const r of rows) {
      if (r.value === undefined) continue
      if (!base.has(r.nsKey)) {
        if (changed.has(r.nsKey) && sourceState(before[r.nsKey], r.enValue, r.value) === 'unrecorded') notInBase.push(r.nsKey)
        continue
      }
      const e = { nsKey: r.nsKey, enBase: base.get(r.nsKey), value: r.value }
      if (changed.has(r.nsKey)) entries.push(e)
      else if (bulkWouldRecord(before, e)) unchanged.push(r.nsKey)
    }
    if (unchanged.length > 0) {
      lines.push(`[${lang}] ${unchanged.length} unrecorded key(s) skipped, unchanged since ${ref} (accept them one at a time if they're right):`)
      lines.push(...unchanged.map(k => `  ${k}`))
    }
    if (notInBase.length > 0) {
      lines.push(`[${lang}] ${notInBase.length} key(s) skipped, not in English at ${ref}:`)
      lines.push(...notInBase.map(k => `  ${k}`))
    }
  } else {
    for (const nsKey of keys) {
      const r = byKey.get(nsKey)
      if (r?.value === undefined) fail(`${lang}:${nsKey}: no translation to accept`)
      if (!base.has(nsKey)) fail(`${lang}:${nsKey}: not in English at ${ref}`)
      entries.push({ nsKey, enBase: base.get(nsKey), value: r.value })
    }
  }

  const done = finishPlan(rows, before, acceptRecords(before, entries, keys === 'bulk' ? 'bulk' : 'key'))
  lines.unshift(`[${lang}] ${done.changed} record(s) written against ${ref}, ${done.dropped} dropped`)
  return { lang, records: done.records, lines }
}

/**
 * The keys a run acts on: every row in `want` state, or the listed ones, each
 * of which must be in `want` state or the whole run fails before any write.
 */
function targetRows(
  lang: string,
  rows: readonly Row[],
  keys: string[] | 'all',
  stateOf: (r: Row) => string,
  want: string,
  wantLabel: string,
): Row[] {
  if (keys === 'all') return rows.filter(r => stateOf(r) === want)
  const byKey = new Map(rows.map(r => [r.nsKey, r]))
  const bad = keys.map(k => {
    const r = byKey.get(k)
    if (r === undefined) return `${lang}:${k}: not a key ${lang} has`
    const state = stateOf(r)
    return state === want ? null : `${lang}:${k}: ${state}, not ${wantLabel}`
  }).filter(m => m !== null)
  if (bad.length > 0) fail(`${bad.join('\n✗ ')}\nnothing written`)
  return keys.map(k => byKey.get(k)!)
}

/**
 * Drop the draft mark from records whose hashes still match: someone read
 * them. Stale and unrecorded keys never qualify; a listed one that isn't a
 * draft fails the whole run.
 */
function planDrafts(lang: string, keys: string[] | 'all'): Plan {
  const rows = currentRows(lang, discoverNamespaces())
  const before = loadSourceRecords(lang)
  const stateOf = (r: Row): string =>
    r.value === undefined ? 'missing' : sourceState(before[r.nsKey], r.enValue, r.value)

  const after = { ...before }
  for (const r of targetRows(lang, rows, keys, stateOf, 'draft', 'a draft')) {
    after[r.nsKey] = before[r.nsKey].split(':').slice(0, 2).join(':')
  }
  const done = finishPlan(rows, before, after)
  return { lang, records: done.records, lines: [`[${lang}] ${done.changed} draft(s) approved, ${done.dropped} dropped`] }
}

/**
 * Record stale keys against today's English as drafts: the old translation
 * still fits, but no native speaker has said so. Same reading of "stale" as
 * --list (recordState), so the two can't disagree. The translations
 * themselves aren't touched.
 */
function planDraftStale(lang: string, keys: string[] | 'all'): Plan {
  const rows = currentRows(lang, discoverNamespaces())
  const before = loadSourceRecords(lang)
  const stateOf = (r: Row): string =>
    r.value === undefined ? 'missing' : (recordState(before[r.nsKey], r.enValue, r.value) ?? 'untranslated')

  const after = { ...before }
  for (const r of targetRows(lang, rows, keys, stateOf, 'stale', 'stale')) {
    after[r.nsKey] = `${hash8(r.enValue)}:${r.value === r.enValue ? '=' : hash8(r.value)}:d`
  }
  const done = finishPlan(rows, before, after)
  return { lang, records: done.records, lines: [`[${lang}] ${done.changed} stale key(s) re-dated as drafts, ${done.dropped} dropped`] }
}

function main(): void {
  const args = process.argv.slice(2)
  const known = new Set(discoverLanguages())
  const checkLang = (lang: string | undefined): string => {
    if (lang === undefined) fail('no language given', true)
    if (!known.has(lang)) fail(`unknown language: ${lang}`, true)
    return lang
  }

  let ref = 'HEAD'
  const positional: string[] = []
  const modes: string[] = []
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--base') {
      const next = args[i + 1]
      if (next === undefined || next.startsWith('--')) fail('--base needs a ref', true)
      ref = next
      i++
    } else if (['--list', '--accept', '--accept-drafts', '--draft-stale'].includes(args[i])) modes.push(args[i])
    else if (args[i].startsWith('--')) fail(`unknown option: ${args[i]}`, true)
    else positional.push(args[i])
  }
  if (modes.length > 1) fail(`pick one of ${modes.join(', ')}`, true)
  const mode = modes[0]
  if (args.includes('--base') && mode !== '--accept') fail('--base only goes with --accept', true)

  if (mode === '--accept' || mode === '--accept-drafts' || mode === '--draft-stale') {
    const plans: Plan[] = []
    if (mode === '--accept') {
      if (positional.length === 0) fail('nothing to accept', true)
      const commit = resolveCommit(ref)
      if (commit === null) fail(`--base ${ref} is not a commit in this repo`)
      const byLang = new Map<string, string[] | 'bulk'>()
      for (const spec of positional) {
        const [lang, ...rest] = spec.split(':')
        if (rest.length === 0) byLang.set(lang, 'bulk')
        else if (byLang.get(lang) !== 'bulk') byLang.set(lang, [...((byLang.get(lang) as string[]) ?? []), rest.join(':')])
      }
      for (const [lang, keys] of byLang) plans.push(planAccept(checkLang(lang), keys, ref, commit))
    } else {
      const [lang, ...keys] = positional
      const plan = mode === '--accept-drafts' ? planDrafts : planDraftStale
      plans.push(plan(checkLang(lang), keys.length === 0 ? 'all' : keys))
    }
    // only write once every language planned cleanly
    for (const p of plans) {
      writeJson(join(SOURCES_DIR, `${p.lang}.json`), p.records)
      for (const line of p.lines) console.log(line)
    }
    return
  }

  const namespaces = discoverNamespaces()
  const english = loadEnglishData(namespaces)

  if (mode === '--list') {
    const [state, lang] = positional
    if (!LIST_STATES.includes(state) || positional.length !== 2) fail(`--list wants one of ${LIST_STATES.join('|')} and a language`, true)
    for (const i of analyzeLocale(checkLang(lang), namespaces, english).issues) {
      if (i.type === state) console.log(`${i.namespace}:${i.key}`)
    }
    return
  }

  if (positional.length > 0) fail(`unexpected argument: ${positional[0]}`, true)
  for (const lang of discoverLanguages()) {
    const counts = { stale: 0, unrecorded: 0, draft: 0 }
    for (const i of analyzeLocale(lang, namespaces, english).issues) {
      if (i.type in counts) counts[i.type as keyof typeof counts]++
    }
    console.log(`[${lang}] stale ${counts.stale}, unrecorded ${counts.unrecorded}, draft ${counts.draft}`)
  }
}

if (import.meta.main) main()
