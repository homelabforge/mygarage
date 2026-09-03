/**
 * The nested half of "native constraints are replaced, not just disabled".
 *
 * `ServiceVisitForm.validation.test.tsx` MOCKS `LineItemEditor`, so neither its
 * behavioural cases nor its structural sweep can see the per-line-item inputs
 * at all. Those are the ones that matter most: they live in sections that can
 * be collapsed or scrolled away, which is exactly where a native constraint
 * aborts a submit with nothing shown, and they were missed by two hand-written
 * revisions of the fix.
 *
 * `validateLineItems` is what replaced `min="0"`, `step="0.01"`, `min="1"` and
 * `SupplyUsedPicker`'s unit-dependent `step`. It had no test of any kind: six
 * branches, and the only thing standing between a removed browser constraint
 * and a bad write. Each branch gets one here, and each asserts BOTH a visible
 * message and that nothing was posted, because a form that complains and posts
 * anyway is the failure this whole change exists to avoid.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import { useSupplies } from '../../hooks/queries/useSupplies'
import type { Supply } from '../../types/supplies'

const mockedApiGet = vi.fn().mockResolvedValue({ data: { items: [] } })
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'metric',
      showBoth: false,
      units: METRIC_UNITS,
      gallonStandard: 'us',
    }),
  }
})

vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

/** A COUNT supply, so the whole-number branch is reachable. */
const OIL_FILTER: Supply = {
  id: 1,
  name: 'Oil Filter',
  unit_type: 'count',
  avg_unit_cost: '10.00',
  on_hand: '20',
  is_active: true,
  is_negative: false,
  created_at: '2026-01-01T00:00:00',
  category: null,
  notes: null,
  part_number: null,
  updated_at: null,
  vin: null,
}

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: vi.fn(() => ({
    data: { supplies: [OIL_FILTER], total: 1 },
    isSuccess: true,
    isLoading: false,
    isError: false,
  })),
}))

vi.mock('../VendorSearch', () => ({ default: () => <div data-testid="vendor-search" /> }))
vi.mock('../ServiceVisitAttachmentUpload', () => ({
  default: () => <div data-testid="attachment-upload" />,
}))
vi.mock('../ServiceVisitAttachmentList', () => ({
  default: () => <div data-testid="attachment-list" />,
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const DEFAULT_PROPS = { vin: 'TEST123', onClose: vi.fn(), onSuccess: vi.fn() }

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

/** The line item needs a description, or its own check fires first. */
const describeTheWork = () =>
  fireEvent.change(screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst'), {
    target: { value: 'Oil change' },
  })

const costField = (): HTMLInputElement =>
  screen.getByText('lineItemEditor.cost').parentElement?.querySelector(
    'input[type="number"]'
  ) as HTMLInputElement

const addSupplyRow = () => fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))

const quantityField = (): HTMLInputElement =>
  screen.getByRole('spinbutton', { name: 'service.suppliesQuantity' }) as HTMLInputElement

/** Submit and assert nothing reached the API. */
const submitAndExpectRefusal = async (message: RegExp) => {
  fireEvent.submit(drawerForm())
  expect(await screen.findByText(message)).toBeTruthy()
  await waitFor(() => expect(mockedApiPost).not.toHaveBeenCalled())
}

describe('ServiceVisitForm — the line-item constraints that replaced native ones', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useSupplies).mockReturnValue({
      data: { supplies: [OIL_FILTER], total: 1 },
      isSuccess: true,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useSupplies>)
  })

  it('the real nested inputs carry no native constraint either', () => {
    // The structural sweep in ServiceVisitForm.validation.test.tsx runs with
    // LineItemEditor MOCKED, so it enumerates a tree these inputs are not in.
    // This one renders them for real. `required` is a bare JSX boolean with no
    // `=`, which is how the visit date survived two inventories of this form.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    addSupplyRow()

    const form = drawerForm()
    const offenders = Array.from(form.querySelectorAll('input, select, textarea')).filter((el) =>
      ['required', 'min', 'max', 'step', 'pattern', 'minlength', 'maxlength'].some((a) =>
        el.hasAttribute(a)
      )
    )
    expect(offenders.map((el) => el.id || el.getAttribute('aria-label'))).toEqual([])
  })

  it('refuses a negative line-item cost', async () => {
    // Replaced `min="0"` at LineItemEditor:226. Under the native rule this
    // aborted submit with no message, and the row may not even be on screen.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    fireEvent.change(costField(), { target: { value: '-5' } })

    await submitAndExpectRefusal(/lineItemCostNegative/)
  })

  it('refuses a third decimal place on a line-item cost', async () => {
    // Replaced `step="0.01"`. The likelier of the two in practice: a negative
    // cost is rare, a third decimal is not, and `stepMismatch` showed nothing.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    fireEvent.change(costField(), { target: { value: '12.005' } })

    await submitAndExpectRefusal(/lineItemCostDecimals/)
  })

  it('treats unparseable text as no cost, rather than throwing or posting NaN', async () => {
    // The specific failure `SupplyHistoryModal` records is a THROW: RHF's own
    // `min` coerces with unary `+` and blows up on the symbol
    // `registerDecimal` emits for unparseable text. Nothing here throws, and
    // nothing garbage reaches the API.
    //
    // Note on `validateLineItems`' `Number.isNaN(item.cost)` branch: it has no
    // test because it has no reachable input. `type="number"` sanitises 'abc'
    // to '' in jsdom and in browsers, and the handler maps '' to `undefined`
    // before the validator ever sees it. It is kept as cheap defence for
    // paste and programmatic paths rather than deleted to satisfy a coverage
    // rule, and this note is here so that is a recorded decision rather than
    // an oversight the next reader has to re-derive.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    fireEvent.change(costField(), { target: { value: 'abc' } })

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { cost?: number | null }[]
    }
    expect(body.line_items[0].cost ?? null).toBeNull()
  })

  it('refuses a negative supply quantity', async () => {
    // Replaced SupplyUsedPicker's `min="0"`, which is the most deeply nested
    // control in this form.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    addSupplyRow()
    fireEvent.change(quantityField(), { target: { value: '-2' } })

    await submitAndExpectRefusal(/supplyQuantityInvalid/)
  })

  it('refuses a fractional quantity of a counted supply', async () => {
    // Replaced SupplyUsedPicker's unit-dependent `step`, which was `'1'` for a
    // count. The backend enforces only `gt=0`, so dropping this check rather
    // than moving it would let "2.5 oil filters" through.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    addSupplyRow()
    fireEvent.change(quantityField(), { target: { value: '2.5' } })

    await submitAndExpectRefusal(/supplyQuantityWholeNumber/)
  })

  it('posts a line item whose numbers are all fine', async () => {
    // The positive control. Without it every test above is satisfied by a form
    // that refuses everything.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    describeTheWork()
    fireEvent.change(costField(), { target: { value: '12.34' } })
    addSupplyRow()
    fireEvent.change(quantityField(), { target: { value: '2' } })

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as {
      line_items: { cost: number; supplies_used: { quantity: number }[] }[]
    }
    expect(body.line_items[0].cost).toBe(12.34)
    expect(body.line_items[0].supplies_used[0].quantity).toBe(2)
  })
})
