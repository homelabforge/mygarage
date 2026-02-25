import { isMobileBrowser } from './mobile'

/**
 * Determine the post-login destination for the current user.
 * Returns '/quick-entry' for mobile users with the setting enabled,
 * otherwise returns '/' (dashboard).
 */
export function resolvePostLoginRoute(user: { mobile_quick_entry_enabled?: boolean }): string {
  if (isMobileBrowser() && user.mobile_quick_entry_enabled) {
    return '/quick-entry'
  }
  return '/'
}
