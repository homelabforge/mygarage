/**
 * A tank's alert lines in its settings block. Labels resolve from the shipped
 * English bundle, so "Level: Low" is the wording a user reads, and two tanks'
 * fields cannot share one accessible name.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import type { DeviceReading } from '@/types/livelink'
import settingsEn from '../../../../locales/en/settings.json'

vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const found = key.split('.').reduce<unknown>(
      (node, part) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined),
      settingsEn,
    )
    if (typeof found !== 'string') return key
    return found.replace(/{{(\w+)}}/g, (_, name: string) => String(options?.[name] ?? ''))
  }
  return {
    useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: () => Promise.resolve() } }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const updateParameter = vi.hoisted(() => vi.fn())
vi.mock('@/services/livelinkService', () => ({ livelinkService: { updateParameter } }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import SensorAlerts from '../SensorAlerts'

const LEVEL = 'PROPANE_T1_LEVEL_PCT'
const BATTERY = 'PROPANE_T1_SENSOR_BATT_PCT'

const reading = (over: Partial<DeviceReading>): DeviceReading => ({
  param_key: 'X',
  display_name: null,
  unit: '%',
  value: 50,
  timestamp: null,
  show_on_dashboard: true,
  format: 'value',
  max_value: null,
  warning_min: null,
  critical_min: null,
  alert_lines: [],
  ...over,
})

const READINGS: DeviceReading[] = [
  reading({
    param_key: LEVEL,
    display_name: 'Tank 1 level',
    warning_min: 25,
    critical_min: 10,
    alert_lines: ['low', 'critical'],
  }),
  reading({ param_key: 'PROPANE_T1_TEMP_C', display_name: 'Tank 1 temperature', unit: 'C' }),
  reading({ param_key: BATTERY, display_name: 'Tank 1 battery', warning_min: 20, alert_lines: ['low'] }),
]

const renderAlerts = (readings: DeviceReading[] = READINGS) => {
  const onSaved = vi.fn()
  const view = render(<SensorAlerts readings={readings} sensorLabel="Tank 1" onSaved={onSaved} />)
  return { onSaved, ...view }
}

const field = (name: string): HTMLInputElement => screen.getByRole('textbox', { name })
const save = (): HTMLElement => screen.getByRole('button', { name: 'Save alerts' })
const type = (name: string, text: string): void => {
  fireEvent.change(field(name), { target: { value: text } })
}

beforeEach(() => {
  vi.clearAllMocks()
  updateParameter.mockResolvedValue({})
})

describe('SensorAlerts', () => {
  it("offers each reading's lines under its short name, with what is set now", () => {
    renderAlerts()

    expect(screen.getByRole('heading', { name: 'Alerts' })).toBeInTheDocument()
    expect(field('Level: Low').value).toBe('25')
    expect(field('Level: Critical').value).toBe('10')
    expect(field('Battery: Low').value).toBe('20')
    // Temperature offers no line.
    expect(screen.getAllByRole('textbox')).toHaveLength(3)
  })

  it('shows a switched-off line blank', () => {
    renderAlerts([reading({ param_key: BATTERY, display_name: 'Tank 1 battery', alert_lines: ['low'] })])

    expect(field('Battery: Low').value).toBe('')
    expect(field('Battery: Low')).toHaveAttribute('placeholder', 'Off')
  })

  it('draws nothing for a sensor with no lines to offer', () => {
    const { container } = renderAlerts([READINGS[1]])

    expect(container).toBeEmptyDOMElement()
  })

  it('saves nothing until something changes', () => {
    renderAlerts()

    expect(save()).toBeDisabled()
    type('Battery: Low', '15')
    expect(save()).toBeEnabled()
  })

  it("saves each changed reading's lines, and only those", async () => {
    const { onSaved } = renderAlerts()

    type('Level: Low', '30')
    type('Level: Critical', '12.5')
    fireEvent.click(save())

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(updateParameter).toHaveBeenCalledTimes(1)
    expect(updateParameter).toHaveBeenCalledWith(LEVEL, { warning_min: 30, critical_min: 12.5 })
    expect(toast.success).toHaveBeenCalledWith('Alerts saved')
  })

  it('cannot be saved twice while a save is on its way', async () => {
    let finish: (value: unknown) => void = () => {}
    updateParameter.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const { onSaved } = renderAlerts()

    type('Battery: Low', '15')
    fireEvent.click(save())

    expect(save()).toBeDisabled()
    expect(field('Battery: Low')).toBeDisabled()
    finish({})
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(updateParameter).toHaveBeenCalledTimes(1)
  })

  it('switches a line off when its field is left blank', async () => {
    const { onSaved } = renderAlerts()

    type('Battery: Low', '  ')
    fireEvent.click(save())

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(updateParameter).toHaveBeenCalledWith(BATTERY, { warning_min: null })
  })

  it.each(['101', '-1', 'lots'])('refuses %s', (text) => {
    renderAlerts()

    type('Battery: Low', text)

    expect(screen.getByRole('alert')).toHaveTextContent('Enter 0 to 100, or leave it blank.')
    expect(save()).toBeDisabled()
  })

  it.each([
    ['10', '10'],
    ['20', '10'],
  ])('refuses critical %s at or above low %s', (critical, low) => {
    renderAlerts()

    type('Level: Low', low)
    type('Level: Critical', critical)

    expect(screen.getByRole('alert')).toHaveTextContent('Critical must be below Low.')
    expect(save()).toBeDisabled()
  })

  it('holds back the whole save while any field is wrong', () => {
    renderAlerts()

    type('Battery: Low', '15')
    type('Level: Low', '150')

    expect(save()).toBeDisabled()
  })

  it('lets a critical line stand alone', async () => {
    const { onSaved } = renderAlerts()

    type('Level: Low', '')
    type('Level: Critical', '40')
    fireEvent.click(save())

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(updateParameter).toHaveBeenCalledWith(LEVEL, { warning_min: null, critical_min: 40 })
  })

  it('says why a save failed, and keeps what was typed', async () => {
    updateParameter.mockRejectedValue(new Error('boom'))
    const { onSaved } = renderAlerts()

    type('Battery: Low', '15')
    fireEvent.click(save())

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
    expect(field('Battery: Low').value).toBe('15')
  })

  it('shows what the server holds once the readings reload', () => {
    const { rerender } = renderAlerts()
    type('Battery: Low', '15')

    const reloaded = READINGS.map((r) => (r.param_key === BATTERY ? { ...r, warning_min: 17 } : r))
    rerender(<SensorAlerts readings={reloaded} sensorLabel="Tank 1" onSaved={vi.fn()} />)

    expect(field('Battery: Low').value).toBe('17')
    expect(save()).toBeDisabled()
  })

  it("puts NumberInput's read-as hint outside the field's label and its narrow box", () => {
    renderAlerts()
    type('Level: Low', '1,234')

    // This file's i18n mock only knows settings, so the common hint reads as its key.
    const hint = screen.getByText('numberInput.readAs')
    const input = field('Level: Low')
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(hint.id)
    // Inside a <label> it joins the label's text, and inside the 5rem box it wraps to nothing.
    expect(hint.closest('label')).toBeNull()
    expect(hint.closest('.w-20')).toBeNull()
  })

  it('labels each field with its line name alone, and keeps the hint out of the name', () => {
    // The wrapping label used to pull in the unit suffix and the hint too. The name half is a
    // guard (aria-label already won it); the labels half fails if the label wraps again or loses htmlFor.
    renderAlerts()
    type('Level: Low', '1,234')

    const input = field('Level: Low')
    expect(Array.from(input.labels ?? []).map((l) => l.textContent)).toEqual(['Low'])
    expect(screen.queryByRole('textbox', { name: /numberInput\.readAs/ })).toBeNull()
  })
})
