import { describe, it, expect } from 'vitest'
import { isValidElement, type ReactElement } from 'react'
import { CATEGORY_SLOTS, CHART_AXIS, CHART_GRID, CHART_OTHER, TOOLTIP_CONTENT_STYLE, TOOLTIP_ITEM_STYLE, categoryColor, chartLegendText, chartSeries, pieLabelText } from '../chartTheme'

// The 10 display strings GarageAnalytics gets from /analytics/garage, plus the
// per-vehicle stacked bar's own keys.
const API_CATEGORIES = [
  'Maintenance', 'Upgrades', 'Inspection', 'Collision', 'Detailing',
  'Fuel', 'DEF', 'Insurance', 'Taxes', 'Financing',
]
const MAPPED = ['Maintenance', 'Fuel', 'DEF', 'Spot Rental', 'Insurance', 'Financing', 'Taxes', 'Upgrades']

describe('chartSeries', () => {
  it('hands out the 8 slots in order, then wraps', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 7].map(chartSeries)).toEqual(
      [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `var(--color-chart-${n})`)
    )
    expect(chartSeries(8)).toBe('var(--color-chart-1)')
  })
})

describe('categoryColor', () => {
  it('gives each of the 8 mapped categories its own slot', () => {
    const colours = MAPPED.map(categoryColor)
    expect(new Set(colours).size).toBe(8)
    for (const c of colours) expect(c).toMatch(/^var\(--color-chart-[1-8]\)$/)
  })

  it('pins the slots by name, so nothing can shuffle them', () => {
    expect(categoryColor('Maintenance')).toBe('var(--color-chart-1)')
    expect(categoryColor('Fuel')).toBe('var(--color-chart-2)')
    expect(categoryColor('DEF')).toBe('var(--color-chart-3)')
    expect(categoryColor('Spot Rental')).toBe('var(--color-chart-4)')
    expect(categoryColor('Insurance')).toBe('var(--color-chart-5)')
    expect(categoryColor('Financing')).toBe('var(--color-chart-6)')
    expect(categoryColor('Taxes')).toBe('var(--color-chart-7)')
    expect(categoryColor('Upgrades')).toBe('var(--color-chart-8)')
  })

  it('makes Service the same blue as Maintenance', () => {
    expect(categoryColor('Service')).toBe(categoryColor('Maintenance'))
  })

  it('folds Inspection, Collision, Detailing and anything unknown into Other', () => {
    for (const c of ['Inspection', 'Collision', 'Detailing', 'Tolls', '', 'maintenance']) {
      expect(categoryColor(c), c).toBe(CHART_OTHER)
    }
    expect(CHART_OTHER).toBe('var(--color-chart-other)')
  })

  it('colours a category the same whatever order the API sends', () => {
    const forward = Object.fromEntries(API_CATEGORIES.map((c) => [c, categoryColor(c)]))
    const backward = Object.fromEntries([...API_CATEGORIES].reverse().map((c) => [c, categoryColor(c)]))
    expect(backward).toEqual(forward)
    // and it isn't trivially one colour for everything
    expect(new Set(Object.values(forward)).size).toBe(8)
  })

  it('maps exactly the 8 categories the brief lists', () => {
    expect(Object.keys(CATEGORY_SLOTS).sort()).toEqual([...MAPPED, 'Service'].sort())
  })
})

describe('chart chrome', () => {
  it('uses the hairline and muted text tokens', () => {
    expect(CHART_GRID).toBe('var(--color-hair)')
    expect(CHART_AXIS).toBe('var(--color-text-mute)')
  })

  it('tooltip box is all tokens', () => {
    expect(TOOLTIP_CONTENT_STYLE).toMatchObject({
      backgroundColor: 'var(--color-surface-2)',
      border: '1px solid var(--color-border)',
      color: 'var(--color-text)',
      borderRadius: '8px',
      padding: '12px',
    })
  })
})

describe('text never wears the series colour', () => {
  it('tooltip rows read in the text colour', () => {
    expect(TOOLTIP_ITEM_STYLE).toEqual({ color: 'var(--color-text)' })
  })

  it('legend labels render on a text token, the swatch keeps the colour', () => {
    const el = chartLegendText('Fuel')
    expect(isValidElement(el)).toBe(true)
    const span = el as ReactElement<{ className: string; children: unknown }>
    expect(span.props.className).toContain('text-text-mid')
    expect(span.props.children).toBe('Fuel')
  })
})

describe('pieLabelText', () => {
  it('draws the slice label in a text token, where Recharts would use the slice colour', () => {
    const el = pieLabelText({ x: 10, y: 20, textAnchor: 'start' }, 'Oil Change 40%')
    expect(isValidElement(el)).toBe(true)
    const text = el as ReactElement<Record<string, unknown>>
    expect(text.type).toBe('text')
    expect(text.props).toMatchObject({ x: 10, y: 20, textAnchor: 'start', fill: 'var(--color-text-mid)' })
    expect(text.props.children).toBe('Oil Change 40%')
  })
})
