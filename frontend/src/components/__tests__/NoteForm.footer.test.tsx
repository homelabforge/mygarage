import { describe, it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import NoteForm from '../NoteForm'

describe('NoteForm — footer submit association', () => {
  it('clicking the footer Create (outside the <form>) triggers the form submit', async () => {
    render(<NoteForm vin="TEST12345678901234" onClose={vi.fn()} onSuccess={vi.fn()} />)
    // Create is in the sticky footer, a sibling of the <form>, wired via form="note-form".
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    // content is required; the message only renders because the submit fired.
    expect(await screen.findByText('common:validation.note.contentRequired')).toBeInTheDocument()
  })
})
