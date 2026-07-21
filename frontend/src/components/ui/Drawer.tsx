import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { IconType } from './types'

/** Design §5.3. `2xs` stays separate from `xs` on purpose: folding them would
 *  widen the equipment drawer by 40px and loosen its clamp. */
export type DrawerWidth = '2xs' | 'xs' | 'sm' | 'md' | 'lg' | 'xl'

const WIDTH: Record<DrawerWidth, string> = {
  '2xs': 'w-[min(400px,92vw)]',
  xs: 'w-[min(440px,96vw)]',
  sm: 'w-[min(540px,96vw)]',
  md: 'w-[min(600px,96vw)]',
  lg: 'w-[min(720px,96vw)]',
  xl: 'w-[min(820px,97vw)]',
}

/**
 * Shared by the initial-focus query (scoped to the body slot only, so it
 * never lands on the header's Close button — see Finding 1 in Task 20's
 * review) and the Tab-trap query (scoped to the whole panel, where the
 * Close button must stay reachable by Tab). One constant so the two
 * selector strings cannot drift apart.
 */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
/** Tab-trap only: also honours elements made focusable purely via tabindex. */
const TAB_TRAP_SELECTOR = `${FOCUSABLE_SELECTOR}, [tabindex]:not([tabindex="-1"])`

/** Added on top of the measured transition duration before the closing
 *  timeout fallback fires — covers rAF/paint scheduling jitter so it never
 *  races a `transitionend` that is genuinely still in flight. */
const TRANSITION_FALLBACK_BUFFER_MS = 50

/**
 * Reads the panel's own computed `transition-duration` — which is owned by
 * the `--duration-drawer` token, see index.css — instead of hard-coding a
 * number here, so the closing-transition timeout fallback tracks the token
 * if it's ever changed. `transitionend` is the primary signal; this is only
 * a backstop, so falling back to 0 (immediate) when it can't be read/parsed
 * (e.g. no stylesheet loaded, as in a unit-test environment) is safe.
 */
function readTransitionDurationMs(el: HTMLElement): number {
  const raw = window.getComputedStyle(el).transitionDuration.split(',')[0]?.trim() ?? ''
  const value = Number.parseFloat(raw)
  if (Number.isNaN(value)) return 0
  return raw.endsWith('ms') ? value : value * 1000
}

interface DrawerProps {
  open: boolean
  onClose: () => void
  /** Already translated. Becomes the dialog's accessible name. */
  title: string
  /** IconType — rendered with aria-hidden="true" (see Task 3). */
  icon?: IconType
  width?: DrawerWidth
  footer?: ReactNode
  /** Accessible name for the close control. Callers translate. */
  closeLabel?: string
  children: ReactNode
}

/**
 * Right-anchored side drawer. The app has no side drawer today — every
 * create/edit flow is a centred modal — and the design makes all of them
 * drawers.
 *
 * Structurally this is FormModalWrapper (sticky header, scrolling body,
 * sticky footer) re-anchored, plus the two things it never had: Escape
 * handling and a focus trap.
 *
 * Portalled to document.body so it escapes any transformed or
 * overflow-hidden ancestor. Fourteen existing tests reach into modal content
 * with container.querySelector, which a portal would break — that is why
 * FormModalWrapper is left completely alone in P1, and why converting its 19
 * callers is P3 work with its own test updates.
 *
 * Motion is §4.8's: a .2s ease-out slide on the panel and a .15s fade on the
 * backdrop, both consuming the Task 1 duration tokens. Body scroll is locked
 * while open (§4.6). Background *inertness* — inert/aria-hidden on the app
 * root — is deferred to P3 with the conversions; see plan §13.
 */
