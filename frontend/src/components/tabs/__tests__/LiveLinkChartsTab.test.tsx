import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup } from '../../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { ReactNode } from 'react'
import type { LiveLinkParameter, LiveLinkParameterListResponse, TelemetryQueryResponse } from '../../../types/livelink'

// ─────────────────────────────────────────────────────────────────────────────
// Harness note — STABLE `t` (mirrors the Task-1/2/3 LiveLink precedent):
//
// `fetchTelemetry` lists `t` in its `useCallback` deps and the mount effect
// depends on `fetchTelemetry`. The GLOBAL react-i18next mock (src/__tests__/
// setup.ts) returns a FRESH `t` on every render, so `fetchTelemetry` is a new
// reference every render and `useEffect([fetchTelemetry])` re-fires after each
// data-commit re-render — a runaway refetch loop that makes the exact
// `getTelemetry.mock.calls` arrays this suite asserts impossible. Real
// react-i18next memoizes `t`, so this loop is a TEST artifact, never production
// behaviour. Override the mock LOCALLY with a STABLE module-level `t` (same
// key-echo shape as the global mock) so `fetchTelemetry` is stable across
// renders — the fetch fires exactly once, as in production. TEST-harness fix
// only; the component's fetch/effect deps are unchanged (reskin = rendering).
// ─────────────────────────────────────────────────────────────────────────────
vi.mock('react-i18next', () => {
  const t = (key: string) => key
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

// R2-B1: type EACH service mock with the REAL callable signature (a bare `vi.fn(() => …)` is inferred
// zero-arg → spreading the wrapper's args into it is TS2556, and tsc runs before the test can go GREEN).
// The wrappers then spread the matching `Parameters<…>` TUPLE (a plain `unknown[]` spread into a typed
// fn is also TS2556). getTelemetryExportUrl is SYNC → string (set via mockReturnValue in beforeEach).
type LLService = (typeof import('@/services/livelinkService'))['livelinkService']
const getVehicleParameters = vi.fn<LLService['getVehicleParameters']>()
const getTelemetry = vi.fn<LLService['getTelemetry']>()
const getTelemetryExportUrl = vi.fn<LLService['getTelemetryExportUrl']>()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getVehicleParameters: (vin: string) => getVehicleParameters(vin),
    getTelemetry: (...a: Parameters<LLService['getTelemetry']>) => getTelemetry(...a),
    getTelemetryExportUrl: (...a: Parameters<LLService['getTelemetryExportUrl']>) => getTelemetryExportUrl(...a),
  },
}))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('@/utils/parseAPITimestamp', () => ({
  parseAPITimestampMs: () => 1,
  formatTime: () => '12:00',
  // Echoes its input so the tooltip-label test can prove WHICH value reached it.
  formatDateTime: (value: unknown) => `fmt:${String(value)}`,
}))
vi.mock('@/constants/i18n', () => ({ getActiveLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// M4: mock recharts at the COMPONENT boundary — stub LineChart to CAPTURE its `data` prop; the rest are
// pass-through/no-op stubs. Do NOT rely on a styled-div ResponsiveContainer mock: recharts 3.9 sizes via
// ResponsiveContainerContext, so that mock gives LineChart no dimensions. Here we never touch SVG internals,
// so the boundary stub is dimension-free and the captured `data` proves the telemetry→series projection.
const captured = vi.hoisted(() => ({
  lineChartData: undefined as unknown,
  tooltipLabelFormatter: undefined as ((label: ReactNode) => ReactNode) | undefined,
  tooltipStyle: undefined as Record<string, unknown> | undefined,
  tooltipItemStyle: undefined as Record<string, unknown> | undefined,
  strokes: {} as Record<string, string | undefined>,
}))
vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    LineChart: ({ data, children }: { data: unknown; children?: ReactNode }) => {
      captured.lineChartData = data
      return <>{children}</>
    },
    Line: ({ dataKey, stroke }: { dataKey: string; stroke?: string }) => {
      captured.strokes[dataKey] = stroke
      return null
    },
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: ({ labelFormatter, contentStyle, itemStyle }: { labelFormatter?: (label: ReactNode) => ReactNode; contentStyle?: Record<string, unknown>; itemStyle?: Record<string, unknown> }) => {
      captured.tooltipLabelFormatter = labelFormatter
      captured.tooltipStyle = contentStyle
      captured.tooltipItemStyle = itemStyle
      return null
    },
    Legend: () => null,
  }
})

