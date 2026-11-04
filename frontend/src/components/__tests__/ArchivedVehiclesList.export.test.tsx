/**
 * Exporting before a delete: the service history prints costs, so it needs the
 * currency (it printed USD for everyone), and both PDFs need the date order
 * the page shows (#278).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const apiGet = vi.hoisted(() => vi.fn())
vi.mock('@/services/api', () => ({ default: { get: apiGet, patch: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
vi.mock('@/hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'EUR', locale: 'de-DE' }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ArchivedVehiclesList from '../ArchivedVehiclesList'
import { setActiveDateFormat } from '@/constants/i18n'

const VIN = '1HGCM82633A004352'

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), writable: true, configurable: true })
  Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  apiGet.mockImplementation(async (url: string) =>
    url === '/vehicles/archived/list'
      ? { data: { vehicles: [{ vin: VIN, year: 2018, make: 'Honda', model: 'Accord', archived_visible: false }] } }
      : { data: new Blob(['x'], { type: 'application/pdf' }) }
  )
  setActiveDateFormat('dmy')
})

afterEach(() => setActiveDateFormat('mdy'))

async function exportAs(button: string): Promise<unknown[]> {
  render(<ArchivedVehiclesList />)
  await screen.findByText(/Accord/)
  fireEvent.click(screen.getAllByRole('checkbox')[1])
  fireEvent.click(screen.getByRole('button', { name: /archivedVehiclesList\.deleteSelected/ }))
  fireEvent.click(screen.getByRole('button', { name: new RegExp(button) }))
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2))
  return apiGet.mock.calls[1]
}

describe('ArchivedVehiclesList export before delete', () => {
  it('sends the currency and date order with the service history', async () => {
    expect(await exportAs('archivedList\\.exportBeforeDelete')).toStrictEqual([
      `/vehicles/${VIN}/reports/service-history-pdf`,
      { responseType: 'blob', params: { currency_code: 'EUR', locale: 'de-DE', date_format: 'dmy' } },
    ])
  })

  it('sends the date order with the sale history, which has no costs', async () => {
    expect(await exportAs('archivedList\\.exportSaleHistory')).toStrictEqual([
      `/vehicles/${VIN}/reports/sale-history-pdf`,
      { responseType: 'blob', params: { date_format: 'dmy' } },
    ])
  })
})
