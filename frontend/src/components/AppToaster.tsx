import { Toaster } from 'sonner'
import { useTheme } from '../contexts/ThemeContext'

/**
 * sonner Toaster, theme-tracked (§4.10). App.tsx renders ThemeProvider and so
 * cannot call useTheme itself; this wrapper sits inside the provider tree.
 * richColors is dropped in favour of toastOptions.classNames mapped to the §4.9
 * status colours (--color-on-status foreground). position and the emitted
 * [data-sonner-toast]/[data-type] attributes are unchanged — e2e pins them.
 */
export default function AppToaster() {
  const { theme } = useTheme()
  return (
    <Toaster
      position="bottom-right"
      theme={theme}
      toastOptions={{
        classNames: {
          error: 'bg-danger text-on-status border-danger',
          success: 'bg-success text-on-status border-success',
          warning: 'bg-warning text-on-status border-warning',
          info: 'bg-info text-on-status border-info',
        },
      }}
    />
  )
}
