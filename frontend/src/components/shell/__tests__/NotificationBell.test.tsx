import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider, focusManager, onlineManager } from '@tanstack/react-query'
import NotificationBell from '../NotificationBell'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: { items: [] } })),
  },
}))

const DISMISSED_KEY = 'mygarage:notification-inbox-dismissed'
const INBOX_KEY = ['notifications', 'inbox']

function item(id: string, title = 'Brake inspection') {
  return {
    id,
    kind: 'reminder_overdue',
    title,
    body: 'Truck',
    vin: 'VIN00000000000001',
    href: '/vehicles/VIN00000000000001?tab=reminders',
    severity: 'critical',
  }
}

// Each test gets its own cache, so nothing one test fetched leaks into the next.
function renderBell(): { client: QueryClient; container: HTMLElement } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const { container } = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { client, container }
}

function badge(container: HTMLElement): Element | null {
  return container.querySelector('span[aria-hidden="true"].pointer-events-none')
}

function storedDismissals(): string[] {
  return JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? '[]') as string[]
}

beforeEach(() => {
  window.localStorage.clear()
  vi.mocked(api.get).mockReset()
  vi.mocked(api.get).mockResolvedValue({ data: { items: [] } })
})

afterEach(() => {
  // Unmount first, so the focus reset below can't wake a mounted bell's query.
  cleanup()
  vi.useRealTimers()
  // Back to "ask the document", so the focus state can't leak into other suites.
  focusManager.setFocused(undefined)
  onlineManager.setOnline(true)
  window.localStorage.clear()
})

describe('NotificationBell', () => {
  it('opens a drawer with an empty-inbox state', async () => {
    renderBell()
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    expect(await screen.findByRole('dialog', { name: 'notifications' })).toBeInTheDocument()
    expect(await screen.findByText('notificationsEmptyTitle')).toBeInTheDocument()
  })

  it('shows no unread badge while the inbox is empty', () => {
    renderBell()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('keeps the accessible name the label alone (no count in it)', () => {
    renderBell()
    expect(screen.getByRole('button', { name: 'notifications' })).toBeInTheDocument()
  })

  it('lets clicks pass through the unread badge to the bell (#195)', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: [item('reminder-reminder_overdue-1')] } })
    renderBell()
    const count = await screen.findByText('1')
    // The badge overlaps the bell button's corner; without pointer-events-none
    // it swallows the click and the user has to aim past the red box.
    const overlay = count.closest('span[aria-hidden="true"]')
    expect(overlay).not.toBeNull()
    expect(overlay!.className).toContain('pointer-events-none')
  })

  it('keeps the list on screen when a refetch fails', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { items: [item('a')] } })
      .mockRejectedValueOnce(new Error('offline'))
    const { client, container } = renderBell()
    expect(await screen.findByText('1')).toBeInTheDocument()

    // Opening the bell asks again, and this time the server is gone.
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(client.getQueryState(INBOX_KEY)?.status).toBe('error'))

    expect(screen.getByText('Brake inspection')).toBeInTheDocument()
    expect(badge(container)?.textContent).toBe('1')
    // We have a list, so a blip isn't worth an error line.
    expect(screen.queryByText('notificationsLoadError')).toBeNull()
  })

  it('says it could not load when the first fetch fails, not that the inbox is empty', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('offline'))
    const { client } = renderBell()
    await waitFor(() => expect(client.getQueryState(INBOX_KEY)?.status).toBe('error'))

    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    expect(await screen.findByText('notificationsLoadError')).toBeInTheDocument()
    expect(screen.queryByText('notificationsEmptyTitle')).toBeNull()
  })

  it('says loading, not all caught up, while the first fetch waits on the network', async () => {
    onlineManager.setOnline(false)
    const { client } = renderBell()
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    expect(await screen.findByRole('dialog', { name: 'notifications' })).toBeInTheDocument()

    // Offline, the query parks: still pending, but not fetching either.
    expect(client.getQueryState(INBOX_KEY)?.fetchStatus).toBe('paused')
    expect(api.get).not.toHaveBeenCalled()
    expect(screen.getByText('notificationsLoading')).toBeInTheDocument()
    expect(screen.queryByText('notificationsEmptyTitle')).toBeNull()
  })

  it('retries from the error line and shows the list once it loads', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('offline'))
    const { client } = renderBell()
    await waitFor(() => expect(client.getQueryState(INBOX_KEY)?.status).toBe('error'))
    fireEvent.click(screen.getByRole('button', { name: 'notifications' }))
    const retry = await screen.findByRole('button', { name: 'common:retry' })
    const callsBefore = vi.mocked(api.get).mock.calls.length

    let answer: (value: { data: { items: ReturnType<typeof item>[] } }) => void = () => {}
    vi.mocked(api.get).mockReturnValue(
      new Promise((resolve) => {
        answer = resolve
      }),
    )
    fireEvent.click(retry)
    // While it's asking again, it says loading rather than the old error.
    expect(await screen.findByText('notificationsLoading')).toBeInTheDocument()
    expect(screen.queryByText('notificationsLoadError')).toBeNull()

    await act(async () => {
      answer({ data: { items: [item('a')] } })
    })
    expect(await screen.findByText('Brake inspection')).toBeInTheDocument()
    expect(vi.mocked(api.get).mock.calls.length).toBe(callsBefore + 1)
    expect(screen.queryByText('notificationsLoadError')).toBeNull()
  })

  // Only intervals are faked, which also stalls RTL's waitFor polling, so these
  // wait on the badge (a DOM change) and count calls straight after the tick.
  it('does not poll while the tab is unfocused', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    focusManager.setFocused(false)
    vi.mocked(api.get).mockResolvedValue({ data: { items: [item('a')] } })
    renderBell()
    expect(await screen.findByText('1')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledTimes(1)

    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('polls once a minute while the tab is focused', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    focusManager.setFocused(true)
    vi.mocked(api.get).mockResolvedValue({ data: { items: [item('a')] } })
    renderBell()
    expect(await screen.findByText('1')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledTimes(1)

    await act(async () => {
      vi.advanceTimersByTime(59_000)
    })
    expect(api.get).toHaveBeenCalledTimes(1)
    await act(async () => {
      vi.advanceTimersByTime(1_000)
    })
    expect(api.get).toHaveBeenCalledTimes(2)
  })
})

