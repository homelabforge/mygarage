#!/usr/bin/env bun
/**
 * Fill missing translations in chunks, with a merge that refuses anything that
 * would break a locale.
 *
 * Usage:
 *   bun run scripts/i18n-fill.ts export <dir> [--langs de,fr] [--max 400]
 *   bun run scripts/i18n-fill.ts merge <dir>
 *
 * export wants a dir with no files from an earlier run. It writes
 * <chunkId>.chunk.json per chunk plus <lang>.terms-input.json: the short
 * strings two or more keys share (settle those first, so every chunk says the
 * same thing the same way) and the locale's existing translations of short
 * strings. Every chunkId ends in the export's run id, so an old output can't
 * land on a new chunk. Whoever translates writes <chunkId>.out.json:
 *   { "chunkId": "...", "entries": { "<key>": "translation" | { "same": "why" } } }
 * merge reads and checks every out file it finds before it writes anything,
 * then folds them back into public/locales, records each accepted value as a
 * machine draft (see i18n-stamp.ts) and writes merge-report.json.
 *
 * Writable keys are missing ones and copies of English nobody approved,
 * checked again at merge against the locale as it is then. Existing
 * translations are never touched; a plural set is accepted or rejected whole.
 */

import { randomBytes } from 'crypto'
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import {
  EN_DIR,
  LOCALES_DIR,
  SOURCES_DIR,
  discoverLanguages,
  checkTranslation,
  expectedKeys,
  flattenKeys,
  getNestedValue,
  hash8,
  isApprovedSame,
  isEnglishCopy,
  loadJson,
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
  /** `<lang>-<ns>-<n>-<runId>`, echoed back by the output. */
  chunkId: string
  /** One per export, so outputs from an earlier export can't match. */
  runId: string
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

/** English for a key, or its set's `_other` when English lacks that category (pl's _few). */
function englishFor(key: string, base: string | null, enValue: (k: string) => unknown): unknown {
  return enValue(key) ?? (base === null ? undefined : enValue(`${base}_other`))
}

/** The plural members that aren't writable, by category: what merge must find unchanged. */
function pluralExisting(
  ns: string,
  base: string,
  cats: readonly string[],
  enValue: (k: string) => unknown,
  langData: Record<string, unknown>,
  records: Readonly<Record<string, string>>,
): Record<string, unknown> {
  const existing: Record<string, unknown> = {}
  for (const c of cats) {
    const k = `${base}_${c}`
    const v = getNestedValue(langData, k)
    if (!isWritable(`${ns}:${k}`, v, englishFor(k, base, enValue), records)) existing[c] = v
  }
  return existing
}

function sameExisting(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = Object.keys(a)
  if (keys.length !== Object.keys(b).length) return false
  return keys.every(c => c in b && asText(a[c]) === asText(b[c]))
}

/** A fresh run id for one export. */
export function newRunId(): string {
  return randomBytes(4).toString('hex')
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
  runId: string,
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
    // same set expectedKeys asks for: an English _zero adds zero for every language
    const baseCats = enSet.has(`${base}_zero`) && !cats.includes('zero') ? ['zero', ...cats] : cats
    const existing = pluralExisting(ns, base, baseCats, k => enValues.get(k), langData, records)
    entry.plural = { base, category: key.slice(base.length + 1), categories: baseCats, existing }
    if (!pluralGroups.has(base)) {
      pluralGroups.set(base, [])
      groups.push(pluralGroups.get(base)!)
    }
    pluralGroups.get(base)!.push(entry)
  }

  const chunks: Chunk[] = []
  const cut = (entries: ChunkEntry[]): void => {
    chunks.push({ chunkId: `${lang}-${ns}-${chunks.length}-${runId}`, runId, lang, ns, entries })
  }
  let current: ChunkEntry[] = []
  for (const group of groups) {
    if (current.length > 0 && current.length + group.length > max) {
      cut(current)
      current = []
    }
    current.push(...group)
  }
  if (current.length > 0) cut(current)
  return chunks
}


