#!/usr/bin/env bun
/**
 * Hardcoded user-facing string detection — the third i18n direction.
 *
 * The other two scripts both use the locale files as their reference:
 * validate-translations.ts checks each language AGAINST English, and
 * validate-i18n-usage.ts checks that every `t('...')` in code RESOLVES in
 * English. A string that never calls t() at all appears in neither, and the
 * vitest mock (`t: (key) => key`) can't see it either. ~770 of them
 * accumulated in the UI before a translator reported it from the outside.
 *
 * This scans code for user-visible text that never reaches i18next: JSX text
 * nodes, user-facing JSX props, toast calls, and object-literal label fields.
 *
 * Both .tsx and .ts are scanned. Restricting it to components was the same
 * blind spot one file extension over — helpers like types/family.ts and
 * schemas/auth.ts return user-facing English that no component-only scan can
 * see. Plain .ts skips the JSX rules, which would only mine generics for noise.
 *
 * Baseline, not a clean-room gate. The existing findings are recorded in
 * hardcoded-strings.baseline.json and stay quiet; only NEW ones fail. That is
 * the same shape as the CodeQL gates — it stops the bleeding immediately
 * without blocking on a ~770-string cleanup.
 *
 * Findings are keyed by (file, kind, exact string), NOT by line number, so
 * moving code around does not invalidate the baseline. Re-wording a string is
 * intentionally a new finding: that is a fresh chance to translate it.
 *
 * Escape hatch: `// i18n-exempt` on the offending line or the line directly
 * above it. Use it for genuinely non-user-facing text (debug output,
 * developer-only tooling, brand names).
 *
 * Usage:
 *   bun run scripts/validate-hardcoded-strings.ts            # gate
 *   bun run scripts/validate-hardcoded-strings.ts --update   # rewrite baseline
 *   bun run scripts/validate-hardcoded-strings.ts --report   # group by file
 * Exit code: 1 if any finding is absent from the baseline.
 */

import { readdirSync, readFileSync, statSync, writeFileSync } from 'fs'
import { join, relative } from 'path'
import { ROOT } from './translation-utils'

const SRC_DIR = join(ROOT, 'src')
const BASELINE_PATH = join(ROOT, 'scripts', 'hardcoded-strings.baseline.json')

interface Finding {
  file: string
  kind: string
  text: string
  line: number
}

/** JSX props whose values are rendered or read aloud to a user. */
const USER_FACING_PROPS = /\b(placeholder|title|aria-label|alt|label|tooltip)\s*=\s*"([^"]{3,})"/g
/**
 * Object-literal fields used to build user-visible option lists.
 *
 * `defaultValue` is here because it is the one field that LOOKS translated and
 * is not. `t('a.b', { defaultValue: 'Gas Stations' })` satisfies
 * validate-i18n-usage.ts whether or not `a.b` exists in English — when it does
 * not, i18next silently renders the defaultValue, so the English lives in the
 * component, ships as the final string, and never reaches a translator. ~47 of
 * them accumulated invisibly to both other scripts. Promote the English to a
 * real key instead. The genuine fail-safe use (ErrorBoundary, which must render
 * before the locale bundles can be trusted) passes a variable, not a literal,
 * so it does not match.
 */
const OBJECT_FIELDS =
  /\b(label|description|title|placeholder|message|heading|text|defaultValue)\s*:\s*['"]([A-Z][^'"]{2,})['"]/g
