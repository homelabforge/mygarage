/**
 * The default marker images ship with the app.
 *
 * All three maps used to point Leaflet's default marker at cdnjs, which was the
 * only reason cdnjs sat in the CSP. The images come from `leaflet/dist/images`
 * now, so a marker never asks a third party for anything.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import L from 'leaflet'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

type Loader = () => Promise<unknown>

// Each map on its own, so one map's fix can't cover for another that lost it.
const MAPS: [string, Loader][] = [
  ['LeafletMap', () => import('../LeafletMap')],
  ['TripRouteMap', () => import('../TripRouteMap')],
  ['LastLocationMap', () => import('../LastLocationMap')],
]

beforeEach(() => {
  // Leaflet is an external dep, so resetModules doesn't give a fresh copy: wipe
  // the options by hand. Our own modules do reload, so the fix runs again.
  vi.resetModules()
  L.Icon.Default.mergeOptions({ iconUrl: 'unset', iconRetinaUrl: 'unset', shadowUrl: 'unset' })
})

describe('Leaflet default marker icon', () => {
  it.each(MAPS)('%s points it at the bundled images, not a CDN', async (_name, load) => {
    await load()
    const options = L.Icon.Default.prototype.options

    expect(options.iconUrl).toBe(iconUrl)
    expect(options.iconRetinaUrl).toBe(iconRetinaUrl)
    expect(options.shadowUrl).toBe(shadowUrl)
    for (const url of [options.iconUrl, options.iconRetinaUrl, options.shadowUrl]) {
      expect(url).not.toMatch(/^https?:/)
    }
  })
})
