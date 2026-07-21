import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Select from '../Select'

const OPTIONS = [
  { value: 'gasoline', label: 'Gasoline' },
  { value: 'diesel', label: 'Diesel' },
]

describe('Select', () => {
  it('renders a native select element', () => {
    const { container } = render(<Select options={OPTIONS} aria-label="Fuel" />)
    expect(container.querySelector('select')).toBeInTheDocument()
  })

  it('renders exactly one placeholder option plus the real ones', () => {
    // VehicleEdit.test.tsx:72,96 and VehicleWizard.test.tsx:92 assert
    // toHaveLength(FUEL_TYPE_VALUES.length + 1). No optgroup, no extras.
    const { container } = render(
      <Select options={OPTIONS} placeholder="Select fuel" aria-label="Fuel" />,
    )
    expect(container.querySelectorAll('option')).toHaveLength(OPTIONS.length + 1)
    expect(container.querySelectorAll('optgroup')).toHaveLength(0)
  })

  it('is visible, not a hidden control behind a custom combobox', () => {
    // i18n.spec.ts:32,62 assert toBeVisible() on the select itself.
    const { container } = render(<Select options={OPTIONS} aria-label="Fuel" />)
    const select = container.querySelector('select') as HTMLSelectElement
    expect(select.className).not.toMatch(/\b(sr-only|hidden|invisible)\b/)
  })

  it('forwards id verbatim', () => {
    const { container } = render(<Select id="unit_type" options={OPTIONS} aria-label="Fuel" />)
    expect(container.querySelector('select')).toHaveAttribute('id', 'unit_type')
  })

  it('reports the selected value', () => {
    const { container } = render(
      <Select options={OPTIONS} defaultValue="diesel" aria-label="Fuel" />,
    )
    expect(container.querySelector('select')).toHaveValue('diesel')
  })

  it('responds to a change event', () => {
    const { container } = render(<Select options={OPTIONS} aria-label="Fuel" />)
    const select = container.querySelector('select') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'diesel' } })
    expect(select.value).toBe('diesel')
  })

  it('finds options by value, as e2e does', () => {
    render(<Select options={OPTIONS} aria-label="Fuel" />)
    expect(screen.getByRole('option', { name: 'Diesel' })).toHaveValue('diesel')
  })
})
