import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// The card reads `useUnitFormat()` for the service-reminder lead-distance
// suffix, and that reaches `useAuth()`, which throws without a provider. An
// anonymous client is the shape these tests have always assumed.
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, defaultUnitPrefs: null }),
}))

import { EventNotificationsCard } from '../EventNotificationsCard'

describe('EventNotificationsCard — DEF-low event (Task 17)', () => {
  const noop = () => {}

  it('renders every group statically with its toggle visible (no accordion)', () => {
    render(
      <EventNotificationsCard
        settings={{ notify_def_low: 'true' }}
        onSettingChange={noop}
        onTextChange={noop}
        saving={false}
        hasEnabledService
      />,
    )

    // Static: no expand step. The group, its toggle label and the saved
    // checked state are all present on first render.
    expect(screen.getByText('events.defLow.group')).toBeInTheDocument()
    expect(screen.getByText('events.defLow.label')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'events.defLow.label' })).toBeChecked()
  })

  it('renders the DEF toggle and percent field (default 25)', () => {
    render(
      <EventNotificationsCard
        settings={{}}
        onSettingChange={noop}
        onTextChange={noop}
        saving={false}
        hasEnabledService
      />,
    )

    expect(screen.getByText('events.defLow.label')).toBeInTheDocument()
    expect(screen.getByText('events.defLow.description')).toBeInTheDocument()

    const checkbox = screen.getByRole('checkbox', { name: 'events.defLow.label' })
    expect(checkbox).not.toBeChecked()

    const percentInput = screen.getByDisplayValue('25')
    expect(percentInput).toHaveAttribute('type', 'number')
    expect(percentInput).toHaveAttribute('min', '1')
    expect(percentInput).toHaveAttribute('max', '99')
    // No setting yet -> toggle off -> percent field disabled.
    expect(percentInput).toBeDisabled()
  })

  it('reflects a saved percent value and enables the field once the toggle is on', () => {
    render(
      <EventNotificationsCard
        settings={{ notify_def_low: 'true', notify_def_low_threshold_percent: '10' }}
        onSettingChange={noop}
        onTextChange={noop}
        saving={false}
        hasEnabledService
      />,
    )

    const checkbox = screen.getByRole('checkbox', { name: 'events.defLow.label' })
    expect(checkbox).toBeChecked()

    const percentInput = screen.getByDisplayValue('10')
    expect(percentInput).toBeEnabled()
  })

  it('toggling the checkbox calls onSettingChange with the notify_def_low key', () => {
    const onSettingChange = vi.fn()
    render(
      <EventNotificationsCard
        settings={{ notify_def_low: 'false' }}
        onSettingChange={onSettingChange}
        onTextChange={noop}
        saving={false}
        hasEnabledService
      />,
    )

    fireEvent.click(screen.getByRole('checkbox', { name: 'events.defLow.label' }))

    expect(onSettingChange).toHaveBeenCalledWith('notify_def_low', true)
  })

  it('changing the percent field calls onTextChange with the threshold key', () => {
    const onTextChange = vi.fn()
    render(
      <EventNotificationsCard
        settings={{ notify_def_low: 'true', notify_def_low_threshold_percent: '25' }}
        onSettingChange={noop}
        onTextChange={onTextChange}
        saving={false}
        hasEnabledService
      />,
    )

    fireEvent.change(screen.getByDisplayValue('25'), { target: { value: '15' } })

    expect(onTextChange).toHaveBeenCalledWith('notify_def_low_threshold_percent', '15')
  })
})
