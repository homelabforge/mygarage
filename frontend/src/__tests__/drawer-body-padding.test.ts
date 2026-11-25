import { describe, it, expect } from 'vitest'
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'
import * as ts from 'typescript'

// Drawer and Dialog already pad their body to line up with the header title.
// A form that pads itself on top of that sits indented, so the outermost body
// element gets vertical padding at most.

const SRC = resolve(__dirname, '..')
const HOSTS = new Set(['Drawer', 'FormModalWrapper', 'Dialog'])
// The primitives themselves render {children} into the padded body.
const SKIP = new Set(['components/ui/Drawer.tsx', 'components/ui/Dialog.tsx', 'components/FormModalWrapper.tsx'])
// Horizontal padding only, with or without a variant prefix (sm:px-4).
// The value can be a number, a bracket or a v4 var: p-6, px-[10px], p-(--gap).
const H_PAD = /(^|[\s:])(p|px|pl|pr|ps|pe)-(\d|\[|\(|px\b)/
// A full border (border, border-2) draws its own box, like a dropzone or an
// error alert. Its edge is what lines up with the title, so its padding is inside.
// Both ternary branches land in one string, so a border that's only on in one
// branch still counts. Accepted gap.
const BOXED = /(^|\s)border(-[1-9]\d*|-\[\d[^\]]*\])?(?=\s|$)/

type El = ts.JsxElement | ts.JsxSelfClosingElement
type Top = { host: boolean; node: El }
interface Fs {
  read: (file: string) => string
  exists: (file: string) => boolean
}
const diskFs: Fs = { read: (f) => readFileSync(f, 'utf8'), exists: existsSync }

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === '__tests__' || entry === 'node_modules') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx$/.test(full) && !/\.test\.tsx$/.test(full)) out.push(full)
  }
  return out
}

function tagOf(n: El): string {
  return (ts.isJsxElement(n) ? n.openingElement.tagName : n.tagName).getText()
}

/** Every static string in className: literals, template heads and tails, cn() args. */
function classText(n: El): string {
  const attrs = ts.isJsxElement(n) ? n.openingElement.attributes : n.attributes
  const parts: string[] = []
  for (const a of attrs.properties) {
    if (!ts.isJsxAttribute(a) || a.name.getText() !== 'className' || !a.initializer) continue
    const visit = (x: ts.Node): void => {
      if (ts.isStringLiteral(x) || ts.isNoSubstitutionTemplateLiteral(x)) parts.push(x.text)
      else if (ts.isTemplateExpression(x)) {
        parts.push(x.head.text)
        x.templateSpans.forEach((s) => parts.push(s.literal.text))
      }
      ts.forEachChild(x, visit)
    }
    visit(a.initializer)
  }
  return parts.join(' ')
}

/** Outermost JSX elements under a node, through fragments, conditionals, ternaries and map arrows. */
function tops(node: ts.Node, out: Top[] = []): Top[] {
  const visit = (x: ts.Node): void => {
    if (ts.isJsxElement(x) || ts.isJsxSelfClosingElement(x)) {
      const tag = tagOf(x)
      if (tag === 'Fragment' || tag === 'React.Fragment') {
        if (ts.isJsxElement(x)) x.children.forEach(visit)
        return
      }
      out.push({ host: /^[a-z]/.test(tag), node: x })
      return
    }
    if (ts.isJsxFragment(x)) {
      x.children.forEach(visit)
      return
    }
    // props like footer={...} aren't the body
    if (ts.isJsxAttribute(x)) return
    ts.forEachChild(x, visit)
  }
  visit(node)
  return out
}

const WRAPPERS = new Set(['memo', 'React.memo', 'forwardRef', 'React.forwardRef'])

/** memo(fn) and forwardRef(fn) hide the real component one call deep, maybe two. */
function unwrap(fn: ts.Node): ts.Node {
  while (ts.isCallExpression(fn) && WRAPPERS.has(fn.expression.getText()) && fn.arguments.length > 0) fn = fn.arguments[0]
  return fn
}