function checkValue(entry: ChunkEntry, raw: unknown, lang: string, ns: string): { value: string; same?: string } | string {
  if (typeof raw === 'object' && raw !== null && 'same' in raw) {
    const reason = (raw as { same: unknown }).same
    if (typeof reason !== 'string' || reason.trim() === '') return 'same-without-reason'
    return { value: entry.en, same: reason }
  }
  if (typeof raw !== 'string') return 'not-a-string'
  if (raw.trim() === '') return 'empty'
  if (raw === entry.en) return 'copy'
  // the gate's own check, so nothing merges that the gate would then fail
  const problems = checkTranslation(`${ns}:${entry.key}`, entry.en, raw, lang)
  if (problems.length > 0) return problems.map(p => (p.detail ? `${p.type}: ${p.detail}` : p.type)).join('; ')
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
 * other problem is a per-key rejection. A key that stopped being writable
 * since export, or a plural set whose kept members moved, is rejected as
 * changed-since-export. Throws too if anything outside the accepted keys
 * would change, which no input should be able to cause.
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
  const enValue = (k: string): unknown => getNestedValue(enData, k)
  // Kept plural members have to look the way they did on export, or the set was built against something else.
  const movedBases = new Set<string>()
  for (const entry of chunk.entries) {
    const p = entry.plural
    if (!p || movedBases.has(p.base)) continue
    if (!sameExisting(p.existing, pluralExisting(chunk.ns, p.base, p.categories, enValue, langData, records))) movedBases.add(p.base)
  }

  for (const key of Object.keys(out.entries ?? {})) {
    if (!byKey.has(key)) report.rejected.push({ key, reason: 'not-writable' })
  }
  for (const entry of chunk.entries) {
    const raw = out.entries?.[entry.key]
    if (raw === undefined) {
      failed.set(entry.key, 'not-returned')
      continue
    }
    const enNow = englishFor(entry.key, entry.plural?.base ?? null, enValue)
    if (enNow === undefined || hash8(enNow) !== entry.enHash) {
      failed.set(entry.key, 'english-changed')
      continue
    }
    // Same rule as export, against the locale as it is now: a translation that landed since wins.
    const moved = entry.plural !== undefined && movedBases.has(entry.plural.base)
    if (moved || !isWritable(`${chunk.ns}:${entry.key}`, getNestedValue(langData, entry.key), enNow, records)) {
      failed.set(entry.key, 'changed-since-export')
      continue
    }
    const res = checkValue(entry, raw, chunk.lang, chunk.ns)
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

/** Where export and merge read English and write locales and records. Tests point these at a temp tree. */
export interface FillRoots {
  enDir: string
  localesDir: string
  sourcesDir: string
}

const DEFAULT_ROOTS: FillRoots = { enDir: EN_DIR, localesDir: LOCALES_DIR, sourcesDir: SOURCES_DIR }

const namespacesIn = (enDir: string): string[] =>
  readdirSync(enDir).filter(f => f.endsWith('.json')).map(f => f.slice(0, -'.json'.length))

function readRecords(roots: FillRoots, lang: string): Record<string, string> {
  const path = join(roots.sourcesDir, `${lang}.json`)
  return existsSync(path) ? (loadJson(path) as Record<string, string>) : {}
}

const isFillFile = (f: string): boolean =>
  f.endsWith('.chunk.json') || f.endsWith('.out.json') || f.endsWith('.terms-input.json') || f === 'merge-report.json'

/** Write one export's chunks into `dir`, which must hold nothing from an earlier run. Returns the chunks. */
export function exportAll(dir: string, langs: string[], max: number, roots: FillRoots = DEFAULT_ROOTS): Chunk[] {
  // Refuse rather than tidy up: an old out file next to new chunks is how stale work gets merged.
  const leftovers = readdirSync(dir).filter(isFillFile)
  if (leftovers.length > 0) {
    const list = leftovers.slice(0, 3).join(', ') + (leftovers.length > 3 ? ', ...' : '')
    throw new Error(`${dir} holds files from an earlier run (${list}); export into an empty dir`)
  }
  const runId = newRunId()
  const namespaces = namespacesIn(roots.enDir)
  const written: Chunk[] = []
  let total = 0
  for (const lang of langs) {
    const records = readRecords(roots, lang)
    // Short strings two or more keys share: settle those once per language
    // so every chunk uses the same word for the same thing.
    const shortUses = new Map<string, number>()
    const shortKnown: Record<string, string> = {}
    let n = 0
    for (const ns of namespaces) {
      const en = loadJson(join(roots.enDir, `${ns}.json`))
      const enKeys = flattenKeys(en)
      const enValues = new Map(enKeys.map(k => [k, getNestedValue(en, k)]))
      const path = join(roots.localesDir, lang, `${ns}.json`)
      const data = existsSync(path) ? loadJson(path) : {}
      for (const chunk of buildChunks(lang, ns, enKeys, enValues, data, records, max, runId)) {
        writeFileSync(join(dir, `${chunk.chunkId}.chunk.json`), JSON.stringify(chunk, null, 2) + '\n')
        written.push(chunk)
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
  console.log(`${total} entries in ${dir} (run ${runId})`)
  return written
}

function readJsonFile(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, 'utf-8'))
  } catch (e) {
    throw new Error(`${path}: ${(e as Error).message}`, { cause: e })
  }
}

const isPlainObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

function asChunk(raw: unknown): Chunk {
  const c = raw as Partial<Chunk>
  if (!isPlainObject(raw) || typeof c.runId !== 'string' || typeof c.chunkId !== 'string' || typeof c.lang !== 'string' || typeof c.ns !== 'string' || !Array.isArray(c.entries)) {
    throw new Error('not a chunk this version of the fill wrote; export again')
  }
  return raw as unknown as Chunk
}

function asOutput(raw: unknown): ChunkOutput {
  if (!isPlainObject(raw)) throw new Error('output is not an object')
  if (!isPlainObject(raw.entries)) throw new Error('output entries must be an object of key to translation')
  return raw as unknown as ChunkOutput
}

interface PendingLocale {
  before: Record<string, unknown>
  data: Record<string, unknown>
  owned: Set<string>
}

/** Merge every output in `dir`. Checks them all first, so a bad one means nothing gets written. */
export function mergeAll(dir: string, roots: FillRoots = DEFAULT_ROOTS): MergeReport[] {
  const reports: MergeReport[] = []
  const chunkFiles = readdirSync(dir).filter(f => f.endsWith('.chunk.json')).sort()
  const enCache = new Map<string, Record<string, unknown>>()
  const locales = new Map<string, PendingLocale>()
  const records = new Map<string, Record<string, string>>()
  const chunkIds = new Set<string>()
  let runId: string | undefined

  // Pass 1: everything in memory. Any throw here leaves the disk as it was.
  for (const file of chunkFiles) {
    try {
      const chunk = asChunk(readJsonFile(join(dir, file)))
      runId ??= chunk.runId
      if (chunk.runId !== runId) throw new Error(`mixes runs ${runId} and ${chunk.runId}; merge one export at a time`)
      chunkIds.add(chunk.chunkId)
      const outPath = join(dir, `${chunk.chunkId}.out.json`)
      if (!existsSync(outPath)) {
        console.log(`  ${chunk.chunkId}: no output yet, skipped`)
        continue
      }
      const out = asOutput(readJsonFile(outPath))
      if (!enCache.has(chunk.ns)) enCache.set(chunk.ns, loadJson(join(roots.enDir, `${chunk.ns}.json`)))
      const path = join(roots.localesDir, chunk.lang, `${chunk.ns}.json`)
      if (!locales.has(path)) {
        const before = existsSync(path) ? loadJson(path) : {}
        locales.set(path, { before, data: before, owned: new Set() })
      }
      const locale = locales.get(path)!
      if (!records.has(chunk.lang)) records.set(chunk.lang, readRecords(roots, chunk.lang))
      const res = mergeChunk(chunk, out, enCache.get(chunk.ns)!, locale.data, records.get(chunk.lang)!)
      locale.data = res.data
      for (const e of chunk.entries) locale.owned.add(e.key)
      records.set(chunk.lang, res.records)
      reports.push(res.report)
      console.log(`  ${chunk.chunkId}: ${res.report.accepted} accepted, ${res.report.rejected.length} rejected, ${res.report.same.length} same`)
    } catch (e) {
      throw new Error(`${file}: ${(e as Error).message}; nothing written`, { cause: e })
    }
  }
  for (const f of readdirSync(dir).filter(f => f.endsWith('.out.json'))) {
    if (!chunkIds.has(f.slice(0, -'.out.json'.length))) console.log(`  ${f}: matches no chunk in this export, ignored`)
  }

  // Pass 2: records before values. A record whose value never landed is
  // harmless; a value with no record is a draft nobody can find.
  const namespaces = namespacesIn(roots.enDir)
  for (const [lang, recs] of records) {
    const order: string[] = []
    for (const ns of namespaces) {
      const en = enCache.get(ns) ?? loadJson(join(roots.enDir, `${ns}.json`))
      const enKeys = flattenKeys(en)
      const enValues = new Map(enKeys.map(k => [k, getNestedValue(en, k)]))
      for (const { key } of expectedKeys(enKeys, enValues, lang)) order.push(`${ns}:${key}`)
    }
    writeJson(join(roots.sourcesDir, `${lang}.json`), Object.fromEntries(order.filter(k => k in recs).map(k => [k, recs[k]])))
  }
  for (const [path, locale] of locales) {
    writeJson(path, locale.data)
    // Read it back: the file on disk has to keep everything it had.
    assertOnlyChanged(locale.before, loadJson(path), locale.owned)
  }
  writeFileSync(join(dir, 'merge-report.json'), JSON.stringify(reports, null, 2) + '\n')
  const acc = reports.reduce((s, r) => s + r.accepted, 0)
  const rej = reports.reduce((s, r) => s + r.rejected.length, 0)
  console.log(`${acc} accepted, ${rej} rejected; report in ${join(dir, 'merge-report.json')}`)
  return reports
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
  try {
    if (cmd === 'export') exportAll(dir, arg('--langs')?.split(',') ?? discoverLanguages(), Number(arg('--max') ?? 400))
    else if (cmd === 'merge') mergeAll(dir)
    else {
      console.error(`unknown command: ${cmd}`)
      process.exit(1)
    }
  } catch (e) {
    console.error((e as Error).message)
    process.exit(1)
  }
}

if (import.meta.main) main()
