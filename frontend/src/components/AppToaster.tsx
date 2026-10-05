import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Toaster, useSonner } from 'sonner'
import { useTheme } from '../contexts/ThemeContext'
import { useAnyDrawerOpen } from './ui/openDrawers'

type Corner = 'top-left' | 'bottom-left'

/**
 * sonner Toaster, theme-tracked (§4.10). App.tsx renders ThemeProvider and so
 * cannot call useTheme itself; this wrapper sits inside the provider tree.
 * richColors is dropped in favour of toastOptions.classNames mapped to the §4.9
 * status colours (--color-on-status foreground). The emitted
 * [data-sonner-toast]/[data-type] attributes are unchanged — e2e pins them.
 *
 * Bottom-left, and top-left while a drawer is open. Drawers open on the right,
 * so a bottom-right toast sat on the footer's Cancel and Save, and hovering it
 * to reach them paused its dismiss timer. It stayed put as long as you aimed at
 * the button. Bottom-left alone isn't enough: narrower than the drawer + 380px
 * (up to ~1200px for xl) the drawer reaches the left corner too, and some
 * footers keep Save, Back or Delete on the left. Top-left sits on the drawer's
 * header. A longer toast reaches into the top of the drawer body, and on phones
 * (sonner's full-width layout under 600px) it covers Close. That's the leftover.
 *
 * The corner only moves while nothing is showing. Changing position remounts
 * sonner's list, and a toast you were hovering never gets its mouseleave, so it
 * stays paused for good. A toast that's already up keeps its corner until it goes.
 *
 * --toast-lift (index.css) keeps bottom toasts above the phone tab bar.
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
  const drawerOpen = useAnyDrawerOpen()
  const { toasts } = useSonner()
  const wanted: Corner = drawerOpen ? 'top-left' : 'bottom-left'
  const [position, setPosition] = useState<Corner>(wanted)
  if (position !== wanted && toasts.length === 0) setPosition(wanted)
  return createPortal(
    <Toaster
      position={position}
      offset={{ bottom: 'calc(24px + var(--toast-lift))' }}
      mobileOffset={{ bottom: 'calc(16px + var(--toast-lift))' }}
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