/** Outermost elements a component returns, across every return. */
function returnedTops(fn: ts.Node): Top[] {
  const out: Top[] = []
  if (ts.isArrowFunction(fn) && !ts.isBlock(fn.body)) return tops(fn.body, out)
  const visit = (x: ts.Node): void => {
    if (x !== fn && (ts.isFunctionDeclaration(x) || ts.isFunctionExpression(x) || ts.isArrowFunction(x))) return
    if (ts.isReturnStatement(x) && x.expression) tops(x.expression, out)
    ts.forEachChild(x, visit)
  }
  ts.forEachChild(fn, visit)
  return out
}

function findFn(sf: ts.SourceFile, name: string): ts.Node | null {
  for (const st of sf.statements) {
    if (ts.isFunctionDeclaration(st) && st.name?.text === name) return st
    if (ts.isVariableStatement(st)) {
      for (const d of st.declarationList.declarations) {
        if (ts.isIdentifier(d.name) && d.name.text === name && d.initializer) return unwrap(d.initializer)
      }
    }
  }
  return null
}

function findDefault(sf: ts.SourceFile): ts.Node | null {
  for (const st of sf.statements) {
    if (ts.isFunctionDeclaration(st) && st.modifiers?.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)) return st
    if (ts.isExportAssignment(st)) {
      const fn = unwrap(st.expression)
      return ts.isIdentifier(fn) ? findFn(sf, fn.text) : fn
    }
  }
  return null
}

/**
 * Scans `files` under `root` and returns one row per outermost body element:
 * `PAD host -> <tag> where [classes]` or `ok  host -> <tag> where`.
 * Components are followed one level, through same-file or relative/@ .tsx
 * imports only. The ui barrel is index.ts, so Card and friends count as boxes.
 */
