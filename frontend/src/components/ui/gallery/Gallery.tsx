import { useState } from 'react'
import { Wrench } from 'lucide-react'
import Section from './Section'
// Import through the barrel, never from a component file directly: this single
// specifier is the only thing that puts ../index.ts — and, through it,
// ../types.ts — on the graph validate-reachability walks from main.tsx.
import { Badge, Chip, Mono, type Size } from '..'
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
    </div>
  )
}
