/**
 * SavePackDialog - the vehicle is the pack editor.
 *
 * The dialog turns a vehicle's maintenance RULES into a save request. Most of
 * what it has to get right is which rules may go in a pack at all: the backend
 * resolves a pack item to a rule by maintenance_type, so a typeless rule and the
 * second rule of a repeated type are refused, and this dialog must not open in a
 * state the API would reject.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { MaintenanceRuleResponse } from '../../types/reminder'

const rulesMock = vi.fn()
const saveMock = vi.fn()
const overwriteMock = vi.fn()
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceRules: (...args: unknown[]) => rulesMock(...args),
  useSavePack: () => ({ mutateAsync: saveMock, isPending: false }),
  useOverwritePack: () => ({ mutateAsync: overwriteMock, isPending: false }),
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'metric',
      showBoth: false,
      units: METRIC_UNITS,
      gallonStandard: 'us',
    }),
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import SavePackDialog from '../SavePackDialog'

const VIN = '1HGCM82633A123456'

const rule = (
  id: number,
  maintenance_type: string | null,
  title: string
): MaintenanceRuleResponse =>
  ({
    id,
    vin: VIN,
    maintenance_type,
    title,
    interval_km: '8000',
    interval_months: 6,
    interval_days: null,
    interval_hours: null,
    source: 'manual',
    is_active: true,
  }) as MaintenanceRuleResponse

function renderDialog(rules: MaintenanceRuleResponse[]) {
  rulesMock.mockReturnValue({ data: rules, isLoading: false })
  return render(
    <SavePackDialog
      vin={VIN}
      vehicleType="Truck"
      onClose={vi.fn()}
      onSaved={vi.fn()}
    />
  )
}

const saveButton = () => screen.getByRole('button', { name: 'savePack.action' })

beforeEach(() => {
  rulesMock.mockReset()
  saveMock.mockReset()
  overwriteMock.mockReset()
  saveMock.mockResolvedValue({})
})

describe('choosing what goes in', () => {
  it('sends the ticked rules with the typed name', async () => {
    renderDialog([rule(1, 'engine_oil_filter', 'Oil & Filter'), rule(2, 'tire_rotation', 'Tires')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    fireEvent.click(saveButton())

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    expect(saveMock.mock.calls[0][0]).toMatchObject({
      vin: VIN,
      name: 'Truck Standard',
      rule_ids: [1, 2],
    })
  })

  it('prefills the vehicle types from the source vehicle', async () => {
    renderDialog([rule(1, 'engine_oil_filter', 'Oil & Filter')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    fireEvent.click(saveButton())

    await waitFor(() => expect(saveMock).toHaveBeenCalled())
    expect(saveMock.mock.calls[0][0].vehicle_types).toEqual(['Truck'])
  })

  it('ticks no type for a vehicle that has none, so the pack is for all types', async () => {
    rulesMock.mockReturnValue({ data: [rule(1, 'engine_oil_filter', 'Oil & Filter')], isLoading: false })
    render(<SavePackDialog vin={VIN} vehicleType={null} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Mine' } })

    fireEvent.click(saveButton())

    // Pins out a dialog that guesses a type for a null one.
    await waitFor(() => expect(saveMock).toHaveBeenCalled())
    expect(saveMock.mock.calls[0][0].vehicle_types).toEqual([])
  })

  it('drops a rule the user unticks', async () => {
    renderDialog([rule(1, 'engine_oil_filter', 'Oil & Filter'), rule(2, 'tire_rotation', 'Tires')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })
    fireEvent.click(screen.getByLabelText('Tires'))

    fireEvent.click(saveButton())

    await waitFor(() => expect(saveMock).toHaveBeenCalled())
    expect(saveMock.mock.calls[0][0].rule_ids).toEqual([1])
  })

  it('cannot be saved with nothing ticked', () => {
    renderDialog([rule(1, 'engine_oil_filter', 'Oil & Filter')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })
    fireEvent.click(screen.getByLabelText('Oil & Filter'))

    expect(saveButton()).toBeDisabled()
  })

  it('cannot be saved without a name', () => {
    renderDialog([rule(1, 'engine_oil_filter', 'Oil & Filter')])
    expect(saveButton()).toBeDisabled()
  })
})

describe('what a pack cannot hold', () => {
  it('opens without the later duplicate of a type ticked', async () => {
    // Ticking both would open in a state the API refuses, leaving the user to
    // work out which two rows are fighting.
    renderDialog([
      rule(1, 'engine_oil_filter', 'Oil & Filter'),
      rule(2, 'engine_oil_filter', 'Oil & Filter (winter)'),
    ])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    fireEvent.click(saveButton())

    await waitFor(() => expect(saveMock).toHaveBeenCalled())
    expect(saveMock.mock.calls[0][0].rule_ids).toEqual([1])
  })

  it('opens without a typeless rule ticked', async () => {
    renderDialog([rule(1, null, 'Check the winch'), rule(2, 'tire_rotation', 'Tires')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    fireEvent.click(saveButton())

    await waitFor(() => expect(saveMock).toHaveBeenCalled())
    expect(saveMock.mock.calls[0][0].rule_ids).toEqual([2])
  })

  it('explains itself and blocks the save if a typeless rule is ticked anyway', () => {
    renderDialog([rule(1, null, 'Check the winch')])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    fireEvent.click(screen.getByLabelText('Check the winch'))

    // The reason is on screen, not just a disabled button with no explanation.
    expect(screen.getByText(/savePack\.cannotInclude/)).toBeInTheDocument()
    expect(saveButton()).toBeDisabled()
  })

  it('clears the conflict when the other duplicate is unticked', () => {
    renderDialog([
      rule(1, 'engine_oil_filter', 'Oil & Filter'),
      rule(2, 'engine_oil_filter', 'Oil & Filter (winter)'),
    ])
    fireEvent.change(screen.getByLabelText('savePack.name'), { target: { value: 'Truck Standard' } })

    // Tick the second: now two ticked rules share a type.
    fireEvent.click(screen.getByLabelText('Oil & Filter (winter)'))
    expect(saveButton()).toBeDisabled()

    // Untick the first: one of the pair is a perfectly good pack.
    fireEvent.click(screen.getByLabelText('Oil & Filter'))
    expect(saveButton()).toBeEnabled()
  })

  it('says so when the vehicle has no recurring reminders at all', () => {
    renderDialog([])
    expect(screen.getByText('savePack.noRules')).toBeInTheDocument()
  })
})

describe('overwriting an existing pack', () => {
  it('sends to the overwrite mutation, keeping the pack id', async () => {
    rulesMock.mockReturnValue({
      data: [rule(1, 'engine_oil_filter', 'Oil & Filter')],
      isLoading: false,
    })
    overwriteMock.mockResolvedValue({})
    render(
      <SavePackDialog
        vin={VIN}
        vehicleType="Truck"
        existingPack={{
          id: 'custom-truck-standard',
          name: 'Truck Standard',
          description: '',
          vehicle_types: ['Truck'],
        }}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    )

    fireEvent.click(saveButton())

    await waitFor(() => expect(overwriteMock).toHaveBeenCalledTimes(1))
    expect(overwriteMock.mock.calls[0][0].packId).toBe('custom-truck-standard')
    expect(saveMock).not.toHaveBeenCalled()
  })
})

describe('an untouched overwrite keeps what the pack already says', () => {
  const overwrite = async (stored: { description: string; vehicle_types: string[] }) => {
    rulesMock.mockReturnValue({ data: [rule(1, 'engine_oil_filter', 'Oil & Filter')], isLoading: false })
    overwriteMock.mockResolvedValue({})
    render(
      <SavePackDialog
        vin={VIN}
        vehicleType="Truck"
        existingPack={{ id: 'custom-standard', name: 'Standard', ...stored } as never}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    )
    fireEvent.click(saveButton())
    await waitFor(() => expect(overwriteMock).toHaveBeenCalledTimes(1))
    return overwriteMock.mock.calls[0][0].body
  }

  it('posts the stored description and vehicle types', async () => {
    const body = await overwrite({ description: 'Full service', vehicle_types: ['Car', 'Truck'] })
    expect(body.description).toBe('Full service')
    expect(body.vehicle_types).toEqual(['Car', 'Truck'])
  })

  it('keeps an all-types pack for all types', async () => {
    const body = await overwrite({ description: '', vehicle_types: [] })
    expect(body.vehicle_types).toEqual([])
  })

  it('drops a stored type the app does not know, so the edit saves instead of 422ing', async () => {
    // A restored backup can carry a type this version has never heard of. The
    // save input is strict, so sending it back would refuse the whole edit.
    const body = await overwrite({ description: '', vehicle_types: ['Car', 'Hovercraft'] })

    expect(screen.getByLabelText('vehicleTypeLabels.Car')).toBeChecked()
    expect(body.vehicle_types).toEqual(['Car'])
  })
})
