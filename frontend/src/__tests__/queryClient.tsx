import type { ReactElement, ReactNode } from 'react'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfirmProvider } from '../components/ui/ConfirmDialog'

/**
 * A fresh query client for one test. No retries: plenty of tests queue their
 * api mocks by call order (`mockResolvedValueOnce` and friends), and a retry
 * would quietly eat the next queued answer.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

/** A `wrapper` for render/renderHook that keeps one client across rerenders. */
export function queryWrapper(
  client: QueryClient = createTestQueryClient(),
): (props: { children: ReactNode }) => ReactElement {
  return function QueryWrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

/**
 * `render` inside a fresh retry-free QueryClientProvider. Hands the client back
 * too. Carries a ConfirmProvider like test-utils' render, since any delete
 * button now asks through useConfirm.
 */
export function renderWithQueryClient(
  ui: ReactElement,
  options: Omit<RenderOptions, 'wrapper'> & { client?: QueryClient } = {},
): RenderResult & { client: QueryClient } {
  const { client = createTestQueryClient(), ...rest } = options
  const Queries = queryWrapper(client)
  const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
    <Queries>
      <ConfirmProvider>{children}</ConfirmProvider>
    </Queries>
  )
  return { ...render(ui, { wrapper, ...rest }), client }
}
