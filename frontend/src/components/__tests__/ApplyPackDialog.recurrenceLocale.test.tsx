/**
 * ApplyPackDialog: a typed interval saves the number its "Read as" hint names.
 *
 * RecurrenceFields reads each box when it's typed and keeps the number, so the
 * distance box has to read locale text the way NumberInput does ("1,234" in en
 * is 1234; Number() made it NaN and the interval was dropped), and the hint has to keep the locale of that typing after a
 * language switch, because the saved number does.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import { setActiveLocale } from '@/constants/i18n'
import type { ApplyPackPreview } from '../../types/reminder'

// Keys stay keys, except the hint, which gets its shipped en words so the number in it can be read.
vi.mock('react-i18next', async () => {
  const en = (await import('@/locales/en/common.json')).default as { numberInput: { readAs: string } }
  const t = (key: string, opts?: Record<string, unknown>): string =>
    key === 'numberInput.readAs' ? en.numberInput.readAs.replace('{{value}}', String(opts?.value)) : key
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const previewMock = vi.fn()
const applyMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  usePackPreview: (...args: unknown[]) => previewMock(...args),
  useApplyPack: () => ({ mutateAsync: applyMock, isPending: false }),
}))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS, gallonStandard: 'us' })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ApplyPackDialog from '../ApplyPackDialog'

const preview: ApplyPackPreview = {
  pack_id: 'oil_and_filter',
  pack_name: 'Oil & Filter Service',
  items: [
    {
      key: 'oil_filter',
      maintenance_type: 'engine_oil_filter',
      title: 'Oil & Filter Change',
      interval_km: '8000',
      interval_months: 6,
      interval_days: null,
      interval_hours: null,
      rule_action: 'create',
      rule_id: null,
      skip_reason: null,
      keep_reminder_id: null,
      adopted: false,
      supersede_reminder_ids: [],
      anchor: null,
      newer_service: null,
      typed_history: [],
      untyped_candidates: [],
      due_date: '2026-12-13',
      due_mileage_km: '151063.89',
      due_hours: null,
      reminder_type: 'smart',
      note: null,
    },
  ],
}

/** The dialog plus two language buttons. In the app i18n.ts moves the locale, then useTranslation re-renders. */
function Harness(): React.JSX.Element {
  const [, setLang] = useState('')
  return (
    <>
      <button type="button" onClick={() => { setActiveLocale('de'); setLang('de') }}>Deutsch</button>
      <button type="button" onClick={() => { setActiveLocale('en'); setLang('en') }}>English</button>
      <ApplyPackDialog vin="V1" packId="oil_and_filter" packName="Oil & Filter Service" onClose={vi.fn()} onApplied={vi.fn()} />
    </>
  )
}

const distance = () => screen.getByLabelText(/recurrence\.everyDistance/)
const months = () => screen.getByLabelText(/recurrence\.everyMonths/)
const apply = () => screen.getByRole('button', { name: 'reminderList.applyPack' })

/** Wait out the debounced re-preview, apply, and hand back what was sent for the item. */
async function applied(): Promise<Record<string, unknown>> {
  await waitFor(() => expect(apply()).toBeEnabled())
  fireEvent.click(apply())
  await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1))
  return applyMock.mock.calls[0][0].overrides.oil_filter
}

beforeEach(() => {
  vi.clearAllMocks()
  previewMock.mockReturnValue({ data: preview, isLoading: false, error: null })
  applyMock.mockResolvedValue([])
})
afterEach(() => setActiveLocale('en'))

describe('ApplyPackDialog: a typed interval in the user language', () => {
  it('en: "1,234" km is 1234, as the hint says, not dropped as unreadable', async () => {
    render(<Harness />)
    fireEvent.change(distance(), { target: { value: '1,234' } })
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    expect((await applied()).interval_km).toBe(1234)
  })

  it('de: "1.234" km is 1234, as the hint says, not 1.234', async () => {
    setActiveLocale('de')
    render(<Harness />)
    fireEvent.change(distance(), { target: { value: '1.234' } })
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    expect((await applied()).interval_km).toBe(1234)
  })

  it('de -> en: the distance hint still names the 1234 that gets saved', async () => {
    setActiveLocale('de')
    render(<Harness />)
    fireEvent.change(distance(), { target: { value: '1.234' } })
    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    expect((await applied()).interval_km).toBe(1234)
  })

  it('en -> de: months typed "1,234" were read as 1234, and the hint keeps saying so', async () => {
    render(<Harness />)
    fireEvent.change(months(), { target: { value: '1,234' } })
    fireEvent.click(screen.getByRole('button', { name: 'Deutsch' }))
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    expect((await applied()).interval_months).toBe(1234)
  })

  it('en -> de: distance typed "1.234" was read as 1.234, so no hint appears and 1.234 is saved', async () => {
    render(<Harness />)
    fireEvent.change(distance(), { target: { value: '1.234' } })
    fireEvent.click(screen.getByRole('button', { name: 'Deutsch' }))
    expect(screen.queryByText(/^Read as/)).toBeNull()
    expect((await applied()).interval_km).toBe(1.234)
  })
})
