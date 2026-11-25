import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import CardHeader from '../CardHeader'
import type { IconType } from '../types'

// A bare svg has no aria-hidden default of its own (lucide does), so whatever
// lands on it came from CardHeader.
const BareIcon: IconType = (props) => <svg data-testid="icon" {...props} />

const before = (a: Element, b: Element): boolean =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

describe('CardHeader leading layout', () => {
  it('puts the icon before the title', () => {
    render(<CardHeader title="LLM Features" icon={BareIcon} iconPosition="leading" />)
    const icon = screen.getByTestId('icon')
    const heading = screen.getByRole('heading', { name: 'LLM Features' })
    expect(before(icon, heading)).toBe(true)
  })

  it('renders the description right under the title', () => {
    render(
      <CardHeader title="LLM Features" description="Opt-in helpers" icon={BareIcon} iconPosition="leading" />,
    )
    const heading = screen.getByRole('heading', { name: 'LLM Features' })
    const desc = screen.getByText('Opt-in helpers')
    expect(desc.tagName).toBe('P')
    expect(heading.nextElementSibling).toBe(desc)
  })

  it('marks the leading icon aria-hidden itself', () => {
    // Go through the leading slot, or the old trailing icon would pass this too.
    const { container } = render(<CardHeader title="X" icon={BareIcon} iconPosition="leading" />)
    const slot = container.querySelector('header > div > svg')
    expect(slot).toBe(screen.getByTestId('icon'))
    expect(slot).toHaveAttribute('aria-hidden', 'true')
  })

  it('renders exactly the markup IntegrationCard used to hand-roll', () => {
    // Settings > Integrations looked like this before the move, so pin it byte for byte.
    const { container } = render(
      <CardHeader
        title="CarComplaints"
        description="Links to consumer complaint data."
        icon={BareIcon}
        iconPosition="leading"
        actions={<button type="button">About</button>}
      />,
    )
    expect(container.innerHTML).toBe(
      '<header class="mb-4 flex items-start justify-between gap-4">' +
        '<div class="flex items-start gap-3">' +
        '<svg data-testid="icon" aria-hidden="true" class="mt-0.5 h-5 w-5 shrink-0 text-(--accent-fg)"></svg>' +
        '<div>' +
        '<h3 class="text-[15px] font-bold tracking-[-.02em] text-text">CarComplaints</h3>' +
        '<p class="mt-0.5 text-sm text-text-mute">Links to consumer complaint data.</p>' +
        '</div>' +
        '</div>' +
        '<button type="button">About</button>' +
        '</header>',
    )
  })
})

describe('CardHeader trailing layout (the default)', () => {
  it('keeps the icon after the actions when no position is given', () => {
    render(<CardHeader title="Costs" icon={BareIcon} actions={<button type="button">Edit</button>} />)
    const icon = screen.getByTestId('icon')
    const action = screen.getByRole('button', { name: 'Edit' })
    const heading = screen.getByRole('heading', { name: 'Costs' })
    expect(before(heading, action)).toBe(true)
    expect(before(action, icon)).toBe(true)
  })

  it('puts a description under the title with the icon still on the right', () => {
    render(<CardHeader title="Costs" description="This year" icon={BareIcon} />)
    const heading = screen.getByRole('heading', { name: 'Costs' })
    const desc = screen.getByText('This year')
    expect(heading.nextElementSibling).toBe(desc)
    expect(before(desc, screen.getByTestId('icon'))).toBe(true)
  })

  it('renders the same markup the ~18 existing callers already get', () => {
    // Every current caller is title-only or title + icon. This is the
    // pre-change output, so the new props can't leak into the old look.
    const { container } = render(
      <CardHeader title="Costs" icon={BareIcon} actions={<button type="button">Edit</button>} />,
    )
    expect(container.innerHTML).toBe(
      '<div class="mb-3 flex items-center justify-between gap-3">' +
        '<h3 class="text-[15px] font-bold tracking-[-.02em] text-text">Costs</h3>' +
        '<div class="flex items-center gap-2">' +
        '<button type="button">Edit</button>' +
        '<svg data-testid="icon" aria-hidden="true" class="h-5 w-5 text-(--accent-fg)"></svg>' +
        '</div>' +
        '</div>',
    )

    const { container: bare } = render(<CardHeader title="Basic Information" />)
    expect(bare.innerHTML).toBe(
      '<div class="mb-3 flex items-center justify-between gap-3">' +
        '<h3 class="text-[15px] font-bold tracking-[-.02em] text-text">Basic Information</h3>' +
        '<div class="flex items-center gap-2"></div>' +
        '</div>',
    )
  })
})
