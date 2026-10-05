import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, fireEvent } from '@testing-library/react'
import { toast } from 'sonner'

vi.mock('../../contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }))
import AppToaster from '../AppToaster'
import Drawer from '../ui/Drawer'

// Real sonner, not the mock in AppToaster.test.tsx. The corner hold leans on
// sonner's own timing (useSonner vs the Toaster's list), so an upgrade that
// shifts it should fail here.
const ui = (open: boolean) => (
  <>
    <AppToaster />
    <Drawer open={open} onClose={() => {}} title="Edit">body</Drawer>
  </>
)
const list = () => document.querySelector<HTMLElement>('[data-sonner-toaster]')
const item = () => document.querySelector<HTMLElement>('[data-sonner-toast]')
// Small steps on purpose. One big advance skips the timers sonner's effects
// schedule mid-run (its 200ms unmount, the rAF publish).
const settle = (total: number, step = 20) => {
  for (let t = 0; t < total; t += step) act(() => { vi.advanceTimersByTime(step) })
}

describe('AppToaster against real sonner', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'requestAnimationFrame', 'cancelAnimationFrame'],
    })
  })
  afterEach(() => {
    act(() => { toast.dismiss() })
    settle(2000)
    vi.useRealTimers()
  })

  it('a hovered toast is not remounted when its drawer closes, so it still dismisses', () => {
    const { rerender } = render(ui(true))
    act(() => { toast.error('refused') })
    settle(100)
    const first = list()!
    expect(first.getAttribute('data-y-position')).toBe('top')
    act(() => { fireEvent.mouseEnter(first) })
    expect(item()!.getAttribute('data-expanded')).toBe('true')

    rerender(ui(false))
    settle(100)
    // Same list. A new one would never see the mouseleave, and the toast
    // would stay paused for good.
    expect(list()).toBe(first)
    expect(list()!.getAttribute('data-y-position')).toBe('top')

    act(() => { fireEvent.mouseLeave(first) })
    settle(10_000)
    expect(item()).toBeNull()
    act(() => { toast.success('next') })
    settle(100)
    expect(list()!.getAttribute('data-y-position')).toBe('bottom')
  })

  it('a toast already up when a drawer opens keeps its corner, the next one moves', () => {
    const { rerender } = render(ui(false))
    act(() => { toast.success('saved') })
    settle(100)
    expect(list()!.getAttribute('data-y-position')).toBe('bottom')
    rerender(ui(true))
    settle(100)
    expect(list()!.getAttribute('data-y-position')).toBe('bottom')
    settle(10_000)
    expect(item()).toBeNull()
    act(() => { toast.error('oops') })
    settle(100)
    expect(list()!.getAttribute('data-y-position')).toBe('top')
  })

  it('only the bottom offsets carry the tab-bar lift', () => {
    render(ui(false))
    act(() => { toast.success('saved') })
    settle(100)
    const s = list()!.style
    expect(s.getPropertyValue('--offset-bottom')).toBe('calc(24px + var(--toast-lift))')
    expect(s.getPropertyValue('--offset-top')).toBe('24px')
    expect(s.getPropertyValue('--offset-left')).toBe('24px')
    expect(s.getPropertyValue('--mobile-offset-bottom')).toBe('calc(16px + var(--toast-lift))')
    expect(s.getPropertyValue('--mobile-offset-top')).toBe('16px')
  })
})
