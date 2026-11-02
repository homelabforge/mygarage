/**
 * #211 — the tax type select follows the vehicle's country profile: the
 * country's types first, in its order and with its national names, then every
 * other code; without a profile, the plain list in the contract's order.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { TAX_TYPE_VALUES } from '../../schemas/tax'

vi.mock('../../hooks/queries/useTaxRecords', () => ({
  useCreateTaxRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdateTaxRecord: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'EUR', locale: 'fr-FR', formatCurrency: vi.fn() }),
}))
vi.mock('../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { registration_country: 'FR' } }) },
}))

const state = vi.hoisted(() => ({ country: null as string | null, profile: undefined as unknown }))
vi.mock('../../hooks/useResolvedCountry', () => ({ useResolvedCountry: () => state.country }))
vi.mock('../../hooks/queries/useCountryProfile', () => ({
  useCountryProfile: () => ({ data: state.profile }),
}))

import TaxRecordForm from '../TaxRecordForm'

const FR_PROFILE = {
  country: 'FR',
  taxes: {
    types: ['registration_tax', 'co2_malus', 'inspection', 'registration', 'other'],
    names: {
      registration_tax: 'Carte grise – taxe régionale (Y.1)',
      co2_malus: 'Malus écologique (Y.3)',
      inspection: 'Contrôle technique',
    },
  },
}

const optionLabels = (): string[] =>
  Array.from((screen.getByLabelText('taxRecordForm.type') as HTMLSelectElement).options)
    .filter((o) => o.value !== '')
    .map((o) => o.textContent ?? '')

beforeEach(() => {
  vi.clearAllMocks()
  state.country = null
  state.profile = undefined
})

describe('TaxRecordForm — tax types by country (#211)', () => {
  it('without a profile offers every code in the contract order', () => {
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    const select = screen.getByLabelText('taxRecordForm.type') as HTMLSelectElement
    const values = Array.from(select.options).filter((o) => o.value !== '').map((o) => o.value)
    expect(values).toEqual([...TAX_TYPE_VALUES])
    expect(optionLabels()[0]).toBe('forms:taxTypes.registration')
  })

  it("with the French profile puts the country's types first, with their national names", () => {
    state.country = 'FR'
    state.profile = FR_PROFILE
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    const labels = optionLabels()
    expect(labels.slice(0, 5)).toEqual([
      'forms:taxTypes.registrationTax (Carte grise – taxe régionale (Y.1))',
      'forms:taxTypes.co2Malus (Malus écologique (Y.3))',
      'forms:taxTypes.inspection (Contrôle technique)',
      'forms:taxTypes.registration',
      'forms:taxTypes.other',
    ])
    // The rest follow, once each: every code is offered.
    expect(labels).toHaveLength(TAX_TYPE_VALUES.length)
    expect(labels).toContain('forms:taxTypes.propertyTax')
  })
})