function scan(root: string, files: string[], fs: Fs = diskFs): string[] {
  const cache = new Map<string, ts.SourceFile>()
  const parse = (file: string): ts.SourceFile => {
    let sf = cache.get(file)
    if (!sf) {
      sf = ts.createSourceFile(file, fs.read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
      cache.set(file, sf)
    }
    return sf
  }
  const lineOf = (sf: ts.SourceFile, n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1

  const resolveComp = (file: string, name: string): { file: string; fn: ts.Node } | null => {
    const sf = parse(file)
    const local = findFn(sf, name)
    if (local) return { file, fn: local }
    for (const st of sf.statements) {
      if (!ts.isImportDeclaration(st) || !st.importClause) continue
      const spec = (st.moduleSpecifier as ts.StringLiteral).text
      const clause = st.importClause
      const isDefault = clause.name?.text === name
      const named =
        clause.namedBindings && ts.isNamedImports(clause.namedBindings)
          ? clause.namedBindings.elements.find((e) => e.name.text === name)
          : undefined
      if (!isDefault && !named) continue
      let base: string
      if (spec.startsWith('@/')) base = resolve(root, spec.slice(2))
      else if (spec.startsWith('.')) base = resolve(dirname(file), spec)
      else return null
      for (const cand of [base + '.tsx', join(base, 'index.tsx')]) {
        if (!fs.exists(cand)) continue
        const target = parse(cand)
        const fn = isDefault ? findDefault(target) : findFn(target, named?.propertyName?.text ?? name)
        if (fn) return { file: cand, fn }
      }
    }
    return null
  }

  const rows: string[] = []
  for (const file of files) {
    const rel = relative(root, file)
    if (SKIP.has(rel)) continue
    const sf = parse(file)
    const visit = (x: ts.Node): void => {
      if (ts.isJsxElement(x) && HOSTS.has(tagOf(x))) {
        const host = `${rel}:${lineOf(sf, x)} <${tagOf(x)}>`
        const check = (t: Top, inFile: string, via: string, followed: boolean): void => {
          const tag = tagOf(t.node)
          const where = `${relative(root, inFile)}:${lineOf(parse(inFile), t.node)}`
          if (t.host) {
            const cls = classText(t.node)
            const pads = BOXED.test(cls) ? [] : cls.split(/\s+/).filter((c) => H_PAD.test(c))
            rows.push(
              pads.length > 0
                ? `PAD ${host} -> ${via}<${tag}> ${where}  [${pads.join(' ')}]`
                : `ok  ${host} -> ${via}<${tag}> ${where}`,
            )
            return
          }
          // a nested Drawer/Dialog is its own host, and one level is enough
          if (HOSTS.has(tag) || followed) return
          const r = resolveComp(inFile, tag)
          const inner = r ? returnedTops(r.fn) : []
          // can't see inside it, so say so instead of passing quietly
          if (!r || inner.length === 0) rows.push(`comp ${host} -> ${via}<${tag}> ${where} (${r ? 'no JSX' : 'unresolved'})`)
          if (r) inner.forEach((i) => check(i, r.file, `${via}<${tag}>/`, true))
        }
        x.children.forEach((c) => tops(c).forEach((t) => check(t, file, '', false)))
      }
      ts.forEachChild(x, visit)
    }
    visit(sf)
  }
  return rows.sort()
}

/** Scans inline sources through a fake fs, so a fixture never touches src. */
function scanInline(sources: Record<string, string>): string[] {
  const root = '/virtual'
  const files = Object.keys(sources).map((f) => join(root, f))
  const fs: Fs = {
    read: (f) => sources[relative(root, f)],
    exists: (f) => relative(root, f) in sources,
  }
  return scan(root, files, fs)
}

const padded = (rows: string[]): string[] => rows.filter((r) => r.startsWith('PAD'))

/** Component names the walk couldn't open, deduped. */
const unresolved = (rows: string[]): string[] =>
  [...new Set(rows.filter((r) => r.startsWith('comp')).map((r) => /-> <(\w+)>/.exec(r)?.[1] ?? r))].sort()

// Things the walk can't open on purpose. Anything new here needs a reason, or
// it's a form wrapper the guard just stopped seeing.
const UNRESOLVED_OK: Readonly<Record<string, string>> = {
  Field: 'ui primitive behind the barrel, a label and its control, no body padding',
  EmptyState: 'ui primitive behind the barrel, a centred empty message',
}

describe('drawer and dialog bodies own their padding', () => {
  it('no outermost body element pads itself horizontally', () => {
    const offenders = padded(scan(SRC, walk(SRC)))
    expect(
      offenders,
      "Drawer and Dialog bodies are already padded. Drop the element's p-*/px-* (py-* is fine).\n" +
        offenders.join('\n'),
    ).toEqual([])
  })

  it('actually walks src: real hosts, Dialog bodies and a followed component all show up', () => {
    // So a broken walk can't pass the guard above by finding nothing.
    const rows = scan(SRC, walk(SRC))
    expect(rows.length).toBeGreaterThan(60)
    expect(rows.some((r) => r.includes('components/FuelRecordForm.tsx:') && r.includes('<FormModalWrapper> -> <form>'))).toBe(true)
    expect(rows.some((r) => r.includes('<Dialog> -> '))).toBe(true)
    expect(rows.some((r) => r.includes('<RegistrationCertificateImport>/<div>'))).toBe(true)
  })

  it('flags a padded form straight inside FormModalWrapper', () => {
    const rows = scanInline({
      'Form.tsx': [
        'export function Form() {',
        '  return (',
        '    <FormModalWrapper title="t" onClose={close}>',
        '      <form className="p-6 space-y-4" />',
        '    </FormModalWrapper>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(padded(rows)).toEqual(['PAD Form.tsx:3 <FormModalWrapper> -> <form> Form.tsx:4  [p-6]'])
  })

  it('flags a template literal behind a conditional, and lets vertical padding through', () => {
    const rows = scanInline({
      'Cond.tsx': [
        'export function Cond() {',
        '  return (',
        '    <Drawer open onClose={close} title="t">',
        '      {cond && <div className={`px-4 ${x}`} />}',
        '      <p className="py-6 text-sm" />',
        '    </Drawer>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(rows).toEqual([
      'PAD Cond.tsx:3 <Drawer> -> <div> Cond.tsx:4  [px-4]',
      'ok  Cond.tsx:3 <Drawer> -> <p> Cond.tsx:5',
    ])
  })

  it('flags every horizontal spelling: variants, logical sides, brackets and v4 vars', () => {
    const rows = scanInline({
      'Spell.tsx': [
        'export function Spell() {',
        '  return (',
        '    <Drawer open onClose={close} title="t">',
        '      <div className="sm:px-6" />',
        '      <div className="pr-[10px]" />',
        '      <div className="ps-2" />',
        '      <div className="pe-2" />',
        '      <div className="p-(--gap)" />',
        '      <div className="px-(--x)" />',
        '    </Drawer>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(padded(rows)).toEqual([
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:4  [sm:px-6]',
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:5  [pr-[10px]]',
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:6  [ps-2]',
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:7  [pe-2]',
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:8  [p-(--gap)]',
      'PAD Spell.tsx:3 <Drawer> -> <div> Spell.tsx:9  [px-(--x)]',
    ])
  })

  it('lets a bordered box keep its padding, but not a one-sided, zero or colour-only border', () => {
    const rows = scanInline({
      'Box.tsx': [
        'export function Box() {',
        '  return (',
        '    <Dialog open onClose={close} title="t">',
        '      <div className={`border-2 border-dashed rounded-lg p-8 ${drag}`} />',
        '      <div className="border-b p-4" />',
        '      <div className="border-0 p-6" />',
        '      <div className="border-[color:var(--x)] px-4" />',
        '    </Dialog>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(padded(rows)).toEqual([
      'PAD Box.tsx:3 <Dialog> -> <div> Box.tsx:5  [p-4]',
      'PAD Box.tsx:3 <Dialog> -> <div> Box.tsx:6  [p-6]',
      'PAD Box.tsx:3 <Dialog> -> <div> Box.tsx:7  [px-4]',
    ])
  })

  it('follows a component into its own file and flags its padded root', () => {
    const dir = mkdtempSync(join(tmpdir(), 'drawer-pad-'))
    try {
      writeFileSync(
        join(dir, 'Host.tsx'),
        [
          "import MyForm from './MyForm'",
          'export function Host() {',
          '  return (',
          '    <Drawer open onClose={close} title="t">',
          '      <MyForm />',
          '    </Drawer>',
          '  )',
          '}',
        ].join('\n'),
      )
      writeFileSync(
        join(dir, 'MyForm.tsx'),
        ['export default function MyForm() {', '  return <form className="space-y-4 pl-6" />', '}'].join('\n'),
      )
      const rows = scan(dir, walk(dir))
      expect(padded(rows)).toEqual(['PAD Host.tsx:4 <Drawer> -> <MyForm>/<form> MyForm.tsx:2  [pl-6]'])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('unwraps memo and forwardRef to reach the padded root', () => {
    const rows = scanInline({
      'Wrapped.tsx': [
        "import { memo, forwardRef } from 'react'",
        'const MemoForm = memo(function MemoForm() {',
        '  return <form className="p-6" />',
        '})',
        'const RefForm = React.forwardRef((props, ref) => <form ref={ref} className="px-4" />)',
        'export function Host() {',
        '  return (',
        '    <Drawer open onClose={close} title="t">',
        '      <MemoForm />',
        '      <RefForm />',
        '    </Drawer>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(padded(rows)).toEqual([
      'PAD Wrapped.tsx:8 <Drawer> -> <MemoForm>/<form> Wrapped.tsx:3  [p-6]',
      'PAD Wrapped.tsx:8 <Drawer> -> <RefForm>/<form> Wrapped.tsx:5  [px-4]',
    ])
  })

  it('reports a component it cannot follow, so a new form wrapper cannot hide', () => {
    const rows = scanInline({
      'Pkg.tsx': [
        "import { MysteryForm } from 'some-pkg'",
        'export function Host() {',
        '  return (',
        '    <Drawer open onClose={close} title="t">',
        '      <MysteryForm />',
        '    </Drawer>',
        '  )',
        '}',
      ].join('\n'),
    })
    expect(unresolved(rows)).toEqual(['MysteryForm'])
  })

  it('src only has the allowlisted components it cannot open', () => {
    expect(unresolved(scan(SRC, walk(SRC)))).toEqual(Object.keys(UNRESOLVED_OK).sort())
  })
})
