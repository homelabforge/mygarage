import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { isMobileBrowser } from '../utils/mobile'

/**
 * Layout-route gate that redirects mobile users to Quick Entry on each new
 * browser session, when the preference is explicitly enabled.
 *
 * Uses a user-scoped sessionStorage flag (`qe_redirected:<id>`) so that
 * clicking "Dashboard" from Quick Entry works normally for the rest of the
 * session. The flag is cleared on logout, so the redirect fires again on
 * the next login/session.
 */
export default function MobileQuickEntryGate() {
  const { user } = useAuth()

  if (
    user?.mobile_quick_entry_enabled === true &&
    isMobileBrowser() &&
    !sessionStorage.getItem(`qe_redirected:${user.id}`)
  ) {
    return <Navigate to="/quick-entry" replace />
  }

  return <Outlet />
}
