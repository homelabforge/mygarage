import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '../../__tests__/test-utils'
import { fireEvent, within } from '@testing-library/react'
import type { TollTag } from '../../types/toll'

const useTollTagsMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useTollRecords', () => ({
  useTollTags: () => useTollTagsMock(),
  useDeleteTollTag: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import TollTagList from '../TollTagList'

const activeTag = {
  id: 1, toll_system: 'E-ZPass', tag_number: '0012345678', status: 'active', notes: 'daily commute',
} as unknown as TollTag
const inactiveTag = { ...activeTag, id: 2, tag_number: '0099999999', status: 'inactive' } as unknown as TollTag

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  useTollTagsMock.mockReturnValue({ data: { toll_tags: [activeTag] }, isLoading: false, error: null })
})

describe('TollTagList — rendering + row actions', () => {
  it('renders the toll system + the tag number (fails if the header content or the mono tag number is dropped)', () => {
    render(<TollTagList {...PROPS} />)
    expect(screen.getByText('E-ZPass')).toBeInTheDocument()
    expect(screen.getByText('0012345678')).toBeInTheDocument()
  })

  it('clicking row Edit calls onEditClick with THE WHOLE tag (fails if edit is unwired, passes the wrong row, or a truncated object)', () => {
    render(<TollTagList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(activeTag)
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the tag id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<TollTagList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('clicking row Delete with confirm REJECTED does NOT call the delete mutation (B4 — fails if the handler ignores a false confirm and deletes anyway)', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<TollTagList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the row Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if IconButton regresses to a title-only <button>)', () => {
    render(<TollTagList {...PROPS} />)
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('each tag is an article named by its toll system, holding its own Edit (the e2e finds the card this way)', () => {
    render(<TollTagList {...PROPS} />)
    const card = screen.getByRole('article', { name: 'E-ZPass' })
    fireEvent.click(within(card).getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(activeTag)
  })
})

describe('TollTagList — status (both ways) + empty state', () => {
  it('an active tag shows the Active status label (fails if the active status marker stops rendering)', () => {
    render(<TollTagList {...PROPS} />)
    expect(screen.getByText('tollStatuses.active')).toBeInTheDocument()
  })

  it('an inactive tag shows the Inactive status label, not Active (fails if the status is hardcoded to one value or inverted)', () => {
    useTollTagsMock.mockReturnValue({ data: { toll_tags: [inactiveTag] }, isLoading: false, error: null })
    render(<TollTagList {...PROPS} />)
    expect(screen.getByText('tollStatuses.inactive')).toBeInTheDocument()
    expect(screen.queryByText('tollStatuses.active')).not.toBeInTheDocument()
  })

  it('with zero tags, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useTollTagsMock.mockReturnValue({ data: { toll_tags: [] }, isLoading: false, error: null })
    render(<TollTagList {...PROPS} />)
    expect(screen.getByText('tollTagList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'tollTagList.addFirstTollTag' }))
    expect(onAddClick).toHaveBeenCalled()
  })

  // B9: the status TONE is the LOCKED off-accent §4.3 decision (active→success / inactive→muted). jsdom runs
  // no CSS, so tone is not a rendered-style assertion (no toHaveClass, G6); pin the exact conditional at the
  // SOURCE — an inverted mapping ('muted' : 'success') or an accent/info/warning/danger tone fails this.
  it('the status Chip tone is the locked active→success / inactive→muted conditional (fails if inverted or accent-derived)', () => {
    const src = readFileSync(resolve(__dirname, '../TollTagList.tsx'), 'utf8')
    expect(src).toMatch(/tone=\{tag\.status === 'active' \? 'success' : 'muted'\}/)
  })
})
