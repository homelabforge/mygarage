import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { IconType } from './types'
import { FOCUSABLE_SELECTOR, FORM_FIELD_SELECTOR, isRendered, trapTab } from './focusTrap'
import { isTopLayer, pushLayer, syncInert, type ModalLayer } from './modalStack'

/** Design §5.3. `2xs` stays separate from `xs` on purpose: folding them would
 *  widen the equipment drawer by 40px and loosen its clamp. */
export type DrawerWidth = '2xs' | 'xs' | 'sm' | 'md' | 'lg' | 'xl'

// Set as --drawer-w, which the panel's width and pl-drawer-safe (index.css)
// both read: the left inset only matters where the panel actually reaches it.
const WIDTH: Record<DrawerWidth, string> = {
  '2xs': '[--drawer-w:min(400px,92vw)]',
  xs: '[--drawer-w:min(440px,96vw)]',
  sm: '[--drawer-w:min(540px,96vw)]',
  md: '[--drawer-w:min(600px,96vw)]',
  lg: '[--drawer-w:min(720px,96vw)]',
  xl: '[--drawer-w:min(820px,97vw)]',
}

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
  /** Renders at +10 (z-drawer-nested*) and outranks a plain drawer in the
   *  modal stack, so its Esc never closes the ancestor too (design §4.9). */
  nested?: boolean
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
 * backdrop, both consuming the Task 1 duration tokens. Scroll lock, inert,
 * Escape, Tab and focus restore all belong to the modal stack (modalStack.ts),
 * shared with Dialog, so the drawer just registers a layer while it's open.
 */
export default function Drawer({
  open,
  onClose,
  title,
  icon: Icon,
  width = 'md',
  footer,
  closeLabel = 'Close',
  nested = false,
  children,
}: DrawerProps) {
  const backdropRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<ModalLayer | null>(null)
  const [entered, setEntered] = useState(false)
  // Whether the panel is still in the DOM. True the whole time `open` is
  // true, and for the tail of a closing transition after `open` flips to
  // false — see the second effect below. Initialised from `open` so a
  // Drawer that is never opened renders nothing on its very first paint.
  const [rendered, setRendered] = useState(open)

  // onClose is held in a ref and deliberately NOT in the effect's dep array.
  // Every consumer passes an inline arrow, so its identity changes on every
  // parent render; with [open, onClose] the open effect would tear down and
  // re-run on each keystroke in any controlled input, and its release focuses
  // the trigger, so focus would jump back to it after every character
  // typed in all 15 record forms. The gallery can't catch this: its demo Input
  // is uncontrolled.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) {
      setEntered(false)
      return
    }
    const layer: ModalLayer = {
      kind: 'drawer',
      nested,
      nodes: () => [backdropRef.current, panelRef.current].filter((node) => node !== null),
      onEscape: () => onCloseRef.current(),
      onTab: (event) => trapTab(event, panelRef.current),
      restoreTo: document.activeElement as HTMLElement | null,
    }
    layerRef.current = layer
    const release = pushLayer(layer)

    // Next frame, so the browser paints the off-screen start state first and
    // the transition actually runs instead of being skipped.
    const raf = requestAnimationFrame(() => setEntered(true))

    return () => {
      cancelAnimationFrame(raf)
      layerRef.current = null
      release()
    }
  }, [open, nested])

  // Keeps the panel mounted through its exit slide, then unmounts. Its own
  // effect so the one above keeps its [open, nested] deps (no onClose, see
  // onCloseRef). Unmounting on the render that flips open skipped the slide.
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

  // A stay-mounted drawer has no nodes yet when it pushes its layer, so the
  // stack gets another go at inert once they exist.
  useEffect(() => {
    if (rendered) syncInert()
  }, [rendered])

  // Initial focus. `rendered` is in the deps so this runs again once the
  // panel exists: a drawer that stays mounted closed renders null on the
  // render that flips `open`, so the refs are still empty the first time.
  // Declared after the first effect so the layer grabs the trigger before
  // focus moves. Still no children in the deps: a re-render must never move
  // focus (see onCloseRef). Only the top layer takes focus, so a parent
  // mounting with its nested drawer can't steal it back.
  useEffect(() => {
    if (!open) return
    const body = bodyRef.current
    const panel = panelRef.current
    if (!body || !panel) return
    if (!layerRef.current || !isTopLayer(layerRef.current)) return
    // Body slot first, never the header's Close (Finding 1): its first form
    // field, else its first focusable, skipping anything not rendered. The
    // panel is the fallback so focus never drops to <body>; the footer never gets it.
    const candidates = (): HTMLElement[] =>
      [
        ...body.querySelectorAll<HTMLElement>(FORM_FIELD_SELECTOR),
        ...body.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ].filter(isRendered)
    // The activeElement check backs up isRendered: anything focus() won't take, try the next.
    const focusFirst = (found: HTMLElement[]): boolean =>
      found.some((el) => {
        el.focus()
        return document.activeElement === el
      })
    if (focusFirst(candidates())) return
    panel.focus()
    // Body is still a spinner. Step in once, when the first field shows up
    // (or a disabled or hidden one comes alive), and only if focus is still
    // parked on the panel.
    const observer = new MutationObserver(() => {
      const found = candidates()
      if (found.length === 0) return
      observer.disconnect()
      if (document.activeElement === panel) focusFirst(found)
    })
    observer.observe(body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['disabled', 'hidden', 'style', 'class'],
    })
    return () => observer.disconnect()
  }, [open, rendered])

  if (!rendered) return null

  const backdropZ = nested ? 'z-drawer-nested-backdrop' : 'z-drawer-backdrop'
  const panelZ = nested ? 'z-drawer-nested' : 'z-drawer'
  // Still sliding out. It's already off the stack, so the panel goes dead to
  // clicks, keys and focus, or a Cancelled form can still submit on its way out.
  // The backdrop stays hit-testable but does nothing, so a double-click's
  // second hit doesn't fall through to the page underneath.
  const closing = !open
  const gone = closing ? 'pointer-events-none' : ''

  return createPortal(
    <>
      <div
        ref={backdropRef}
        data-testid="drawer-backdrop"
        onClick={open ? onClose : undefined}
        className={`fixed inset-0 ${backdropZ} bg-black/50 transition-opacity duration-(--duration-fast) ease-standard motion-reduce:transition-none ${
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
        inert={closing || undefined}
        className={`fixed right-0 top-0 ${panelZ} flex h-full w-(--drawer-w) flex-col border-l border-border bg-surface pt-safe-top pr-safe-right pl-drawer-safe shadow-drawer transition-transform duration-(--duration-drawer) ease-standard motion-reduce:transition-none ${
          entered ? 'translate-x-0' : 'translate-x-full'
        } ${WIDTH[width]} ${gone}`}
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

        {/* With no footer the body is what sits on the home indicator, so it takes the inset. */}
        <div
          ref={bodyRef}
          className={`flex-1 overflow-y-auto px-6 pt-5 ${footer ? 'pb-5' : 'pb-[calc(1.25rem+var(--spacing-safe-bottom))]'}`}
        >
          {children}
        </div>

        {footer ? (
          <footer className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-border bg-surface px-6 pt-4 pb-[calc(1rem+var(--spacing-safe-bottom))]">
            {footer}
          </footer>
        ) : null}
      </div>
    </>,
    document.body,
  )
}
