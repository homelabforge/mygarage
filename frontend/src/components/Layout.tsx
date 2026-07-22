import { Outlet, Link, useNavigate } from 'react-router-dom'
import { Settings, Info, LogOut, User } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { useAppVersion } from '../hooks/useAppVersion'
import { useEffect, useState } from 'react'
import OfflineBanner from './OfflineBanner'
import Logo from './shell/Logo'
import TopNavLink from './shell/TopNavLink'
import MobileTabBar from './shell/MobileTabBar'
import NavSearch from './shell/NavSearch'
import NotificationBell from './shell/NotificationBell'
import { DESKTOP_NAV_ITEMS } from './shell/navItems'
import api from '../services/api'

export default function Layout() {
  const { t } = useTranslation('nav')
  const { t: tc } = useTranslation('common')
  const navigate = useNavigate()
  const { user, isAuthenticated, isAdmin, logout } = useAuth()
  const version = useAppVersion()
  const [authMode, setAuthMode] = useState<string>('none')

  // Check authentication mode
  useEffect(() => {
    api.get('/settings/public')
      .then(res => {
        const authModeSetting = res.data.settings.find((s: { key: string; value?: string | null }) => s.key === 'auth_mode')
        setAuthMode(authModeSetting?.value || 'none')
      })
      .catch(() => setAuthMode('none'))
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

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

            <div className="hidden md:flex items-center space-x-4">
              <NavSearch placeholder={t('search')} className="hidden nav:flex w-[150px]" />
              <NotificationBell />
              <Link
                to="/about"
                className="text-garage-text-muted hover:text-garage-text transition-colors"
                title={t('about')}
                aria-label={t('about')}
              >
                <Info className="w-5 h-5" />
              </Link>
              <Link
                to="/settings"
                className="text-garage-text-muted hover:text-garage-text transition-colors"
                title={t('settings')}
                aria-label={t('settings')}
              >
                <Settings className="w-5 h-5" />
              </Link>

              {/* User Authentication UI - Only show if auth is enabled */}
              {authMode !== 'none' && (
                <>
                  {isAuthenticated && user ? (
                    <div className="flex items-center gap-3 pl-4 border-l border-garage-border">
                      <div className="flex items-center gap-2">
                        <User className="w-4 h-4 text-garage-text-muted" />
                        <span className="text-sm font-medium text-garage-text">{user.username}</span>
                        {isAdmin && (
                          <span className="px-2 py-0.5 text-xs font-semibold bg-danger-500 text-white rounded">
                            {t('admin')}
                          </span>
                        )}
                      </div>
                      <button
                        onClick={handleLogout}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-garage-text-muted hover:text-garage-text hover:bg-garage-bg rounded-lg transition-colors"
                        title={t('logout')}
                      >
                        <LogOut className="w-4 h-4" />
                        <span>{t('logout')}</span>
                      </button>
                    </div>
                  ) : (
                    <Link
                      to="/login"
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      <User className="w-4 h-4" />
                      <span>{t('login')}</span>
                    </Link>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
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
