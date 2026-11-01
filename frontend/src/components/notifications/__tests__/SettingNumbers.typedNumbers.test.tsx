/**
 * Number settings are typed text read in the user's language (G1b-21). They
 * were native number boxes whose min/max did nothing, so 15 retry attempts
 * saved, and a German "2,5" second delay read as blank.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { setActiveLocale } from '@/constants/i18n'
import { EventNotificationsCard } from '../EventNotificationsCard'
import { EmailConfig } from '../EmailConfig'

afterEach(() => setActiveLocale('en'))

const renderCard = (onTextChange = vi.fn(), settings: Record<string, unknown> = {}) => {
  render(
    <EventNotificationsCard
      settings={settings}
      onSettingChange={vi.fn()}
      onTextChange={onTextChange}
      saving={false}
      hasEnabledService
    />,
  )
  fireEvent.click(screen.getByText('events.card.advanced'))
  return onTextChange
}

// By the label's text and the box beside it, so these go red on main for the
// parsing, not for the label wiring.
const boxBeside = (labelText: string): HTMLInputElement =>
  screen.getByText(labelText).closest('.flex.items-center')?.querySelector('input') as HTMLInputElement

describe('EventNotificationsCard: number settings', () => {
  it('de: a 2,5 second retry delay saves as 2.5', () => {
    setActiveLocale('de')
    const onTextChange = renderCard()
    fireEvent.change(boxBeside('events.card.retryDelay'), { target: { value: '2,5' } })
    expect(onTextChange).toHaveBeenLastCalledWith('notification_retry_delay', '2.5')
  })

  it('refuses 15 retry attempts and says the range', () => {
    const onTextChange = renderCard()
    fireEvent.change(boxBeside('events.card.retryAttempts'), { target: { value: '15' } })
    expect(onTextChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('numberField.wholeBetween')
  })

  it('refuses a fractional number of days', () => {
    const onTextChange = renderCard(vi.fn(), { notify_insurance_expiring: 'true' })
    // Insurance days come first of the two 30s.
    const days = screen.getAllByDisplayValue('30')[0]
    fireEvent.change(days, { target: { value: '7,5' } })
    expect(onTextChange).not.toHaveBeenCalled()
    expect(days).toHaveAttribute('aria-invalid', 'true')
    expect(days).toHaveAccessibleName('events.card.insuranceExpiringLabel: events.card.daysBefore')
  })
})

describe('EmailConfig: SMTP port', () => {
  it('refuses a port that is not a whole number in range', () => {
    const onTextChange = vi.fn()
    render(
      <EmailConfig
        settings={{ email_enabled: 'true', email_smtp_port: '587' }}
        onSettingChange={vi.fn()}
        onTextChange={onTextChange}
        onTest={vi.fn()}
        testing={false}
        saving={false}
      />,
    )
    fireEvent.change(document.getElementById('email_smtp_port') as HTMLInputElement, { target: { value: '70000' } })
    expect(onTextChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('numberField.wholeBetween')
  })
})
