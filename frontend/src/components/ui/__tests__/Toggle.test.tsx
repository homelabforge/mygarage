import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Toggle from '../Toggle'
import Checkbox from '../Checkbox'

describe('Toggle', () => {
  it('exposes the checkbox role, NOT switch', () => {
    // Five tests use getByRole('checkbox') on controls the design calls
    // toggles (EventNotificationsCard.test.tsx:44,68,88;
    // SettingsNotificationsTab.test.tsx:70,84). role="switch" breaks them.
    render(<Toggle label="DEF Low" checked={false} onChange={() => {}} />)
    expect(screen.getByRole('checkbox', { name: 'DEF Low' })).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })

  it('reflects checked state', () => {
    render(<Toggle label="DEF Low" checked onChange={() => {}} />)
    expect(screen.getByRole('checkbox', { name: 'DEF Low' })).toBeChecked()
  })

  it('fires onChange when clicked', () => {
    const onChange = vi.fn()
    render(<Toggle label="DEF Low" checked={false} onChange={onChange} />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'DEF Low' }))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('is genuinely disabled, not just faded', () => {
    render(<Toggle label="DEF Low" checked={false} onChange={() => {}} disabled />)
    expect(screen.getByRole('checkbox', { name: 'DEF Low' })).toBeDisabled()
  })

  it('forwards id', () => {
    render(<Toggle id="notify_def_low" label="DEF Low" checked={false} onChange={() => {}} />)
    expect(screen.getByRole('checkbox', { name: 'DEF Low' })).toHaveAttribute('id', 'notify_def_low')
  })

  it('carries a stable test id', () => {
    render(<Toggle label="DEF Low" checked={false} onChange={() => {}} />)
    expect(screen.getByTestId('toggle')).toBeInTheDocument()
  })
})

describe('Checkbox', () => {
  it('forwards id verbatim', () => {
    // one_time_visit, poi_gas_station and is_active are pinned by
    // document.getElementById in three unit-test files (G6).
    render(<Checkbox id="one_time_visit" label="One-time visit" />)
    expect(document.getElementById('one_time_visit')).toBeInTheDocument()
  })

  it('associates its label', () => {
    render(<Checkbox id="is_active" label="Active" />)
    expect(screen.getByRole('checkbox', { name: 'Active' })).toHaveAttribute('id', 'is_active')
  })
})
