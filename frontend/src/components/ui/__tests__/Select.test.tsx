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

  it('is not hidden via a known class-name convention or the native hidden/display mechanisms', () => {
    // This only proves the absence of a few specific hiding mechanisms
    // jsdom can see (literal sr-only/hidden/invisible class substrings, the
    // native `hidden` attribute, inline display:none). jsdom applies no
    // Tailwind CSS, so it cannot prove the element is actually visible on
    // screen (e.g. opacity-0, w-0 overflow-hidden, off-screen positioning
    // would all pass here). Full on-screen visibility is enforced by
    // Playwright's real toBeVisible() in e2e/i18n.spec.ts:32,62.
    const { container } = render(<Select options={OPTIONS} aria-label="Fuel" />)
    const select = container.querySelector('select') as HTMLSelectElement
    expect(select.className).not.toMatch(/\b(sr-only|hidden|invisible)\b/)
    expect(select).toBeVisible()
  })

  it('renders the placeholder option as selectable (not disabled) by default', () => {
    // A disabled option cannot be selected by mouse or keyboard in any
    // browser. VehicleEdit.tsx/VehicleWizard.tsx rely on a selectable empty
    // option to let a user clear fuel_type back to null; see
    // VehicleEdit.test.tsx's "submits fuel_type as null" test.
    const { container } = render(
      <Select options={OPTIONS} placeholder="Select fuel" aria-label="Fuel" />,
    )
    const placeholderOption = container.querySelector('option[value=""]')
    expect(placeholderOption).not.toBeDisabled()
  })

  it('disables the placeholder option when placeholderDisabled is passed', () => {
    const { container } = render(
      <Select
        options={OPTIONS}
        placeholder="Select fuel"
        placeholderDisabled
        aria-label="Fuel"
      />,
    )
    const placeholderOption = container.querySelector('option[value=""]')
    expect(placeholderOption).toBeDisabled()
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
