import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as ThemeContext from '../../../contexts/ThemeContext'
import * as AuthContext from '../../../contexts/AuthContext'
import TopNav from '../TopNav'

vi.mock('../../../contexts/ThemeContext')
vi.mock('../../../contexts/AuthContext')
// QuickSettingsDrawer (a descendant via RightCluster) reads useAccent; stub it.
vi.mock('../../../contexts/AccentContext', () => ({
  useAccent: () => ({ accent: 'blue', setAccent: vi.fn() }),
}))

function setup() {
  vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({ theme: 'dark', toggleTheme: vi.fn(), setTheme: vi.fn() })
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: null, isAuthenticated: false, isAdmin: false, logout: vi.fn(), authMode: 'none',
  } as unknown as ReturnType<typeof AuthContext.useAuth>)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <TopNav />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('TopNav', () => {
  it('renders the inline nav behind the nav: breakpoint', () => {
    setup()
    const nav = screen.getByRole('navigation')
    expect(nav).toHaveClass('hidden', 'nav:flex')
  })

  it('renders the hamburger only in the tablet band', () => {
    setup()
    // jsdom applies no CSS, so this only pins the class string — it cannot verify
    // computed display. The real proof is the browser check (see task-10 fix report).
    expect(screen.getByRole('button', { name: 'openMenu' })).toHaveClass('max-md:hidden', 'nav:hidden')
  })

  it('toggling the hamburger mounts and unmounts the panel', () => {
    setup()
    // panel closed: the hamburger placeholder text is the only search trigger
    expect(screen.queryByRole('button', { name: 'searchPlaceholder' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'openMenu' }))
    expect(screen.getByRole('button', { name: 'searchPlaceholder' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'closeMenu' }))
    expect(screen.queryByRole('button', { name: 'searchPlaceholder' })).toBeNull()
  })
})

// jsdom has no layout, so the widths are stubbed: the links need 1000px and the
// row leaves them 1000 - 120 (logo) - 280 (right cluster) - 2 gaps.
function stubLayout(navWidth: number) {
  class RO {
    constructor(private cb: ResizeObserverCallback) {}
    observe() {
      this.cb([], this as unknown as ResizeObserver)
    }
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal('ResizeObserver', RO)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return this.tagName === 'NAV' ? navWidth : 0
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return this.dataset.navRow !== undefined ? 1000 : 0
  })
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (this: HTMLElement) {
    // The whole cluster also holds the hamburger (44 more); its first child is
    // the controls that sit beside the links.
    if (this.dataset.navCluster !== undefined) return 324
    if (this.parentElement?.dataset.navCluster !== undefined && this.parentElement.firstElementChild === this) return 280
    const row = this.parentElement
    return row?.dataset.navRow !== undefined && row.firstElementChild === this ? 120 : 0
  })
}

describe('TopNav: links that do not fit', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  // Polish links need 1510px of viewport and English 1164, but the inline nav
  // took over at 900, so the bar scrolled sideways in between.
  it('swaps the inline links for the hamburger when they need more room than the bar has', () => {
    stubLayout(1000)
    setup()
    expect(screen.getByRole('navigation', { hidden: true })).toHaveClass('invisible')
    const burger = screen.getByRole('button', { name: 'openMenu' })
    expect(burger).not.toHaveClass('nav:hidden')
    fireEvent.click(burger)
    const panelSearch = screen.getByRole('button', { name: 'searchPlaceholder' })
    expect(panelSearch.closest('div.border-t')).toHaveClass('md:block')
    // the bar keeps its own search at 900 and up, so the panel's one hides there
    expect(panelSearch).toHaveClass('nav:hidden')
  })

  // An absolutely placed nowrap row still counts as page overflow, so the hidden
  // links scrolled the page sideways just above 900px in Polish.
  it('clips the hidden links to the bar so they cannot widen the page', () => {
    stubLayout(1000)
    setup()
    expect(screen.getByRole('navigation', { hidden: true })).toHaveClass('absolute', 'left-0', 'max-w-full', 'overflow-hidden')
  })

  // Hiding the links shows the hamburger, which widens the cluster; counting it
  // kept the links hidden after the window grew back (1100 -> 1200 in English).
  it("doesn't count the hamburger as room the links need", () => {
    stubLayout(580)
    setup()
    expect(screen.getByRole('navigation')).not.toHaveClass('invisible')
  })

  it('keeps the inline links when they fit', () => {
    stubLayout(400)
    setup()
    expect(screen.getByRole('navigation')).not.toHaveClass('invisible')
    expect(screen.getByRole('navigation')).not.toHaveClass('overflow-hidden')
    expect(screen.getByRole('button', { name: 'openMenu' })).toHaveClass('nav:hidden')
    fireEvent.click(screen.getByRole('button', { name: 'openMenu' }))
    expect(screen.getByRole('button', { name: 'searchPlaceholder' })).not.toHaveClass('nav:hidden')
  })
})
