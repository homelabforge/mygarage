import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NotificationBell from '../NotificationBell'

describe('NotificationBell (shelled)', () => {
  it('opens a drawer with an empty-inbox state', async () => {
    render(<NotificationBell />)
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    expect(await screen.findByRole('dialog', { name: 'notifications' })).toBeInTheDocument()
    expect(screen.getByText('notificationsEmptyTitle')).toBeInTheDocument()
  })

  it('shows no unread badge while the inbox is empty', () => {
    render(<NotificationBell />)
    // shelled count is 0, so the badge is not rendered at all
    expect(screen.queryByText('0')).toBeNull()
  })

  it('keeps the accessible name the label alone (no count in it)', () => {
    render(<NotificationBell />)
    expect(screen.getByRole('button', { name: 'notifications' })).toBeInTheDocument()
  })
})
