import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'

// Every map went grey because the SW grabbed OSM tile loads and re-fetched
// them itself, and CSP connect-src 'self' blocks that fetch. These run the
// real public/sw.js in a fake worker scope and fire fetch events at it.
const SW_SOURCE = readFileSync(resolve(__dirname, '../../public/sw.js'), 'utf-8')
const ORIGIN = 'https://garage.example'

type FetchHandler = (event: unknown) => void

function loadFetchHandler(): FetchHandler {
  const handlers: Record<string, FetchHandler> = {}
  const self = {
    location: { href: `${ORIGIN}/sw.js?v=test`, origin: ORIGIN },
    addEventListener: (type: string, fn: FetchHandler): void => {
      handlers[type] = fn
    },
    skipWaiting: (): void => {},
    clients: { claim: (): void => {} },
  }
  const never = (): Promise<never> => new Promise(() => {})
  runInNewContext(SW_SOURCE, {
    self,
    URL,
    Response,
    console,
    setTimeout,
    fetch: never,
    caches: { match: never, open: never, keys: never },
  })
  return handlers.fetch
}

function fire(handler: FetchHandler, url: string, extra: Record<string, string> = {}): boolean {
  let responded = false
  handler({
    request: { url, method: 'GET', mode: 'no-cors', destination: 'image', ...extra },
    respondWith: (): void => {
      responded = true
    },
  })
  return responded
}

describe('sw.js fetch handler', () => {
  const handler = loadFetchHandler()

  it('leaves OSM tiles to the browser', () => {
    expect(fire(handler, 'https://tile.openstreetmap.org/13/1949/3321.png')).toBe(false)
  })

  it('leaves any other cross-origin load alone too', () => {
    expect(fire(handler, 'https://elsewhere.example/app.js', { destination: 'script' })).toBe(false)
  })

  it('still handles its own static assets', () => {
    expect(fire(handler, `${ORIGIN}/assets/index-abc123.js`, { destination: 'script' })).toBe(true)
  })

  it('still handles its own API calls', () => {
    expect(fire(handler, `${ORIGIN}/api/vehicles`, { destination: '' })).toBe(true)
  })
})
