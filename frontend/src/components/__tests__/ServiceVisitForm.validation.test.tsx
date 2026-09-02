import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import api from '../../services/api'

/**
 * Native constraints on this form abort submit silently.
 *
 * `<form onSubmit={handleSubmit}>` had no `noValidate`, and the inputs inside
 * it carry `required`, `min` and `step`. When a constraint fails the browser
 * aborts the submit and tries to focus the offending control -- but the
 * per-line-item fields live in sections that may be collapsed or scrolled
 * away, where the browser cannot focus them, so nothing is shown and Save
 * appears to do nothing at all.
 *
 * The fix is `noValidate` plus real validation. `noValidate` ALONE would be
 * worse than the bug: `required` on the visit date (`:553`) is the only thing
 * currently stopping a blank date from reaching the API, and `handleSubmit`
 * checked only line-item descriptions and inspection results. That would turn
 * a silent no-op into a silent bad write.
 *
 * So each test below seeds a value that the removed native constraint used to
 * reject, and asserts two things: a visible error, and that no request was
 * sent. Asserting only the error would pass against a form that shows a
 * message and posts anyway.
 */

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
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

vi.mock('../VendorSearch', () => ({ default: () => <div data-testid="vendor-search" /> }))
vi.mock('../LineItemEditor', () => ({ default: () => <div data-testid="line-item-editor" /> }))
vi.mock('../ServiceVisitAttachmentUpload', () => ({
  default: () => <div data-testid="attachment-upload" />,
}))
vi.mock('../ServiceVisitAttachmentList', () => ({
  default: () => <div data-testid="attachment-list" />,
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const DEFAULT_PROPS = { vin: 'TEST123', onClose: vi.fn(), onSuccess: vi.fn() }

const save = async () => {
  const user = userEvent.setup()
  // The submit button lives OUTSIDE the <form> and is bound to it with
  // `form="service-visit-form"`, so it is found by attribute rather than by
  // an accessible name that the i18n mock renders as a raw key.
  const button = document.querySelector(
    'button[type="submit"][form="service-visit-form"]'
  ) as HTMLButtonElement
  expect(button).toBeTruthy()
  await user.click(button)
  return user
}

describe('ServiceVisitForm – native constraints are replaced, not just disabled', () => {
  beforeEach(() => vi.clearAllMocks())

  it('the form does not defer to browser validation', () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    // The form renders inside a portalled drawer, so it is on document, not
    // inside RTL's container.
    const form = document.querySelector('form#service-visit-form') as HTMLFormElement
    expect(form).toBeTruthy()
    expect(form.noValidate).toBe(true)
  })

  it('carries no native constraint attributes that could abort a submit', () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    // The form renders inside a portalled drawer, so it is on document, not
    // inside RTL's container.
    const form = document.querySelector('form#service-visit-form') as HTMLFormElement
    // Enumerated by ATTRIBUTE across every control in the rendered form,
    // rather than by a list of fields someone remembered. `required` is a
    // bare boolean in JSX and has no `=`, which is how it survived two
    // hand-written inventories of this form.
    const offenders = Array.from(form.querySelectorAll('input, select, textarea')).filter((el) =>
      ['required', 'min', 'max', 'step', 'pattern', 'minlength', 'maxlength'].some((a) =>
        el.hasAttribute(a)
      )
    )
    expect(offenders.map((el) => `${el.id || el.getAttribute('name')}`)).toEqual([])
  })

  it('rejects a blank date with a visible error and sends nothing', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    const user = userEvent.setup()
    const date = screen.getByLabelText(/date/i) as HTMLInputElement
    await user.clear(date)

    await save()

    expect(await screen.findByText(/required|common:required/i)).toBeTruthy()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('rejects a negative odometer with a visible error and sends nothing', async () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    const user = userEvent.setup()
    const odo = screen.getByLabelText(/mileage/i) as HTMLInputElement
    await user.clear(odo)
    await user.type(odo, '-5')

    await save()

    expect(await screen.findByText(/negative|atLeast|min/i)).toBeTruthy()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('rejects too many decimal places with a visible error and sends nothing', async () => {
    // The `step` case. More likely in practice than a negative number: a user
    // typing a third decimal into a currency field was silently blocked with
    // no message at all.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    const user = userEvent.setup()
    const tax = screen.getByLabelText(/tax/i) as HTMLInputElement
    await user.clear(tax)
    await user.type(tax, '12.005')

    await save()

    expect(await screen.findByText(/decimal|step|precision/i)).toBeTruthy()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('does not reject a form whose fields are all valid', async () => {
    // Guards the guard: without this, a validator that rejects everything
    // would pass every test above.
    //
    // A pristine form cannot reach `api.post` -- it starts with one empty line
    // item, and the pre-existing description check blocks it, with
    // `LineItemEditor` mocked out here so the description cannot be filled in.
    // So this asserts the thing actually under test: the new FIELD-level
    // validation passes, and the only complaint is the older form-level one.
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await save()

    expect(await screen.findByText(/allLineItemsNeedDescription/i)).toBeTruthy()
    // None of the field-level messages this file added.
    expect(screen.queryByText(/mustNotBeNegative|tooManyDecimals|mustBeANumber/i)).toBeNull()
  })
})
