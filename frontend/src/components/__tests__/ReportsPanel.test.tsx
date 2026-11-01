import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import api from '../../services/api'
import analyticsEn from '../../locales/en/analytics.json'

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: (v: unknown) => String(v) }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// The shipped English, so the button names below are what a screen reader
// hears. The key-echo mock drops the report title and every PDF would read
// the same, which is the bug.
vi.mock('react-i18next', async () => {
  const i18next = (await import('i18next')).default
  const analytics = (await import('../../locales/en/analytics.json')).default
  const english = i18next.createInstance()
  await english.init({
    lng: 'en',
    ns: ['analytics'],
    defaultNS: 'analytics',
    resources: { en: { analytics } },
    interpolation: { escapeValue: false },
  })
  const t = english.t.bind(english)
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const apiGet = api.get as unknown as ReturnType<typeof vi.fn>
const en = analyticsEn.reports

import ReportsPanel from '../ReportsPanel'

const SERVICE_PDF = 'Download PDF: Service History Report'
const COST_PDF = 'Download PDF: Annual Cost Summary'
const TAX_PDF = 'Download PDF: Tax Deduction Report'
const SALE_PDF = 'Download PDF: Sale history (sanitized)'
const SERVICE_CSV = 'Export CSV: Service History (CSV)'
const ALL_CSV = 'Export CSV: All Records (CSV)'

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), writable: true, configurable: true })
  Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
  // jsdom cannot navigate to the blob: URL a download anchor points at, and
  // logs "Not implemented: navigation to another Document" on every click.
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

describe('ReportsPanel — report generation URLs (SDQ-C, five-action matrix)', () => {
  // Only the service-history reports read the date range. The year-based reports (cost-summary / tax-deduction /
  // all-records) use the component's selectedYear default (= the current year), so their tests read the same
  // expression rather than hard-coding a year.

  it('the service-history PDF button GETs the exact PDF URL (typed start date + currency/locale, no year) as a blob (fails if the date input is unwired, the endpoint is wrong, or a param is dropped/added)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x'], { type: 'application/pdf' }) })
    render(<ReportsPanel vin="V1" />)
    fireEvent.change(screen.getByLabelText(en.startDate), { target: { value: '2026-01-01' } })
    fireEvent.click(screen.getByRole('button', { name: SERVICE_PDF }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    // strict 2-element call-array — extra/dropped params or a wrong endpoint fail toStrictEqual (never expect.anything())
    expect(apiGet.mock.calls[0]).toStrictEqual([
      '/vehicles/V1/reports/service-history-pdf?start_date=2026-01-01&currency_code=USD&locale=en-US',
      { responseType: 'blob' },
    ])
  })

  it('the cost-summary PDF button GETs the exact PDF URL (year = current year + currency/locale) as a blob (fails if cost-summary is routed to the wrong endpoint/handler or drops the year/currency params)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x'], { type: 'application/pdf' }) })
    render(<ReportsPanel vin="V1" />)
    const year = new Date().getFullYear()
    fireEvent.click(screen.getByRole('button', { name: COST_PDF }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    expect(apiGet.mock.calls[0]).toStrictEqual([
      `/vehicles/V1/reports/cost-summary-pdf?year=${year}&currency_code=USD&locale=en-US`,
      { responseType: 'blob' },
    ])
  })

  it('the tax-deduction PDF button GETs the exact PDF URL (year = current year + currency/locale) as a blob (fails if tax-deduction is routed to the wrong endpoint/handler or drops the year/currency params)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x'], { type: 'application/pdf' }) })
    render(<ReportsPanel vin="V1" />)
    const year = new Date().getFullYear()
    fireEvent.click(screen.getByRole('button', { name: TAX_PDF }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    expect(apiGet.mock.calls[0]).toStrictEqual([
      `/vehicles/V1/reports/tax-deduction-pdf?year=${year}&currency_code=USD&locale=en-US`,
      { responseType: 'blob' },
    ])
  })

  it('the service-history CSV button GETs the exact CSV URL (typed start date, trailing &, no year/currency) as a blob (fails if the CSV endpoint is wrong or the date is dropped)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x']) })
    render(<ReportsPanel vin="V1" />)
    fireEvent.change(screen.getByLabelText(en.startDate), { target: { value: '2026-01-01' } })
    fireEvent.click(screen.getByRole('button', { name: SERVICE_CSV }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    // CSV handler builds the query by hand: `service-history-csv?` + `start_date=2026-01-01&` (endDate empty → not appended)
    expect(apiGet.mock.calls[0]).toStrictEqual([
      '/vehicles/V1/reports/service-history-csv?start_date=2026-01-01&',
      { responseType: 'blob' },
    ])
  })

  it('the all-records CSV button GETs the exact CSV URL (year = current year) as a blob (fails if export is unwired or the endpoint/year is wrong)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x']) })
    render(<ReportsPanel vin="V1" />)
    const year = new Date().getFullYear()
    fireEvent.click(screen.getByRole('button', { name: ALL_CSV }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    expect(apiGet.mock.calls[0]).toStrictEqual([`/vehicles/V1/reports/all-records-csv?year=${year}`, { responseType: 'blob' }])
  })
})

