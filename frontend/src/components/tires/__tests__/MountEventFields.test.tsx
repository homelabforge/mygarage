import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import i18next, { type TFunction } from 'i18next'

import { IMPERIAL_UNITS } from '../../../__tests__/factories'
import vehiclesEn from '../../../locales/en/vehicles.json'

const useNearestMock = vi.fn()
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: (vin: string, date: string) => useNearestMock(vin, date),
}))
const useNearestHoursMock = vi.fn()
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: (vin: string, date: string) => useNearestHoursMock(vin, date),
}))

// Imperial, the default for every new account: 100000 km does not survive
// mile rounding (100000 / 1.609344 -> 62137 mi, and back -> 99999.808128 km),
// which is exactly the shape of the defect this file pins.
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: IMPERIAL_UNITS.secondary_gallon,
    units: IMPERIAL_UNITS,
  }),
}))

import MountEventFields, { EMPTY_ODOMETER } from '../MountEventFields'

const VIN = '1HGCM82633A004352'
const READING = { date: '2026-04-01', odometer_km: '100000.00', source: 'manual', days_away: -9 }

function renderField(overrides: Partial<React.ComponentProps<typeof MountEventFields>> = {}) {
  const onDateChange = vi.fn()
  const onOdometerChange = vi.fn()
  render(
    <MountEventFields
      vin={VIN}
      idPrefix="mount"
      dateLabel="tireList.eventDate"
      date="2026-04-10"
      onDateChange={onDateChange}
      odometerLabel="tireList.odometer"
      odometer={EMPTY_ODOMETER}
      onOdometerChange={onOdometerChange}
      {...overrides}
    />
  )
  return { onDateChange, onOdometerChange }
}

describe('MountEventFields', () => {
  beforeEach(() => {
    useNearestMock.mockReturnValue({ data: READING, isSuccess: true })
  })

  it('asks for the reading nearest the date it is given', () => {
    renderField()
    expect(useNearestMock).toHaveBeenCalledWith(VIN, '2026-04-10')
    expect(screen.getByLabelText('tireList.eventDate')).toHaveValue('2026-04-10')
  })

  it('shows the suggestion and reports its exact canonical origin only on Use', () => {
    const { onOdometerChange } = renderField()
    expect(screen.getByTestId('mount-suggestion')).toHaveTextContent('tireList.suggestion')
    expect(onOdometerChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('tireList.suggestionUse'))
    expect(onOdometerChange).toHaveBeenCalledTimes(1)
    const next = onOdometerChange.mock.calls[0][0]
    // The origin must carry the reading's EXACT canonical value (100000), not
    // a re-conversion of the rounded '62137' mi it displays -- that
    // re-conversion is what used to store 99999.55958.
    expect(next.origin.canonical).toBe(100000)
    expect(next.typed).toBe('62137')
    expect(next.typed).toBe(next.origin.display)
  })

  it('never writes over a value the user typed when a suggestion arrives', () => {
    const { onOdometerChange } = renderField({
      odometer: { typed: '123', origin: EMPTY_ODOMETER.origin },
    })
    expect(screen.getByLabelText('tireList.odometer')).toHaveValue(123)
    expect(onOdometerChange).not.toHaveBeenCalled()
  })

  it('typing keeps the prior origin instead of resetting it', () => {
    // A non-null seeded origin is what makes this assertion false-able: if
    // typing reset the origin to the empty one, this would still pass with a
    // seed of `{canonical: null, display: ''}`.
    const seededOrigin = { canonical: 55000, display: '55000' }
    const { onOdometerChange } = renderField({
      odometer: { typed: '55000', origin: seededOrigin },
    })
    fireEvent.change(screen.getByLabelText('tireList.odometer'), { target: { value: '55001' } })
    expect(onOdometerChange).toHaveBeenCalledWith({ typed: '55001', origin: seededOrigin })
  })

  it('says so quietly when the vehicle has no readings', () => {
    useNearestMock.mockReturnValue({ data: null, isSuccess: true })
    renderField()
    expect(screen.getByText('tireList.suggestionNone')).toBeInTheDocument()
    expect(screen.queryByText('tireList.suggestionUse')).toBeNull()
  })

  it('renders nothing about a suggestion while the query is unresolved', () => {
    useNearestMock.mockReturnValue({ data: undefined, isSuccess: false })
    renderField()
    expect(screen.queryByTestId('mount-suggestion')).toBeNull()
    expect(screen.queryByText('tireList.suggestionNone')).toBeNull()
  })
})

describe('MountEventFields on the hour meter (#217)', () => {
  beforeEach(() => {
    // Reset, not just re-stubbed: the suite above has already called the
    // odometer hook, and the first case here says it was never asked.
    useNearestMock.mockReset()
    useNearestMock.mockReturnValue({ data: undefined, isSuccess: false })
    useNearestHoursMock.mockReset()
    useNearestHoursMock.mockReturnValue({ data: undefined, isSuccess: false })
  })

  it('shows only the hour meter on an hours-only vehicle', () => {
    renderField({ tracksDistance: false, tracksHours: true, hours: '', onHoursChange: vi.fn() })
    expect(document.getElementById('mount-odometer')).toBeNull()
    expect(document.getElementById('mount-hours')).not.toBeNull()
    expect(useNearestMock).not.toHaveBeenCalled()
  })

  it('offers the nearest hours reading and seeds it with one decimal on Use', () => {
    useNearestHoursMock.mockReturnValue({
      data: { date: '2026-04-01', engine_hours: '100.0', source: 'manual', days_away: -9 },
      isSuccess: true,
    })
    const onHoursChange = vi.fn()
    renderField({ tracksDistance: false, tracksHours: true, hours: '', onHoursChange })
    expect(useNearestHoursMock).toHaveBeenCalledWith(VIN, '2026-04-10')
    expect(screen.getByTestId('mount-hours-suggestion')).toHaveTextContent('tireList.suggestionHours')
    fireEvent.click(screen.getByText('tireList.suggestionUse'))
    // One decimal, the way the meter reads: '100.0', not '100'.
    expect(onHoursChange).toHaveBeenCalledWith('100.0')
  })

  it('a dual vehicle gets both fields', () => {
    renderField({ tracksHours: true, hours: '', onHoursChange: vi.fn() })
    expect(document.getElementById('mount-odometer')).not.toBeNull()
    expect(document.getElementById('mount-hours')).not.toBeNull()
  })
})

describe('MountEventFields day offset wording', () => {
  // The component's own t() is the global key-echo mock, which cannot show a
  // plural. So the shipped English bundle is resolved through a real i18next
  // instance, the way the app resolves it.
  const english = async (): Promise<TFunction> => {
    const instance = i18next.createInstance()
    await instance.init({
      lng: 'en',
      ns: ['vehicles'],
      defaultNS: 'vehicles',
      resources: { en: { vehicles: vehiclesEn } },
      interpolation: { escapeValue: false },
    })
    return instance.t
  }

  it('reads "1 day", not "1 days"', async () => {
    const t = await english()
    expect(t('tireList.suggestionEarlier', { count: 1 })).toBe('1 day earlier')
    expect(t('tireList.suggestionLater', { count: 1 })).toBe('1 day later')
    expect(t('tireList.suggestionEarlier', { count: 9 })).toBe('9 days earlier')
    expect(t('tireList.suggestionLater', { count: 2 })).toBe('2 days later')
  })
})
