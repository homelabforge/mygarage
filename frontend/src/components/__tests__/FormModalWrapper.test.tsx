import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { Settings } from 'lucide-react'
import FormModalWrapper from '../FormModalWrapper'

describe('FormModalWrapper (Drawer-backed)', () => {
  it('renders a labelled dialog, applies the width, keeps a translated close, and lifts the footer', () => {
    render(
      <FormModalWrapper
        title="Edit thing"
        onClose={vi.fn()}
        width="sm"
        icon={Settings}
        footer={<button type="submit" form="x">Save</button>}
      >
        <form id="x">body</form>
      </FormModalWrapper>
    )
    const dialog = screen.getByRole('dialog', { name: 'Edit thing' })
    expect(dialog).toHaveClass('w-[min(540px,96vw)]')
    expect(screen.getByLabelText('common:close')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('renders nothing while isOpen is false', () => {
    render(
      <FormModalWrapper title="Edit thing" onClose={vi.fn()} isOpen={false}>
        <div>body</div>
      </FormModalWrapper>
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