import LiveLinkChartsTab from '../LiveLinkChartsTab'

// Frozen clock → getTimeRange() is deterministic. rangeFor mirrors the component's Date math against the
// SAME frozen instant, so the expected start/end are timezone-independent (both run in this process).
const FROZEN = '2026-07-26T12:00:00.000Z'
function rangeFor(range: '24h' | '30d') {
  const now = new Date(FROZEN)
  const start = new Date(FROZEN)
  start.setDate(start.getDate() - (range === '30d' ? 30 : 1))
  return { start: start.toISOString(), end: now.toISOString() }
}

// Contract-valid typed builders (`satisfies <Type>`) — populate EVERY required field of the generated
// schemas (no `as unknown as`), so a schema drift fails at type-check.
const mkParam = (id: number, param_key: string, display_name: string, unit: string) =>
  ({
    id, param_key, display_name, unit,
    archive_only: false, category: null, created_at: 'x', display_order: id,
    icon: null, show_on_dashboard: true, storage_interval_seconds: 1,
    updated_at: null, warning_max: null, warning_min: null, critical_min: null,
  }) satisfies LiveLinkParameter
const PARAMS = {
  parameters: [
    mkParam(1, 'p1', 'First Param', 'rpm'),
    mkParam(2, 'p2', 'Second Param', 'C'),
    mkParam(3, 'p3', 'Third Param', 'V'),
    mkParam(4, 'p4', 'Fourth Param', 'rpm'),
  ],
  total: 4,
} satisfies LiveLinkParameterListResponse
const TELEMETRY = {
  vin: 'V1',
  start: '2026-07-25T12:00:00.000Z',
  end: '2026-07-26T12:00:00.000Z',
  total_points: 100,
  series: [
    { param_key: 'p1', display_name: 'First Param', unit: 'rpm', min_value: 1, max_value: 9, avg_value: 5, data: [{ timestamp: 'x', value: 5 }] },
  ],
} satisfies TelemetryQueryResponse

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers({ toFake: ['Date'] }) // freeze Date ONLY — setTimeout stays real so waitFor works
  vi.setSystemTime(new Date(FROZEN))
  captured.lineChartData = undefined
  captured.tooltipLabelFormatter = undefined
  captured.tooltipStyle = undefined
  captured.strokes = {}
  getVehicleParameters.mockResolvedValue(PARAMS)
  getTelemetry.mockResolvedValue(TELEMETRY)
  getTelemetryExportUrl.mockReturnValue('https://export.example/csv')
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('LiveLinkChartsTab — controls + data boundary (SDQ-C, §5c, M4)', () => {
  it('shows the no-params empty state when there are no chartable parameters', async () => {
    getVehicleParameters.mockResolvedValue({ parameters: [], total: 0 })
    render(<LiveLinkChartsTab vin="V1" />)
    expect(await screen.findByText('livelink.charts.noParams')).toBeInTheDocument()
  })

  it('loads the default 24h window with the first 3 params and no downsample (M1: exact getTelemetry args)', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    const { start, end } = rangeFor('24h')
    // M1: scoped to THIS vehicle. The fleet-wide catalog would offer an RV
    // engine PIDs it can never chart, which is the defect this pins.
    expect(getVehicleParameters.mock.calls).toStrictEqual([['V1']])
    expect(getTelemetry.mock.calls).toStrictEqual([['V1', start, end, ['p1', 'p2', 'p3'], undefined]])
  })

  it('projects the telemetry series into the LineChart data prop (fails if chartData stops mapping series points by timestamp)', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    // parseAPITimestampMs is mocked → 1; the single p1 point (value 5) projects to one row.
    await waitFor(() => expect(captured.lineChartData).toStrictEqual([{ timestamp: 1, p1: 5 }]))
  })

  it('formats a numeric or string tooltip label as a date-time and passes any other label through (recharts types it ReactNode)', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(captured.tooltipLabelFormatter).toBeTypeOf('function'))
    const format = captured.tooltipLabelFormatter
    // The XAxis dataKey is the epoch-ms timestamp, so this is the label recharts actually passes.
    expect(format?.(1753531200000)).toBe('fmt:1753531200000')
    expect(format?.('2026-07-26T12:00:00Z')).toBe('fmt:2026-07-26T12:00:00Z')
    // A non-primitive label cannot be a timestamp; it must come back untouched, not stringified.
    const node = <span>custom</span>
    expect(format?.(node)).toBe(node)
  })

  it('changing the time range refetches with the new window AND its downsample interval (M1: 30d → intervalSeconds 3600)', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    getTelemetry.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'livelinkCharts.range30d' }))
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    const { start, end } = rangeFor('30d')
    expect(getTelemetry.mock.calls).toStrictEqual([['V1', start, end, ['p1', 'p2', 'p3'], 3600]])
  })

  it('adding then removing a parameter refetches with the exact updated param list (M1: add p4, then remove p1)', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    const { start, end } = rangeFor('24h')

    getTelemetry.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /Fourth Param/ })) // p4 not selected → add
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    expect(getTelemetry.mock.calls).toStrictEqual([['V1', start, end, ['p1', 'p2', 'p3', 'p4'], undefined]])

    getTelemetry.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /First Param/ })) // p1 selected → remove
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    expect(getTelemetry.mock.calls).toStrictEqual([['V1', start, end, ['p2', 'p3', 'p4'], undefined]])
  })

  it('export calls getTelemetryExportUrl + window.open with the exact args when telemetry has points (M1)', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    const exportBtn = screen.getByRole('button', { name: 'livelinkCharts.exportCsv' })
    expect(exportBtn).toBeEnabled()
    fireEvent.click(exportBtn)
    const { start, end } = rangeFor('24h')
    expect(getTelemetryExportUrl.mock.calls).toStrictEqual([['V1', start, end, 'csv', ['p1', 'p2', 'p3']]]) // M1: exact
    expect(openSpy).toHaveBeenCalledWith('https://export.example/csv', '_blank') // window boundary (not a service)
  })

  it('export is disabled when telemetry has zero points (the FALSE state — fails if the disable guard is dropped)', async () => {
    getTelemetry.mockResolvedValue({ ...TELEMETRY, series: [], total_points: 0 })
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: 'livelinkCharts.exportCsv' })).toBeDisabled()
  })
})

