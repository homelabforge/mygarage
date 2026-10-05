import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import * as ThemeContext from '../../contexts/ThemeContext'

let captured: Record<string, unknown> | null = null
let liveToasts: unknown[] = []
vi.mock('sonner', () => ({
  Toaster: (props: Record<string, unknown>) => { captured = props; return null },
  useSonner: () => ({ toasts: liveToasts }),
}))
vi.mock('../../contexts/ThemeContext')

import AppToaster from '../AppToaster'
import Drawer from '../ui/Drawer'

describe('AppToaster', () => {
  beforeEach(() => {
    liveToasts = []
    vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({ theme: 'dark', toggleTheme: vi.fn(), setTheme: vi.fn() })
  })

  it('tracks the app theme, drops richColors, and maps status classNames', () => {
    render(<AppToaster />)
    expect(captured?.theme).toBe('dark')
    expect(captured?.position).toBe('bottom-left')
    // Bottom toasts ride above the phone tab bar; index.css sets the lift.
    expect(captured?.offset).toEqual({ bottom: 'calc(24px + var(--toast-lift))' })
    expect(captured?.mobileOffset).toEqual({ bottom: 'calc(16px + var(--toast-lift))' })
    expect(captured?.richColors).toBeUndefined()
    const classNames = (captured?.toastOptions as { classNames: Record<string, string> }).classNames
    expect(classNames.error).toContain('bg-danger')
    expect(classNames.error).toContain('text-on-status')
    expect(classNames.success).toContain('bg-success')
  })

  const withDrawer = (open: boolean) => (
    <>
      <AppToaster />
      <Drawer open={open} onClose={() => {}} title="Edit">body</Drawer>
    </>
  )

  it('moves top-left while a drawer is open, so it never sits on the footer', () => {
    const { rerender } = render(withDrawer(true))
    expect(captured?.position).toBe('top-left')
    rerender(withDrawer(false))
    expect(captured?.position).toBe('bottom-left')
  })

  it('keeps its corner while a toast is up, then moves once it is gone', () => {
    // Moving remounts sonner's list, and a hovered toast never gets its
    // mouseleave, so it would sit there paused for good.
    liveToasts = [{ id: 1 }]
    const { rerender } = render(withDrawer(true))
    expect(captured?.position).toBe('bottom-left')
    liveToasts = []
    rerender(withDrawer(true))
    expect(captured?.position).toBe('top-left')
  })
})
