import { useEffect, useId, useLayoutEffect, useRef, useState, type MouseEvent, type PointerEvent, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { FOCUSABLE_SELECTOR, FORM_FIELD_SELECTOR, isRendered, trapTab } from './focusTrap'
import { pushLayer } from './modalStack'

export type DialogSize = 'sm' | 'md' | 'lg' | '2xl' | '3xl'

const SIZE: Record<DialogSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  '2xl': 'max-w-2xl',
  '3xl': 'max-w-3xl',
}

interface DialogProps {
  open: boolean
  /** Esc, a backdrop click and the header X all land here. */
  onClose: () => void
  /** Already translated. Rendered as the h2 and used as the accessible name. */
  title?: string
  /** Id of an element inside that names the dialog, when there's no title. */
  labelledBy?: string
  describedBy?: string
  role?: 'dialog' | 'alertdialog'
  size?: DialogSize
  footer?: ReactNode
  /** Accessible name for the header X. The X only shows when title is set too. */
  closeLabel?: string
  /** 'cancel' focuses the [data-dialog-cancel] element. */
  initialFocus?: 'first-field' | 'cancel'
  children: ReactNode
}

/**
 * Centred modal for confirms and the few overlays that aren't drawers. The
 * modal stack owns Esc, Tab, scroll lock, inert and focus restore, so this
 * only draws the box and picks initial focus. Sits above a nested drawer
 * (z-dialog), so a confirm from inside one lands on top.
 */
export default function Dialog({
  open,
  onClose,
  title,
  labelledBy,
  describedBy,
  role = 'dialog',
  size = 'md',
  footer,
  closeLabel,
  initialFocus = 'first-field',
  children,
}: DialogProps): ReactElement | null {
  const overlayRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const footerRef = useRef<HTMLDivElement>(null)
  const [entered, setEntered] = useState(false)
  const titleId = useId()
  // Whether the last press started, and ended, on the backdrop itself. See onBackdropClick.
  const downOnBackdrop = useRef(false)
  const upOnBackdrop = useRef(false)

  // Same deal as Drawer: callers pass inline arrows, and re-running the
  // effect on every render would bounce focus around.
  // Synced in a layout effect so render never touches them, and it still
  // lands before the open effect below reads them.
  const onCloseRef = useRef(onClose)
  const initialFocusRef = useRef(initialFocus)
  useLayoutEffect(() => {
    onCloseRef.current = onClose
    initialFocusRef.current = initialFocus
  })

  useEffect(() => {
    if (!open) {
      setEntered(false)
      return
    }
    const release = pushLayer({
      kind: 'dialog',
      nodes: () => (overlayRef.current ? [overlayRef.current] : []),
      onEscape: () => onCloseRef.current(),
      onTab: (event) => trapTab(event, panelRef.current),
      restoreTo: document.activeElement as HTMLElement | null,
    })

    const panel = panelRef.current
    if (panel) {
      const cancel = panel.querySelector<HTMLElement>('[data-dialog-cancel]')
      const scopes = [bodyRef.current, footerRef.current].filter((node) => node !== null)
      // Never the header X: a field first, then anything focusable, then the panel.
      const candidates = [
        ...(initialFocusRef.current === 'cancel' && cancel ? [cancel] : []),
        ...scopes.flatMap((scope) => [...scope.querySelectorAll<HTMLElement>(FORM_FIELD_SELECTOR)]),
        ...scopes.flatMap((scope) => [...scope.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)]),
      ].filter(isRendered)
      const landed = candidates.some((el) => {
        el.focus()
        return document.activeElement === el
      })
      if (!landed) panel.focus()
    }

    const raf = requestAnimationFrame(() => setEntered(true))
    return () => {
      cancelAnimationFrame(raf)
      release()
    }
  }, [open])

  if (!open) return null

  const onBackdropPointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    downOnBackdrop.current = event.target === event.currentTarget
    upOnBackdrop.current = false
  }

  const onBackdropPointerUp = (event: PointerEvent<HTMLDivElement>): void => {
    upOnBackdrop.current = event.target === event.currentTarget
  }

  // Both ends have to be on the backdrop. A drag between a field and out here,
  // either way round, gets its click sent to the overlay, and that's not a dismiss.
  const onBackdropClick = (event: MouseEvent<HTMLDivElement>): void => {
    const startedHere = downOnBackdrop.current
    const endedHere = upOnBackdrop.current
    downOnBackdrop.current = false
    upOnBackdrop.current = false
    if (startedHere && endedHere && event.target === event.currentTarget) onCloseRef.current()
  }

  return createPortal(
    <div
      ref={overlayRef}
      data-testid="dialog-backdrop"
      onPointerDown={onBackdropPointerDown}
      onPointerUp={onBackdropPointerUp}
      onClick={onBackdropClick}
      className={`fixed inset-0 z-dialog-backdrop modal-safe-pad flex items-center justify-center bg-black/50 transition-opacity duration-(--duration-fast) ease-standard motion-reduce:transition-none ${
        entered ? 'opacity-100' : 'opacity-0'
      }`}
    >
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-labelledby={title ? titleId : labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
        className={`relative z-dialog w-full ${SIZE[size]} max-h-[min(90vh,100%)] overflow-y-auto rounded-panel border border-border bg-surface shadow-menu`}
      >
        {title ? (
          <header className="sticky top-0 flex items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
            <h2 id={titleId} className="text-base font-bold text-text">{title}</h2>
            {closeLabel ? (
              <button
                type="button"
                onClick={() => onCloseRef.current()}
                aria-label={closeLabel}
                title={closeLabel}
                className="ui-focus-ring ui-motion cursor-pointer inline-flex h-icon-md w-(--height-icon-md) items-center justify-center rounded-icon text-text-mute hover:text-text"
              >
                <X aria-hidden="true" className="h-5 w-5" />
              </button>
            ) : null}
          </header>
        ) : null}
        <div ref={bodyRef} className="p-6">{children}</div>
        {footer ? (
          <div ref={footerRef} className="flex items-center justify-end gap-3 px-6 pb-6">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
