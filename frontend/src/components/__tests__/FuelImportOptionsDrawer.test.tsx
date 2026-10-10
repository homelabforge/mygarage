import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'

import FuelImportOptionsDrawer from '../FuelImportOptionsDrawer'

// The global i18n mock renders keys, so labels below are the keys themselves.
const drawer = () => within(screen.getByRole('dialog', { name: 'fuelList.importOptions.title' }))
const odometerSelect = () =>
  drawer().getByLabelText('fuelList.importOptions.odometerLabel') as HTMLSelectElement
const decimalsSelect = () =>
  drawer().getByLabelText('fuelList.importOptions.decimalsLabel') as HTMLSelectElement
const optionsOf = (select: HTMLSelectElement) =>
  Array.from(select.options).map((o) => ({ value: o.value, label: o.textContent }))

describe('FuelImportOptionsDrawer (G5a-82)', () => {
  it('renders the odometer and decimal choices, with literal number samples for the decimals', () => {
    render(
      <FuelImportOptionsDrawer
        open
        formatLabel="Fuelio"
        defaultOdometerUnit="km"
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(optionsOf(odometerSelect())).toEqual([
      { value: 'km', label: 'edit.distanceUnitKm' },
      { value: 'mi', label: 'edit.distanceUnitMi' },
    ])
    // Samples, not words: the same two strings in every language.
    expect(optionsOf(decimalsSelect())).toEqual([
      { value: 'dot', label: '1,234.5' },
      { value: 'comma', label: '1.234,5' },
    ])
    expect(drawer().getByText('fuelList.importOptions.hint')).toBeInTheDocument()
    expect(drawer().getByRole('button', { name: 'fuelList.importOptions.confirm' })).toBeInTheDocument()
  })

  it('defaults the odometer to defaultOdometerUnit and the decimals to dot', () => {
    const mi = render(
      <FuelImportOptionsDrawer
        open
        formatLabel="Fuelio"
        defaultOdometerUnit="mi"
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(odometerSelect().value).toBe('mi')
    expect(decimalsSelect().value).toBe('dot')
    mi.unmount()

    // Both ways round, so a hardcoded default can't pass.
    render(
      <FuelImportOptionsDrawer
        open
        formatLabel="Fuelio"
        defaultOdometerUnit="km"
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(odometerSelect().value).toBe('km')
    expect(decimalsSelect().value).toBe('dot')
  })

  it('picking mi and comma then Import calls onConfirm with both', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(
      <FuelImportOptionsDrawer
        open
        formatLabel="Fuelio"
        defaultOdometerUnit="km"
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    )
    fireEvent.change(odometerSelect(), { target: { value: 'mi' } })
    fireEvent.change(decimalsSelect(), { target: { value: 'comma' } })
    fireEvent.click(drawer().getByRole('button', { name: 'fuelList.importOptions.confirm' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith({ odometerUnit: 'mi', decimalSeparator: 'comma' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('Cancel calls onClose with no arguments and confirms nothing', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(
      <FuelImportOptionsDrawer
        open
        formatLabel="Fuelio"
        defaultOdometerUnit="km"
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    )
    fireEvent.click(drawer().getByRole('button', { name: 'common:cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('starts from the defaults again on every opening', () => {
    const props = {
      formatLabel: 'Fuelio',
      defaultOdometerUnit: 'km' as const,
      onConfirm: vi.fn(),
      onClose: vi.fn(),
    }
    const { rerender } = render(<FuelImportOptionsDrawer open {...props} />)
    fireEvent.change(odometerSelect(), { target: { value: 'mi' } })
    fireEvent.change(decimalsSelect(), { target: { value: 'comma' } })
    expect(odometerSelect().value).toBe('mi')

    rerender(<FuelImportOptionsDrawer open={false} {...props} />)
    rerender(<FuelImportOptionsDrawer open {...props} />)
    expect(odometerSelect().value).toBe('km')
    expect(decimalsSelect().value).toBe('dot')
  })
})
