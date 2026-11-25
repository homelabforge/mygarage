import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Note } from '../../types/note'

const useNotesMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useNotes', () => ({
  useNotes: () => useNotesMock(),
  useDeleteNote: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import NoteList from '../NoteList'
import { answerConfirm } from '../../__tests__/confirmHelpers'

const note = {
  id: 5, vin: 'V1', date: '2026-01-01', title: 'Road trip', content: 'Drove to the coast',
  created_at: '2026-01-01T00:00:00Z', updated_at: null,
} as unknown as Note

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }

beforeEach(() => {
  vi.clearAllMocks()
  useNotesMock.mockReturnValue({ data: { notes: [note] }, isLoading: false, error: null })
})

describe('NoteList — rendering + row actions', () => {
  it('renders the note title and content (fails if a field is dropped or the list never renders the fetched notes)', () => {
    render(<NoteList {...PROPS} />)
    expect(screen.getByText('Road trip')).toBeInTheDocument()
    expect(screen.getByText('Drove to the coast')).toBeInTheDocument()
  })

  it('clicking Edit calls onEditClick with the FULL note (fails if edit is unwired or passes a partial record)', () => {
    render(<NoteList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledTimes(1)
    expect(onEditClick.mock.calls[0][0]).toBe(note)   // object IDENTITY — the WHOLE note ref, not a clone or objectContaining({id})
  })

  it('clicking Delete (confirm accepted) calls the delete mutation with the exact id + a single-onError options object (fails if delete is unwired, the confirm gate is dropped, the wrong id is passed, or the mutation options shape drifts)', async () => {
    render(<NoteList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'noteList.confirmDelete')
    // COMPLETE two-arg call: id 5 AND exactly { onError: <fn> } (no extra args/keys) — never expect.anything()
    expect(deleteMutate.mock.calls[0]).toStrictEqual([5, { onError: expect.any(Function) }])
  })

  it('clicking Delete with confirm REJECTED does NOT call the mutation (fails if the confirm gate is bypassed)', async () => {
    render(<NoteList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'noteList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the row Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if either regresses to a title-only <button>)', () => {
    render(<NoteList {...PROPS} />)
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('the header Add button fires onAddClick (fails if the header CTA is unwired)', () => {
    render(<NoteList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'noteList.addNote' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('NoteList — empty state', () => {
  it('with zero notes, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the empty title changes)', () => {
    useNotesMock.mockReturnValue({ data: { notes: [] }, isLoading: false, error: null })
    render(<NoteList {...PROPS} />)
    expect(screen.getByText('noteList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'noteList.addFirstNote' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})
