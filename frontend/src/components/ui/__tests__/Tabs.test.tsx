import { describe, it, expect, vi } from 'vitest'
import type { SVGProps } from 'react'
import { Fuel } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Tabs from '../Tabs'

const ITEMS = [
  { id: 'overview', label: 'Overview' },
  { id: 'fuel', label: 'Fuel', icon: Fuel, count: 29 },
  { id: 'hidden', label: 'Hidden', visible: false },
]

describe('Tabs', () => {
  it('renders exactly one tablist with the given accessible name', () => {
    render(<Tabs items={ITEMS} activeId="overview" onChange={() => {}} label="Vehicle sections" />)
    expect(screen.getAllByRole('tablist')).toHaveLength(1)
    expect(screen.getByRole('tablist', { name: 'Vehicle sections' })).toBeInTheDocument()
  })

  it('computes each tab name exactly once', () => {
    // SubTabNav renders the label in two spans (one sm:inline, one sr-only),
    // which jsdom concatenates into "FuelFuel". Render it once.
    render(<Tabs items={ITEMS} activeId="overview" onChange={() => {}} label="Sections" />)
    expect(screen.getByRole('tab', { name: 'Fuel' })).toBeInTheDocument()
  })

  it('marks the active tab', () => {
    render(<Tabs items={ITEMS} activeId="fuel" onChange={() => {}} label="Sections" />)
    expect(screen.getByRole('tab', { name: 'Fuel' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'false')
  })

  it('omits tabs marked not visible', () => {
    render(<Tabs items={ITEMS} activeId="overview" onChange={() => {}} label="Sections" />)
    expect(screen.queryByRole('tab', { name: 'Hidden' })).not.toBeInTheDocument()
  })

  it('reports selection', () => {
    const onChange = vi.fn()
    render(<Tabs items={ITEMS} activeId="overview" onChange={onChange} label="Sections" />)
    fireEvent.click(screen.getByRole('tab', { name: 'Fuel' }))
    expect(onChange).toHaveBeenCalledWith('fuel')
  })

  it('keeps a count out of the accessible name', () => {
    // Design §4.8: count pills are aria-hidden so the name stays the label.
    // Mono (which Badge's count renders through) is a plain <span> with no
    // aria attributes of its own — if the count weren't wrapped in an
    // aria-hidden node here, "29" would concatenate into the computed name.
    render(<Tabs items={ITEMS} activeId="overview" onChange={() => {}} label="Sections" />)
    const tab = screen.getByRole('tab', { name: 'Fuel' })
    expect(tab).toHaveAccessibleName('Fuel')
  })

  it('keeps a status dot aria-hidden so it never enters the accessible name', () => {
    // Same constraint as the count pill, for the online/enabled dot used by
    // the pill variant (e.g. NotificationSubTabs' service status marker).
    render(
      <Tabs
        items={[{ id: 'discord', label: 'Discord', dot: true }]}
        activeId="discord"
        onChange={() => {}}
        label="Channels"
        variant="pill"
      />,
    )
    const tab = screen.getByRole('tab', { name: 'Discord' })
    expect(tab).toHaveAccessibleName('Discord')
    expect(tab.querySelector('[aria-hidden="true"]')).not.toBeNull()
  })

  it('makes the label the direct text of the clickable element', () => {
    // SettingsSystemTab.test.tsx:142 does findByText('auth.local').click().
    render(
      <Tabs
        items={[{ id: 'local', label: 'auth.local' }]}
        activeId="local"
        onChange={() => {}}
        label="Auth mode"
        variant="segmented"
      />,
    )
    expect(screen.getByText('auth.local').closest('button')).toBeInTheDocument()
  })

  it('moves selection with arrow keys', () => {
    const onChange = vi.fn()
    render(<Tabs items={ITEMS} activeId="overview" onChange={onChange} label="Sections" />)
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Overview' }), { key: 'ArrowRight' })
    expect(onChange).toHaveBeenCalledWith('fuel')
  })

  it('carries a stable test id', () => {
    render(<Tabs items={ITEMS} activeId="overview" onChange={() => {}} label="Sections" />)
    expect(screen.getByTestId('tabs')).toBeInTheDocument()
  })

  // lucide-react sets aria-hidden="true" on its own <svg> whenever it is
  // rendered without children or another a11y prop, so a test that renders
  // Fuel and checks aria-hidden would pass whether or not Tabs sets the
  // attribute itself — it would be checking the library, not this component.
  // This uses a bare SVG with no such default to make the assertion real.
  it('sets aria-hidden on the icon itself, not just by virtue of it being a lucide icon', () => {
    const BareIcon = (props: SVGProps<SVGSVGElement>) => <svg data-testid="bare-icon" {...props} />
    render(
      <Tabs
        items={[{ id: 'fuel', label: 'Fuel', icon: BareIcon }]}
        activeId="fuel"
        onChange={() => {}}
        label="Sections"
      />,
    )
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
