import Mono from './Mono'

interface ShareBarProps {
  /** Already translated by the caller. */
  label: string
  /** Formatted amount — currency string, count, whatever. */
  value: string
  /** 0-100. Values outside the range are clamped. */
  percent: number
  /** Category colour from the chart palette (spec sheet §0.3). This is data
   *  colour, not theme colour, so it is passed in rather than tokenised —
   *  the one deliberate exception to "every colour routes through a token"
   *  in this library. Everything else here still uses tokens. */
  color: string
}

/**
 * A ranked-legend row with a proportional bar — the design's Cost by Category
 * legend beside the Analytics donut.
 *
 * Plain DOM, deliberately not a chart. Analytics draws the donut with
 * Recharts; the legend is a list of name/percentage/amount, and building it
 * as a chart too would make it unreadable to assistive tech for no gain.
 * The fill exposes role="progressbar" so the share is announced, following
 * the same pattern as the password-strength meter (Register.tsx) and
 * Stepper's progress indicator — role="progressbar", not role="group",
 * because aria-valuenow/min/max are range-widget attributes every AT ignores
 * on a group.
 *
 * The label and figures sit on the ordinary page surface, not inside a
 * coloured container, so Mono keeps its own default tone here rather than
 * `inherit` — the same call Tile, ListRow and DataTable made. `inherit`
 * exists for Badge/Stepper's case: text painted directly onto a solid accent
 * or status fill, where Mono's own default would fight the container's
 * contrast. Nothing here has that fill under the text — the coloured bar is
 * a sibling element, not an ancestor.
 */
export default function ShareBar({ label, value, percent, color }: ShareBarProps) {
  const clamped = Math.max(0, Math.min(100, percent))

  return (
    <div className="w-full py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-text">{label}</span>
        <span className="flex items-baseline gap-3">
          <Mono size="sm" tone="muted">{`${clamped}%`}</Mono>
          <Mono weight="semibold">{value}</Mono>
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-1.5 h-1.5 w-full overflow-hidden rounded-pill bg-surface-2"
      >
        <div className="h-full rounded-pill" style={{ width: `${clamped}%`, background: color }} />
      </div>
    </div>
  )
}