const TOAST_CALL = /toast\.(?:success|error|info|warning|message)\(\s*['"]([^'"]{3,})['"]/g
const BROWSER_DIALOG = /\b(?:alert|confirm)\(\s*['"]([^'"]{3,})['"]/g
const JSX_TEXT = />([^<>{}\n]{3,})</g

/**
 * Values that look like markup, config, or identifiers rather than prose.
 * Kept deliberately tight: over-skipping here silently hides real findings.
 */
const NON_PROSE =
  /^(true|false|null|undefined|button|submit|reset|text|number|date|email|password|checkbox|radio|file|search|tel|url|month|time|week|color|range|hidden|image|https?:|\/|#|[A-Z_]+_[A-Z_]+)$/i

/** Requires either two real words, or one capitalized word of 4+ letters. */
const LOOKS_LIKE_PROSE = /[A-Za-z]{2,}[\s'’-]+[A-Za-z]{2,}|^[A-Z][a-z]{3,}$/

function isUserFacing(raw: string): boolean {
  const s = raw.trim()
  if (s.length < 3) return false
  if (NON_PROSE.test(s)) return false
  if (!/[A-Za-z]/.test(s)) return false
  // kebab/snake/camel identifiers, css classes, paths
  if (/^[a-z0-9_-]+$/.test(s)) return false
  if (/^[a-z][a-zA-Z0-9]*$/.test(s)) return false
  if (s.includes('{t(') || /\bt\(/.test(s)) return false
  // interpolation-only or template remnants
  if (/^\{+.*\}+$/.test(s)) return false
  return LOOKS_LIKE_PROSE.test(s)
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      walk(full, out)
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

/**
 * JSX text that spans lines, or sits next to an {expression}.
 *
 * Segments run from `>` or `}` to the next `<` or `{`, so this also catches the
 * halves of a sentence broken up by interpolation. Operating on raw source
 * means TS generics (`useState<Foo | null>(…)`) and comparisons (`a > b`) also
 * produce segments, so anything containing code punctuation is rejected below —
 * a noisy gate is a gate people turn off.
 */
const JSX_TEXT_MULTILINE = /[>}]([^<>{}]{3,})[<{]/g
const CODE_PUNCTUATION = /[=;()[\]`$|&\\]|=>|\+\+/
/** Leftovers that prove a segment is code, not prose. */
const CODE_KEYWORD =
  /\b(import|export|interface|typeof|extends|implements|readonly|const|let|function|return|await|async)\b/

/**
 * Blank out import statements while preserving line numbering.
 *
 * Without this the segment between one import's closing `}` and the next
 * import's opening `{` reads as a text node — "from 'react' import" and
 * friends drowned the real findings 4:1 on the first attempt.
 */
function stripImports(source: string): string {
  const blankOut = (m: string) => m.replace(/[^\n]/g, ' ')
  return source
    .replace(/import[\s\S]*?from\s*['"][^'"]*['"]/g, blankOut)
    .replace(/import\s+['"][^'"]*['"]/g, blankOut)
}

/**
 * Blank out comments, preserving line numbering.
 *
 * The line scanner already skips comment lines, but the multiline scanner works
 * on raw source, so any comment containing an angle bracket — `<Trans>`, a
 * generic, an arrow — reads as a JSX text node. That produced findings whose
 * "user-facing string" was a fragment of a code comment.
 *
 * Only block comments and whole-line `//` comments are removed. A trailing `//`
 * is left alone on purpose: stripping it would also eat the `//` inside string
 * literals like 'https://example.com' and corrupt the surrounding segment.
 */
function stripComments(source: string): string {
  const blankOut = (m: string) => m.replace(/[^\n]/g, ' ')
  return source.replace(/\/\*[\s\S]*?\*\//g, blankOut).replace(/^[ \t]*\/\/.*$/gm, blankOut)
}

function scanMultilineJsx(rawSource: string, rel: string): Finding[] {
  const findings: Finding[] = []
  const source = stripComments(stripImports(rawSource))
  for (const m of source.matchAll(JSX_TEXT_MULTILINE)) {
    const raw = m[1]
    // `=> Promise<void>`: the arrow's own `>` is not a JSX delimiter.
    if ((m.index ?? 0) > 0 && source[(m.index ?? 0) - 1] === '=') continue
    if (CODE_PUNCTUATION.test(raw)) continue
    // string literals and code identifiers, never JSX prose (which uses &apos;)
    if (/['"`]/.test(raw)) continue
    if (CODE_KEYWORD.test(raw)) continue
    // prose wraps over a couple of lines; a longer run is almost always code
    if ((raw.match(/\n/g) ?? []).length > 3) continue
    const text = raw.replace(/\s+/g, ' ').trim()
    if (!isUserFacing(text)) continue
    // single-line hits are already covered by the line scanner
    if (!raw.includes('\n')) continue
    const line = source.slice(0, m.index).split('\n').length
    const context = source.slice(Math.max(0, m.index - 200), m.index)
    if (context.includes('i18n-exempt')) continue
    findings.push({ file: rel, kind: 'jsx-text', text, line })
  }
  return findings
}

function scanFile(path: string): Finding[] {
  const findings: Finding[] = []
  const rel = relative(ROOT, path)
  const source = readFileSync(path, 'utf-8')
  const lines = source.split('\n')
  // Plain .ts holds no JSX, and running the JSX scanners over it just mines
  // generics and comparisons for noise. Only the literal-based rules apply.
  const isJsx = path.endsWith('.tsx')

  lines.forEach((line, idx) => {
    const trimmed = line.trim()
    if (
      trimmed.startsWith('//') ||
      trimmed.startsWith('*') ||
      trimmed.startsWith('/*') ||
      trimmed.startsWith('import ')
    ) {
      return
    }
    // escape hatch: same line or the line above
    if (line.includes('i18n-exempt') || (lines[idx - 1] ?? '').includes('i18n-exempt')) return

    const push = (kind: string, text: string) => {
      if (isUserFacing(text)) {
        findings.push({ file: rel, kind, text: text.trim(), line: idx + 1 })
      }
    }

    for (const m of line.matchAll(USER_FACING_PROPS)) push(`prop:${m[1]}`, m[2])
    for (const m of line.matchAll(OBJECT_FIELDS)) push(`field:${m[1]}`, m[2])
    for (const m of line.matchAll(TOAST_CALL)) push('toast', m[1])
    for (const m of line.matchAll(BROWSER_DIALOG)) push('dialog', m[1])
    if (isJsx) {
      for (const m of line.matchAll(JSX_TEXT)) {
        // `=> Promise<void>`: the arrow's own `>` is not a JSX delimiter.
        if ((m.index ?? 0) > 0 && line[(m.index ?? 0) - 1] === '=') continue
        push('jsx-text', m[1])
      }
    }
  })

  if (isJsx) findings.push(...scanMultilineJsx(source, rel))

  return findings
}

/** Stable identity for a finding — deliberately excludes the line number. */
function keyOf(f: Finding): string {
  return `${f.file} ${f.kind} ${f.text}`
}

function main(): void {
  const args = new Set(process.argv.slice(2))
  const findings = walk(SRC_DIR).flatMap(scanFile)

  if (args.has('--update')) {
    const payload = findings
      .map((f) => ({ file: f.file, kind: f.kind, text: f.text }))
      .sort((a, b) =>
        a.file === b.file
          ? a.kind === b.kind
            ? a.text.localeCompare(b.text)
            : a.kind.localeCompare(b.kind)
          : a.file.localeCompare(b.file),
      )
    writeFileSync(BASELINE_PATH, `${JSON.stringify(payload, null, 1)}\n`)
    console.log(`✓ baseline rewritten: ${payload.length} finding(s)`)
    return
  }

  let baseline: Finding[] = []
  try {
    baseline = JSON.parse(readFileSync(BASELINE_PATH, 'utf-8'))
  } catch {
    console.error(`✗ baseline missing at ${relative(ROOT, BASELINE_PATH)} — run with --update`)
    process.exit(1)
  }
  const known = new Set(baseline.map((f) => keyOf(f as Finding)))
  const fresh = findings.filter((f) => !known.has(keyOf(f)))

  if (args.has('--report')) {
    const byFile = new Map<string, Finding[]>()
    for (const f of findings) {
      byFile.set(f.file, [...(byFile.get(f.file) ?? []), f])
    }
    console.log(`${findings.length} hardcoded string(s) across ${byFile.size} file(s):\n`)
    for (const [file, hits] of [...byFile].sort((a, b) => b[1].length - a[1].length)) {
      console.log(`  ${String(hits.length).padStart(4)}  ${file}`)
    }
    console.log('')
  }

  const stale = baseline.length - (findings.length - fresh.length)

  if (fresh.length > 0) {
    console.error(`\n✗ ${fresh.length} new hardcoded user-facing string(s):\n`)
    for (const f of fresh) {
      console.error(`  ${f.file}:${f.line}  [${f.kind}]  ${JSON.stringify(f.text)}`)
    }
    console.error(
      '\nRoute these through t() and add the key to src/locales/en/<namespace>.json.\n' +
        'If the text is genuinely not user-facing, mark the line `// i18n-exempt`.\n' +
        'Do NOT run --update to silence a new finding: the baseline is the existing\n' +
        'debt only, and it should shrink.\n',
    )
    process.exit(1)
  }

  console.log(
    `✓ No new hardcoded strings (${findings.length} known, baseline ${baseline.length}` +
      `${stale > 0 ? `, ${stale} fixed — run --update to shrink the baseline` : ''}).`,
  )
}

main()
