import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import * as ThemeContext from '../../contexts/ThemeContext'

let captured: Record<string, unknown> | null = null
vi.mock('sonner', () => ({ Toaster: (props: Record<string, unknown>) => { captured = props; return null } }))
vi.mock('../../contexts/ThemeContext')

import AppToaster from '../AppToaster'

describe('AppToaster', () => {
  it('tracks the app theme, drops richColors, and maps status classNames', () => {
    vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({ theme: 'dark', toggleTheme: vi.fn(), setTheme: vi.fn() })
    render(<AppToaster />)
    expect(captured?.theme).toBe('dark')
    expect(captured?.position).toBe('bottom-right')
    expect(captured?.richColors).toBeUndefined()
    const classNames = (captured?.toastOptions as { classNames: Record<string, string> }).classNames
    expect(classNames.error).toContain('bg-danger')
    expect(classNames.error).toContain('text-on-status')
    expect(classNames.success).toContain('bg-success')
  })
})
