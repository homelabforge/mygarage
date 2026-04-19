import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import type { WidgetKeySummary } from '@/types/widgetKey'

// Mock the widget-keys query hook + the revoke mutation. Avoids wiring a full
// QueryClient for this unit test.
const useWidgetKeysMock = vi.fn()
const useRevokeWidgetKeyMock = vi.fn()

vi.mock('@/hooks/queries/useWidgetKeys', () => ({
  isAuthDisabledError: (error: unknown) => {
    const e = error as { __authDisabled?: boolean } | null | undefined
    return Boolean(e?.__authDisabled)
  },
  useWidgetKeys: () => useWidgetKeysMock(),
  useRevokeWidgetKey: () => useRevokeWidgetKeyMock(),
}))

// Don't render the full modal during panel tests.
vi.mock('../../modals/CreateWidgetKeyModal', () => ({
  default: () => null,
}))

import WidgetKeysPanel from '../WidgetKeysPanel'

function makeKey(overrides: Partial<WidgetKeySummary> = {}): WidgetKeySummary {
  return {
    id: 1,
    name: 'Test Key',
    key_prefix: 'mg_abcd',
    scope: 'all_vehicles',
    allowed_vins: null,
    created_at: '2026-04-19T14:30:00',
    last_used_at: null,
    revoked_at: null,
    ...overrides,
  } as WidgetKeySummary
}

beforeEach(() => {
  useWidgetKeysMock.mockReset()
  useRevokeWidgetKeyMock.mockReset()
  useRevokeWidgetKeyMock.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('WidgetKeysPanel', () => {
  it('renders the API Keys header (not the old "Homepage / Widget" title)', () => {
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { keys: [] },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByRole('heading', { name: 'API Keys' })).toBeInTheDocument()
    expect(screen.queryByText(/Homepage \/ Widget/i)).not.toBeInTheDocument()
  })

  it('does not render a gethomepage example block (covered in wiki)', () => {
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { keys: [] },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.queryByText(/gethomepage/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/How do I use this with gethomepage\?/i)).not.toBeInTheDocument()
  })

  it('renders "never used" when last_used_at is null', () => {
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: { keys: [makeKey({ last_used_at: null })] },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByText('never used')).toBeInTheDocument()
  })

  it('renders a relative timestamp for last_used_at when set', () => {
    // Fix "now" so formatDistanceToNow output is deterministic.
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-19T15:00:00Z'))
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        keys: [
          // 30 min earlier, naive UTC wire format (current backend)
          makeKey({ last_used_at: '2026-04-19T14:30:00' }),
        ],
      },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByText(/last used .*30 minutes ago/i)).toBeInTheDocument()
  })

  it('shows the stale badge for keys last used >90 days ago', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-19T15:00:00Z'))
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        keys: [makeKey({ last_used_at: '2025-01-01T00:00:00' })],
      },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByText('stale')).toBeInTheDocument()
  })

  it('does not show the stale badge for revoked keys', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-19T15:00:00Z'))
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        keys: [
          makeKey({
            last_used_at: '2025-01-01T00:00:00',
            revoked_at: '2025-02-01T00:00:00',
          }),
        ],
      },
      error: null,
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByText('revoked')).toBeInTheDocument()
    expect(screen.queryByText('stale')).not.toBeInTheDocument()
  })

  it('renders the auth-disabled banner when the hook signals that', () => {
    useWidgetKeysMock.mockReturnValue({
      isLoading: false,
      isError: true,
      data: undefined,
      error: { __authDisabled: true },
    })
    render(<WidgetKeysPanel />)
    expect(screen.getByText(/API keys require authenticated users/i)).toBeInTheDocument()
  })
})
