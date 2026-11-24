import { useSyncExternalStore } from 'react'
import { FOCUSABLE_SELECTOR, isRendered } from './focusTrap'

/**
 * One stack for every Drawer and Dialog. It owns the scroll lock, background
 * inert, Escape and Tab, so a Dialog over a Drawer can't restore stale
 * overflow or inert, and one Esc closes one layer.
 */
export interface ModalLayer {
  kind: 'drawer' | 'dialog'
  /** A nested drawer outranks a plain one. */
  nested?: boolean
  /** This layer's direct children of body. */
  nodes: () => Element[]
  onEscape: () => void
  onTab: (event: KeyboardEvent) => void
  /** document.activeElement at push time. */
  restoreTo: HTMLElement | null
}

const stack: ModalLayer[] = []
let savedOverflow = ''
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

function rank(layer: ModalLayer): number {
  if (layer.kind === 'dialog') return 3
  return layer.nested ? 2 : 1
}

// Top goes by rank, not push order. React runs child effects before parent
// effects in one commit, so a parent drawer and a nested one mounting open
// together push child-first. Ties go to the later push.
function topLayer(): ModalLayer | undefined {
  let top: ModalLayer | undefined
  for (const layer of stack) {
    if (!top || rank(layer) >= rank(top)) top = layer
  }
  return top
}

export function isTopLayer(layer: ModalLayer): boolean {
  return topLayer() === layer
}

/**
 * #root goes inert + aria-hidden while anything is open, and every layer
 * under the top goes inert. aria-hidden on layer nodes is never touched: the
 * Drawer backdrop carries a static one. Drawer calls this again once its
 * nodes exist, since a stay-mounted Drawer renders null on the render that opens it.
 */
export function syncInert(): void {
  const root = document.getElementById('root')
  const top = topLayer()
  if (root) {
    if (top) {
      root.setAttribute('inert', '')
      root.setAttribute('aria-hidden', 'true')
    } else {
      root.removeAttribute('inert')
      root.removeAttribute('aria-hidden')
    }
  }
  for (const layer of stack) {
    for (const node of layer.nodes()) node.toggleAttribute('inert', layer !== top)
  }
}

// Bubble phase on window, so anything inside that already handled the key
// (preventDefault, or a React stopPropagation at the portal) wins.
function onKeyDown(event: KeyboardEvent): void {
  if (event.defaultPrevented) return
  const top = topLayer()
  if (!top) return
  if (event.key === 'Escape') top.onEscape()
  else if (event.key === 'Tab') top.onTab(event)
}

function focusFirstIn(layer: ModalLayer): void {
  const nodes = layer.nodes()
  const found = nodes
    .flatMap((node) => [...node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)])
    .find(isRendered)
  if (found) {
    found.focus()
    return
  }
  // Nothing to focus inside, so the panel itself (it carries tabindex=-1).
  const panel = nodes.find((node): node is HTMLElement => node instanceof HTMLElement && node.hasAttribute('tabindex'))
  panel?.focus()
}

function restoreFocus(released: ModalLayer): void {
  const target = released.restoreTo
  if (target && target.isConnected && !target.closest('[inert]')) {
    target.focus()
    return
  }
  const top = topLayer()
  if (top) focusFirstIn(top)
}

/** Registers an open layer. Call the returned release on close or unmount. */
export function pushLayer(layer: ModalLayer): () => void {
  if (stack.length === 0) {
    savedOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeyDown)
  }
  stack.push(layer)
  syncInert()
  emit()

  let released = false
  return () => {
    if (released) return
    released = true
    const wasTop = isTopLayer(layer)
    stack.splice(stack.indexOf(layer), 1)
    if (stack.length === 0) {
      document.body.style.overflow = savedOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
    syncInert()
    emit()
    // A layer released from under the top leaves focus alone.
    if (wasTop) restoreFocus(layer)
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function anyDrawerOpen(): boolean {
  return stack.some((layer) => layer.kind === 'drawer')
}

/** Drawers only, nested ones included. AppToaster moves out of their way. */
export function useAnyDrawerOpen(): boolean {
  return useSyncExternalStore(subscribe, anyDrawerOpen)
}
