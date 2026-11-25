/**
 * Shared by the initial-focus query (scoped to the body slot only, so it
 * never lands on the header's Close button; see Finding 1 in Task 20's
 * review) and the Tab-trap query (scoped to the whole panel, where the
 * Close button must stay reachable by Tab). One constant so the two
 * selector strings cannot drift apart.
 */
export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
/** Initial focus tries these first: a box the user can type or pick in, so a
 *  Revoke or Delete listed above the form never gets it. */
export const FORM_FIELD_SELECTOR =
  'input:not([disabled]):not([readonly]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]):not([readonly])'
/** Tab-trap only: also honours elements made focusable purely via tabindex. */
export const TAB_TRAP_SELECTOR = `${FOCUSABLE_SELECTOR}, [tabindex]:not([tabindex="-1"])`

/**
 * Whether a candidate is rendered, so focus() can land on it. A display:none
 * file input (an upload's, ahead of its Select file button) matches the
 * selectors but focus() on it does nothing. Uses checkVisibility where the
 * browser has it; jsdom doesn't, so it walks up for `hidden` and display:none.
 */
export function isRendered(el: HTMLElement): boolean {
  if (typeof el.checkVisibility === 'function') return el.checkVisibility({ visibilityProperty: true })
  for (let node: HTMLElement | null = el; node; node = node.parentElement) {
    if (node.hidden || window.getComputedStyle(node).display === 'none') return false
  }
  return window.getComputedStyle(el).visibility !== 'hidden'
}

/** What Tab can actually reach in here: rendered, enabled, not under inert. */
function tabbables(panel: HTMLElement): HTMLElement[] {
  return [...panel.querySelectorAll<HTMLElement>(TAB_TRAP_SELECTOR)].filter(
    (el) => isRendered(el) && !el.matches(':disabled') && !el.closest('[inert]'),
  )
}

/** Wraps Tab and Shift+Tab at the panel's ends. Focus on the panel itself
 *  counts as before the first control, so Shift+Tab from there wraps too.
 *  Anything in between is left to the browser. */
export function trapTab(event: KeyboardEvent, panel: HTMLElement | null): void {
  if (!panel) return
  const focusable = tabbables(panel)
  const active = document.activeElement
  if (focusable.length === 0) {
    // Nothing to land on, so stay on the panel rather than leak out.
    event.preventDefault()
    panel.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const onPanel = active === panel
  if (event.shiftKey && (active === first || onPanel)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || onPanel)) {
    event.preventDefault()
    first.focus()
  }
}
