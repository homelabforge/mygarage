import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import type { ServiceVisitFormLineItem } from '../../types/serviceVisit'

vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ formatCurrency: (n: number) => `$${n}` }),
}))
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
}))

import LineItemEditor from '../LineItemEditor'

const onChange = vi.fn()

const item: ServiceVisitFormLineItem = {
  tempId: -1,
  description: '',
  category: 'Maintenance',
  cost: undefined,
  notes: '',
  is_inspection: false,
  inspection_result: '',
  inspection_severity: '',
  triggered_by_inspection_id: undefined,
  supplies_used: [],
}

function renderEditor(): void {
  render(
    <LineItemEditor
      item={item}
      index={0}
      vin="V1"
      supplies={[]}
      unitsBySupplyId={new Map()}
      failedInspections={[]}
      onChange={onChange}
      onRemove={vi.fn()}
      categories={['Maintenance']}
    />
  )
}

// By label, not role: the description box keeps its Task 3 label either way.
const description = (): HTMLInputElement =>
  screen.getByLabelText(/lineItemEditor\.misc\.descriptionLabel/) as HTMLInputElement
const OIL = 'lineItemEditor.misc.suggestions.oilChange'
const ROTATION = 'lineItemEditor.misc.suggestions.tireRotation'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LineItemEditor description suggestions (G-4)', () => {
  it('ArrowDown moves aria-activedescendant and Enter picks the suggestion', () => {
    // The suggestions were mouse-only buttons with no roles.
    renderEditor()
    description().focus()
    fireEvent.focus(description())
    const box = screen.getByRole('combobox', { name: /lineItemEditor\.misc\.descriptionLabel/ })
    expect(box).toBe(description())
    expect(box).toHaveAttribute('aria-expanded', 'true')
    const list = screen.getByRole('listbox')
    expect(box).toHaveAttribute('aria-controls', list.id)
    const [oil, rotation] = within(list).getAllByRole('option')
    expect(oil).toHaveTextContent(OIL)
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    expect(box).toHaveAttribute('aria-activedescendant', rotation.id)
    expect(box).toHaveFocus()
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(0, 'description', ROTATION)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('typing drops the highlight, so Enter never picks a row nobody heard', () => {
    // The list stays open while the filter still matches and option ids go by position, so
    // the old highlight sat on whatever row slid under it, unannounced.
    const { rerender } = render(
      <LineItemEditor
        item={item}
        index={0}
        vin="V1"
        supplies={[]}
        unitsBySupplyId={new Map()}
        failedInspections={[]}
        onChange={onChange}
        onRemove={vi.fn()}
        categories={['Maintenance']}
      />
    )
    fireEvent.focus(description())
    fireEvent.keyDown(description(), { key: 'ArrowDown' })
    fireEvent.keyDown(description(), { key: 'ArrowDown' })
    expect(description()).toHaveAttribute('aria-activedescendant')
    rerender(
      <LineItemEditor
        item={{ ...item, description: 'o' }}
        index={0}
        vin="V1"
        supplies={[]}
        unitsBySupplyId={new Map()}
        failedInspections={[]}
        onChange={onChange}
        onRemove={vi.fn()}
        categories={['Maintenance']}
      />
    )
    expect(description()).toHaveAttribute('aria-expanded', 'true')
    expect(description()).not.toHaveAttribute('aria-activedescendant')
    fireEvent.keyDown(description(), { key: 'Enter' })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('the suggestions are out of the Tab order and close as soon as focus leaves', () => {
    // Tab went to the suggestion buttons, the 200 ms blur close pulled the list out from
    // under them, and focus fell to <body>.
    renderEditor()
    fireEvent.focus(description())
    const first = screen.getByText(OIL)
    expect(first).toHaveAttribute('tabindex', '-1')
    // Tab hands focus to the next field.
    fireEvent.blur(description(), { relatedTarget: screen.getByLabelText('lineItemEditor.cost') })
    expect(screen.queryByText(OIL)).not.toBeInTheDocument()
  })

  it('a tap on a suggestion picks it, even when the box blurs before the click', () => {
    // On a touch browser the box can blur between the tap's pointerdown and its click.
    // The blur used to close the list, so the click landed on nothing.
    renderEditor()
    fireEvent.focus(description())
    const oil = screen.getByText(OIL)
    fireEvent.pointerDown(oil)
    fireEvent.blur(description())
    fireEvent.click(oil)
    expect(onChange).toHaveBeenCalledWith(0, 'description', OIL)
  })

  it('a pointerdown outside closes the suggestions', () => {
    renderEditor()
    fireEvent.focus(description())
    expect(screen.getByText(OIL)).toBeInTheDocument()
    fireEvent.pointerDown(screen.getByLabelText('lineItemEditor.cost'))
    expect(screen.queryByText(OIL)).not.toBeInTheDocument()
  })

  it('a click still picks a suggestion', () => {
    // Guard, passes before the fix: options pick on click now, with mousedown keeping focus in
    // the box. Killed by the mutant that drops the option onClick.
    renderEditor()
    fireEvent.focus(description())
    const oil = screen.getByText(OIL)
    const kept = fireEvent.mouseDown(oil)
    fireEvent.click(oil)
    expect(kept).toBe(false)
    expect(onChange).toHaveBeenCalledWith(0, 'description', OIL)
  })
})
