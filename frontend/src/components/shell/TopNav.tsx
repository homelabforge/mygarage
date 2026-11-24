import { useLayoutEffect, useRef, useState } from 'react'
import { Menu, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { IconButton } from '../ui'
import Logo from './Logo'
import TopNavLink from './TopNavLink'
import RightCluster from './RightCluster'
import HamburgerPanel from './HamburgerPanel'
import { DESKTOP_NAV_ITEMS } from './navItems'

/**
 * The 62px sticky top bar (prototype dc.html:38-39). One nav affordance per
 * band (LOCKED model): inline links `hidden nav:flex` (>=900); hamburger
 * `max-md:hidden nav:hidden` (768-899, visible via IconButton's base
 * `inline-flex` — media-scoped hides win the cascade over a bare `hidden`,
 * see IconButton); bottom bar `md:hidden` lives in MobileTabBar (<768). Owns
 * menuOpen and renders HamburgerPanel below the bar when open, so the closed
 * DOM stays clean.
 */
export default function TopNav() {
  const { t } = useTranslation('nav')
  const [menuOpen, setMenuOpen] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)
  const navRef = useRef<HTMLElement>(null)
  const clusterRef = useRef<HTMLDivElement>(null)
  // The links' width depends on the language (English needs a 1164px window,
  // Polish 1510), so no fixed breakpoint fits them all. When they don't fit,
  // hide them and use the hamburger instead of scrolling the bar sideways.
  const [linksDontFit, setLinksDontFit] = useState(false)

  useLayoutEffect(() => {
    const row = rowRef.current
    const nav = navRef.current
    const cluster = clusterRef.current
    if (!row || !nav || !cluster || typeof ResizeObserver === 'undefined') return
    const check = (): void => {
      const style = getComputedStyle(row)
      const gap = parseFloat(style.columnGap) || 0
      const inner = row.clientWidth - (parseFloat(style.paddingLeft) || 0) - (parseFloat(style.paddingRight) || 0)
      const logo = row.firstElementChild as HTMLElement | null
      // The controls only, not the cluster: the hamburger shows while the links
      // are hidden, and counting it would keep them hidden once they fit again.
      const controls = cluster.firstElementChild as HTMLElement | null
      const room = inner - (logo?.offsetWidth ?? 0) - (controls?.offsetWidth ?? 0) - 2 * gap
      setLinksDontFit(nav.scrollWidth > room)
    }
    const observer = new ResizeObserver(check)
    for (const el of [row, nav, cluster]) observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <header className="sticky top-0 z-nav border-b border-hair bg-(--color-nav) pt-safe-top pr-safe-right pl-safe-left backdrop-blur-[12px]">
      <div ref={rowRef} data-nav-row="" className="mx-auto flex h-[62px] max-w-[1320px] items-center gap-6 px-[clamp(16px,3vw,30px)]">
        <Logo />
        {/* Still laid out when hidden, so the observer can tell when the links fit
            again. Clipped to the bar so the hidden links can't scroll the page
            sideways; scrollWidth still reads their full width. */}
        <nav
          ref={navRef}
          data-nav="links"
          aria-hidden={linksDontFit || undefined}
          className={`hidden items-center gap-0.5 nav:flex ${linksDontFit ? 'invisible absolute left-0 max-w-full overflow-hidden' : ''}`}
        >
          {DESKTOP_NAV_ITEMS.map((item) => (
            <TopNavLink key={item.to} to={item.to} label={t(item.labelKey)} variant="inline" />
          ))}
        </nav>
        <div ref={clusterRef} data-nav-cluster="" className="ml-auto flex items-center gap-2">
          <RightCluster />
          <IconButton
            icon={menuOpen ? X : Menu}
            label={menuOpen ? t('closeMenu') : t('openMenu')}
            variant="surface"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            data-nav="hamburger"
            className={linksDontFit ? 'max-md:hidden' : 'max-md:hidden nav:hidden'}
          />
        </div>
      </div>
      {menuOpen ? <HamburgerPanel wide={linksDontFit} onNavigate={() => setMenuOpen(false)} /> : null}
    </header>
  )
}
