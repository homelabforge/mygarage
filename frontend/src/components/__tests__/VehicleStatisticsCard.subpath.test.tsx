import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import VehicleStatisticsCard from '../VehicleStatisticsCard'
import { METRIC_UNITS } from '../../__tests__/factories'

/**
 * Component-level guard for subpath deployments (#107).
 *
 * basePath.test.ts already unit-tests withBase() itself; what regressed in #107
 * was a component forgetting to WRAP the src at all, which a util test cannot
 * catch. That guard previously sat on VehicleCard, which had become unreachable
 * — this is the card the dashboard actually renders.
 */

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: METRIC_UNITS,
  }),
}))

vi.mock('../livelink/VehicleLiveLinkWidget', () => ({ default: () => null }))

function setBase(href: string) {
  document.head.querySelector('base')?.remove()
  const el = document.createElement('base')
  el.setAttribute('href', href)
  document.head.appendChild(el)
}

const stats = {
  vin: 'V',
  year: 2018,
  make: 'Honda',
  model: 'Accord',
  main_photo_url: '/api/vehicles/V/photos/p.jpg',
  total_service_records: 0,
  total_fuel_records: 0,
  total_odometer_records: 0,
}

describe('VehicleStatisticsCard photo under a subpath', () => {
  afterEach(() => {
    setBase('/')
    window.history.pushState({}, '', '/')
  })

  it('prefixes the photo <img> src with the base', () => {
    setBase('/mygarage/')
    // test-utils wraps in <BrowserRouter basename={basePath()}>; the router only
    // renders when the current location actually starts with that basename.
    window.history.pushState({}, '', '/mygarage/')

    render(<VehicleStatisticsCard stats={stats as never} />)

    const img = screen.getByRole('img') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/mygarage/api/vehicles/V/photos/p.jpg')
  })
})
