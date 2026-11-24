import { Link, useNavigate } from 'react-router-dom'
import { LogOut, Moon, Sun, User } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Avatar, Badge, IconButton } from '../ui'
import NavSearch from './NavSearch'
import NotificationBell from './NotificationBell'
import QuickSettingsDrawer from './QuickSettingsDrawer'
import { useThemePreference } from '../../hooks/useThemePreference'
import { useAuth } from '../../contexts/AuthContext'

/**
 * The nav right cluster (LOCKED responsive model). Search collapses below 900px
 * (max-nav:hidden). The gear (QuickSettingsDrawer) is reachable on every
 * viewport so phone users can reach the per-account accent picker and logout,
 * which live inside the drawer. The theme toggle is a standalone icon; the gear
 * opens the quick-settings drawer (I2) — there is no separate /settings link
 * (About + full Settings live inside the drawer). The standalone logout
 * IconButton is a desktop-only one-tap shortcut (max-md:hidden); on phone,
 * logout is in the drawer. Auth behaviour preserved: cluster gated on
 * authMode !== 'none' (from useAuth, replacing Layout's duplicate
 * /settings/public fetch).
 */
export default function RightCluster() {
  const { t } = useTranslation('nav')
  const { theme, toggleTheme } = useThemePreference()
  const { user, isAuthenticated, isAdmin, logout, authMode } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="flex items-center gap-2">
      <NavSearch placeholder={t('search')} className="max-nav:hidden w-[150px]" />
      <IconButton
        icon={theme === 'dark' ? Sun : Moon}
        label={t('themeToggle')}
        variant="surface"
        onClick={toggleTheme}
      />
      <NotificationBell />
      <QuickSettingsDrawer />
      {authMode !== 'none' &&
        (isAuthenticated && user ? (
          <div className="flex items-center gap-2 border-l border-border pl-2">
            <Avatar name={user.username} size="sm" />
            {/* Tablet band only. On a phone it pushed the bar past the screen
                edge (#298), and from 900 up its 61px kept the English top links
                from fitting at 1280. */}
            {isAdmin ? (
              <span aria-hidden="true" className="max-md:hidden nav:hidden">
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