describe('LiveLinkChartsTab chart theme', () => {
  const lineStrokes = (): Record<string, string | undefined> => ({ ...captured.strokes })

  it('draws lines from the chart slots and the tooltip from surface tokens', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(Object.keys(lineStrokes())).toHaveLength(3))
    expect(lineStrokes()).toEqual({
      p1: 'var(--color-chart-1)',
      p2: 'var(--color-chart-2)',
      p3: 'var(--color-chart-3)',
    })
    expect(captured.tooltipStyle).toMatchObject({
      backgroundColor: 'var(--color-surface-2)',
      border: '1px solid var(--color-border)',
      color: 'var(--color-text)',
    })
    expect(captured.tooltipItemStyle).toEqual({ color: 'var(--color-text)' })
  })

  it('keeps the survivors on their colours when a parameter is dropped', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(Object.keys(lineStrokes())).toHaveLength(3))
    const before = lineStrokes()

    fireEvent.click(screen.getByRole('button', { name: /First Param/ })) // drop p1
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(2))
    captured.strokes = {}
    fireEvent.click(screen.getByRole('button', { name: /Fourth Param/ })) // add p4
    await waitFor(() => expect(Object.keys(lineStrokes()).sort()).toEqual(['p2', 'p3', 'p4']))

    expect(lineStrokes().p2).toBe(before.p2)
    expect(lineStrokes().p3).toBe(before.p3)
    // p4 takes the slot p1 freed, not a colour p2 or p3 already wears
    expect(lineStrokes().p4).toBe('var(--color-chart-1)')
  })

  it('marks a selected chip with its series colour, not a filled chip under white text', async () => {
    render(<LiveLinkChartsTab vin="V1" />)
    await waitFor(() => expect(getTelemetry).toHaveBeenCalledTimes(1))
    const chip = screen.getByRole('button', { name: /Second Param/ })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    expect(chip.style.backgroundColor).toBe('')
    expect(chip.className).toContain('text-text')
    const swatch = chip.querySelector('[data-testid="series-swatch"]') as HTMLElement | null
    expect(swatch?.getAttribute('style') ?? '').toContain('var(--color-chart-2)')
    expect(screen.getByRole('button', { name: /Fourth Param/ }).querySelector('[data-testid="series-swatch"]')).toBeNull()
  })
})
