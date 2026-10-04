import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import { makeTollTagSchema } from '../tollTag'
import { TOLL_COUNTRIES } from '../../constants/tollSystems'
import { TOLL_OTHER } from '../../utils/tollSystems'

// Same shape as the global react-i18next mock in src/__tests__/setup.ts:
// messages come back as their i18n key, which is all these tests need.
const t = ((key: string) => key) as unknown as TFunction
const schema = makeTollTagSchema(t)

const valid = {
  toll_country: 'US',
  toll_system: 'SunPass',
  toll_system_other: '',
  tag_number: 'TAG-12345',
  status: 'active' as const,
}

/** "path: message" per issue, sorted, so a test names the field and the rule. */
function issues(input: Record<string, unknown>): string[] {
  const result = schema.safeParse(input)
  return result.success ? [] : result.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).sort()
}

const COUNTRY = 'toll_country: common:validation.tollTag.countryRequired'
const SYSTEM = 'toll_system: common:validation.tollTag.systemRequired'
const NAME = 'toll_system_other: common:validation.tollTag.systemNameRequired'
const NAME_LONG = 'toll_system_other: common:validation.tollTag.systemNameTooLong'

describe('toll tag schema', () => {
  it('accepts every listed system under every country that lists it', () => {
    for (const c of TOLL_COUNTRIES) {
      for (const s of c.systems) expect(issues({ ...valid, toll_country: c.country, toll_system: s }), s).toEqual([])
    }
  })

  it('asks for a country when none is chosen, or the code is not one we list', () => {
    expect(issues({ ...valid, toll_country: '', toll_system: '' })).toEqual([COUNTRY])
    expect(issues({ ...valid, toll_country: 'ZZ' })).toEqual([COUNTRY])
  })

  it('asks for a system when the country has none chosen', () => {
    expect(issues({ ...valid, toll_system: '' })).toEqual([SYSTEM])
  })

  it('refuses a system the chosen country does not list', () => {
    expect(issues({ ...valid, toll_system: 'Telepass' })).toEqual([SYSTEM])
  })

  it('needs a typed name when the system is Other', () => {
    expect(issues({ ...valid, toll_system: TOLL_OTHER, toll_system_other: '   ' })).toEqual([NAME])
    expect(issues({ ...valid, toll_system: TOLL_OTHER, toll_system_other: 'PikePass' })).toEqual([])
  })

  it('needs a typed name when the country is Other, whatever the system select holds', () => {
    expect(issues({ ...valid, toll_country: TOLL_OTHER, toll_system: '', toll_system_other: '' })).toEqual([NAME])
    expect(issues({ ...valid, toll_country: TOLL_OTHER, toll_system: '', toll_system_other: 'Via Verde' })).toEqual([])
  })

  it('caps the typed name at 50 characters, counted after trimming', () => {
    expect(issues({ ...valid, toll_system: TOLL_OTHER, toll_system_other: 'A'.repeat(51) })).toEqual([NAME_LONG])
    expect(issues({ ...valid, toll_system: TOLL_OTHER, toll_system_other: `  ${'A'.repeat(50)}  ` })).toEqual([])
  })

  it('reports a missing system and a missing tag number together', () => {
    expect(issues({ ...valid, toll_system: '', tag_number: '' })).toEqual(
      ['tag_number: common:validation.tollTag.tagNumberRequired', SYSTEM].sort(),
    )
  })

  it('rejects tag_number over 50 characters', () => {
    expect(issues({ ...valid, tag_number: 'A'.repeat(51) })).toEqual([
      'tag_number: common:validation.tollTag.tagNumberTooLong',
    ])
  })

  it('requires status to be active or inactive', () => {
    expect(schema.safeParse({ ...valid, status: 'suspended' }).success).toBe(false)
  })
})
