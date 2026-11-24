import { describe, it, expect } from 'vitest'
import { scanFile } from '../../scripts/validate-i18n-usage'

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
