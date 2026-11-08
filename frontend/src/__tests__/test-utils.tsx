import { ReactElement, useState } from 'react'
import { render, RenderOptions } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { basePath } from '../utils/basePath'
import { createTestQueryClient } from './queryClient'

// Custom render with common providers
const AllTheProviders = ({ children }: { children: React.ReactNode }) => {
  // One client per mount, so a rerender keeps the cache.
  const [queryClient] = useState(createTestQueryClient)
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basePath() || undefined}>
        {children}
      </BrowserRouter>
    </QueryClientProvider>
  )
}

const customRender = (
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>,
) => render(ui, { wrapper: AllTheProviders, ...options })

// Re-export everything from testing library
export * from '@testing-library/react'
export { customRender as render }
