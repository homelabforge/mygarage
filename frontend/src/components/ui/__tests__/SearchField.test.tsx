import type { SVGProps } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import SearchField from '../SearchField'

// lucide's <Search> supplies its own aria-hidden="true" default
// (`!children && !hasA11yProp(rest)`) whenever no a11y prop is present, so a
// test asserting on the rendered attribute cannot tell "SearchField set
// this" from "lucide defaulted it" — SearchField's explicit aria-hidden
// could be deleted and the assertion below would still pass. The icon isn't
// an injectable prop here (SearchField always renders lucide's own `Search`
// internally), so the usual fix — substitute a bare, non-lucide icon and
// prove the component sets the attribute itself — doesn't apply. Mocking
// the module instead isolates SearchField's own choice to pass aria-hidden
// from lucide's internal default. Nothing else in this codebase mocks
// lucide-react yet; this establishes the pattern.
vi.mock('lucide-react', () => ({
  Search: (props: SVGProps<SVGSVGElement>) => <svg data-testid="mock-search" {...props} />,
}))

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

  // `Input` puts its own `className` on the `<input>` element alongside its
  // unconditional `w-full` — same specificity, and `.w-full` is declared
  // later in the compiled stylesheet than any `w-<n>` utility, so it always
  // wins. A width class forwarded into Input's className slot is silently
  // defeated. SearchField must apply the caller's className to its own
  // outer wrapper instead, where nothing competes with it.
  it('applies a width className to an outer wrapper, not the input (avoids the w-full specificity trap)', () => {
    const { container } = render(
      <SearchField value="" onChange={() => {}} label="Search" className="w-64" />,
    )
    const input = screen.getByRole('searchbox')
    expect(input.className.split(' ')).not.toContain('w-64')
    expect(input.className.split(' ')).toContain('w-full')
    const wrapper = container.firstElementChild
    expect(wrapper).not.toBeNull()
    expect(wrapper).not.toBe(input)
    expect(wrapper?.className.split(' ')).toContain('w-64')
  })

  // Same assertion shape as Gallery.tsx's own two demo instances
  // (`className="w-64"` and `className="w-48"`), which is exactly what
  // demonstrated the bug live before this fix.
  it('gallery-demo widths land on the wrapper, matching Gallery.tsx call sites', () => {
    const wide = render(
      <SearchField value="" onChange={() => {}} label="Search contacts" className="w-64" />,
    )
    expect(wide.container.firstElementChild?.className.split(' ')).toContain('w-64')

    const narrow = render(
      <SearchField value="ram" onChange={() => {}} label="Search" size="sm" className="w-48" />,
    )
    expect(narrow.container.firstElementChild?.className.split(' ')).toContain('w-48')
  })

  // Discriminates against SearchField's own aria-hidden, not lucide's
  // default, because `Search` above is the mock — it only has aria-hidden if
  // SearchField's <Search aria-hidden="true" .../> call put it there.
  // Proven by sabotage: deleting that prop from SearchField.tsx fails this
  // test (and only this test); restoring it turns the suite green again. See
  // the task-17 report for the sabotage transcript.
  it('hides the decorative icon', () => {
    const { container } = render(<SearchField value="" onChange={() => {}} label="Search" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
