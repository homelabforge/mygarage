import { describe, it, expect } from 'vitest'
import type { TollCountry } from '../../constants/tollSystems'
import {
  TOLL_OTHER,
  canonicalTollSystem,
  choiceForCountry,
  guessTollCountry,
  initialTollSelection,
  listedTollSystem,
  selectedTollSystem,
  tidyTollSystem,
  tollCountryName,
  tollCountryOptions,
  tollSystemMatchKey,
  tollSystemsFor,
  usesOtherName,
} from '../tollSystems'

// Two euro countries sharing a system. The shipped data has neither case yet.
const EURO: readonly TollCountry[] = [
  { country: 'IT', currencies: ['EUR'], languages: ['it'], systems: ['Telepass', 'UnipolMove'] },
  { country: 'FR', currencies: ['EUR'], languages: ['fr'], systems: ['Bip&Go', 'Telepass'] },
]

describe('matching a typed name', () => {
  it('ignores case, spacing and punctuation but keeps non-Latin letters', () => {
    expect(tollSystemMatchKey('Touch \'n Go RFID')).toBe(tollSystemMatchKey('touch n go rfid'))
    expect(tollSystemMatchKey('E-ZPass')).toBe('ezpass')
    expect(tollSystemMatchKey('Ключ-Тег')).toBe('ключтег')
  })

  it('tidies by trimming and collapsing whitespace', () => {
    expect(tidyTollSystem('  Via   Verde \t')).toBe('Via Verde')
  })

  // The backend tidies with Python's str.split(), which also splits on these.
  it('treats the whitespace Python splits on as whitespace', () => {
    expect(tidyTollSystem('\u0085Pike\u001fPass\u001c')).toBe('Pike Pass')
  })

  it('finds the listed spelling, or null', () => {
    expect(listedTollSystem('ezpass')).toBe('E-ZPass')
    expect(listedTollSystem('  TOUCH N GO RFID ')).toBe('Touch \'n Go RFID')
    expect(listedTollSystem('telepass')).toBe('Telepass')
    expect(listedTollSystem('PikePass')).toBeNull()
    expect(listedTollSystem('Other')).toBeNull()
    expect(listedTollSystem('')).toBeNull()
    expect(listedTollSystem('!!!')).toBeNull()
  })

  it('saves the listed spelling when there is one, else the tidied text', () => {
    expect(canonicalTollSystem(' ezpass ')).toBe('E-ZPass')
    expect(canonicalTollSystem('  Pike   Pass ')).toBe('Pike Pass')
    expect(canonicalTollSystem('   ')).toBe('')
  })
})

describe('guessTollCountry', () => {
  it('counts currency over language', () => {
    expect(guessTollCountry('USD', 'en')).toBe('US')
    expect(guessTollCountry('MYR', 'en')).toBe('MY')
    expect(guessTollCountry('EUR', 'it')).toBe('IT')
    expect(guessTollCountry('USD', 'it')).toBe('US')
    expect(guessTollCountry('GBP', 'ms')).toBe('MY')
  })

  it('guesses nothing with no match or a tie', () => {
    expect(guessTollCountry('GBP', 'en')).toBeNull()
    expect(guessTollCountry('EUR', 'en', EURO)).toBeNull()
    expect(guessTollCountry('EUR', 'fr', EURO)).toBe('FR')
  })
})

