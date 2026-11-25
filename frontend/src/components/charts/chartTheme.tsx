import type { CSSProperties, ReactNode, SVGProps } from 'react'

// Chart colours as theme tokens. The --color-chart-* steps live in index.css
// (@theme static, light steps in html.light), so every chart flips with the theme.

/** Gridlines: a hairline, one shade off the surface. */
export const CHART_GRID = 'var(--color-hair)'
/** Axis lines, ticks and axis labels. */
export const CHART_AXIS = 'var(--color-text-mute)'
/** The neutral grey for anything folded into Other. Not a hue on purpose. */
export const CHART_OTHER = 'var(--color-chart-other)'

// Stacked segments get a 2px gap drawn in whatever the panel behind them is,
// so pick the one that matches the card the chart sits on.
export const CHART_GAP_SURFACE = 'var(--color-surface)'
export const CHART_GAP_BG = 'var(--color-bg)'

// Rolling averages are a reference over the total, not a series of their own,
// so they stay neutral and dashed instead of borrowing a category's hue.
export const CHART_AVG_SHORT = 'var(--color-text-dim)'
export const CHART_AVG_LONG = 'var(--color-text-mute)'

/**
 * Series colour for charts whose series are parameters, not fixed categories
 * (LiveLink, tires). Past 8 the fix is fewer series, not more hues, so this
 * just wraps.
 */
export function chartSeries(i: number): string {
  return `var(--color-chart-${(i % 8) + 1})`
}

/**
 * One fixed slot per spend category, so a colour means the same thing on every
 * chart and never moves with rank or response order. Service is Analytics'
 * sum of the service categories, so it rides Maintenance's blue.
 */
export const CATEGORY_SLOTS: Readonly<Record<string, number>> = {
  Maintenance: 1,
  Service: 1,
  Fuel: 2,
  DEF: 3,
  'Spot Rental': 4,
  Insurance: 5,
  Financing: 6,
  Taxes: 7,
  Upgrades: 8,
}

/**
 * Colour for a spend category. Inspection, Collision, Detailing and anything
 * we don't know (a future API category) fold into the Other grey: a 9th
 * category never gets a made-up hue.
 */
export function categoryColor(category: string): string {
  const slot = CATEGORY_SLOTS[category]
  return slot === undefined ? CHART_OTHER : `var(--color-chart-${slot})`
}

/** Whether a category has a slot of its own, or folds into Other. */
export function hasCategorySlot(category: string): boolean {
  return CATEGORY_SLOTS[category] !== undefined
}

/** contentStyle for Recharts' built-in tooltip. */
export const TOOLTIP_CONTENT_STYLE: CSSProperties = {
  backgroundColor: 'var(--color-surface-2)',
  border: '1px solid var(--color-border)',
  borderRadius: '8px',
  padding: '12px',
  color: 'var(--color-text)',
}

// Text never wears the series colour: slots 3-5 are under 3:1 as text on
// light. The mark beside the text (dot, swatch, line key) carries identity.

/** itemStyle for Recharts' built-in tooltip, so rows read in ink. */
export const TOOLTIP_ITEM_STYLE: CSSProperties = { color: 'var(--color-text)' }

/** Legend formatter: the label on a text token, the icon keeps the colour. */
export function chartLegendText(value: ReactNode): ReactNode {
  return <span className="text-text-mid">{value}</span>
}

interface PieLabelSpot {
  x?: number | string
  y?: number | string
  textAnchor?: SVGProps<SVGTextElement>['textAnchor']
}

/** A pie slice label in ink. Recharts draws it in the slice colour otherwise. */
export function pieLabelText({ x, y, textAnchor }: PieLabelSpot, text: string): ReactNode {
  return (
    <text x={x} y={y} textAnchor={textAnchor} dominantBaseline="central" fill="var(--color-text-mid)" fontSize={12}>
      {text}
    </text>
  )
}

interface ChartTooltipBoxProps {
  title?: ReactNode
  children?: ReactNode
}

/**
 * The box for custom `content=` tooltips. Muted lines inside go on
 * `text-sm text-text-mute`, not an inline grey.
 */
export function ChartTooltipBox({ title, children }: ChartTooltipBoxProps): ReactNode {
  return (
    <div data-testid="chart-tooltip" className="rounded-lg border border-border bg-surface-2 p-3 text-text shadow-lg">
      {title != null && <p className="mb-2 font-semibold">{title}</p>}
      {children}
    </div>
  )
}
