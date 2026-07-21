import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import SearchField from '../SearchField'

describe('SearchField', () => {
  it('renders a searchbox with an accessible name', () => {
    render(<SearchField value="" onChange={() => {}} label="Search contacts" />)
    expect(screen.getByRole('searchbox', { name: 'Search contacts' })).toBeInTheDocument()
  })

  it('reports typed input', () => {
    const onChange = vi.fn()
    render(<SearchField value="" onChange={onChange} label="Search" />)
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'ram' } })
    expect(onChange).toHaveBeenCalledWith('ram')
  })

  it('forwards the placeholder', () => {
    render(<SearchField value="" onChange={() => {}} label="Search" placeholder="Find a shop" />)
    expect(screen.getByPlaceholderText('Find a shop')).toBeInTheDocument()
  })

  // NOTE on discrimination (see standing instructions, "lucide-react
  // aria-hidden trap"): the icon here is not an injectable prop — SearchField
  // always renders lucide's <Search>, never a caller-supplied component — so
  // the usual fix (substitute a bare, non-lucide icon and prove the
  // component sets the attribute itself) does not apply: there is nothing to
  // substitute. Confirmed by sabotage: deleting the explicit
  // aria-hidden="true" from SearchField.tsx's <Search> element leaves this
  // test GREEN, because lucide's own default (`!children &&
  // !hasA11yProp(rest)`) still supplies aria-hidden="true" with nothing else
  // changed. What this test actually guards is coarser: that the icon is
  // still rendered at all (an svg exists to assert on) and that no future
  // change accidentally adds a conflicting a11y prop (e.g. aria-label) that
  // would suppress lucide's default and expose the glyph to assistive tech —
  // deleting the whole prefix/icon does fail this test. See the task-17
  // report for the sabotage transcript.
  it('hides the decorative icon', () => {
    const { container } = render(<SearchField value="" onChange={() => {}} label="Search" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
