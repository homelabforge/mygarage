/**
 * Test helpers for useConfirm callers. withConfirm is a render wrapper for
 * tests that skip test-utils; answerConfirm answers the open confirm and
 * fails loudly when there isn't one, so a test can't pass by never asking.
 */
import { createElement, type ReactElement, type ReactNode } from 'react'
import { expect } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { ConfirmProvider } from '../components/ui/ConfirmDialog'

export function withConfirm({ children }: { children: ReactNode }): ReactElement {
  return createElement(ConfirmProvider, null, children)
}

/** Clicks Cancel or the confirm button on the open confirm, then waits for it to close. */
export async function answerConfirm(choice: 'confirm' | 'cancel', name?: RegExp | string): Promise<void> {
  const dialog = await screen.findByRole('alertdialog')
  if (name !== undefined) expect(dialog).toHaveAccessibleName(name)
  const buttons = within(dialog).getAllByRole('button')
  const cancel = buttons.filter((button) => button.hasAttribute('data-dialog-cancel'))
  const confirm = buttons.filter((button) => !button.hasAttribute('data-dialog-cancel'))
  expect(cancel, 'confirm dialog has no single Cancel').toHaveLength(1)
  expect(confirm, 'confirm dialog has no single confirm button').toHaveLength(1)
  fireEvent.click(choice === 'cancel' ? cancel[0] : confirm[0])
  await waitFor(() => expect(dialog).not.toBeInTheDocument())
}
