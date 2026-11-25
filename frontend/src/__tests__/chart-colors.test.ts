import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, relative } from 'node:path'
import * as ts from 'typescript'

// Chart colours come from the theme tokens in components/charts/chartTheme.tsx,
// so they flip with html.light. A hex here is a colour that stays dark-theme
// forever. Walks the AST, so issue refs like #131 in comments never count.

const SRC = resolve(__dirname, '..')

const CHART_FILES = [
  'pages/Analytics.tsx',
  'pages/GarageAnalytics.tsx',
  'components/TireAnalyticsSection.tsx',
  'components/tabs/LiveLinkChartsTab.tsx',
]
const CHART_DIR = 'components/charts'

const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/
const COLOUR_PROPS = new Set(['stroke', 'fill'])
const BACKGROUND_PROPS = new Set(['backgroundColor'])

/** A literal paint value that's fine anywhere: no paint, or a token. */
function isSafePaint(value: string): boolean {
  const v = value.trim()
  return v === 'none' || v === 'transparent' || v.startsWith('var(')
}

function propName(name: ts.PropertyName | ts.JsxAttributeName, sf: ts.SourceFile): string {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text
  return name.getText(sf)
}

/** What a literal sits in: a JSX attribute or an object property name, or ''. */
function owner(node: ts.Node, sf: ts.SourceFile): string {
  const parent = node.parent
  if (ts.isJsxAttribute(parent)) return propName(parent.name, sf)
  // fill={'blue'} wraps the literal in a JsxExpression first
  if (ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent)) return propName(parent.parent.name, sf)
  if (ts.isPropertyAssignment(parent) && parent.initializer === node) return propName(parent.name, sf)
  return ''
}

interface ChartColourHit {
  line: number
  text: string
  reasons: string[]
}

/** One hit per offending string literal, so a hex in a stroke still counts once. */
function scanChartColours(fileName: string, text: string): ChartColourHit[] {
  const kind = fileName.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, kind)
  const hits: ChartColourHit[] = []
  const visit = (node: ts.Node): void => {
    const isLiteral =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    if (isLiteral) {
      const value = (node as ts.LiteralLikeNode).text
      const reasons: string[] = []
      if (HEX.test(value)) reasons.push('hex')
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        const name = owner(node, sf)
        if (COLOUR_PROPS.has(name) && !isSafePaint(value)) reasons.push(`${name} literal`)
        if (BACKGROUND_PROPS.has(name) && !isSafePaint(value)) reasons.push('backgroundColor literal')
      }
      if (reasons.length > 0) {
        const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1
        hits.push({ line, text: node.getText(sf), reasons })
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

function chartSources(): string[] {
  const files = CHART_FILES.map((rel) => resolve(SRC, rel))
  const dir = resolve(SRC, CHART_DIR)
  if (existsSync(dir)) {
    const walk = (d: string): void => {
      for (const entry of readdirSync(d)) {
        if (entry === '__tests__') continue
        const full = join(d, entry)
        if (statSync(full).isDirectory()) walk(full)
        else if (/\.tsx?$/.test(full) && !/\.test\.tsx?$/.test(full)) files.push(full)
      }
    }
    walk(dir)
  }
  return files
}

describe('chart colours come from theme tokens', () => {
  it('finds both kinds of offender in a snippet (guard the guard)', () => {
    const snippet = [
      'const a = <CartesianGrid stroke="#333" />',
      "const b = <div style={{ backgroundColor: '#1a1f28' }} />",
    ].join('\n')
    expect(scanChartColours('snippet.tsx', snippet)).toHaveLength(2)
  })

  it('catches a named colour on stroke, fill and backgroundColor too', () => {
    const snippet = [
      'const a = <Line stroke="red" />',
      "const b = <Bar fill={'blue'} />",
      "const c = { backgroundColor: 'white' }",
      "const d = <Dot fill={{ fill: 'green' }.fill} />",
    ].join('\n')
    expect(scanChartColours('snippet.tsx', snippet).map((h) => h.line)).toEqual([1, 2, 3, 4])
  })

  it('leaves comments, tokens and no-paint alone', () => {
    const snippet = [
      '// see #172',
      'const a = <div>{/* #131 */}</div>',
      '/* #152 too */',
      'const b = <Pie fill="none" stroke="transparent" />',
      "const c = <Line stroke=\"var(--color-chart-1)\" dot={{ fill: 'var(--color-chart-1)' }} />",
      "const d = { backgroundColor: 'var(--color-surface-2)' }",
    ].join('\n')
    expect(scanChartColours('snippet.tsx', snippet)).toEqual([])
  })

  it('scans the chart files and they exist', () => {
    const files = chartSources()
    for (const f of files) expect(existsSync(f), f).toBe(true)
    // the 4 named files plus at least chartTheme.tsx
    expect(files.length).toBeGreaterThanOrEqual(5)
  })

  // Recharts paints legend text in the series colour, and slots 3-5 fail as
  // text on light. The formatter puts the label back on a text token.
  it('every Legend in a chart file passes a formatter', () => {
    const bare: string[] = []
    let legends = 0
    for (const file of chartSources()) {
      const rel = relative(SRC, file)
      const sf = ts.createSourceFile(rel, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
      const visit = (node: ts.Node): void => {
        if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(sf) === 'Legend') {
          legends++
          const has = node.attributes.properties.some((p) => ts.isJsxAttribute(p) && p.name.getText(sf) === 'formatter')
          if (!has) bare.push(`${rel}:${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}`)
        }
        ts.forEachChild(node, visit)
      }
      visit(sf)
    }
    expect(legends).toBeGreaterThanOrEqual(10)
    expect(bare).toEqual([])
  })

  it('no chart file has a literal colour', () => {
    const report: Record<string, number> = {}
    const lines: string[] = []
    for (const file of chartSources()) {
      const rel = relative(SRC, file)
      const hits = scanChartColours(rel, readFileSync(file, 'utf8'))
      if (hits.length > 0) {
        report[rel] = hits.length
        for (const h of hits) lines.push(`${rel}:${h.line} ${h.text} (${h.reasons.join(', ')})`)
      }
    }
    expect(report, lines.join('\n')).toEqual({})
  })
})
