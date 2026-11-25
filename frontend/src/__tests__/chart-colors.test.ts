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
// Props whose whole value is a colour. Shorthands like `border` carry a
// width too, so they only trip the hex rule.
const COLOUR_PROPS = new Set([
  'stroke', 'fill', 'color', 'background', 'backgroundColor',
  'borderColor', 'borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor',
  'outlineColor', 'stopColor', 'floodColor', 'lightingColor', 'fillColor',
])

// Every custom property index.css declares, so a var() has to name a real one.
const TOKENS = new Set([...readFileSync(resolve(SRC, 'index.css'), 'utf8').matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]))

/**
 * A var() that's really a token: its name is declared in index.css, and any
 * fallback is another such var(). var(--misspelled, red) renders red in both
 * themes, so a literal fallback doesn't count.
 */
function isTokenVar(value: string): boolean {
  const m = /^var\(\s*(--[\w-]+)\s*(?:,\s*(.*))?\)$/.exec(value.trim())
  if (!m || !TOKENS.has(m[1])) return false
  return m[2] === undefined || isTokenVar(m[2])
}

/** A literal paint value that's fine anywhere: no paint, inherited, or a token. */
function isSafePaint(value: string): boolean {
  const v = value.trim()
  return ['none', 'transparent', 'inherit', 'currentColor', 'currentcolor'].includes(v) || isTokenVar(v)
}

/** A built token like `var(--color-chart-${n})`: some declared token starts with
 *  the head's name, and no literal fallback follows in the tail. */
function isTokenTemplate(node: ts.TemplateExpression): boolean {
  const head = /^var\(\s*(--[\w-]*)$/.exec(node.head.text.trim())
  if (!head || ![...TOKENS].some((token) => token.startsWith(head[1]))) return false
  const rest = node.templateSpans.map((span) => span.literal.text).join('')
  return !/,\s*(?!var\()\S/.test(rest)
}

function propName(name: ts.PropertyName | ts.JsxAttributeName, sf: ts.SourceFile): string {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text
  return name.getText(sf)
}

/**
 * What a literal ends up in: a JSX attribute or an object property name, or ''.
 * Walks up through the wrappers a value can hide in on the way there:
 * fill={'blue'}, fill={on ? 'red' : x}, fill={c || 'blue'}, fill={('green')}.
 */
function owner(node: ts.Node, sf: ts.SourceFile): string {
  let child: ts.Node = node
  let parent = node.parent
  while (
    ts.isJsxExpression(parent) ||
    ts.isParenthesizedExpression(parent) ||
    (ts.isConditionalExpression(parent) && parent.condition !== child) ||
    (ts.isBinaryExpression(parent) &&
      [ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.AmpersandAmpersandToken].includes(parent.operatorToken.kind) &&
      !(parent.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken && parent.left === child))
  ) {
    child = parent
    parent = parent.parent
  }
  if (ts.isJsxAttribute(parent)) return propName(parent.name, sf)
  if (ts.isPropertyAssignment(parent) && parent.initializer === child) return propName(parent.name, sf)
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
        // chartTheme's constants reach a stroke through a name, so any var() anywhere has to be a real token.
        else if (value.trim().startsWith('var(') && !isTokenVar(value)) reasons.push('bad var()')
      }
      // A built string on a colour prop is fine only as a token: `var(--color-chart-${n})`.
      if (ts.isTemplateHead(node)) {
        const name = owner(node.parent, sf)
        if (COLOUR_PROPS.has(name) && !isTokenTemplate(node.parent as ts.TemplateExpression)) reasons.push(`${name} template`)
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

  // One line per form the first version walked straight past.
  it.each([
    ['a ternary branch', "const a = <Line stroke={on ? 'red' : 'var(--color-chart-1)'} />"],
    ['a fallback', "const a = <Bar fill={c || 'blue'} />"],
    ['parentheses', "const a = <Bar fill={('green')} />"],
    ['color', "const a = { color: 'tomato' }"],
    ['borderColor', "const a = { borderColor: 'navy' }"],
    ['background', "const a = { background: 'white' }"],
    ['a template on stroke', 'const a = <Line stroke={`rgb(${r}, 0, 0)`} />'],
    ['a template on fill', 'const a = { fill: `hsl(${h} 50% 50%)` }'],
    ['a misspelled token with a literal fallback', 'const a = <Line stroke="var(--misspelled-token, red)" />'],
    ['a real token with a literal fallback', "const a = { fill: 'var(--color-chart-1, red)' }"],
    ['a token index.css never declares', "const a = { color: 'var(--colour-text)' }"],
    ['a token template with a literal fallback', 'const a = <Line stroke={`var(--color-chart-${n}, red)`} />'],
    ['a token template on a made-up prefix', 'const a = <Line stroke={`var(--chart-colour-${n})`} />'],
    ['a theme constant with a typo and a fallback', "export const CHART_GRID = 'var(--color-hiar, red)'"],
  ])('catches a literal colour through %s', (_form, snippet) => {
    expect(scanChartColours('snippet.tsx', snippet)).toHaveLength(1)
  })

  it('still passes token templates and inherited colour', () => {
    const snippet = [
      'const a = <Line stroke={`var(--color-chart-${n})`} />',
      "const b = { color: 'inherit', borderColor: 'currentColor' }",
      "const c = <Bar fill={on ? 'var(--color-chart-1)' : 'none'} />",
      "const d = { color: 'var(--color-text-mute, var(--color-text))' }",
    ].join('\n')
    expect(scanChartColours('snippet.tsx', snippet)).toEqual([])
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
