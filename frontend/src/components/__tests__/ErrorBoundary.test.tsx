import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorBoundary } from '../ErrorBoundary'

// Component that throws on render
function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test error from component')
  }
  return <div>Working component</div>
}

describe('ErrorBoundary', () => {
  // Suppress console.error for expected errors during testing
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={false} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Working component')).toBeInTheDocument()
  })

  it('renders default error UI when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText(/unexpected error occurred/)).toBeInTheDocument()
  })

  it('renders custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<div>Custom error fallback</div>}>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Custom error fallback')).toBeInTheDocument()
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  it('shows Try Again and Go to Dashboard buttons', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Try Again')).toBeInTheDocument()
    expect(screen.getByText('Go to Dashboard')).toBeInTheDocument()
  })

  it('resets error state on Try Again click', () => {
    // Use a mutable ref so the value is read at render time, not baked into JSX props
    const throwRef = { current: true }

    function ConditionalThrower() {
      if (throwRef.current) {
        throw new Error('Test error from component')
      }
      return <div>Working component</div>
    }

    render(
      <ErrorBoundary>
        <ConditionalThrower />
      </ErrorBoundary>
    )

    // Should show error UI
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()

    // Stop throwing before clicking reset
    throwRef.current = false

    // Click Try Again — ErrorBoundary resets state and re-renders children
    fireEvent.click(screen.getByText('Try Again'))

    // ConditionalThrower reads throwRef.current at render time, now false
    expect(screen.getByText('Working component')).toBeInTheDocument()
  })

  it('navigates to dashboard on Go to Dashboard click', () => {
    // Mock window.location.href assignment
    const originalHref = window.location.href
    Object.defineProperty(window, 'location', {
      value: { href: originalHref },
      writable: true,
    })

    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>
    )

    fireEvent.click(screen.getByText('Go to Dashboard'))

    expect(window.location.href).toBe('/')
  })
})
