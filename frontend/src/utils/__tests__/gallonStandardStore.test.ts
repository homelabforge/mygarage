import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

/**
 * The store's contract is about WHEN the value is right, not just what it is.
 *
 * A persisted UK setting has to be live before the first render and before any
 * non-React caller converts anything. The previous shape read localStorage and
 * wrote UnitConverter inside a hook's render body, and pushed the server value
 * in an effect that resolves after first paint, so the opening frame and every
 * already-mounted component were on US gallons.
 */

const STORAGE_KEY = 'imperial_gallon_standard'

async function freshStore(persisted?: 'us' | 'uk') {
  vi.resetModules()
  localStorage.clear()
  if (persisted) localStorage.setItem(STORAGE_KEY, persisted)
  const store = await import('../gallonStandardStore')
  const { UnitConverter } = await import('../units')
  return { store, UnitConverter }
}

describe('gallonStandardStore', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('initialises from localStorage at module load, before any snapshot is read', async () => {
    const { store, UnitConverter } = await freshStore('uk')

    // Both agree immediately: no effect has run yet.
    expect(store.getGallonStandard()).toBe('uk')
    expect(UnitConverter.getGallonStandard()).toBe('uk')
  })

  it('defaults to US when nothing is persisted', async () => {
    const { store, UnitConverter } = await freshStore()
    expect(store.getGallonStandard()).toBe('us')
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('a UK store converts litres to UK gallons, not US', async () => {
    const { UnitConverter } = await freshStore('uk')
    // 45.4609 L is exactly 10 UK gallons (12.01 US gallons).
    expect(UnitConverter.litersToGallons(45.4609)).toBeCloseTo(10, 2)
  })

  it('setting the standard persists it, updates the converter and notifies', async () => {
    const { store, UnitConverter } = await freshStore('us')
    const listener = vi.fn()
    const unsubscribe = store.subscribeToGallonStandard(listener)

    store.setGallonStandard('uk')

    expect(listener).toHaveBeenCalledTimes(1)
    expect(store.getGallonStandard()).toBe('uk')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('uk')
    expect(UnitConverter.getGallonStandard()).toBe('uk')

    unsubscribe()
    store.setGallonStandard('us')
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('setting the same value again notifies nobody (no render loop)', async () => {
    const { store } = await freshStore('uk')
    const listener = vi.fn()
    store.subscribeToGallonStandard(listener)

    store.setGallonStandard('uk')

    expect(listener).not.toHaveBeenCalled()
  })

  it('survives localStorage throwing (private mode)', async () => {
    vi.resetModules()
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    try {
      const store = await import('../gallonStandardStore')
      expect(store.getGallonStandard()).toBe('us')
    } finally {
      getItem.mockRestore()
    }
  })
})
