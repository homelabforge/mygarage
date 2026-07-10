import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import VehicleCard from '../VehicleCard'

// Mock currency preference hook (requires AuthProvider otherwise)
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

function setBase(href: string) {
  document.head.querySelector('base')?.remove()
  const el = document.createElement('base'); el.setAttribute('href', href); document.head.appendChild(el)
}

describe('VehicleCard photo under a subpath', () => {
  afterEach(() => {
    setBase('/')
    window.history.pushState({}, '', '/')
  })
  it('prefixes the photo <img> src with the base', () => {
    setBase('/mygarage/')
    // test-utils wraps in <BrowserRouter basename={basePath()}>; the router only
    // renders when the current location actually starts with that basename.
    window.history.pushState({}, '', '/mygarage/')
    // Render with a vehicle carrying a server-style photo path (adapt props to VehicleCard's shape).
    render(<VehicleCard vehicle={{ vin: 'V', main_photo: '/api/vehicles/V/photos/p.jpg' } as never} />)
    const img = screen.getByRole('img') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/mygarage/api/vehicles/V/photos/p.jpg')
  })
})