describe('NotificationBell dismissals', () => {
  it('prunes a dismissed id the inbox no longer carries, after a good fetch', async () => {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(['gone', 'kept']))
    vi.mocked(api.get).mockResolvedValue({ data: { items: [item('kept')] } })
    renderBell()
    await waitFor(() => expect(storedDismissals()).toEqual(['kept']))
  })

  it('prunes nothing when the FIRST fetch fails', async () => {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(['a', 'b']))
    vi.mocked(api.get).mockRejectedValue(new Error('offline'))
    const { client } = renderBell()
    await waitFor(() => expect(client.getQueryState(INBOX_KEY)?.status).toBe('error'))
    expect(storedDismissals()).toEqual(['a', 'b'])
  })

  it('keeps a dismissal the inbox still carries through mount, pending and the first answer', async () => {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(['x']))
    let answer: (value: { data: { items: ReturnType<typeof item>[] } }) => void = () => {}
    vi.mocked(api.get).mockReturnValue(
      new Promise((resolve) => {
        answer = resolve
      }),
    )
    const { client, container } = renderBell()

    // Mounted, the fetch still out.
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
    expect(client.getQueryState(INBOX_KEY)?.status).toBe('pending')
    expect(badge(container)).toBeNull()
    expect(storedDismissals()).toEqual(['x'])

    await act(async () => {
      answer({ data: { items: [item('x')] } })
    })
    await waitFor(() => expect(client.getQueryState(INBOX_KEY)?.status).toBe('success'))
    expect(badge(container)).toBeNull()
    expect(storedDismissals()).toEqual(['x'])
  })
})
