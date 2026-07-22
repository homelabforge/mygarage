import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import InstallPrompt from '../InstallPrompt'

function fireInstallPrompt() {
  const e = new Event('beforeinstallprompt') as Event & { prompt: () => Promise<void>; userChoice: Promise<unknown> }
  e.prompt = async () => {}
  e.userChoice = Promise.resolve({ outcome: 'dismissed' })
  window.dispatchEvent(e)
}

describe('InstallPrompt', () => {
  beforeEach(() => localStorage.clear())

  it('shows a tokenized card and no raw palette after the install event', async () => {
    vi.useFakeTimers()
    render(<InstallPrompt />)
    act(() => fireInstallPrompt())
    await act(async () => { vi.advanceTimersByTime(3000) })
    const install = screen.getByText('installPrompt.install')
    expect(install).toHaveClass('bg-primary', 'text-(--accent-on-solid)')
    expect(install.className).not.toMatch(/-(primary|blue)-\d00\b/)
    expect(install.className).not.toMatch(/text-white/)
    vi.useRealTimers()
  })

  it('stops showing after dismiss (behaviour preserved)', async () => {
    vi.useFakeTimers()
    render(<InstallPrompt />)
    act(() => fireInstallPrompt())
    await act(async () => { vi.advanceTimersByTime(3000) })
    fireEvent.click(screen.getByText('installPrompt.install').parentElement!.querySelector('button:last-child')!)
    expect(localStorage.getItem('pwa-install-dismissed')).toBe('true')
    expect(screen.queryByText('installPrompt.install')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
