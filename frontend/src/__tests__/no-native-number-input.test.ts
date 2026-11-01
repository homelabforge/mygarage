import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, relative } from 'node:path'
import * as ts from 'typescript'

// A native number box reads a comma decimal as blank and drops it, and its
// min/max/step either do nothing or block the save with the browser's own
// bubble. Typed numbers go through NumberInput / registerDecimal instead.

const SRC = resolve(__dirname, '..')

/** Recharts axes take type="number" for a numeric scale; they aren't inputs. */
const CHART_AXES = new Set(['XAxis', 'YAxis', 'ZAxis'])

// The dev-only primitive gallery shows the raw Input on purpose. Exact count,
// so a new one in there still trips this.
const ALLOWLIST: Readonly<Record<string, number>> = {
  'components/ui/gallery/Gallery.tsx': 2,
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(full) && !/\.test\.tsx?$/.test(full)) out.push(full)
  }
  return out
}

/** Whether a `type` attribute's value is, or could be, the string "number". */
function couldBeNumber(init: ts.JsxAttributeValue | undefined): boolean {
  if (init === undefined) return false
  if (ts.isStringLiteral(init)) return init.text === 'number'
  let found = false
  const visit = (node: ts.Node): void => {
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && node.text === 'number') found = true
    ts.forEachChild(node, visit)
  }
  visit(init)
  return found
}

function tagName(attr: ts.JsxAttribute): string {
  const element = attr.parent.parent
  return ts.isJsxOpeningElement(element) || ts.isJsxSelfClosingElement(element) ? element.tagName.getText() : ''
}

/** Every `type="number"` (or `type={... 'number' ...}`) on a JSX element under src, as file:line <Tag>. */
function collectNumberTypeHits(): Map<string, string[]> {
  const hits = new Map<string, string[]>()
  for (const file of walk(SRC)) {
    const rel = relative(SRC, file)
    const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    const sf = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, kind)
    const visit = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) && node.name.getText(sf) === 'type' && couldBeNumber(node.initializer)) {
        const tag = tagName(node)
        if (!CHART_AXES.has(tag)) {
          const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1
          hits.set(rel, [...(hits.get(rel) ?? []), `${rel}:${line} <${tag}>`])
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(sf)
  }
  return hits
}

describe('native number inputs', () => {
  it('has no type="number" outside the gallery and chart axes', () => {
    const offenders: string[] = []
    const allowlisted: Record<string, number> = {}
    for (const [rel, found] of collectNumberTypeHits()) {
      if (rel in ALLOWLIST) allowlisted[rel] = found.length
      else offenders.push(...found)
    }
    expect(
      offenders,
      'Use NumberInput (controlled, read with parseDecimalInput / canonicalFromTypedUnitField) ' +
        'or registerDecimal, never a native number input.\n' + offenders.join('\n'),
    ).toEqual([])
    expect(allowlisted, 'gallery allowlist drifted').toEqual(ALLOWLIST)
  })

  it('sees a conditional type and skips a chart axis', () => {
    // The scanner itself, so a broken walk can't pass the guard above by finding nothing.
    const hits = collectNumberTypeHits()
    expect(hits.get('components/ui/gallery/Gallery.tsx')).toHaveLength(2)
    expect([...hits.keys()].some((rel) => rel.startsWith('pages/Analytics'))).toBe(false)
  })
})
