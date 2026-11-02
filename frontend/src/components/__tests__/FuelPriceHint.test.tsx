import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import type { ReactNode } from 'react'

vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
// The Chip probe surfaces its tone, like the upload dialog's tests do.
vi.mock('../ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../ui')>()
  return {
    ...actual,
    Chip: ({ tone, children }: { tone?: string; children: ReactNode }) => <span data-tone={tone}>{children}</span>,
  }
})

import FuelPriceHint, { relativeMinutes } from '../FuelPriceHint'
import type { FuelPrice, FuelPricesResponse } from '../../hooks/queries/useFuelPrices'

// The caller owns money and volume formatting; here it is a plain echo.
const formatPrice = (price: FuelPrice) => `€${price.price}`

const NOW = Date.parse('2026-10-07T07:00:00Z')

const answer = (over: Partial<FuelPricesResponse> = {}): FuelPricesResponse => ({
  provider: 'fr_instantane',
  currency: 'EUR',
  country: 'FR',
  warnings: [],
  stations: [
    {
      external_id: '63000012',
      name: null,
      address: '12 Avenue de la République',
      city: 'Clermont-Ferrand',
      postal_code: '63000',
      latitude: 45.7797,
      longitude: 3.0862,
      distance_km: 0.041,
      prices: [
        { grade: 'B7', octane: null, price: '1.689', currency: 'EUR', updated_at: '2026-10-07T06:48:00Z' },
        { grade: 'E10', octane: 95, price: '1.729', currency: 'EUR', updated_at: '2026-10-07T06:48:00Z' },
        { grade: 'E5', octane: 98, price: '1.819', currency: 'EUR', updated_at: null },
      ],
    },
  ],
  ...over,
})

describe('FuelPriceHint (#211)', () => {
  it('lists the station’s prices with the form’s fuel first, and hands the chosen price back', async () => {
    const user = userEvent.setup()
    const onUsePrice = vi.fn()
    render(<FuelPriceHint prices={answer()} grade="E10" octane={95} onUsePrice={onUsePrice} formatPrice={formatPrice} />)
    expect(screen.getByText('fuel.pricesTitle')).toBeInTheDocument()
    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('E10 95')).toBeInTheDocument()
    expect(within(rows[0]).getByText('€1.729')).toBeInTheDocument()
    expect(within(rows[0]).getByText('fuel.pricesCurrentFuel')).toHaveAttribute('data-tone', 'accent')
    expect(rows[0]).toHaveAttribute('data-testid', 'fuel-price-current')
    expect(rows[1]).toHaveAttribute('data-testid', 'fuel-price-other')
    await user.click(within(rows[2]).getByRole('button', { name: 'fuel.pricesUseThisPrice' }))
    expect(onUsePrice).toHaveBeenCalledWith(expect.objectContaining({ grade: 'E5', octane: 98, price: '1.819' }))
  })

  it('tells E5 at 95 from E5 at 98 by the octane the form holds', () => {
    render(<FuelPriceHint prices={answer()} grade="E5" octane={98} onUsePrice={vi.fn()} formatPrice={formatPrice} />)
    const rows = screen.getAllByRole('listitem')
    expect(within(rows[0]).getByText('E5 98')).toBeInTheDocument()
    expect(rows[0]).toHaveAttribute('data-testid', 'fuel-price-current')
  })

  it('renders nothing without a provider or while loading, and says so without a price', () => {
    const { rerender } = render(
      <FuelPriceHint prices={answer({ provider: null, stations: [] })} onUsePrice={vi.fn()} formatPrice={formatPrice} />
    )
    expect(screen.queryByTestId('fuel-price-hint')).not.toBeInTheDocument()
    expect(screen.queryByTestId('fuel-price-hint-empty')).not.toBeInTheDocument()
    rerender(<FuelPriceHint prices={answer()} loading onUsePrice={vi.fn()} formatPrice={formatPrice} />)
    expect(screen.queryByTestId('fuel-price-hint')).not.toBeInTheDocument()
    rerender(<FuelPriceHint prices={answer({ stations: [] })} onUsePrice={vi.fn()} formatPrice={formatPrice} />)
    expect(screen.getByText('fuel.pricesNone')).toBeInTheDocument()
    rerender(
      <FuelPriceHint
        prices={answer({ stations: [], warnings: ['fr_instantane: request failed'] })}
        onUsePrice={vi.fn()}
        formatPrice={formatPrice}
      />
    )
    expect(screen.getByText('fuel.pricesUnavailable')).toBeInTheDocument()
  })

  it('says how long ago a price was reported, in the active locale', () => {
    expect(relativeMinutes('2026-10-07T06:48:00Z', 'en-US', NOW)).toBe('12 minutes ago')
    expect(relativeMinutes('2026-10-07T06:48:00Z', 'fr-FR', NOW)).toBe('il y a 12 minutes')
    expect(relativeMinutes('2026-10-07T01:00:00Z', 'en-US', NOW)).toBe('6 hours ago')
    expect(relativeMinutes('2026-10-01T07:00:00Z', 'en-US', NOW)).toBe('6 days ago')
    expect(relativeMinutes('2026-10-07T08:00:00Z', 'en-US', NOW)).toBeNull()
    expect(relativeMinutes(null, 'en-US', NOW)).toBeNull()
    expect(relativeMinutes('nonsense', 'en-US', NOW)).toBeNull()
  })
})
