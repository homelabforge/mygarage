import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Field from '../Field'

describe('Field', () => {
  it('associates the label with the control via the caller id', () => {
    render(
      <Field id="nickname" label="Nickname">
        <input id="nickname" />
      </Field>,
    )
    expect(screen.getByLabelText('Nickname')).toHaveAttribute('id', 'nickname')
  })

  it('puts the required marker INSIDE the accessible name', () => {
    // VehicleEdit.test.tsx:189 queries findByLabelText('edit.nickname *').
    // aria-hidden on the asterisk, or moving it outside the <label>, breaks it.
    render(
      <Field id="nickname" label="Nickname" required>
        <input id="nickname" />
      </Field>,
    )
    expect(screen.getByLabelText('Nickname *')).toBeInTheDocument()
  })

  it('does not hide the required marker behind aria-hidden', () => {
    // getByLabelText (used above and by VehicleEdit.test.tsx) matches on the
    // <label>'s textContent — it does not run the accname algorithm and does
    // NOT exclude aria-hidden descendants. Verified experimentally: wrapping
    // the marker in <span aria-hidden="true"> still passes the test above.
    // getByRole computes the real accessible name (accname), which DOES
    // exclude aria-hidden content, so this is the assertion that actually
    // enforces "plain text, not a decoration."
    render(
      <Field id="nickname" label="Nickname" required>
        <input id="nickname" />
      </Field>,
    )
    expect(screen.getByRole('textbox', { name: 'Nickname *' })).toBeInTheDocument()
  })

  it('puts the unit suffix INSIDE the accessible name', () => {
    // VehicleEdit.test.tsx:237,250,266 query
    // findByLabelText('edit.defTankCapacity (L)').
    render(
      <Field id="def" label="DEF Tank Capacity" unit="L">
        <input id="def" />
      </Field>,
    )
    expect(screen.getByLabelText('DEF Tank Capacity (L)')).toBeInTheDocument()
  })

  it('composes required and unit in that order', () => {
    render(
      <Field id="x" label="Volume" required unit="gal">
        <input id="x" />
      </Field>,
    )
    expect(screen.getByLabelText('Volume * (gal)')).toBeInTheDocument()
  })

  it('renders a string error with an alert role', () => {
    render(
      <Field id="x" label="Cost" error="Required">
        <input id="x" />
      </Field>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
  })

  it('accepts a react-hook-form FieldError object', () => {
    render(
      <Field id="x" label="Cost" error={{ type: 'required', message: 'Required' }}>
        <input id="x" />
      </Field>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
  })

  it('renders no alert when there is no error', () => {
    render(
      <Field id="x" label="Cost">
        <input id="x" />
      </Field>,
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('gives hint and error deterministic ids the caller can point at', () => {
    // Field cannot attach aria-describedby itself — children is opaque and
    // cloneElement no-ops on the fragment/Controller shapes this codebase
    // uses — so it guarantees the ids instead and the caller wires them.
    const { container } = render(
      <Field id="cost" label="Cost" hint="Excluding tax." error="Required">
        <input id="cost" aria-describedby="cost-hint cost-error" />
      </Field>,
    )
    expect(container.querySelector('#cost-hint')).toHaveTextContent('Excluding tax.')
    expect(container.querySelector('#cost-error')).toHaveTextContent('Required')
    expect(screen.getByLabelText('Cost')).toHaveAccessibleDescription(
      'Excluding tax. Required',
    )
  })
})
