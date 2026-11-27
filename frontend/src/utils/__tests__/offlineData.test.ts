import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { claimOfflineData, forgetOfflineData } from '../offlineData'

const COPIES = [
  'analytics-cache-1-V1',
  'garage-analytics-cache',
  'vehicle-cache-V1',
  'photos-cache-V1',
]
const PREFS = ['theme', 'accent', 'unit_preference']
const MARKER = 'offline-data-owner'

interface FakeRequest {
  url: string
}

// Just enough CacheStorage for forgetOfflineData: named caches holding requests.
class FakeCache {
  entries: FakeRequest[]
  constructor(urls: string[]) {
    this.entries = urls.map((url) => ({ url }))
  }
  keys(): Promise<FakeRequest[]> {
    return Promise.resolve([...this.entries])
  }
  delete(request: FakeRequest): Promise<boolean> {
    const before = this.entries.length
    this.entries = this.entries.filter((entry) => entry.url !== request.url)
    return Promise.resolve(this.entries.length !== before)
  }
  urls(): string[] {
    return this.entries.map((entry) => entry.url)
  }
}

const ORIGIN = 'http://localhost:3000'

function fakeCaches(): { storage: unknown; byName: Map<string, FakeCache> } {
  const byName = new Map<string, FakeCache>([
    ['mygarage-static-x', new FakeCache([`${ORIGIN}/api/vehicles`, `${ORIGIN}/assets/a.js`])],
    ['mygarage-runtime-x', new FakeCache([`${ORIGIN}/api/vehicles`, `${ORIGIN}/assets/a.js`])],
  ])
  const storage = {
    keys: (): Promise<string[]> => Promise.resolve([...byName.keys()]),
    open: (name: string): Promise<FakeCache> => Promise.resolve(byName.get(name)!),
  }
  return { storage, byName }
}

function seed(): void {
  for (const key of [...COPIES, ...PREFS]) localStorage.setItem(key, '{}')
}

let byName: Map<string, FakeCache>

beforeEach(() => {
  localStorage.clear()
  seed()
  const fake = fakeCaches()
  byName = fake.byName
  vi.stubGlobal('caches', fake.storage)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('forgetOfflineData', () => {
  it('drops every offline copy and keeps the preferences', async () => {
    await forgetOfflineData()

    // Pins out a forget that only knows analytics-cache- (the old forgetAllAnalytics).
    for (const key of COPIES) expect(localStorage.getItem(key)).toBeNull()
    for (const key of PREFS) expect(localStorage.getItem(key)).toBe('{}')
  })

  it('deletes only the runtime cache API entries', async () => {
    await forgetOfflineData()

    // Pins out a forget that leaves the service worker alone, or one that
    // empties whole caches including the static shell.
    expect(byName.get('mygarage-runtime-x')!.urls()).toStrictEqual([`${ORIGIN}/assets/a.js`])
    expect(byName.get('mygarage-static-x')!.urls()).toStrictEqual([
      `${ORIGIN}/api/vehicles`,
      `${ORIGIN}/assets/a.js`,
    ])
  })

  it('clears localStorage before its first await', async () => {
    // Hold the CacheStorage pass open so the promise can't resolve yet.
    let release = (): void => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal('caches', {
      keys: async (): Promise<string[]> => {
        await gate
        return []
      },
      open: (): Promise<never> => Promise.reject(new Error('unused')),
    })

    const done = forgetOfflineData()
    // Pins out a forget that awaits the caches first: a tab closed mid-logout
    // would keep the copies.
    for (const key of COPIES) expect(localStorage.getItem(key)).toBeNull()
    release()
    await done
  })

  it('resolves with no CacheStorage at all', async () => {
    vi.stubGlobal('caches', undefined)
    await expect(forgetOfflineData()).resolves.toBeUndefined()
    for (const key of COPIES) expect(localStorage.getItem(key)).toBeNull()
  })

  it('still clears the service worker cache when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'key').mockImplementation(() => {
      throw new Error('blocked')
    })

    // Pins out a single try around both passes, where a storage failure skips the caches.
    await expect(forgetOfflineData()).resolves.toBeUndefined()
    expect(byName.get('mygarage-runtime-x')!.urls()).toStrictEqual([`${ORIGIN}/assets/a.js`])
  })
})

describe('claimOfflineData', () => {
  it('keeps the data for the same owner', async () => {
    localStorage.setItem(MARKER, '1')
    await claimOfflineData('1')

    // Pins out a claim that wipes on every load.
    expect(localStorage.getItem('vehicle-cache-V1')).toBe('{}')
    expect(byName.get('mygarage-runtime-x')!.urls()).toHaveLength(2)
    expect(localStorage.getItem(MARKER)).toBe('1')
  })

  it('wipes the data for a different owner', async () => {
    localStorage.setItem(MARKER, '1')
    await claimOfflineData('2')

    for (const key of COPIES) expect(localStorage.getItem(key)).toBeNull()
    expect(byName.get('mygarage-runtime-x')!.urls()).toStrictEqual([`${ORIGIN}/assets/a.js`])
    expect(localStorage.getItem(MARKER)).toBe('2')
  })

  it('wipes data an older build left with no marker', async () => {
    await claimOfflineData('1')

    // Pins out a claim that trusts unmarked data as the current owner's.
    for (const key of COPIES) expect(localStorage.getItem(key)).toBeNull()
    expect(localStorage.getItem(MARKER)).toBe('1')
  })

  it('leaves the data and the marker alone with nobody to claim for', async () => {
    localStorage.setItem(MARKER, '1')
    await claimOfflineData(null)

    // Pins out a claim that treats null as a different owner.
    expect(localStorage.getItem('vehicle-cache-V1')).toBe('{}')
    expect(localStorage.getItem(MARKER)).toBe('1')
  })
})
