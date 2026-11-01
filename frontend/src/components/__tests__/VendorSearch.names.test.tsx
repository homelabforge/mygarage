/**
 * The clear button says which vendor it clears. Focus lands on it after a
 * pick, so "Clear vendor" alone never told a screen reader what was picked.
 * Strings come from the en bundle so the vendor's name shows up.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Vendor } from '../../types/vendor'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())
const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', () => ({ default: { get, post: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import VendorSearch from '../VendorSearch'

describe('VendorSearch clear button', () => {
  it('names the vendor it clears', async () => {
    get.mockResolvedValue({ data: { id: 1, name: 'Mavis' } as Vendor })
    render(<VendorSearch id="vendor" value={1} onSelect={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Clear vendor: Mavis' })).toBeInTheDocument()
  })
})
