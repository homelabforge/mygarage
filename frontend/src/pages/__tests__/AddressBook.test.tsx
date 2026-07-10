import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '../../__tests__/test-utils'  // no `screen` — tests select by id
import { AddressBookForm } from '../AddressBook'   // export the form (Step 3)

// vi.mock is hoisted above module-level consts, so spies must be created with
// vi.hoisted or the factory closes over uninitialized bindings (Codex R1-F4).
const { post, put } = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn() }))
vi.mock('../../services/api', () => ({ default: { post, put } }))

beforeEach(() => {
  vi.clearAllMocks()
  post.mockResolvedValue({ data: {} })
  put.mockResolvedValue({ data: {} })
})

const form = (c: HTMLElement) => c.querySelector('form') as HTMLFormElement
// Select by id, NOT label text — the global i18n test mock renders keys, so
// getByLabelText(/gas station/i) would not match the aria-label (Codex R1-F1).
const gasBox = () => document.getElementById('poi_gas_station') as HTMLInputElement | null

describe('AddressBookForm gas-station checkbox', () => {
  it('checked for a gas_station entry', () => {
    render(<AddressBookForm entry={{ id: 1, business_name: 'Shell', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(gasBox()).toBeChecked()
  })

  it('unchecked for an untagged entry', () => {
    render(<AddressBookForm entry={{ id: 2, business_name: 'Bob', poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(gasBox()).not.toBeChecked()
  })

  it('does NOT render the checkbox for a non-gas POI category (protects auto_shop etc.)', () => {
    render(<AddressBookForm entry={{ id: 3, business_name: 'Joe Auto', poi_category: 'auto_shop' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(gasBox()).toBeNull()
  })

  it('editing a non-gas entry never serializes poi_category (clobber proof; Codex R1-H1)', async () => {
    const { container } = render(<AddressBookForm entry={{ id: 3, business_name: 'Joe Auto', poi_category: 'auto_shop' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.submit(form(container))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect('poi_category' in body).toBe(false)  // omitted → backend preserves auto_shop
  })

  it('checking the box on an untagged entry submits poi_category="gas_station" (Codex R1-H2)', async () => {
    const { container } = render(<AddressBookForm entry={{ id: 4, business_name: 'New Fuel', poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.click(gasBox() as HTMLInputElement)
    fireEvent.submit(form(container))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.poi_category).toBe('gas_station')
  })

  it('unchecking a gas_station entry submits poi_category=null to clear it (Codex R1-H2)', async () => {
    const { container } = render(<AddressBookForm entry={{ id: 5, business_name: 'Shell', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.click(gasBox() as HTMLInputElement)  // uncheck
    fireEvent.submit(form(container))
    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.poi_category).toBeNull()
  })
})
