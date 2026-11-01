/**
 * S2-04: on a vehicle with both meters there are two "Use" buttons, one per
 * suggestion. Each one's name says which reading it takes and what it is,
 * and still starts with the "Use" you can see.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { IMPERIAL_UNITS } from '../../../__tests__/factories'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({
    data: { date: '2026-04-01', odometer_km: '100000.00', source: 'manual', days_away: -9 },
    isSuccess: true,
  }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({
    data: { date: '2026-04-02', engine_hours: '812.4', source: 'manual', days_away: -8 },
    isSuccess: true,
  }),
}))
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: IMPERIAL_UNITS.secondary_gallon,
    units: IMPERIAL_UNITS,
  }),
}))

import MountEventFields, { EMPTY_ODOMETER } from '../MountEventFields'

describe('MountEventFields Use buttons', () => {
  it('names each Use after the reading it takes', () => {
    const onOdometerChange = vi.fn()
    const onHoursChange = vi.fn()
    render(
      <MountEventFields
        vin="1HGCM82633A004352"
        idPrefix="mount"
        dateLabel="Date"
        date="2026-04-10"
        onDateChange={vi.fn()}
        odometerLabel="Odometer"
        odometer={EMPTY_ODOMETER}
        onOdometerChange={onOdometerChange}
        tracksDistance
        tracksHours
        hours=""
        onHoursChange={onHoursChange}
      />,
    )

    // Both still read "Use" on screen.
    expect(screen.getAllByText('Use')).toHaveLength(2)
    const odometerUse = screen.getByRole('button', { name: /^Use nearest odometer reading, 62,137/ })
    const hoursUse = screen.getByRole('button', { name: /^Use nearest hour meter reading, 812\.4/ })

    fireEvent.click(hoursUse)
    expect(onHoursChange).toHaveBeenCalledWith('812.4')
    expect(onOdometerChange).not.toHaveBeenCalled()
    fireEvent.click(odometerUse)
    expect(onOdometerChange).toHaveBeenCalledTimes(1)
  })
})
