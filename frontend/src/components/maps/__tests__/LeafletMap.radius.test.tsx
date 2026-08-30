/**
 * The search-radius circle.
 *
 * `LeafletMap` used to take the radius in MILES and multiply by a hardcoded
 * `1609.34` UNCONDITIONALLY, so a metric user who picked a 25 km radius
 * searched 25 km and was drawn a 40.2 km circle. It now takes metres and does
 * no arithmetic at all, which is the only way a map component can be right for
 * a client whose distance unit it does not know.
 */
import { describe, it, expect, vi } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen } from '../../../__tests__/test-utils'

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Circle: ({ radius }: { radius: number }) => (
    <div data-testid="radius-circle" data-radius={String(radius)} />
  ),
}))
vi.mock('leaflet', () => ({
  default: {
    Icon: { Default: { prototype: {}, mergeOptions: () => {} } },
    divIcon: () => ({}),
  },
}))

import LeafletMap from '../LeafletMap'

const props = {
  pois: [],
  userLocation: { lat: 1, lng: 2 },
  onMarkerClick: () => {},
}

describe('LeafletMap search radius', () => {
  it('draws the circle at the metres it is given, scaling nothing', () => {
    render(<LeafletMap {...props} radiusMeters={25000} />)
    expect(screen.getByTestId('radius-circle')).toHaveAttribute('data-radius', '25000')
  })

  it('draws a different radius at those metres too, so the value is carried not fixed', () => {
    render(<LeafletMap {...props} radiusMeters={8047} />)
    expect(screen.getByTestId('radius-circle')).toHaveAttribute('data-radius', '8047')
  })
})
