import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import {
  DEFAULT_SUPPLIES_VIEW, readSuppliesView, rememberSuppliesView,
} from '../suppliesViewStore'

const KEY = 'mygarage:supplies:view'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('suppliesViewStore', () => {
  it('round-trips a full prefs object', () => {
    rememberSuppliesView({ sort: 'stock', group: 'vehicle', view: 'list' })
    expect(readSuppliesView()).toEqual({ sort: 'stock', group: 'vehicle', view: 'list' })
  })

  it('nothing stored reads as the default', () => {
    expect(readSuppliesView()).toEqual(DEFAULT_SUPPLIES_VIEW)
  })

  it('invalid JSON falls back to the default', () => {
    localStorage.setItem(KEY, 'not json {')
    expect(readSuppliesView()).toEqual(DEFAULT_SUPPLIES_VIEW)
  })

  it('an unknown token falls back per field, keeping the valid ones', () => {
    localStorage.setItem(KEY, JSON.stringify({ sort: 'price', view: 'list' }))
    expect(readSuppliesView()).toEqual({ sort: 'name', group: 'none', view: 'list' })
  })

  it('a throwing getItem returns the default', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(readSuppliesView()).toEqual(DEFAULT_SUPPLIES_VIEW)
  })

  it('a throwing setItem does not throw out', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => rememberSuppliesView({ sort: 'name', group: 'none', view: 'grid' })).not.toThrow()
  })
})
