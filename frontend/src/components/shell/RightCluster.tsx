import { Link, useNavigate } from 'react-router-dom'
import { LogOut, Moon, Sun, User } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Avatar, Badge, IconButton } from '../ui'
import NavSearch from './NavSearch'
import NotificationBell from './NotificationBell'
import QuickSettingsDrawer from './QuickSettingsDrawer'
import { useTheme } from '../../contexts/ThemeContext'
import { useAuth } from '../../contexts/AuthContext'

/**
 * The nav right cluster (LOCKED responsive model). Search collapses below 900px
 * (hidden nav:flex); the gear (QuickSettingsDrawer) drops on phone (max-md:hidden,
 * visible via IconButton's base inline-flex) where Settings lives in the bottom
 * bar. The theme toggle is a
 * standalone icon; the gear is a button that opens the quick-settings drawer
 * (I2) — there is no separate /settings link (About + full Settings live inside
 * the drawer). Auth behaviour preserved: cluster gated on authMode !== 'none'
 * (from useAuth, replacing Layout's duplicate /settings/public fetch).
 */
export default function RightCluster() {
  const { t } = useTranslation('nav')
  const { theme, toggleTheme } = useTheme()
  const { user, isAuthenticated, isAdmin, logout, authMode } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex items-center gap-2">
      <NavSearch placeholder={t('search')} className="hidden nav:flex w-[150px]" />
      <IconButton
        icon={theme === 'dark' ? Sun : Moon}
        label={t('themeToggle')}
        variant="surface"
        onClick={toggleTheme}
      />
      <NotificationBell />
      <QuickSettingsDrawer className="max-md:hidden" />
      {authMode !== 'none' &&
        (isAuthenticated && user ? (
          <div className="flex items-center gap-2 border-l border-border pl-2">
            <Avatar name={user.username} size="sm" />
            {isAdmin ? (
              <span aria-hidden="true">
                <Badge tone="danger">{t('admin')}</Badge>
              </span>
            ) : null}
            <IconButton
              icon={LogOut}
              label={t('logout')}
              variant="ghost"
              onClick={handleLogout}
              className="max-md:hidden"
            />
          </div>
        ) : (
          <Link
            to="/login"
            className="ui-focus-ring ui-motion inline-flex cursor-pointer items-center gap-1.5 rounded-control bg-primary px-3 py-1.5 text-sm text-(--accent-on-solid) hover:bg-primary/90"
          >
            <User aria-hidden="true" className="h-4 w-4" />
            <span>{t('login')}</span>
          </Link>
        ))}
    </div>
  )
}
