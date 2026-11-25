import { describe, it, expect, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'

// The vehicle never loads, so the visit form waits behind the loading overlay.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(() => new Promise(() => {})) },
}))
vi.mock('../../ServiceVisitList', () => ({
  default: ({ onAddClick }: { onAddClick: () => void }) => (
    <button type="button" onClick={onAddClick}>
      add visit
    </button>
  ),
}))
vi.mock('../../ServiceVisitForm', () => ({ default: () => null }))

import ServiceTab from '../ServiceTab'

describe('ServiceTab loading overlay', () => {
  it('keeps its box inside the safe area (#305)', () => {
    render(<ServiceTab vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'add visit' }))

    const overlay = screen.getByText('common:loading').closest('.fixed.inset-0')
    // No padding of its own before, so the insets alone.
    expect(overlay).toHaveClass('modal-safe-inset')
  })

  it('reads its box out as a polite status, not the whole scrim', () => {
    render(<ServiceTab vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'add visit' }))

    const status = screen.getByRole('status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveTextContent('common:loading')
    expect(status).not.toHaveClass('fixed')
  })
})
