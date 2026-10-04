/**
 * Money fields pad past the currency symbol at the width it is drawn.
 *
 * Every form used to put an absolute symbol beside a fixed `pl-7`, which fits
 * "$" and hid the digits behind "PLN", "CHF" or "R$". jsdom lays nothing out,
 * so the symbol's drawn width is stubbed by its text.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import type { ServiceVisitFormLineItem } from '../../../types/serviceVisit'

vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'PLN',
    locale: 'en-US',
    formatCurrency: (n: number) => `${n}`,
  }),
}))
vi.mock('../../../hooks/useReminders', () => ({ useMaintenanceTypes: () => ({ data: [] }) }))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({ system: 'imperial', showBoth: false, units: IMPERIAL_UNITS, gallonStandard: 'us' }),
  }
})

import CurrencyInput from '../CurrencyInput'
import LineItemEditor from '../../LineItemEditor'

const drawn = (widths: Record<string, number>): void => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return { width: widths[this.textContent ?? ''] ?? 0 } as DOMRect
  })
}

afterEach(() => vi.restoreAllMocks())

describe('CurrencyInput', () => {
  it('pads past a three-letter symbol', () => {
    drawn({ PLN: 31 })
    render(<CurrencyInput aria-label="Cost" />)

    const input = screen.getByRole('textbox', { name: 'Cost' })
    expect(screen.getByText('PLN')).toHaveAttribute('aria-hidden', 'true')
    expect(input).toHaveClass('pl-affix')
    expect(input).not.toHaveClass('pl-7')
    expect(input.style.getPropertyValue('--affix-start')).toBe('31px')
  })

  it('keeps the NumberInput behaviour: text with the decimal keypad', () => {
    render(<CurrencyInput aria-label="Cost" />)

    const input = screen.getByRole('textbox', { name: 'Cost' })
    expect([input.getAttribute('type'), input.getAttribute('inputmode')]).toEqual(['text', 'decimal'])
  })
})

describe("the line item's cost field", () => {
  const item: ServiceVisitFormLineItem = {
    tempId: -1,
    description: 'Oil change',
    category: 'Maintenance',
    cost: undefined,
    notes: '',
    is_inspection: false,
    inspection_result: '',
    inspection_severity: '',
    triggered_by_inspection_id: undefined,
    supplies_used: [],
  }

  it('pads past the symbol too, though it is not the Input primitive', () => {
    drawn({ PLN: 31 })
    render(
      <LineItemEditor
        item={item}
        index={0}
        vin="V1"
        supplies={[]}
        unitsBySupplyId={new Map()}
        failedInspections={[]}
        onChange={vi.fn()}
        onRemove={vi.fn()}
        categories={['Maintenance']}
      />,
    )

    const cost = screen.getByPlaceholderText('0.00')
    expect(cost).toHaveClass('pl-affix')
    expect(cost.style.getPropertyValue('--affix-start')).toBe('31px')
  })
})
