/**
 * `/settings/public` is one cached query that every reader selects from, so a
 * page that mounts several readers asks the server once.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactElement } from 'react'
import { screen, waitFor, act } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { usePublicSettings, publicSettingsQuery } from '../usePublicSettings'
import { useAiDocumentReading } from '../useAiDocumentReading'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

const mockedGet = vi.mocked(api.get)

const publicCalls = (): number =>
  mockedGet.mock.calls.filter(([url]) => url === '/settings/public').length

function payload(rows: { key: string; value: string | null }[]): { data: { settings: typeof rows } } {
  return { data: { settings: rows } }
}

function Reader({ name, setting }: { name: string; setting: string }): ReactElement {
  const values = usePublicSettings()
  return <span data-testid={name}>{String(values[setting] ?? 'unset')}</span>
}

function DocumentReadingReader(): ReactElement {
  const { enabled, isLoading } = useAiDocumentReading()
  return <span data-testid="doc-reading">{isLoading ? 'loading' : String(enabled)}</span>
}

function ClosedReader(): ReactElement {
  const values = usePublicSettings({ enabled: false })
  return <span data-testid="closed">{String(values.nhtsa_enabled ?? 'unset')}</span>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('usePublicSettings', () => {
  it('two readers mounted together make one request and both get the value', async () => {
    mockedGet.mockResolvedValue(
      payload([
        { key: 'nhtsa_enabled', value: 'true' },
        { key: 'window_sticker_enabled', value: 'false' },
      ]),
    )

    renderWithQueryClient(
      <>
        <Reader name="a" setting="nhtsa_enabled" />
        <Reader name="b" setting="window_sticker_enabled" />
      </>,
    )

    await waitFor(() => expect(screen.getByTestId('a')).toHaveTextContent('true'))
    expect(screen.getByTestId('b')).toHaveTextContent('false')
    expect(publicCalls()).toBe(1)
  })

  it('shares the request with the flag hooks that select from it', async () => {
    mockedGet.mockResolvedValue(payload([{ key: 'llm_document_reading_enabled', value: 'true' }]))

    renderWithQueryClient(
      <>
        <Reader name="a" setting="llm_document_reading_enabled" />
        <DocumentReadingReader />
      </>,
    )

    await waitFor(() => expect(screen.getByTestId('doc-reading')).toHaveTextContent('true'))
    expect(screen.getByTestId('a')).toHaveTextContent('true')
    expect(publicCalls()).toBe(1)
  })

  it('is an empty map after a failed fetch, so each caller falls back', async () => {
    mockedGet.mockRejectedValue(new Error('offline'))

    renderWithQueryClient(<Reader name="a" setting="nhtsa_enabled" />)

    await waitFor(() => expect(publicCalls()).toBe(1))
    expect(screen.getByTestId('a')).toHaveTextContent('unset')
  })

  it('keeps the last good map when a refetch fails', async () => {
    mockedGet.mockResolvedValueOnce(payload([{ key: 'nhtsa_enabled', value: 'true' }]))
    const { client } = renderWithQueryClient(<Reader name="a" setting="nhtsa_enabled" />)
    await waitFor(() => expect(screen.getByTestId('a')).toHaveTextContent('true'))

    mockedGet.mockRejectedValueOnce(new Error('offline'))
    await act(async () => {
      await client.refetchQueries({ queryKey: publicSettingsQuery.queryKey })
    })
    expect(publicCalls()).toBe(2)
    expect(client.getQueryState(publicSettingsQuery.queryKey)?.status).toBe('error')
    expect(screen.getByTestId('a')).toHaveTextContent('true')
  })

  it('makes no request while disabled', async () => {
    mockedGet.mockResolvedValue(payload([{ key: 'nhtsa_enabled', value: 'true' }]))

    renderWithQueryClient(<ClosedReader />)

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(publicCalls()).toBe(0)
    expect(screen.getByTestId('closed')).toHaveTextContent('unset')
  })
})
