import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { Car, Settings, Home, Info, BookUser, BarChart3, Calendar, LogOut, User, MapPin } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { useAppVersion } from '../hooks/useAppVersion'
import { useEffect, useState } from 'react'
import OfflineBanner from './OfflineBanner'
import api from '../services/api'

export default function Layout() {
  const { t } = useTranslation('nav')
  const { t: tc } = useTranslation('common')
  const location = useLocation()
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
            <Link to="/" className="flex items-center space-x-2">
              <Car className="w-6 h-6 md:w-8 md:h-8 text-primary-500" />
              <span className="text-lg md:text-xl font-bold">MyGarage</span>
            </Link>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex space-x-6">
              <Link
                to="/"
                className="flex items-center space-x-2 text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <Home className="w-4 h-4" />
                <span>{t('dashboard')}</span>
              </Link>
              <Link
                to="/analytics"
                className="flex items-center space-x-2 text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <BarChart3 className="w-4 h-4" />
                <span>{t('analytics')}</span>
              </Link>
              <Link
                to="/address-book"
                className="flex items-center space-x-2 text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <BookUser className="w-4 h-4" />
                <span>{t('addressBook')}</span>
              </Link>
              <Link
                to="/poi-finder"
                className="flex items-center space-x-2 text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <MapPin className="w-4 h-4" />
                <span>{t('findPOI')}</span>
              </Link>
              <Link
                to="/calendar"
                className="flex items-center space-x-2 text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <Calendar className="w-4 h-4" />
                <span>{t('calendar')}</span>
              </Link>
            </nav>

            <div className="hidden md:flex items-center space-x-4">
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
                      className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
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

      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-garage-surface border-t border-garage-border z-40">
        <div className="flex items-center justify-around h-16 px-2">
          <Link
            to="/"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <Home className="w-5 h-5" />
            <span className="text-xs mt-1">{t('home')}</span>
          </Link>

          <Link
            to="/address-book"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/address-book'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <BookUser className="w-5 h-5" />
            <span className="text-xs mt-1">{t('contacts')}</span>
          </Link>

          <Link
            to="/poi-finder"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/poi-finder'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <MapPin className="w-5 h-5" />
            <span className="text-xs mt-1">{t('poi')}</span>
          </Link>

          <Link
            to="/calendar"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/calendar'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <Calendar className="w-5 h-5" />
            <span className="text-xs mt-1">{t('calendar')}</span>
          </Link>

          <Link
            to="/analytics"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/analytics'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <BarChart3 className="w-5 h-5" />
            <span className="text-xs mt-1">{t('analytics')}</span>
          </Link>

          <Link
            to="/settings"
            className={`flex flex-col items-center justify-center min-w-[56px] py-3 px-3 rounded-lg transition-colors ${
              location.pathname === '/settings'
                ? 'text-primary-500 bg-primary-500/10'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            <Settings className="w-5 h-5" />
            <span className="text-xs mt-1">{t('settings')}</span>
          </Link>
        </div>
      </nav>

      {/* Footer - hidden on mobile */}
      <footer className="hidden md:block bg-garage-surface border-t border-garage-border py-4">
        <div className="container mx-auto px-4 text-center text-garage-text-muted text-sm">
          <p>{tc('footer', { version })}</p>
        </div>
      </footer>
    </div>
  )
}
