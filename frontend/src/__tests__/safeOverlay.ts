/**
 * The old centred modals (#305) pad their overlay with the shared
 * `modal-safe-pad` utility and let the box fill it, so the box centres inside
 * the iPhone safe area. jsdom has no layout, so this checks the classes; what
 * the utility computes to is measured once, in e2e/safe-area.spec.ts.
 */
import { expect } from 'vitest'

/** Pass any element inside the modal; checks its overlay and the box under it. */
export function expectSafeOverlay(inside: Element): void {
  const overlay = inside.closest('.fixed.inset-0')
  expect(overlay, 'no fixed inset-0 overlay above this element').not.toBeNull()
  expect(overlay).toHaveClass('modal-safe-pad')
  // A leftover p-4 would fight the utility's padding.
  expect(overlay!.className).not.toMatch(/(^|\s)p-4(\s|$)/)
  const box = overlay!.firstElementChild
  expect(box).toHaveClass('max-h-full')
  expect(box!.className).not.toMatch(/max-h-\[\d+vh\]/)
}
