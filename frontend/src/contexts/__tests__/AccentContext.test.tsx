import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AccentProvider, useAccent } from '../AccentContext'
import { ACCENTS } from '../../constants/accents'

const themeState = vi.hoisted(() => ({ theme: 'dark' as 'light' | 'dark' }))

vi.mock('../ThemeContext', () => ({
  useTheme: () => ({ theme: themeState.theme, toggleTheme: () => {}, setTheme: () => {} }),
}))

function Probe() {
  const { accent, setAccent } = useAccent()
  return (
    <>
      <span data-testid="accent">{accent}</span>
      <button onClick={() => setAccent('amber')}>go-amber</button>
    </>
  )
}

describe('AccentProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('style')
    themeState.theme = 'dark'
  })

  it('defaults to blue when localStorage is empty', () => {
    render(<AccentProvider><Probe /></AccentProvider>)
    expect(screen.getByTestId('accent')).toHaveTextContent('blue')
  })

  it('writes the accent custom properties to documentElement, not a child', () => {
    render(<AccentProvider><Probe /></AccentProvider>)
    const style = document.documentElement.style
    expect(style.getPropertyValue('--accent')).toBe(ACCENTS.blue.accent)
    expect(style.getPropertyValue('--accent-solid')).toBe(ACCENTS.blue.solid)
    expect(style.getPropertyValue('--accent-on-solid')).toBe(ACCENTS.blue.onSolid)
  })

  it('restores a persisted accent', () => {
    localStorage.setItem('accent', 'teal')
    render(<AccentProvider><Probe /></AccentProvider>)
    expect(screen.getByTestId('accent')).toHaveTextContent('teal')
    expect(document.documentElement.style.getPropertyValue('--accent')).toBe(ACCENTS.teal.accent)
  })

  it('falls back to the default for an unknown persisted value', () => {
    localStorage.setItem('accent', 'chartreuse')
    render(<AccentProvider><Probe /></AccentProvider>)
    expect(screen.getByTestId('accent')).toHaveTextContent('blue')
  })

  it('persists and repaints on change', async () => {
    const user = userEvent.setup()
    render(<AccentProvider><Probe /></AccentProvider>)
    await user.click(screen.getByText('go-amber'))
    expect(screen.getByTestId('accent')).toHaveTextContent('amber')
    expect(localStorage.getItem('accent')).toBe('amber')
    expect(document.documentElement.style.getPropertyValue('--accent-on-solid'))
      .toBe(ACCENTS.amber.onSolid)
  })

  it('reapplies --accent-fg when theme changes with the accent held constant', () => {
    const { rerender } = render(<AccentProvider><Probe /></AccentProvider>)
    expect(document.documentElement.style.getPropertyValue('--accent-fg')).toBe(ACCENTS.blue.fgDark)

    themeState.theme = 'light'
    rerender(<AccentProvider><Probe /></AccentProvider>)
    expect(document.documentElement.style.getPropertyValue('--accent-fg')).toBe(ACCENTS.blue.fgLight)
  })

  it('throws outside a provider', () => {
    expect(() => render(<Probe />)).toThrow(/useAccent must be used within/)
  })
})
