import { createPortal } from 'react-dom'
import { Toaster } from 'sonner'
import { useTheme } from '../contexts/ThemeContext'

/**
 * sonner Toaster, theme-tracked (§4.10). App.tsx renders ThemeProvider and so
 * cannot call useTheme itself; this wrapper sits inside the provider tree.
 * richColors is dropped in favour of toastOptions.classNames mapped to the §4.9
 * status colours (--color-on-status foreground). The emitted
 * [data-sonner-toast]/[data-type] attributes are unchanged — e2e pins them.
 *
 * Bottom-left, not bottom-right. Drawers open on the right, so a bottom-right
 * toast sat on the footer's Cancel and Save, and hovering it to reach them
 * paused its dismiss timer. It stayed put as long as you aimed at the button.
 *
 * Portalled to document.body on purpose. Rendered in place it is a child of
 * #root, which Drawer marks `inert` while open (Drawer.tsx:46) — and `inert`
 * strips its subtree from the accessibility tree, so every toast raised from
 * inside a drawer went unannounced and could not be dismissed. It still
 * painted, which is why the defect went unnoticed. The portal makes it a
 * sibling of #root; React portals preserve context, so useTheme still works.
 */
export default function AppToaster() {
  const { theme } = useTheme()
  return createPortal(
    <Toaster
      position="bottom-left"
      theme={theme}
      toastOptions={{
        classNames: {
          error: 'bg-danger text-on-status border-danger',
          success: 'bg-success text-on-status border-success',
          warning: 'bg-warning text-on-status border-warning',
          info: 'bg-info text-on-status border-info',
        },
      }}
    />,
    document.body,
  )
}
