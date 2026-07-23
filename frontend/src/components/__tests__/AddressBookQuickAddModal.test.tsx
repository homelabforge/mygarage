import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import AddressBookQuickAddModal from '../AddressBookQuickAddModal'

describe('AddressBookQuickAddModal (Drawer-backed)', () => {
  it('renders a labelled nested dialog with the footer Add action', () => {
    render(
      <AddressBookQuickAddModal isOpen nested onClose={vi.fn()} onAdded={vi.fn()} title="Add station" />,
    )
    const dialog = screen.getByRole('dialog', { name: 'Add station' })
    expect(dialog).toHaveClass('z-drawer-nested') // nested -> +10 panel token, mirrors the Drawer nested test
    expect(screen.getByRole('button', { name: 'addressBookQuickAdd.add' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'addressBookQuickAdd.add' })).toHaveAttribute(
      'form',
      'ab-quick-add-form',
    )
    expect(screen.getByRole('dialog').querySelector('#ab-quick-add-form')).toBeInTheDocument()
  })
})