describe('initialTollSelection', () => {
  it('starts a new tag on the guess with no system', () => {
    expect(initialTollSelection(undefined, 'US')).toEqual({ country: 'US', choice: '', otherName: '' })
    expect(initialTollSelection(null, null)).toEqual({ country: '', choice: '', otherName: '' })
  })

  it('opens a listed system under its country, loose spellings included', () => {
    expect(initialTollSelection('SunPass', null)).toEqual({ country: 'US', choice: 'SunPass', otherName: '' })
    expect(initialTollSelection('sunpass ', 'MY')).toEqual({ country: 'US', choice: 'SunPass', otherName: '' })
  })

  it('opens a system listed in several countries under the guess, else the first in the data', () => {
    expect(initialTollSelection('Telepass', 'FR', EURO).country).toBe('FR')
    expect(initialTollSelection('Telepass', null, EURO).country).toBe('IT')
    expect(initialTollSelection('Telepass', 'US', EURO).country).toBe('IT')
  })

  it('opens anything else on Other with the saved text, the old literal "Other" included', () => {
    expect(initialTollSelection('PikePass', 'US')).toEqual({ country: 'US', choice: TOLL_OTHER, otherName: 'PikePass' })
    expect(initialTollSelection('PikePass', null)).toEqual({ country: TOLL_OTHER, choice: TOLL_OTHER, otherName: 'PikePass' })
    expect(initialTollSelection('Other', 'MY')).toEqual({ country: 'MY', choice: TOLL_OTHER, otherName: 'Other' })
  })
})

describe('what a selection saves', () => {
  it('uses the name field when either dropdown is on Other', () => {
    expect(usesOtherName({ country: 'US', choice: 'SunPass' })).toBe(false)
    expect(usesOtherName({ country: 'US', choice: TOLL_OTHER })).toBe(true)
    expect(usesOtherName({ country: TOLL_OTHER, choice: '' })).toBe(true)
  })

  it('saves the choice, or the canonical typed name', () => {
    expect(selectedTollSystem({ country: 'US', choice: 'SunPass', otherName: 'ignored' })).toBe('SunPass')
    expect(selectedTollSystem({ country: 'US', choice: TOLL_OTHER, otherName: ' ezpass ' })).toBe('E-ZPass')
    expect(selectedTollSystem({ country: TOLL_OTHER, choice: '', otherName: 'Via  Verde' })).toBe('Via Verde')
    expect(selectedTollSystem({ country: TOLL_OTHER, choice: 'SunPass', otherName: 'Via Verde' })).toBe('Via Verde')
  })
})

describe('choiceForCountry', () => {
  it('keeps a system the new country lists, and Other', () => {
    expect(choiceForCountry('E-ZPass', 'US')).toBe('E-ZPass')
    expect(choiceForCountry(TOLL_OTHER, 'MY')).toBe(TOLL_OTHER)
    expect(choiceForCountry('Telepass', 'FR', EURO)).toBe('Telepass')
  })

  it('clears a system the new country does not list', () => {
    expect(choiceForCountry('SunPass', 'MY')).toBe('')
  })

  it('forces Other for country Other and clears for no country', () => {
    expect(choiceForCountry('SunPass', TOLL_OTHER)).toBe(TOLL_OTHER)
    expect(choiceForCountry(TOLL_OTHER, '')).toBe('')
  })
})

describe('options', () => {
  it('sorts countries by their name in the reader language', () => {
    expect(tollCountryOptions('en-US')).toEqual([
      { value: 'IT', label: 'Italy' },
      { value: 'MY', label: 'Malaysia' },
      { value: 'US', label: 'United States' },
    ])
    expect(tollCountryOptions('it-IT').map((o) => o.label)).toEqual(['Italia', 'Malaysia', 'Stati Uniti'])
  })

  it('sorts a country\'s systems by name, and has none for no country or Other', () => {
    expect(tollSystemsFor('US', 'en-US')).toEqual([
      'E-ZPass', 'EZ TAG', 'FasTrak', 'I-PASS', 'NTTA TollTag', 'SunPass', 'TxTag',
    ])
    expect(tollSystemsFor('', 'en-US')).toEqual([])
    expect(tollSystemsFor(TOLL_OTHER, 'en-US')).toEqual([])
  })

  it('falls back to the code when the browser has no Intl.DisplayNames', () => {
    const intl = Intl as unknown as Record<string, unknown>
    const original = intl.DisplayNames
    intl.DisplayNames = undefined
    try {
      expect(tollCountryName('US', 'en-US')).toBe('US')
      expect(tollCountryOptions('en-US').map((o) => o.label)).toEqual(['IT', 'MY', 'US'])
    } finally {
      intl.DisplayNames = original
    }
  })
})
