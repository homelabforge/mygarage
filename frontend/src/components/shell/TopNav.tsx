import { useState } from 'react'
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
 * `hidden md:max-nav:inline-flex` (768-899); bottom bar `md:hidden` lives in
 * MobileTabBar (<768). Owns menuOpen and renders HamburgerPanel below the bar
 * when open, so the closed DOM stays clean.
 */
export default function TopNav() {
  const { t } = useTranslation('nav')
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="sticky top-0 z-nav border-b border-hair bg-(--color-nav) backdrop-blur-[12px]">
      <div className="mx-auto flex h-[62px] max-w-[1320px] items-center gap-6 px-[clamp(16px,3vw,30px)]">
        <Logo />
        <nav className="hidden items-center gap-0.5 nav:flex">
          {DESKTOP_NAV_ITEMS.map((item) => (
            <TopNavLink key={item.to} to={item.to} label={t(item.labelKey)} variant="inline" />
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <RightCluster />
          <IconButton
            icon={menuOpen ? X : Menu}
            label={menuOpen ? t('closeMenu') : t('openMenu')}
            variant="surface"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="hidden md:max-nav:inline-flex"
          />
        </div>
      </div>
      {menuOpen ? <HamburgerPanel onNavigate={() => setMenuOpen(false)} /> : null}
    </header>
  )
}
