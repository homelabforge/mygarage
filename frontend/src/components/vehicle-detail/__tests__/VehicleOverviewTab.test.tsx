import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import type { Vehicle } from '../../../types/vehicle'
import { makeUser, makeUnitSet, IMPERIAL_UNITS, type User } from '../../../__tests__/factories'

// VehicleOverviewTab reads useUnitPreference / useCurrencyPreference / useTimeFormat,
// all of which call useAuth() directly — it throws without an AuthProvider ancestor.
// test-utils' shared `render` wrapper doesn't include one (most of its consumers
// don't need it), so mock the hook here, same pattern as VehicleKeyFacts.test.tsx
// in this same directory.
// Hoisted so the unit-preference tests below can put an account with CUSTOM
// resolved units on rung 1; every other test leaves it null and renders as the
// anonymous client this file has always assumed.
const auth = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: auth.user,
    isAuthenticated: auth.user !== null,
    defaultUnitPrefs: null,
  }),
}))

beforeEach(() => {
  auth.user = null
})

import VehicleOverviewTab from '../VehicleOverviewTab'

// A vehicle whose VIN never decoded: no trim/engine/warranty data at all.
// This is the case the old conditional rendering hid entirely.
const bareVehicle = {
  vin: 'TEST0000000000001',
  nickname: 'Bare',
  vehicle_type: 'Car',
  year: 2019,
  make: 'Mitsubishi',
  model: 'Mirage',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
} as unknown as Vehicle

const trailer = { ...bareVehicle, vehicle_type: 'Trailer' } as unknown as Vehicle

function renderTab(vehicle: Vehicle, onEditCard = vi.fn()) {
  render(
    <VehicleOverviewTab
      vin={vehicle.vin}
      vehicle={vehicle}
      lastLocation={null}
      onEditPricing={vi.fn()}
      onEditCard={onEditCard}
    />,
  )
  return { onEditCard }
}

describe('VehicleOverviewTab — cards stay addable when the vehicle has no decoded data', () => {
  it('renders Vehicle Details and Powertrain for a vehicle with none of their fields', () => {
    renderTab(bareVehicle)
    expect(screen.getByRole('heading', { name: 'detail.vehicleDetails' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'detail.powertrain' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'detail.warranty' })).toBeInTheDocument()
  })

  it('offers an edit affordance on each empty card, so the fields can be ADDED', () => {
    const { onEditCard } = renderTab(bareVehicle)
    // All four onEditCard cards (basic, details, powertrain, warranty) carry the
    // shared CardEditOverlay. Its accessible name is the same for every card,
    // because the global i18n mock discards interpolation — so count them
    // rather than querying by section name.
    const overlays = screen.getAllByRole('button', { name: 'detail.cardEdit.title' })
    expect(overlays).toHaveLength(4)
    // DOM order is basic, details, powertrain, warranty. Clicking the EMPTY
    // Details card must open the Details editor — without this an empty card is
    // a dead end, which is the failure this whole task exists to prevent.
    fireEvent.click(overlays[1])
    expect(onEditCard).toHaveBeenCalledWith('details')
  })

  it('shows the empty-state line instead of a blank card body', () => {
    renderTab(bareVehicle)
    // One line per empty card: Details, Powertrain, Warranty.
    expect(screen.getAllByText('detail.cardEmpty')).toHaveLength(3)
  })

  it('still hides Powertrain for a non-motorized vehicle', () => {
    renderTab(trailer)
    // A trailer has no engine; an empty engine card there is noise, not an
    // affordance. Details and Warranty still render.
    expect(screen.queryByRole('heading', { name: 'detail.powertrain' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'detail.vehicleDetails' })).toBeInTheDocument()
  })

  it('renders real values rather than the empty line when data exists', () => {
    renderTab({ ...bareVehicle, trim: 'Limited', cylinders: 4 } as unknown as Vehicle)
    expect(screen.getByText('Limited')).toBeInTheDocument()
    // Details and Powertrain now have data; only Warranty is empty.
    expect(screen.getAllByText('detail.cardEmpty')).toHaveLength(1)
  })
})

describe('VehicleOverviewTab — the three EPA fuel-economy figures', () => {
  /** A decoded vehicle carrying all three canonical L/100km figures. */
  const rated = {
    ...bareVehicle,
    fuel_economy_city_l_per_100km: '11.2',
    fuel_economy_highway_l_per_100km: '8.4',
    fuel_economy_combined_l_per_100km: '9.4160546',
  } as unknown as Vehicle

  it('★ reads the account\'s consumption token, not a system collapsed from volume', () => {
    // These three sites went through `formatFuelEconomy(l, unitSystem)`, and
    // `unitSystem` is collapsed from VOLUME (spec D8). This account chose
    // litres and MPG, so it was shown all three figures in L/100km: the app
    // ignoring the one preference that decides this card.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: makeUnitSet({ consumption: 'mpg_us' }),
    })

    renderTab(rated)

    // 235.214 / 11.2 = 21.0, / 8.4 = 28.0, / 9.4160546 = 25.0.
    expect(screen.getByText('21.0 MPG')).toBeInTheDocument()
    expect(screen.getByText('28.0 MPG')).toBeInTheDocument()
    expect(screen.getByText('25.0 MPG')).toBeInTheDocument()
    expect(screen.queryByText('11.2 L/100km')).not.toBeInTheDocument()
  })

  it('★ and the mirror: a gallons account that chose L/100km reads L/100km', () => {
    // Without the mirror, the assertion above is satisfied by anything that
    // always answers MPG.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: { ...IMPERIAL_UNITS, consumption: 'l_100km' },
    })

    renderTab(rated)

    expect(screen.getByText('11.20 L/100km')).toBeInTheDocument()
    expect(screen.getByText('8.40 L/100km')).toBeInTheDocument()
    expect(screen.getByText('9.42 L/100km')).toBeInTheDocument()
    expect(screen.queryByText('21.0 MPG')).not.toBeInTheDocument()
  })

  it('never appends a counterpart here, whatever show-both says', () => {
    // `formatPrimary`, not `format`: these are three dense figures in one row
    // and a parenthesised second unit on each is noise. Show-both is a
    // preference about A reading, not about every reading.
    auth.user = makeUser({
      unit_preference: 'custom',
      show_both_units: true,
      resolved_units: makeUnitSet({ consumption: 'mpg_us' }),
    })

    renderTab(rated)

    // All THREE figures, because a mutant that swaps one site for `format`
    // survives an assertion aimed at another. `getByText` matches the whole
    // normalised text node, so each positive below is itself a counterpart
    // check; the negatives name the exact string the mutant would produce.
    expect(screen.getByText('21.0 MPG')).toBeInTheDocument()
    expect(screen.getByText('28.0 MPG')).toBeInTheDocument()
    expect(screen.getByText('25.0 MPG')).toBeInTheDocument()
    expect(screen.queryByText('21.0 MPG (11.20 L/100km)')).not.toBeInTheDocument()
    expect(screen.queryByText('28.0 MPG (8.40 L/100km)')).not.toBeInTheDocument()
    expect(screen.queryByText('25.0 MPG (9.42 L/100km)')).not.toBeInTheDocument()
  })
})
