/**
 * Pack names (#211): a shipped pack reads its name from the bundle by id and
 * falls back to the file's text; a saved pack is shown as typed.
 */
import { describe, it, expect } from 'vitest'
import type { TFunction } from 'i18next'
import { packDescription, packDisplayName } from '../reminderPacks'

const BUNDLE: Record<string, string> = {
  'vehicles:reminderPacks.oil_and_filter.name': 'Vidange et filtre à huile',
  'vehicles:reminderPacks.oil_and_filter.description': 'Vidange tous les 8 000 km.',
}

// i18next's own fallback contract: the key's text, else `defaultValue`.
const t = ((key: string, options?: { defaultValue?: string }) =>
  BUNDLE[key] ?? options?.defaultValue ?? key) as unknown as TFunction

describe('packDisplayName', () => {
  it('reads a shipped pack by id', () => {
    expect(packDisplayName({ id: 'oil_and_filter', name: 'Oil & Filter Service' }, t)).toBe(
      'Vidange et filtre à huile'
    )
  })

  it('falls back to the file name for a pack the bundle does not know', () => {
    expect(packDisplayName({ id: 'brand_new_pack', name: 'Brand New Pack' }, t)).toBe(
      'Brand New Pack'
    )
  })

  it('shows a saved pack as typed, even when its id looks like a shipped one', () => {
    expect(
      packDisplayName({ id: 'oil_and_filter', name: 'My own oil pack', is_custom: true }, t)
    ).toBe('My own oil pack')
  })
})

describe('packDescription', () => {
  it('reads a shipped description by id and falls back to the file text', () => {
    expect(
      packDescription({ id: 'oil_and_filter', name: 'x', description: 'DIY oil change' }, t)
    ).toBe('Vidange tous les 8 000 km.')
    expect(packDescription({ id: 'other', name: 'x', description: 'As shipped' }, t)).toBe(
      'As shipped'
    )
    expect(packDescription({ id: 'other', name: 'x' }, t)).toBe('')
  })
})
