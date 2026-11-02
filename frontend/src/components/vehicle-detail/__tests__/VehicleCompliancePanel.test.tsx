/**
 * The compliance card (#211): nothing without a country or a profile; the
 * Crit'Air chip with its basis, the other schemes' "set by hand" class, the
 * next inspection with its window, and the certificate figures.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Vehicle } from '../../../types/vehicle'
import type { VehicleCompliance } from '../../../types/compliance'

const state = vi.hoisted(() => ({ data: undefined as unknown }))
vi.mock('../../../hooks/queries/useVehicleCompliance', () => ({
  useVehicleCompliance: () => ({ data: state.data }),
}))
vi.mock('../../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options ? [key, ...Object.values(options).map(String)].join('|') : key,
  }),
}))

import VehicleCompliancePanel from '../VehicleCompliancePanel'

const vehicle = (overrides: Partial<Vehicle> = {}): Vehicle =>
  ({ vin: 'V1', nickname: 'Clio', vehicle_type: 'Car', ...overrides }) as Vehicle

const FR: VehicleCompliance = {
  vin: 'V1',
  country: 'FR',
  profile_country: 'FR',
  euro_class: 6,
  euro_class_estimated: true,
  lez: {
    scheme: 'critair',
    name: "Crit'Air",
    url: 'https://www.certificat-air.gouv.fr/',
    value: '1',
    basis: 'first_registration',
    overridden: false,
    computed: true,
  },
  inspection: {
    name: 'Contrôle technique',
    automatic: true,
    next_due_date: '2027-03-12',
    lead_days: 180,
    window_opens_on: '2026-09-13',
    reminder_id: 8,
    rule_id: 1,
    anchor_kind: 'baseline',
    from_registration: true,
  },
  sources: [],
  reason: null,
}

beforeEach(() => {
  state.data = undefined
})

describe('VehicleCompliancePanel', () => {
  it('renders nothing without data, without a country, or without a profile', () => {
    const { container, rerender } = render(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(container).toBeEmptyDOMElement()
    state.data = { ...FR, country: null, lez: null, inspection: null, reason: 'no_country' }
    rerender(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(container).toBeEmptyDOMElement()
    state.data = { ...FR, country: 'US', profile_country: null, lez: null, inspection: null, reason: 'no_profile' }
    rerender(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("shows the Crit'Air chip, its basis, the official link, the inspection and the figures", () => {
    state.data = FR
    render(
      <VehicleCompliancePanel
        vin="V1"
        vehicle={vehicle({ fiscal_power: 5, co2_g_km: 118, power_kw: 74 })}
      />
    )
    expect(screen.getByText('compliance.title')).toBeInTheDocument()
    expect(screen.getByText("compliance.lezBadge|Crit'Air|1")).toBeInTheDocument()
    expect(screen.getByText('compliance.lezEstimated')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /compliance.officialSite/ })).toHaveAttribute(
      'href',
      'https://www.certificat-air.gouv.fr/'
    )
    expect(screen.getByText('Contrôle technique')).toBeInTheDocument()
    expect(screen.getByText('Mar 12, 2027')).toBeInTheDocument()
    expect(screen.getByText('compliance.inspectionWindow|Sep 13, 2026')).toBeInTheDocument()
    expect(screen.getByText('compliance.inspectionFromRegistration')).toBeInTheDocument()
    expect(screen.getByText('compliance.euroValue|6 compliance.estimated')).toBeInTheDocument()
    expect(screen.getByText('compliance.fiscalPowerValue|5')).toBeInTheDocument()
    expect(screen.getByText('compliance.co2Value|118')).toBeInTheDocument()
    expect(screen.getByText('compliance.powerValue|74')).toBeInTheDocument()
    expect(screen.getByText('compliance.disclaimer')).toBeInTheDocument()
  })

  it('says unclassified for a computed scheme without a class, and "set by hand" for an override', () => {
    state.data = { ...FR, lez: { ...FR.lez!, value: null, basis: null } }
    const { rerender } = render(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(screen.getByText('compliance.lezUnclassified')).toBeInTheDocument()

    state.data = { ...FR, lez: { ...FR.lez!, value: '2', basis: 'override', overridden: true } }
    rerender(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(screen.getByText("compliance.lezBadge|Crit'Air|2")).toBeInTheDocument()
    expect(screen.getByText('compliance.lezOverridden')).toBeInTheDocument()
    expect(screen.queryByText('compliance.lezEstimated')).not.toBeInTheDocument()
  })

  it('points to the official site for a scheme it does not compute, and says when nothing is scheduled', () => {
    state.data = {
      ...FR,
      country: 'DE',
      profile_country: 'DE',
      euro_class: null,
      euro_class_estimated: false,
      lez: { scheme: 'umweltplakette', name: 'Umweltplakette', url: 'https://gis.uba.de/', value: null, basis: null, overridden: false, computed: false },
      inspection: { name: 'Hauptuntersuchung (HU)', automatic: false, next_due_date: null, lead_days: null, window_opens_on: null, reminder_id: null, rule_id: null, anchor_kind: null, from_registration: false },
    }
    render(<VehicleCompliancePanel vin="V1" vehicle={vehicle()} />)
    expect(screen.getByText('compliance.lezUnknown')).toBeInTheDocument()
    expect(screen.getByText('compliance.inspectionNone')).toBeInTheDocument()
    expect(screen.queryByTestId('compliance-figures')).not.toBeInTheDocument()
  })
})
