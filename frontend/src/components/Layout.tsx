import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Menu, X } from 'lucide-react'
import { useAppVersion } from '../hooks/useAppVersion'
import OfflineBanner from './OfflineBanner'
import Logo from './shell/Logo'
import TopNavLink from './shell/TopNavLink'
import MobileTabBar from './shell/MobileTabBar'
import RightCluster from './shell/RightCluster'
import HamburgerPanel from './shell/HamburgerPanel'
import { DESKTOP_NAV_ITEMS } from './shell/navItems'
import { IconButton } from './ui'

export default function Layout() {
  const { t } = useTranslation('nav')
  const { t: tc } = useTranslation('common')
  const version = useAppVersion()
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-screen flex flex-col pb-16 md:pb-0">
      {/* Header */}
      <header className="bg-garage-surface border-b border-garage-border sticky top-0 z-40">
        <div className="container mx-auto px-4">
          <div className="flex items-center justify-between h-14 md:h-16">
            <Logo />

            {/* Desktop Navigation */}
            <nav className="hidden md:flex space-x-6">
              {DESKTOP_NAV_ITEMS.map((item) => (
                <TopNavLink key={item.to} to={item.to} label={t(item.labelKey)} variant="inline" />
              ))}
            </nav>

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

      <OfflineBanner />

      {/* Main content */}
      <main className="flex-1">
        <Outlet />
      </main>

      <MobileTabBar />

      {/* Footer - hidden on mobile */}
      <footer className="hidden md:block bg-garage-surface border-t border-garage-border py-4">
        <div className="container mx-auto px-4 text-center text-garage-text-muted text-sm">
          <p>{tc('footer', { version })}</p>
        </div>
      </footer>
    </div>
  )
}