export default function Drawer({
  open,
  onClose,
  title,
  icon: Icon,
  width = 'md',
  footer,
  closeLabel = 'Close',
  children,
}: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)
  const [entered, setEntered] = useState(false)
  // Whether the panel is still in the DOM. True the whole time `open` is
  // true, and for the tail of a closing transition after `open` flips to
  // false — see the second effect below. Initialised from `open` so a
  // Drawer that is never opened renders nothing on its very first paint.
  const [rendered, setRendered] = useState(open)

  // onClose is held in a ref and deliberately NOT in the effect's dep array.
  // Every consumer passes an inline arrow, so its identity changes on every
  // parent render; with [open, onClose] the effect tears down and re-runs on
  // each keystroke in any controlled input, and its cleanup focuses
  // restoreRef while its body focuses the first focusable node — so focus
  // jumps to the Close button after every character typed in all 15 record
  // forms. The gallery cannot catch this: its demo Input is uncontrolled.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) {
      setEntered(false)
      return
    }
    restoreRef.current = document.activeElement as HTMLElement | null

    // Scroll lock (§4.6). Restored on close, including on unmount.
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(TAB_TRAP_SELECTOR)
      if (!focusable || focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    // Focus the first focusable node *in the body slot* — not the header's
    // Close button, which a whole-panel, document-order query would always
    // hit first, since the header renders before the body in every
    // instance (Finding 1). Falls back to the panel itself so focus never
    // escapes to <body> when the body has no focusable control; this
    // deliberately does not fall further to the footer.
    const first = bodyRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    ;(first ?? panelRef.current)?.focus()

    // Next frame, so the browser paints the off-screen start state first and
    // the transition actually runs instead of being skipped.
    const raf = requestAnimationFrame(() => setEntered(true))

    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      restoreRef.current?.focus()
    }
  }, [open])

  // Closing-transition mount lifecycle — deliberately a separate effect from
  // the one above, so that effect's [open]-only dependency (load-bearing,
  // see its own comment) stays untouched. Keeps the panel mounted for the
  // tail of the exit transition instead of unmounting in the same render
  // that flips `open` false, which previously skipped the slide/fade
  // entirely (Finding 2).
  useEffect(() => {
    if (open) {
      setRendered(true)
      return
    }
    const panel = panelRef.current
    if (!panel) {
      setRendered(false)
      return
    }
    // Reduced-motion users already get an instant close from the CSS
    // (`motion-reduce:transition-none` sets transition-property to `none`,
    // so `transitionend` never fires for them). Waiting on that event here
    // would strand the drawer mounted — with its full-screen, now-invisible
    // backdrop still catching clicks — for no visible benefit. Skip the
    // wait entirely and unmount in the same tick, matching pre-fix
    // behaviour exactly for these users.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setRendered(false)
      return
    }

    let finished = false
    const finish = (): void => {
      if (finished) return
      finished = true
      window.clearTimeout(timeoutId)
      panel.removeEventListener('transitionend', onTransitionEnd)
      setRendered(false)
    }
    // Ignore transitionend bubbling up from a descendant's own transition
    // (e.g. the Close button's hover ui-motion) — only the panel's own
    // slide-out should end the drawer's life.
    const onTransitionEnd = (event: TransitionEvent): void => {
      if (event.target !== panel) return
      finish()
    }
    // Belt-and-braces: if transitionend never fires (a mismatched property,
    // a duration that reads as 0, a browser quirk) this still unmounts
    // rather than leaving the drawer's invisible backdrop blocking the page
    // forever.
    const timeoutId = window.setTimeout(
      finish,
      readTransitionDurationMs(panel) + TRANSITION_FALLBACK_BUFFER_MS,
    )
    panel.addEventListener('transitionend', onTransitionEnd)

    return () => {
      window.clearTimeout(timeoutId)
      panel.removeEventListener('transitionend', onTransitionEnd)
    }
  }, [open])

  if (!rendered) return null

  return createPortal(
    <>
      <div
        data-testid="drawer-backdrop"
        onClick={onClose}
        className={`fixed inset-0 z-drawer-backdrop bg-black/50 transition-opacity duration-(--duration-fast) ease-standard motion-reduce:transition-none ${
          entered ? 'opacity-100' : 'opacity-0'
        }`}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-testid="drawer"
        tabIndex={-1}
        className={`fixed right-0 top-0 z-drawer flex h-full flex-col border-l border-border bg-surface shadow-drawer transition-transform duration-(--duration-drawer) ease-standard motion-reduce:transition-none ${
          entered ? 'translate-x-0' : 'translate-x-full'
        } ${WIDTH[width]}`}
      >
        <header className="sticky top-0 flex items-center justify-between gap-3 border-b border-border bg-surface px-6 py-4">
          <h2 className="flex items-center gap-2 text-base font-bold text-text">
            {Icon ? <Icon aria-hidden="true" className="h-5 w-5 text-(--accent-fg)" /> : null}
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            title={closeLabel}
            className="ui-focus-ring ui-motion cursor-pointer inline-flex h-icon-md w-(--height-icon-md) items-center justify-center rounded-icon text-text-mute hover:text-text"
          >
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </header>

        <div ref={bodyRef} className="flex-1 overflow-y-auto px-6 py-5">{children}</div>

        {footer ? (
          <footer className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-border bg-surface px-6 py-4">
            {footer}
          </footer>
        ) : null}
      </div>
    </>,
    document.body,
  )
}