describe('ReportsPanel: every download says which report it is (G2b-16)', () => {
  it('each PDF and CSV button has its own name, starting with the visible text', () => {
    render(<ReportsPanel vin="V1" />)
    for (const name of [SERVICE_PDF, COST_PDF, TAX_PDF, SALE_PDF, SERVICE_CSV, ALL_CSV]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    // Label in name: the phone hides the text, the desktop shows it, and a
    // voice user says what they see.
    for (const button of screen.getAllByRole('button', { name: /^Download PDF: / })) {
      expect(button).toHaveTextContent(en.downloadPdf)
    }
    for (const button of screen.getAllByRole('button', { name: /^Export CSV: / })) {
      expect(button).toHaveTextContent(en.exportCsv)
    }
  })
})

describe('ReportsPanel: one year control for the yearly reports (D4)', () => {
  const lastYear = String(new Date().getFullYear() - 1)

  it('there is one labelled year select, not three', () => {
    render(<ReportsPanel vin="V1" />)
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
    expect(screen.getByRole('combobox', { name: en.selectYear })).toBeInTheDocument()
  })

  it.each([
    [COST_PDF, `/vehicles/V1/reports/cost-summary-pdf?year=${lastYear}&currency_code=USD&locale=en-US`],
    [TAX_PDF, `/vehicles/V1/reports/tax-deduction-pdf?year=${lastYear}&currency_code=USD&locale=en-US`],
    [ALL_CSV, `/vehicles/V1/reports/all-records-csv?year=${lastYear}`],
  ])('the picked year drives %s', async (name, url) => {
    apiGet.mockResolvedValue({ data: new Blob(['x']) })
    render(<ReportsPanel vin="V1" />)
    fireEvent.change(screen.getByRole('combobox', { name: en.selectYear }), { target: { value: lastYear } })
    fireEvent.click(screen.getByRole('button', { name }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    expect(apiGet.mock.calls[0]).toStrictEqual([url, { responseType: 'blob' }])
  })

  it('All Years exports every year to the CSV, with no year=0', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x']) })
    render(<ReportsPanel vin="V1" />)
    fireEvent.change(screen.getByRole('combobox', { name: en.selectYear }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: ALL_CSV }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1))
    expect(apiGet.mock.calls[0]).toStrictEqual(['/vehicles/V1/reports/all-records-csv?', { responseType: 'blob' }])
  })

  it('All Years holds the yearly PDFs back and says why', () => {
    render(<ReportsPanel vin="V1" />)
    const year = screen.getByRole('combobox', { name: en.selectYear })
    expect(screen.getByRole('button', { name: COST_PDF })).toBeEnabled()
    expect(year).toHaveAccessibleDescription(en.yearHint)

    fireEvent.change(year, { target: { value: '' } })

    expect(screen.getByRole('button', { name: COST_PDF })).toBeDisabled()
    expect(screen.getByRole('button', { name: TAX_PDF })).toBeDisabled()
    // The date-range and sale-history PDFs don't read the year.
    expect(screen.getByRole('button', { name: SERVICE_PDF })).toBeEnabled()
    expect(screen.getByRole('button', { name: SALE_PDF })).toBeEnabled()
    expect(screen.getByRole('button', { name: ALL_CSV })).toBeEnabled()
    expect(year).toHaveAccessibleDescription(en.allYearsCsvOnly)
  })

  it('the held-back PDFs point at the note that says why', () => {
    // Disabled with no reason a screen reader could reach.
    render(<ReportsPanel vin="V1" />)
    fireEvent.change(screen.getByRole('combobox', { name: en.selectYear }), { target: { value: '' } })
    expect(screen.getByRole('button', { name: COST_PDF })).toHaveAccessibleDescription(en.allYearsCsvOnly)
    expect(screen.getByRole('button', { name: TAX_PDF })).toHaveAccessibleDescription(en.allYearsCsvOnly)
  })

  it('the card holding the year control is headed for both', () => {
    // It was still "Date Range Selection" with a year select in it.
    render(<ReportsPanel vin="V1" />)
    expect(screen.getByRole('heading', { name: 'Date Range and Year' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Date Range Selection' })).toBeNull()
  })
})
