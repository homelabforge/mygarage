import type { KeyboardEvent } from 'react'
import type { IconType } from './types'
import Badge from './Badge'

export interface TabItem {
  id: string
  /** Already translated by the caller. */
  label: string
  /** IconType — rendered with aria-hidden="true" (see Task 3). */
  icon?: IconType
  /** Rendered as an aria-hidden Badge so the accessible name stays the label. */
  count?: number
  /** Status marker (e.g. "this service is enabled"). Always aria-hidden. */
  dot?: boolean
  visible?: boolean
}

type TabsVariant = 'underline' | 'pill' | 'segmented'

interface TabsProps {
  items: TabItem[]
  activeId: string
  onChange: (id: string) => void
  /** Accessible name for the tablist. Freeze 'Vehicle sections' on the
   *  primary vehicle tablist — e2e queries it by name (G6). */
  label: string
  variant?: TabsVariant
}

// Three containers. `segmented` and `pill` share the button skin below and
// differ ONLY here — a bordered inline tray versus a wrapping translucent
// bar. That is deliberate, not an oversight: the design distinguishes them
// by their container, and inventing a third active treatment to justify the
// third name would be scope it does not ask for.
const CONTAINER: Record<TabsVariant, string> = {
  underline: 'flex gap-1 overflow-x-auto border-b border-border',
  segmented: 'inline-flex gap-1 rounded-control border border-border bg-surface-2 p-1',
  pill: 'flex flex-wrap gap-2 rounded-control border border-border bg-surface/50 p-1',
}

/**
 * One tablist, three containers.
 *
 * Absorbs SubTabNav (underline), NotificationSubTabs (pill) and the auth-mode
 * bar (segmented), which were three copies of the same component. `pill` and
 * `segmented` share a button skin and differ only in their wrapper.
 *
 * Two things here are constraints, not preferences:
 *
 *  1. The label is rendered ONCE. SubTabNav renders it in two spans — one
 *     `hidden sm:inline`, one `sr-only sm:hidden` — and jsdom applies no CSS,
 *     so it concatenates both and a tab named "Fuel" computes as "FuelFuel".
 *     Responsive collapse is done by hiding the text with CSS on a single
 *     node, never by duplicating it "for safety".
 *  2. The label is the direct text of the <button>. SettingsSystemTab.test.tsx
 *     does findByText('auth.local') and clicks the result; if that returns a
 *     non-clickable inner node the click never reaches the handler.
 */
export default function Tabs({ items, activeId, onChange, label, variant = 'underline' }: TabsProps) {
  const visible = items.filter((item) => item.visible !== false)
  if (visible.length === 0) return null

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number): void => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const nextIndex = (index + delta + visible.length) % visible.length
    onChange(visible[nextIndex].id)
    // Roving-tabindex focus follow: programmatic .focus() works on a
    // tabIndex=-1 element even before the parent's activeId re-render lands.
    const container = event.currentTarget.parentElement
    const nextButton = container?.children[nextIndex]
    if (nextButton instanceof HTMLElement) nextButton.focus()
  }

  return (
    <div role="tablist" aria-label={label} data-testid="tabs" className={CONTAINER[variant]}>
      {visible.map((item, index) => {
        const Icon = item.icon
        const active = item.id === activeId
        // Two button skins for three variants: segmented and pill share this
        // second branch verbatim. See the CONTAINER comment above.
        const skin =
          variant === 'underline'
            ? `border-b-2 px-4 py-2.5 ${active ? 'border-(--accent) text-(--accent-fg)' : 'border-transparent text-text-mute hover:text-text'}`
            : `rounded-[7px] px-3 py-1.5 ${active ? 'bg-(--accent-soft) text-(--accent-fg)' : 'text-text-mute hover:text-text'}`

        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`ui-focus-ring ui-motion flex shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap text-sm ${skin}`}
          >
            {Icon ? <Icon aria-hidden="true" className="h-4 w-4 shrink-0" /> : null}
            {/* Single node. Hidden with CSS on narrow screens when there is an
                icon to stand in for it — never duplicated into a second span. */}
            <span className={Icon ? 'hidden sm:inline' : undefined}>{item.label}</span>
            {item.count !== undefined ? (
              // A real Badge, not an inline pill: Badge already routes the
              // figure through Mono, which is where the G8.2 mono rule lives.
              // aria-hidden keeps the count out of the tab's accessible name.
              <span aria-hidden="true">
                <Badge tone="muted" count={item.count} />
              </span>
            ) : null}
            {item.dot ? (
              <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
