import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NotificationBell from '../NotificationBell'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: { items: [] } })),
  },
}))

describe('NotificationBell', () => {
  it('opens a drawer with an empty-inbox state', async () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    expect(await screen.findByRole('dialog', { name: 'notifications' })).toBeInTheDocument()
    expect(await screen.findByText('notificationsEmptyTitle')).toBeInTheDocument()
  })

  it('shows no unread badge while the inbox is empty', () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    )
    expect(screen.queryByText('0')).toBeNull()
  })

  it('keeps the accessible name the label alone (no count in it)', () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: 'notifications' })).toBeInTheDocument()
  })
})
