import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import QuickSettingsDrawer from '../QuickSettingsDrawer'

function setup() {
  return render(
    <MemoryRouter>
      <QuickSettingsDrawer />
    </MemoryRouter>
  )
}

describe('QuickSettingsDrawer (shelled)', () => {
  it('opens from the settings gear into a minimal drawer', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'quickSettings' }))
    expect(await screen.findByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
  })

  it('links to About and to full Settings', async () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'quickSettings' }))
    expect(await screen.findByRole('link', { name: /allSettings/ })).toHaveAttribute('href', '/settings')
    expect(screen.getByRole('link', { name: /about/ })).toHaveAttribute('href', '/about')
  })
})
