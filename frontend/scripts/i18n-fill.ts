#!/usr/bin/env bun
/**
 * Fill missing translations in chunks, with a merge that refuses anything that
 * would break a locale.
 *
 * Usage:
 *   bun run scripts/i18n-fill.ts export <dir> [--langs de,fr] [--max 400]
 *   bun run scripts/i18n-fill.ts merge <dir>
 *
 * export writes <chunkId>.chunk.json per chunk plus <lang>.terms-input.json:
 * the short strings two or more keys share (settle those first, so every chunk
 * says the same thing the same way) and the locale's existing translations of
 * short strings. Whoever translates writes <chunkId>.out.json:
 *   { "chunkId": "...", "entries": { "<key>": "translation" | { "same": "why" } } }
 * merge folds every out file it finds back into public/locales, records each
 * accepted value as a machine draft (see i18n-stamp.ts) and writes
 * merge-report.json.
 *
 * Writable keys are missing ones and copies of English nobody approved.
 * Existing translations are never touched; a plural set is accepted or
 * rejected whole.
 */

import { existsSync, readdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import {
  EN_DIR,
  LOCALES_DIR,
  SOURCES_DIR,
  discoverLanguages,
  discoverNamespaces,
  expectedKeys,
  flattenKeys,
  getNestedValue,
  hash8,
  isApprovedSame,
  isEnglishCopy,
  loadJson,
  loadSourceRecords,
  placeholderTokens,
  pluralBase,
  pluralCategories,
  protectedSpans,
  sortToEnglish,
  writeJson,
} from './translation-utils'

export interface ChunkEntry {
  key: string
  en: string
  enHash: string
  placeholders: string[]
  protected: string[]
  plural?: {
    base: string
    category: string
    categories: string[]
    /** Members already translated, by category. Read-only context. */
    existing: Record<string, unknown>
  }
}

export interface Chunk {
  chunkId: string
  lang: string
  ns: string
  entries: ChunkEntry[]
}

export interface ChunkOutput {
  chunkId: string
  entries: Record<string, string | { same: string }>
}

export interface MergeReport {
  chunkId: string
  accepted: number
  rejected: { key: string; reason: string }[]
  same: { key: string; reason: string }[]
}

const asText = (v: unknown): string => (typeof v === 'string' ? v : JSON.stringify(v))

function isWritable(nsKey: string, value: unknown, enValue: unknown, records: Readonly<Record<string, string>>): boolean {
  if (value === undefined || value === null || value === '') return true
  return isEnglishCopy(value, enValue) && !isApprovedSame(records[nsKey], enValue, value)
}

/** Writable keys for one language and namespace, cut into chunks of at most `max` (a plural set never splits). */
export function buildChunks(
  lang: string,
  ns: string,
  enKeys: readonly string[],
  enValues: ReadonlyMap<string, unknown>,
  langData: Record<string, unknown>,
  records: Readonly<Record<string, string>>,
  max: number,
): Chunk[] {
  const enSet = new Set(enKeys)
  const cats = pluralCategories(lang)
  const groups: ChunkEntry[][] = []
  const pluralGroups = new Map<string, ChunkEntry[]>()

  for (const { key, enValue } of expectedKeys(enKeys, enValues, lang)) {
    const value = getNestedValue(langData, key)
    if (!isWritable(`${ns}:${key}`, value, enValue, records)) continue
    const en = asText(enValue)
    const entry: ChunkEntry = {
      key,
      en,
      enHash: hash8(enValue),
      placeholders: [...placeholderTokens(en)],
      protected: protectedSpans(`${ns}:${key}`, en),
    }
    const base = pluralBase(key, enSet)
    if (base === null) {
      groups.push([entry])
      continue
    }
    const existing: Record<string, unknown> = {}
    for (const c of cats) {
      const k = `${base}_${c}`
      const v = getNestedValue(langData, k)
      if (!isWritable(`${ns}:${k}`, v, enValues.get(k) ?? enValues.get(`${base}_other`), records)) existing[c] = v
    }
    entry.plural = { base, category: key.slice(base.length + 1), categories: cats, existing }
    if (!pluralGroups.has(base)) {
      pluralGroups.set(base, [])
      groups.push(pluralGroups.get(base)!)
    }
    pluralGroups.get(base)!.push(entry)
  }

  const chunks: Chunk[] = []
  let current: ChunkEntry[] = []
  for (const group of groups) {
    if (current.length > 0 && current.length + group.length > max) {
      chunks.push({ chunkId: `${lang}-${ns}-${chunks.length}`, lang, ns, entries: current })
      current = []
    }
    current.push(...group)
  }
  if (current.length > 0) chunks.push({ chunkId: `${lang}-${ns}-${chunks.length}`, lang, ns, entries: current })
  return chunks
}

const edge = (s: string): [string, string] => [s.match(/^\s*/)![0], s.match(/\s*$/)![0]]
const WRONG_SCRIPT: Record<string, RegExp> = { uk: /[ыэъё]/i, ru: /[іїєґ]/i }

function checkValue(entry: ChunkEntry, raw: unknown, lang: string): { value: string; same?: string } | string {
  if (typeof raw === 'object' && raw !== null && 'same' in raw) {
    const reason = (raw as { same: unknown }).same
    if (typeof reason !== 'string' || reason.trim() === '') return 'same-without-reason'
    return { value: entry.en, same: reason }
  }
  if (typeof raw !== 'string') return 'not-a-string'
  if (raw.trim() === '') return 'empty'
  if (raw === entry.en) return 'copy'
  if (raw.includes('$t(')) return 'nesting'
  const want = new Set(entry.placeholders)
  const got = placeholderTokens(raw)
  if (want.size !== got.size || [...want].some(t => !got.has(t))) return `placeholders: want ${[...want].join(' ') || 'none'}`
  const lost = entry.protected.filter(span => !raw.includes(span))
  if (lost.length > 0) return `protected: ${lost.join(' ')}`
  const [a, b] = [edge(entry.en), edge(raw)]
  if (a[0] !== b[0] || a[1] !== b[1]) return 'whitespace'
  if (WRONG_SCRIPT[lang]?.test(raw)) return 'wrong-script'
  return { value: raw }
}

function setNested(obj: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.')
  let cur = obj
  for (const p of parts.slice(0, -1)) {
    if (typeof cur[p] !== 'object' || cur[p] === null) cur[p] = {}
    cur = cur[p] as Record<string, unknown>
  }
  cur[parts[parts.length - 1]] = value
}

/**
 * Fold one chunk's output into a locale. Throws on a wrong chunkId; every
 * other problem is a per-key rejection. Throws too if anything outside the
 * accepted keys would change, which no input should be able to cause.
 */
export function mergeChunk(
  chunk: Chunk,
  out: ChunkOutput,
  enData: Record<string, unknown>,
  langData: Record<string, unknown>,
  records: Readonly<Record<string, string>>,
): { data: Record<string, unknown>; records: Record<string, string>; report: MergeReport } {
  if (!out || out.chunkId !== chunk.chunkId) throw new Error(`chunkId mismatch: expected ${chunk.chunkId}, got ${out?.chunkId}`)
  const report: MergeReport = { chunkId: chunk.chunkId, accepted: 0, rejected: [], same: [] }
  const byKey = new Map(chunk.entries.map(e => [e.key, e]))
  const accepted = new Map<string, { value: string; same?: string; entry: ChunkEntry }>()
  const failed = new Map<string, string>()

  for (const key of Object.keys(out.entries ?? {})) {
    if (!byKey.has(key)) report.rejected.push({ key, reason: 'not-writable' })
  }
  for (const entry of chunk.entries) {
    const raw = out.entries?.[entry.key]
    if (raw === undefined) {
      failed.set(entry.key, 'not-returned')
      continue
    }
    // A category English doesn't have (pl's _few) reads English _other, as on export.
    const enNow = getNestedValue(enData, entry.key) ?? (entry.plural ? getNestedValue(enData, `${entry.plural.base}_other`) : undefined)
    if (enNow === undefined || hash8(enNow) !== entry.enHash) {
      failed.set(entry.key, 'english-changed')
      continue
    }
    const res = checkValue(entry, raw, chunk.lang)
    if (typeof res === 'string') failed.set(entry.key, res)
    else accepted.set(entry.key, { ...res, entry })
  }
  // A plural set goes in whole or not at all.
  const brokenBases = new Set([...failed.keys()].map(k => byKey.get(k)!.plural?.base).filter(Boolean))
  for (const [key, a] of [...accepted]) {
    if (a.entry.plural && brokenBases.has(a.entry.plural.base)) {
      accepted.delete(key)
      failed.set(key, 'plural-set')
    }
  }
  for (const entry of chunk.entries) {
    if (failed.has(entry.key)) report.rejected.push({ key: entry.key, reason: failed.get(entry.key)! })
  }

  const data = structuredClone(langData)
  const newRecords: Record<string, string> = { ...records }
  for (const [key, a] of accepted) {
    setNested(data, key, a.value)
    newRecords[`${chunk.ns}:${key}`] = `${a.entry.enHash}:${a.same !== undefined ? '=' : hash8(a.value)}:d`
    if (a.same !== undefined) report.same.push({ key, reason: a.same })
    report.accepted++
  }
  const sorted = sortToEnglish(enData, data, chunk.lang)
  assertOnlyChanged(langData, sorted, new Set(accepted.keys()))
  return { data: sorted, records: newRecords, report }
}

/** Every key and value from before survives unless it's one we meant to write. */
export function assertOnlyChanged(before: Record<string, unknown>, after: Record<string, unknown>, writable: ReadonlySet<string>): void {
  for (const key of flattenKeys(before)) {
    if (writable.has(key)) continue
    if (getNestedValue(after, key) !== getNestedValue(before, key)) throw new Error(`merge would change ${key}, which it doesn't own`)
  }
  for (const key of flattenKeys(after)) {
    if (!writable.has(key) && getNestedValue(before, key) === undefined) throw new Error(`merge would add ${key}, which it doesn't own`)
  }
}

// ── CLI ─────────────────────────────────────────────────────────────────────

function exportAll(dir: string, langs: string[], max: number): void {
  const namespaces = discoverNamespaces()
  let total = 0
  for (const lang of langs) {
    const records = loadSourceRecords(lang)
    // Short strings two or more keys share: settle those once per language
    // so every chunk uses the same word for the same thing.
    const shortUses = new Map<string, number>()
    const shortKnown: Record<string, string> = {}
    let n = 0
    for (const ns of namespaces) {
      const en = loadJson(join(EN_DIR, `${ns}.json`))
      const enKeys = flattenKeys(en)
      const enValues = new Map(enKeys.map(k => [k, getNestedValue(en, k)]))
      const path = join(LOCALES_DIR, lang, `${ns}.json`)
      const data = existsSync(path) ? loadJson(path) : {}
      for (const chunk of buildChunks(lang, ns, enKeys, enValues, data, records, max)) {
        writeFileSync(join(dir, `${chunk.chunkId}.chunk.json`), JSON.stringify(chunk, null, 2) + '\n')
        n += chunk.entries.length
        for (const e of chunk.entries) {
          if (e.en.split(/\s+/).length <= 3 && e.placeholders.length === 0) shortUses.set(e.en, (shortUses.get(e.en) ?? 0) + 1)
        }
      }
      for (const k of enKeys) {
        const v = getNestedValue(data, k)
        const e = enValues.get(k)
        if (typeof e === 'string' && typeof v === 'string' && e.split(/\s+/).length <= 4 && !isEnglishCopy(v, e)) shortKnown[e] ??= v
      }
    }
    const todo = [...shortUses].filter(([en, uses]) => uses >= 2 && !(en in shortKnown)).map(([en]) => en)
    writeFileSync(join(dir, `${lang}.terms-input.json`), JSON.stringify({ lang, known: shortKnown, todo }, null, 2) + '\n')
    console.log(`[${lang}] ${n} entries exported, ${todo.length} shared short strings to settle first`)
    total += n
  }
  console.log(`${total} entries in ${dir}`)
}

function mergeAll(dir: string): void {
  const reports: MergeReport[] = []
  const chunkFiles = readdirSync(dir).filter(f => f.endsWith('.chunk.json')).sort()
  const recordCache = new Map<string, Record<string, string>>()
  for (const file of chunkFiles) {
    const chunk = JSON.parse(readFileSync(join(dir, file), 'utf-8')) as Chunk
    const outPath = join(dir, `${chunk.chunkId}.out.json`)
    if (!existsSync(outPath)) {
      console.log(`  ${chunk.chunkId}: no output yet, skipped`)
      continue
    }
    const out = JSON.parse(readFileSync(outPath, 'utf-8')) as ChunkOutput
    const enData = loadJson(join(EN_DIR, `${chunk.ns}.json`))
    const path = join(LOCALES_DIR, chunk.lang, `${chunk.ns}.json`)
    const before = existsSync(path) ? loadJson(path) : {}
    if (!recordCache.has(chunk.lang)) recordCache.set(chunk.lang, loadSourceRecords(chunk.lang))
    const res = mergeChunk(chunk, out, enData, before, recordCache.get(chunk.lang)!)
    writeJson(path, res.data)
    // Read it back: the file on disk has to keep everything it had.
    const written = loadJson(path)
    assertOnlyChanged(before, written, new Set(chunk.entries.map(e => e.key)))
    recordCache.set(chunk.lang, res.records)
    reports.push(res.report)
    console.log(`  ${chunk.chunkId}: ${res.report.accepted} accepted, ${res.report.rejected.length} rejected, ${res.report.same.length} same`)
  }
  const namespaces = discoverNamespaces()
  for (const [lang, records] of recordCache) {
    const order: string[] = []
    for (const ns of namespaces) {
      const en = loadJson(join(EN_DIR, `${ns}.json`))
      const enKeys = flattenKeys(en)
      const enValues = new Map(enKeys.map(k => [k, getNestedValue(en, k)]))
      for (const { key } of expectedKeys(enKeys, enValues, lang)) order.push(`${ns}:${key}`)
    }
    writeJson(join(SOURCES_DIR, `${lang}.json`), Object.fromEntries(order.filter(k => k in records).map(k => [k, records[k]])))
  }
  writeFileSync(join(dir, 'merge-report.json'), JSON.stringify(reports, null, 2) + '\n')
  const acc = reports.reduce((s, r) => s + r.accepted, 0)
  const rej = reports.reduce((s, r) => s + r.rejected.length, 0)
  console.log(`${acc} accepted, ${rej} rejected; report in ${join(dir, 'merge-report.json')}`)
}

function main(): void {
  const [cmd, dir] = process.argv.slice(2)
  const arg = (name: string): string | undefined => {
    const i = process.argv.indexOf(name)
    return i === -1 ? undefined : process.argv[i + 1]
  }
  if (!dir || !existsSync(dir)) {
    console.error('usage: i18n-fill.ts export|merge <existing dir>')
    process.exit(1)
  }
  if (cmd === 'export') exportAll(dir, arg('--langs')?.split(',') ?? discoverLanguages(), Number(arg('--max') ?? 400))
  else if (cmd === 'merge') mergeAll(dir)
  else {
    console.error(`unknown command: ${cmd}`)
    process.exit(1)
  }
}

if (import.meta.main) main()
