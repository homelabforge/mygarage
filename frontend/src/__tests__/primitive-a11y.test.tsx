import { describe, it, expect } from 'vitest'
import { Box, Trash2, Wrench } from 'lucide-react'
import { render, screen, fireEvent } from './test-utils'
import {
  Avatar, Badge, Button, Card, CardHeader, Checkbox, Chip, DataTable, Drawer,
  Dropdown, EmptyState, Field, IconButton, Input, ListRow, Mono, PageContainer,
  PageHeader, SearchField, Select, ShareBar, Stepper, Tabs, Textarea, Tile,
  Toggle,
} from '../components/ui'

describe('primitive semantics', () => {
  it('every interactive primitive renders a real focusable control', () => {
    render(
      <>
        <Button>Save</Button>
        <IconButton icon={Trash2} label="Delete" />
        <Toggle label="Alerts" checked={false} onChange={() => {}} />
        <Checkbox id="c1" label="JPG" />
        <Chip onClick={() => {}}>Filter</Chip>
        <Card interactive onClick={() => {}}>Card</Card>
      </>,
    )
    // Six controls, each reachable by role — no div-with-onClick anywhere —
    // AND each still in the tab order. Role + accessible name alone would
    // still pass a real <button> that also carries tabIndex={-1}: it keeps
    // its role and its name, but a keyboard user can never reach it. The
    // `not.toHaveAttribute('tabindex', '-1')` half of each pair is what
    // catches that regression; today's primitives are native
    // <button>/<input>, which carry no explicit tabindex at all, so this
    // passes cleanly (sabotage-proofed in p1-fix-m1-m4-report.md).
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeInTheDocument()
    expect(save).not.toHaveAttribute('tabindex', '-1')

    const deleteBtn = screen.getByRole('button', { name: 'Delete' })
    expect(deleteBtn).toBeInTheDocument()
    expect(deleteBtn).not.toHaveAttribute('tabindex', '-1')

    const alertsToggle = screen.getByRole('checkbox', { name: 'Alerts' })
    expect(alertsToggle).toBeInTheDocument()
    expect(alertsToggle).not.toHaveAttribute('tabindex', '-1')

    const jpgCheckbox = screen.getByRole('checkbox', { name: 'JPG' })
    expect(jpgCheckbox).toBeInTheDocument()
    expect(jpgCheckbox).not.toHaveAttribute('tabindex', '-1')

    const filterChip = screen.getByRole('button', { name: 'Filter' })
    expect(filterChip).toBeInTheDocument()
    expect(filterChip).not.toHaveAttribute('tabindex', '-1')

    const card = screen.getByRole('button', { name: 'Card' })
    expect(card).toBeInTheDocument()
    expect(card).not.toHaveAttribute('tabindex', '-1')
  })

  it('disabled controls are genuinely disabled, not just faded', () => {
    render(<Button disabled>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('Drawer moves focus into the dialog on open and unmounts after its close transition', () => {
    // The Drawer deliberately stays mounted through its exit transition and
    // unmounts on the panel's transitionend (Drawer.tsx "Finding 2"; setup.ts
    // mocks matchMedia matches:false, so the reduced-motion synchronous path
    // is NOT taken here). Assert the close the same way Drawer.test.tsx does —
    // grab the panel while open, rerender closed, fire its transitionEnd.
    const { rerender } = render(
      <>
        <button>outside</button>
        <Drawer open onClose={() => {}} title="Add Fuel">
          <input aria-label="Litres" />
        </Drawer>
      </>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    rerender(
      <>
        <button>outside</button>
        <Drawer open={false} onClose={() => {}} title="Add Fuel">
          <input aria-label="Litres" />
        </Drawer>
      </>,
    )
    // Still mounted mid-transition, then gone once the panel's transitionend fires.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.transitionEnd(dialog)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Tabs exposes exactly one tablist and roving tabindex', () => {
    render(
      <Tabs
        label="Sections"
        activeId="a"
        onChange={() => {}}
        items={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]}
      />,
    )
    expect(screen.getAllByRole('tablist')).toHaveLength(1)
    expect(screen.getByRole('tab', { name: 'A' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: 'B' })).toHaveAttribute('tabindex', '-1')
  })

  it('count pills stay out of accessible names', () => {
    render(
      <Tabs
        label="Sections"
        activeId="fuel"
        onChange={() => {}}
        items={[{ id: 'fuel', label: 'Fuel', count: 29 }]}
      />,
    )
    expect(screen.getByRole('tab', { name: 'Fuel' })).toHaveAccessibleName('Fuel')
  })

  it('no primitive emits a raw palette colour class', () => {
    // Every colour must route through a token so all six accents and both
    // themes work. This is the P0 lesson applied to the new library.
    //
    // Renders EVERY primitive in the barrel, and each of the toned ones in a
    // status tone, because the earlier three-component version was vacuous:
    // it never rendered a Badge, so Badge's status foregrounds were invisible
    // to it, and the trailing -\d{2,3} in the regex means a bare text-white
    // would slip through even if it had.
    render(
      <>
        <Mono tone="danger">1,234.56</Mono>
        <Badge tone="danger" count={2} />
        <Badge tone="success">Active</Badge>
        <Badge tone="warning">Due</Badge>
        <Badge tone="info">Info</Badge>
        <Chip tone="danger">Overdue</Chip>
        <Avatar name="Jamey Starett" />
        <EmptyState icon={Box} title="Empty" description="Nothing here." />
        <PageContainer><span>measure</span></PageContainer>
        <PageHeader title="My Garage" subtitle="3 vehicles" />
        <Card><CardHeader title="Basic Information" icon={Wrench} /></Card>
        <Tile icon={Wrench} label="Overdue" value={2} tone="danger" />
        <ListRow icon={Wrench} label="Last Service" value="Jun 19, 2026" />
        <Button variant="primary">Save</Button>
        <Button variant="danger">Remove</Button>
        <IconButton icon={Trash2} label="Delete" variant="danger" />
        <Field id="pa-cost" label="Cost" hint="Excluding tax." error="Required">
          <Input id="pa-cost" aria-describedby="pa-cost-hint pa-cost-error" invalid />
        </Field>
        <Textarea aria-label="Notes" />
        <Select aria-label="Fuel" options={[{ value: 'gas', label: 'Gasoline' }]} />
        <Checkbox id="pa-jpg" label="JPG" />
        <Toggle label="Alerts" checked onChange={() => {}} />
        <Toggle label="Gas Stations" checked={false} onChange={() => {}} variant="onOff" />
        <SearchField value="" onChange={() => {}} label="Search" />
        <Tabs
          label="Sections"
          activeId="fuel"
          onChange={() => {}}
          items={[{ id: 'fuel', label: 'Fuel', icon: Wrench, count: 29 }]}
        />
        <Dropdown label="Export" items={[{ id: 'csv', label: 'CSV', onSelect: () => {} }]} />
        <Drawer open onClose={() => {}} title="Add Fuel" footer={<Button>Save</Button>}>
          <Input aria-label="Litres" />
        </Drawer>
        <Stepper
          label="Progress"
          valueText="Step 2 of 3"
          current={2}
          steps={[{ number: 1, title: 'VIN' }, { number: 2, title: 'Details' }, { number: 3, title: 'Review' }]}
        />
        <DataTable
          caption="Fuel"
          rowKey={(r: { id: string }) => r.id}
          columns={[{ id: 'cost', header: 'Cost', align: 'right', mono: true, render: () => '62.40' }]}
          rows={[{ id: '1' }]}
        />
        <ShareBar label="Maintenance" value="$1,284.00" percent={42} color="#f0a53a" />
      </>,
    )
    // Scan document.body rather than the render container: Drawer portals to
    // body, and body already contains the container, so this one string
    // covers everything rendered above.
    const html = document.body.innerHTML

    // Full Tailwind palette, not a hand-picked subset: the earlier list omitted
    // teal and violet — two of THIS app's own six accent-family names
    // (constants/accents.ts) — so a primitive regressing to text-teal-500 /
    // bg-violet-600 instead of --accent-fg / --accent-soft would have passed
    // undetected, and raw text-teal-500 already exists elsewhere in the app.
    expect(html).not.toMatch(/\b(bg|text|border)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}\b/)

    // Separate assertion, separate reason. text-white and bg-white carry no
    // numeric suffix, so the ramp regex above cannot see them — and they are
    // the specific defect Task 24 exists to delete from the rest of the app.
    // On a fixed status fill they are also an AA failure in their own right:
    // white on --color-danger #f0503a is 3.55:1. Status foregrounds go
    // through --color-on-status; accent foregrounds through
    // --accent-on-solid; the toggle knob through --color-toggle-knob.
    //
    // Raw white/black on any colour-bearing utility is forbidden — text-white
    // on a solid accent/status fill is a Task-24-class AA failure, and there
    // is no token for it to route through. The ONE sanctioned exception is
    // Drawer's dimming scrim (bg-black/50 = rgba(0,0,0,.5)), which is a
    // dimming layer, not a colour role. Everything else — bg-white,
    // text-white/80, border-black, any opacity suffix — fails. (An earlier
    // version of this assertion, `/\b(bg|text)-(white|black)\b(?!\/)/`, both
    // permitted ANY slash-suffix — not just the one sanctioned scrim — and
    // omitted `border` from the alternation entirely, so `border-white` was
    // invisible to it. Confirmed empirically; see p1-final-review.md M2.)
    const SANCTIONED_SCRIM = 'bg-black/50'
    const rawBW = (html.match(/\b(?:bg|text|border)-(?:white|black)(?:\/\d+)?\b/g) ?? [])
      .filter((cls) => cls !== SANCTIONED_SCRIM)
    expect(rawBW).toEqual([])
  })
})
