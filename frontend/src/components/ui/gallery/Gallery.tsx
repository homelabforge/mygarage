import { useState } from 'react'
import { Box, Fuel, Pencil, Plus, Trash2, Wrench, X } from 'lucide-react'
import Section from './Section'
// Import through the barrel, never from a component file directly: this single
// specifier is the only thing that puts ../index.ts — and, through it,
// ../types.ts — on the graph validate-reachability walks from main.tsx.
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  Chip,
  DataTable,
  Drawer,
  Dropdown,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListRow,
  Mono,
  PageContainer,
  PageHeader,
  SearchField,
  Select,
  Stepper,
  Tabs,
  Textarea,
  Tile,
  Toggle,
  type Size,
} from '..'
import { ACCENT_KEYS } from '../../../constants/accents'
import { useAccent } from '../../../contexts/AccentContext'
import { useTheme } from '../../../contexts/ThemeContext'

const SIZES: Size[] = ['sm', 'md', 'lg']

/** Static class strings — Tailwind's scanner cannot see `h-btn-${size}`. */
const HEIGHT_DEMO: Record<Size, string> = {
  sm: 'h-btn-sm leading-[34px]',
  md: 'h-btn-md leading-[38px]',
  lg: 'h-btn-lg leading-[42px]',
}

/** Shared base classes for the theme/accent toggle buttons — only the border
 *  colour differs between them, layered on top of this. */
const TOGGLE_BUTTON_BASE =
  'ui-focus-ring ui-motion h-btn-md rounded-control border px-4 text-sm'

/**
 * Dev-only review surface for the primitive library.
 *
 * Two jobs. First, it makes every primitive genuinely reachable from
 * main.tsx, which is what keeps ALLOWLIST empty (design P1 rationale).
 * Second, it is the P1 exit checkpoint: every variant, both themes, all six
 * accents, on one page.
 *
 * Mounted only under `import.meta.env.DEV` — the dynamic import in App.tsx
 * is statically eliminated from production bundles, while the reachability
 * gate (which reads import specifiers as text) still sees it.
 */
