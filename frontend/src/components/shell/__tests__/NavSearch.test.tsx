import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NavSearch from '../NavSearch'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: { results: [] } })),
  },
}))

describe('NavSearch', () => {
  it('is a button that opens a search drawer', () => {
    const { container } = render(
      <MemoryRouter>
        <NavSearch placeholder="search" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: 'search' })).toBeInTheDocument()
    expect(container.querySelector('input')).toBeNull()
  })

  it('opens a drawer with a search field and hint', async () => {
    render(
      <MemoryRouter>
        <NavSearch placeholder="search" />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'search' }))
    expect(await screen.findByRole('dialog', { name: 'search' })).toBeInTheDocument()
    expect(screen.getByLabelText('searchPlaceholder')).toBeInTheDocument()
    expect(screen.getByText('searchHint')).toBeInTheDocument()
  })

  it('forwards a band className onto the trigger', () => {
    render(
      <MemoryRouter>
        <NavSearch placeholder="search" className="hidden nav:flex" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: 'search' })).toHaveClass('hidden', 'nav:flex')
  })
})
