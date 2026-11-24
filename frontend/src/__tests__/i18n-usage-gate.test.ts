import { describe, it, expect } from 'vitest'
import { collectReferences, emptyReferences, findUnusedKeys, scanFile } from '../../scripts/validate-i18n-usage'

// Fixtures go through the gate's real per-file scan. Keys that start with
// `nope.` don't exist in English, so each one should come back as a violation.
const keys = (source: string): string[] => scanFile(source, 'fixture.tsx').map((v) => v.key)

const bound = "const { t } = useTranslation('vehicles')\n"

// Each form gets a real key next to a missing one, so a test proves the scan
// both found the key and resolved it, not just that it found something.
describe('validate-i18n-usage: key fields read back through t()', () => {
  it('checks descKey', () => {
    expect(keys(`${bound}const X = [{ descKey: 'detail.powertrain' }, { descKey: 'nope.desc' }]\n`)).toEqual(['nope.desc'])
  })

  it('checks titleKey', () => {
    expect(keys(`${bound}const S = [{ titleKey: 'detail.powertrain' }, { titleKey: 'nope.title' }]\n`)).toEqual(['nope.title'])
  })

  it('checks hintKey, qualified or bound', () => {
    expect(
      keys("const H = [{ hintKey: 'forms:insuranceCoverages.actualCashValue' }, { hintKey: 'forms:nope.hint' }]\n"),
    ).toEqual(['forms:nope.hint'])
    expect(keys(`${bound}const H = [{ hintKey: 'detail.powertrain' }, { hintKey: 'nope.hint' }]\n`)).toEqual(['nope.hint'])
  })
})

describe('validate-i18n-usage: double-quoted keys', () => {
  it('checks t("...")', () => {
    expect(keys(`${bound}t("detail.powertrain")\nt("nope.double")\n`)).toEqual(['nope.double'])
  })

  it('checks a double-quoted module const passed to t()', () => {
    expect(keys(`${bound}const OK = "detail.powertrain"\nconst KEY = "nope.const"\nt(OK)\nt(KEY)\n`)).toEqual(['nope.const'])
  })

  it('honours a double-quoted ns option', () => {
    expect(keys(`${bound}t("powertrain", { ns: "nope" })\n`)).toEqual(['powertrain'])
    expect(keys(`${bound}t("detail.powertrain", { ns: "vehicles" })\n`)).toEqual([])
  })

  it('still checks single quotes', () => {
    expect(keys(`${bound}t('detail.powertrain')\nt('nope.single')\n`)).toEqual(['nope.single'])
  })
})

describe('validate-i18n-usage: unused English keys', () => {
  const english = new Map<string, Set<string>>([
    ['vehicles', new Set(['detail.powertrain', 'detail.gone', 'types.car', 'types.boat', 'days_one', 'days_other', 'days', 'field.title'])],
    ['forms', new Set(['fuel.grade', 'fuel.dead'])],
  ])
  const unused = (...sources: string[]): string[] => {
    const refs = emptyReferences()
    for (const s of sources) collectReferences(s, refs, 'fixture.tsx')
    return findUnusedKeys(english, refs)
  }

  it('reports keys nothing references', () => {
    expect(unused('')).toEqual([
      'vehicles:detail.powertrain',
      'vehicles:detail.gone',
      'vehicles:types.car',
      'vehicles:types.boat',
      'vehicles:days_one',
      'vehicles:days_other',
      'vehicles:days',
      'vehicles:field.title',
      'forms:fuel.grade',
      'forms:fuel.dead',
    ])
  })

  it('counts bare, ns-qualified, plural-base, prefix and field references as used', () => {
    expect(
      unused(
        "t('detail.powertrain')",
        't("forms:fuel.grade")',
        "t('days', { count })",
        'const label = t(`types.${kind}`)',
        "const F = { titleKey: 'vehicles:field.title' }",
      ),
    ).toEqual(['vehicles:detail.gone', 'forms:fuel.dead'])
  })

  it('scopes an ns-qualified prefix to its namespace', () => {
    expect(unused('t(`forms:fuel.${g}`)')).not.toContain('forms:fuel.grade')
    expect(unused('t(`forms:fuel.${g}`)')).toContain('vehicles:detail.gone')
  })

  it("doesn't let a bare or dot-less template mark everything used", () => {
    expect(unused('const k = `${a}`', 'const j = `${ns}:${key}`', 'const p = `types${x}`')).toHaveLength(10)
  })

  it("doesn't count a key that only a comment mentions", () => {
    const src = "// `detail.gone` lied to metric users\n/* 'forms:fuel.dead' too */\nconst url = 'https://x.y/detail.powertrain'\n"
    expect(unused(src)).toContain('vehicles:detail.gone')
    expect(unused(src)).toContain('forms:fuel.dead')
  })

  it("doesn't read a /* inside a string as a comment", () => {
    const src = '<input accept="image/*" />\n{t(\'detail.gone\')}\n{/* jsx note */}\n'
    expect(unused(src)).not.toContain('vehicles:detail.gone')
  })

  it("counts a 'prefix.' + x concatenation", () => {
    expect(unused("t('types.' + kind)")).not.toContain('vehicles:types.boat')
  })
})

// The comment stripper used to be a regex, so a ` //` inside a string ate the
// rest of the line and a comment glued to code survived. Each fixture here was
// wrong under that regex.
describe('validate-i18n-usage: comments vs literals', () => {
  const english = new Map<string, Set<string>>([['vehicles', new Set(['detail.gone', 'types.boat'])]])
  const unused = (source: string, file = 'fixture.tsx'): string[] => {
    const refs = emptyReferences()
    collectReferences(source, refs, file)
    return findUnusedKeys(english, refs)
  }

  it('keeps a key after a string holding " //" on the same line', () => {
    expect(unused("const note = 'a // b'; t('detail.gone')\n")).toEqual(['vehicles:types.boat'])
    expect(unused("t('types.boat', { u: 'see http: //x' }); t('detail.gone')\n")).toEqual([])
  })

  it("doesn't count a key in a comment glued to code", () => {
    expect(unused("foo()//t('detail.gone')\nbar()/*'types.boat'*/\n")).toEqual(['vehicles:detail.gone', 'vehicles:types.boat'])
  })

  it("doesn't count a key in a JSDoc block", () => {
    expect(unused("/** Shows 'detail.gone'. */\nexport const x = t('types.boat')\n")).toEqual(['vehicles:detail.gone'])
  })

  it('keeps a key after JSX text holding //', () => {
    expect(unused("const A = (): JSX.Element => <p>use a // here {t('detail.gone')}</p>\n")).toEqual(['vehicles:types.boat'])
    // Text that opens with ` //` looks exactly like trivia to the comment helpers.
    expect(unused("const B = (): JSX.Element => <p> // here {t('detail.gone')}</p>\n")).toEqual(['vehicles:types.boat'])
  })

  it('keeps a key after a template literal holding //', () => {
    expect(unused("const u = `http: //x/${id}`; t('detail.gone')\n")).toEqual(['vehicles:types.boat'])
  })

  it('keeps a key after a regex holding //', () => {
    expect(unused("const re = /[ //]/; t('detail.gone')\n")).toEqual(['vehicles:types.boat'])
  })

  it('parses a .ts file as TS, not JSX', () => {
    // As TSX, `<string>foo` opens a JSX element and the comment turns into JSX text.
    expect(unused("const v = <string>foo // 'detail.gone'\n", 'fixture.ts')).toEqual([
      'vehicles:detail.gone',
      'vehicles:types.boat',
    ])
  })
})