export default function Gallery() {
  const { accent, setAccent } = useAccent()
  const { theme, setTheme } = useTheme()
  // Unconsumed here by design: Task 11 (Button) and later primitive tasks
  // render `disabled={disabled}` in their gallery sections so a reviewer can
  // toggle every primitive's disabled state from this one control. Do not
  // remove as dead code.
  const [disabled, setDisabled] = useState(false)
  const [toggleOn, setToggleOn] = useState(true)
  const [searchValue, setSearchValue] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="mx-auto max-w-[1320px] px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-extrabold tracking-tight text-text">
          UI primitives
        </h1>
        <p className="mt-2 text-text-mute">
          Dev-only. Every variant, both themes, all six accents.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={`${TOGGLE_BUTTON_BASE} border-border`}
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            Theme: {theme}
          </button>

          {ACCENT_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={accent === key}
              className={`${TOGGLE_BUTTON_BASE} ${
                accent === key ? 'border-(--accent-line)' : 'border-border'
              }`}
              onClick={() => setAccent(key)}
            >
              {key}
            </button>
          ))}

          <label className="flex items-center gap-2 text-sm text-text-mute">
            <input
              type="checkbox"
              checked={disabled}
              onChange={(e) => setDisabled(e.target.checked)}
            />
            Disable all
          </label>
        </div>
      </header>

      {/* Sections are appended here as each primitive task lands. */}
      <Section title="Tokens" note="Proves the Task 1 scales generate utilities.">
        {SIZES.map((size) => (
          <div
            key={size}
            className={`rounded-control bg-surface-2 px-3 text-sm ${HEIGHT_DEMO[size]}`}
          >
            h-btn-{size}
          </div>
        ))}
      </Section>

      <Section title="Mono" note="All technical and numeric values. Tabular by default so columns align.">
        <Mono variant="vin" tone="muted" size="sm">1HGCM82633A004352</Mono>
        <Mono size="2xl" weight="bold">29.9</Mono>
        <Mono tone="danger" weight="semibold">$1,284.00</Mono>
        <Mono tone="success">+12.4%</Mono>
        <Mono tone="muted" size="sm">2026-07-21</Mono>
        <Mono tone="accent" weight="semibold">89,230 mi</Mono>
      </Section>

      <Section title="Badge" note="Status marker. Not interactive.">
        <Badge tone="danger" count={2} />
        <Badge tone="warning" icon={Wrench}>1 Upcoming</Badge>
        <Badge tone="success">Active</Badge>
        <Badge>Default</Badge>
      </Section>

      <Section title="Chip" note="Category label, or filter button with aria-pressed.">
        <Chip>Truck</Chip>
        <Chip tone="accent">Fifth Wheel</Chip>
        <Chip icon={Wrench} onClick={() => {}}>Service</Chip>
        <Chip onClick={() => {}} selected>Gas Station</Chip>
      </Section>

      <Section title="Avatar" note="Gradient tracks the accent. Accessible name is the full name.">
        <Avatar name="Jamey Starett" size="sm" />
        <Avatar name="Jamey Starett" />
        <Avatar name="Jamey Starett" size="lg" />
        <Avatar name="Wendy" />
      </Section>

      <Section title="EmptyState" note="Replaces 38 hand-rolled copies across 23 files.">
        <div className="w-full rounded-card border border-border bg-surface">
          <EmptyState
            icon={Box}
            title="No supplies yet"
            description="Track oil, filters and fluids across your vehicles."
            action={
              <button className="ui-focus-ring ui-motion h-btn-md rounded-control bg-(--accent-solid) px-4 text-sm font-semibold text-(--accent-on-solid)">
                Add Your First Supply
              </button>
            }
          />
        </div>
      </Section>

      <Section title="PageContainer / PageHeader" note="1320px measure, clamp gutters — not Tailwind container. Resize the window and watch the gutters.">
        <div className="w-full outline-1 outline-dashed outline-(--accent-line)">
          <PageContainer>
            <div className="outline-1 outline-dashed outline-border">
              <PageHeader
                title="My Garage"
                subtitle="Managing 3 vehicle(s)"
                actions={
                  <button className="ui-focus-ring ui-motion h-btn-md rounded-control bg-(--accent-solid) px-4 text-sm font-semibold text-(--accent-on-solid)">
                    Add Vehicle
                  </button>
                }
              />
            </div>
          </PageContainer>
        </div>
      </Section>

      <Section title="Card / CardHeader" note="Interactive cards are real buttons — the whole vehicle card is clickable.">
        <Card className="w-64">
          <CardHeader title="Basic Information" icon={Wrench} />
          <p className="text-sm text-text-mute">Inert card.</p>
        </Card>
        <Card interactive onClick={() => {}} className="w-64">
          <CardHeader title="2019 Mitsubishi Mirage" />
          <p className="text-sm text-text-mute">Hover me — border picks up the accent.</p>
        </Card>
      </Section>

      <Section title="Tile" note="Extracted from StatBadge. Value is always Mono.">
        <Tile icon={Wrench} label="Service" value={10} />
        <Tile icon={Wrench} label="Overdue" value={2} tone="danger" />
        <Tile icon={Wrench} label="Spent 2026" value="$1,284.00" tone="accent" />
      </Section>

      <Section title="ListRow" note="Key → mono value. The prototype carries a per-row mono flag.">
        <div className="w-80 rounded-card border border-border bg-surface p-4">
          <ListRow icon={Wrench} label="Last Service" value="Jun 19, 2026" />
          <ListRow label="Latest Odometer" value="89,230 mi" />
          <ListRow label="Type" value="Truck" mono={false} />
          <ListRow label="Docs" value="2" onClick={() => {}} />
          <ListRow
            label="Warranty"
            value="Active"
            mono={false}
            trailing={<Badge tone="accent">New</Badge>}
          />
        </div>
      </Section>

      <Section title="Button" note="Solid variant uses --accent-on-solid; text-white on amber is ~2:1. Hover: solid lifts, bordered variants move their border.">
        <Button variant="primary" icon={Plus}>Add Vehicle</Button>
        <Button variant="secondary">Cancel</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Remove</Button>
        <Button variant="accentTint">Analytics</Button>
        <Button loading>Saving</Button>
        <Button disabled={disabled}>Respects toggle</Button>
        <Button size="sm">Small</Button>
        <Button size="lg">Large</Button>
      </Section>

      <Section title="IconButton" note="title stays alongside aria-label — e2e pins button[title='Delete'].">
        <IconButton icon={Trash2} label="Delete" variant="danger" />
        <IconButton icon={Pencil} label="Edit" />
        <IconButton icon={X} label="Close" variant="surface" />
        <IconButton icon={Trash2} label="Delete" size="sm" />
        <IconButton icon={Trash2} label="Delete" size="lg" disabled={disabled} />
      </Section>

      <Section title="Field" note="Required marker and unit live INSIDE the label — two VehicleEdit tests query the composed string. The caller wires aria-describedby.">
        <div className="w-72">
          <Field id="g-nickname" label="Nickname" required>
            <input
              id="g-nickname"
              className="ui-focus-input h-input-md w-full rounded-control border border-border bg-surface-2 px-3"
            />
          </Field>
          <Field id="g-def" label="DEF Tank Capacity" unit="L" hint="Leave blank if not equipped.">
            <input
              id="g-def"
              aria-describedby="g-def-hint"
              className="ui-focus-input h-input-md w-full rounded-control border border-border bg-surface-2 px-3"
            />
          </Field>
          <Field id="g-cost" label="Cost" error="Required">
            <input
              id="g-cost"
              aria-describedby="g-cost-error"
              className="ui-focus-input h-input-md w-full rounded-control border border-danger bg-surface-2 px-3"
            />
          </Field>
        </div>
      </Section>

      <Section title="Input / Textarea" note="type forwards untouched — implicit roles hang off it. mono for numeric/currency/date.">
        <div className="grid w-full max-w-xl gap-3">
          <Input placeholder="Standard" aria-label="Standard" />
          <Input mono placeholder="1HGCM82633A004352" aria-label="VIN" />
          <Input prefix="$" mono placeholder="0.00" aria-label="Cost" />
          <Input type="number" placeholder="0" aria-label="Quantity" />
          <Input invalid placeholder="Invalid" aria-label="Invalid" />
          <Input disabled={disabled} placeholder="Respects toggle" aria-label="Disabled demo" />
          <Textarea placeholder="Notes" aria-label="Notes" />
        </div>
      </Section>

      <Section title="Select" note="Native select, visible, exactly options.length + 1 options.">
        <div className="grid w-full max-w-xl gap-3">
          <Select
            aria-label="Fuel type"
            placeholder="Select fuel type"
            options={[
              { value: 'gasoline', label: 'Gasoline' },
              { value: 'diesel', label: 'Diesel' },
              { value: 'electric', label: 'Electric' },
            ]}
          />
          <Select aria-label="Small" size="sm" options={[{ value: 'a', label: 'Small' }]} />
          <Select aria-label="Invalid" invalid options={[{ value: 'a', label: 'Invalid' }]} />
        </div>
      </Section>

      <Section title="Toggle / Checkbox" note="Toggle keeps the implicit checkbox role — role='switch' would break 5 tests. Check the knob against the off-track in LIGHT theme.">
        <Toggle label="Safety alerts" checked={toggleOn} onChange={setToggleOn} />
        <Toggle label="Gas Stations" checked={toggleOn} onChange={setToggleOn} variant="onOff" />
        <Toggle label="Disabled" checked={false} onChange={() => {}} disabled />
        <Checkbox id="g-jpg" label=".jpg" defaultChecked />
        <Checkbox id="g-png" label=".png" />
      </Section>

      <Section title="SearchField" note="Replaces six copies whose icon size had drifted.">
        <SearchField
          value={searchValue}
          onChange={setSearchValue}
          label="Search contacts"
          placeholder="Search contacts"
          className="w-64"
        />
        <SearchField value="ram" onChange={() => {}} label="Search" size="sm" className="w-48" />
      </Section>

      <Section title="Tabs" note="One tablist, three containers. Label rendered once — the dual-span pattern computes 'FuelFuel' in jsdom.">
        <div className="w-full">
          <Tabs
            label="Vehicle sections"
            activeId="fuel"
            onChange={() => {}}
            items={[
              { id: 'overview', label: 'Overview' },
              { id: 'fuel', label: 'Fuel', icon: Fuel, count: 29 },
              { id: 'media', label: 'Media' },
            ]}
          />
          <div className="mt-4 flex gap-4">
            <Tabs
              label="Channels"
              variant="pill"
              activeId="discord"
              onChange={() => {}}
              items={[
                { id: 'discord', label: 'Discord', dot: true },
                { id: 'slack', label: 'Slack' },
              ]}
            />
            <Tabs
              label="Auth mode"
              variant="segmented"
              activeId="local"
              onChange={() => {}}
              items={[
                { id: 'none', label: 'None' },
                { id: 'local', label: 'Local' },
                { id: 'oidc', label: 'OIDC' },
              ]}
            />
          </div>
        </div>
      </Section>

      <Section title="Dropdown" note="Catcher at z-dropdown-catcher (44), panel at z-dropdown (45). Escape and arrow keys work.">
        <Dropdown
          label="Sort by Name"
          items={[
            { id: 'name', label: 'Name', onSelect: () => {}, checked: true },
            { id: 'newest', label: 'Newest First', onSelect: () => {} },
            { id: 'maint', label: 'By Maintenance', onSelect: () => {} },
          ]}
        />
      </Section>

      <Section title="Drawer" note="Right-anchored, focus-trapped, Escape-closing. The app has no side drawer today.">
        <Button onClick={() => setDrawerOpen(true)}>Open drawer</Button>
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          title="Add Fuel"
          width="md"
          footer={
            <>
              <Button variant="secondary" onClick={() => setDrawerOpen(false)}>Cancel</Button>
              <Button onClick={() => setDrawerOpen(false)}>Save</Button>
            </>
          }
        >
          <Field id="g-liters" label="Litres" required>
            <Input id="g-liters" type="number" mono placeholder="0.00" />
          </Field>
          <p className="text-sm text-text-mute">Tab is trapped. Escape closes. Focus restores to the trigger. Type in the field — focus must stay put.</p>
        </Drawer>
      </Section>

      <Section title="Stepper" note="Extracted from two near-identical wizard copies. Now announces progress as a progressbar.">
        <div className="w-full max-w-lg">
          <Stepper
            label="Add vehicle progress"
            valueText="Step 2 of 4"
            current={2}
            steps={[
              { number: 1, title: 'VIN' },
              { number: 2, title: 'Details' },
              { number: 3, title: 'Photos' },
              { number: 4, title: 'Review' },
            ]}
          />
        </div>
      </Section>

      <Section title="DataTable" note="Owns its overflow wrapper. Numeric columns are right-aligned Mono.">
        <div className="w-full max-w-xl rounded-card border border-border bg-surface">
          <DataTable
            caption="Fuel records"
            rowKey={(r) => r.id}
            columns={[
              { id: 'date', header: 'Date', render: (r) => r.date },
              { id: 'volume', header: 'Litres', align: 'right', mono: true, render: (r) => r.volume },
              { id: 'cost', header: 'Cost', align: 'right', mono: true, render: (r) => r.cost },
            ]}
            rows={[
              { id: '1', date: 'Jul 13, 2026', volume: '41.2', cost: '$62.40' },
              { id: '2', date: 'Jun 30, 2026', volume: '38.9', cost: '$58.10' },
            ]}
          />
        </div>
        <div className="w-full max-w-xl rounded-card border border-border bg-surface">
          <DataTable
            caption="Fuel records (empty)"
            rowKey={(r) => r.id}
            columns={[
              { id: 'date', header: 'Date', render: (r) => r.date },
              { id: 'cost', header: 'Cost', align: 'right', mono: true, render: (r) => r.cost },
            ]}
            rows={[] as Array<{ id: string; date: string; cost: string }>}
            emptyState={<EmptyState icon={Box} title="No fuel records yet" size="sm" />}
          />
        </div>
      </Section>
    </div>
  )
}
