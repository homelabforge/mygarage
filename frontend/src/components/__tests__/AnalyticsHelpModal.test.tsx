import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// The unit and currency hooks read useAuth, and the shared render has no AuthProvider.
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))
import { render, screen } from '../../__tests__/test-utils'
import AnalyticsHelpModal from '../AnalyticsHelpModal'

describe('AnalyticsHelpModal layout', () => {
  it('pads the drawer clear of the iPhone insets (#305)', () => {
    // A drawer now, so the insets live on the panel and its footer, not a centring overlay.
    render(<AnalyticsHelpModal isOpen onClose={vi.fn()} />)
    const drawer = screen.getByTestId('drawer')
    expect(drawer).toHaveClass('pt-safe-top', 'pr-safe-right', 'pl-drawer-safe')
    const footer = drawer.querySelector(':scope > footer')
    expect(footer, 'the Got it footer is gone').not.toBeNull()
    expect(footer!.className).toContain('var(--spacing-safe-bottom)')
  })
})

describe('AnalyticsHelpModal as a drawer', () => {
  let root: HTMLElement
  beforeEach(() => {
    root = document.body.appendChild(document.createElement('div'))
    root.id = 'root'
  })
  afterEach(() => root.remove())

  it('is a named drawer outside #root', () => {
    render(<AnalyticsHelpModal isOpen onClose={vi.fn()} />, { container: root })
    const drawer = screen.getByTestId('drawer')
    expect(drawer).toHaveAccessibleName('vehicleHelp.title')
    // Same width as its garage sibling.
    expect(drawer).toHaveClass('[--drawer-w:min(720px,96vw)]')
    expect(root.contains(drawer)).toBe(false)
  })
})
