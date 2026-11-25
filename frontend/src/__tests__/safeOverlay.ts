/**
 * The old centred modals (#305) pad their overlay with the shared
 * `modal-safe-pad` utility and cap the box at min(their old vh cap, 100%), so
 * desktop keeps its height and a phone's box stays inside the safe area. jsdom
 * has no layout, so this checks the classes; what they compute to is measured
 * once, in e2e/safe-area.spec.ts.
 */
import { expect } from 'vitest'

function expectPaddedOverlay(overlay: Element | null, box: Element | null, cap: '80vh' | '90vh'): void {
  expect(overlay).toHaveClass('modal-safe-pad')
  // A leftover p-4 would fight the utility's padding.
  expect(overlay!.className).not.toMatch(/(^|\s)p-4(\s|$)/)
  // The desktop cap it always had, but never past the padded box.
  expect(box).toHaveClass(`max-h-[min(${cap},100%)]`)
  expect(box!.className).not.toMatch(/(^|\s)max-h-(full|\[\d+vh\])(\s|$)/)
}

/** Pass the dialog itself (getByRole('dialog')); its parent is the overlay. */
export function expectSafeOverlay(dialog: Element, cap: '80vh' | '90vh' = '90vh'): void {
  expect(dialog, 'pass the role=dialog panel, not something inside it').toHaveAttribute('role', 'dialog')
  expectPaddedOverlay(dialog.parentElement, dialog, cap)
}
