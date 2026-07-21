import { useState } from 'react'
import { Box, Pencil, Plus, Trash2, Wrench, X } from 'lucide-react'
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
  Chip,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListRow,
  Mono,
  PageContainer,
  PageHeader,
  Textarea,
  Tile,
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
    </div>
  )
}
