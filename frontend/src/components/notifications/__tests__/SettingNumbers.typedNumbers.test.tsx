/**
 * Number settings are typed text read in the user's language (G1b-21). They
 * were native number boxes whose min/max did nothing, so 15 retry attempts
 * saved, and a German "2,5" second delay read as blank.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setActiveLocale } from '@/constants/i18n'
import { EventNotificationsCard } from '../EventNotificationsCard'
import { EmailConfig } from '../EmailConfig'

afterEach(() => setActiveLocale('en'))

const card = (onTextChange: (key: string, value: string) => void, settings: Record<string, unknown>) => (
  <EventNotificationsCard
    settings={settings}
    onSettingChange={vi.fn()}
    onTextChange={onTextChange}
    onNumberValidity={vi.fn()}
    saving={false}
    hasEnabledService
  />
)

const renderCard = (onTextChange = vi.fn(), settings: Record<string, unknown> = {}) => {
  const view = render(card(onTextChange, settings))
  fireEvent.click(screen.getByText('events.card.advanced'))
  return Object.assign(onTextChange, { rerender: view.rerender })
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
    fireEvent.blur(boxBeside('events.card.retryDelay'))
    expect(onTextChange).toHaveBeenLastCalledWith('notification_retry_delay', '2.5')
  })

  it('typing 15 retry attempts never saves the 1 on the way', async () => {
    // Every valid prefix used to go up as it was typed, so 15 saved 1.
    const user = userEvent.setup()
    const onTextChange = renderCard()
    const box = boxBeside('events.card.retryAttempts')
    await user.clear(box)
    await user.type(box, '15')
    await user.tab()
    expect(onTextChange).not.toHaveBeenCalled()
    expect(box).toHaveValue('15')
    expect(box).toHaveAttribute('aria-invalid', 'true')
  })

  it('de: a stored 1.234 second delay shows as 1,234 with no error, and a blur leaves it alone', () => {
    // The API's "1.234" was read as German text, so it came out 1234 and out of range.
    setActiveLocale('de')
    const onTextChange = renderCard(vi.fn(), { notification_retry_delay: '1.234' })
    const box = boxBeside('events.card.retryDelay')
    expect(box).toHaveValue('1,234')
    expect(box).not.toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByRole('alert')).toBeNull()
    fireEvent.focus(box)
    fireEvent.blur(box)
    expect(onTextChange).not.toHaveBeenCalled()
  })

  it('a delay typed in en still reads right after switching to de', () => {
    const onTextChange = renderCard()
    const box = boxBeside('events.card.retryDelay')
    fireEvent.change(box, { target: { value: '1.234' } })
    fireEvent.blur(box)
    expect(onTextChange).toHaveBeenLastCalledWith('notification_retry_delay', '1.234')

    setActiveLocale('de')
    onTextChange.rerender(card(onTextChange, { notification_retry_delay: '1.234' }))
    expect(box).toHaveValue('1,234')
    expect(screen.queryByRole('alert')).toBeNull()
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
        onNumberValidity={vi.fn()}
        onTest={vi.fn()}
        testing={false}
        saving={false}
      />,
    )
    const port = document.getElementById('email_smtp_port') as HTMLInputElement
    fireEvent.change(port, { target: { value: '7000' } })
    fireEvent.change(port, { target: { value: '70000' } })
    fireEvent.blur(port)
    // 7000 was a valid stop on the way to 70000 and used to save.
    expect(onTextChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('numberField.wholeBetween')
  })
})
