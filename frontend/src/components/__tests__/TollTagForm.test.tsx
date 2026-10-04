import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useTranslation } from 'react-i18next'
import { render } from '../../__tests__/test-utils'
import type { TollTag } from '../../types/toll'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useTollRecords', () => ({
  useCreateTollTag: () => ({ mutateAsync: createMutateAsync }),
  useUpdateTollTag: () => ({ mutateAsync: updateMutateAsync }),
}))
// The country guess reads the currency setting. The real hook needs an AuthProvider.
const currency = vi.hoisted(() => ({ code: 'USD' }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: currency.code, locale: 'en-US', formatCurrency: vi.fn() }),
}))

import TollTagForm from '../TollTagForm'

beforeEach(() => {
  vi.clearAllMocks()
  currency.code = 'USD'
})

const OTHER = '__other__'
const control = <T extends HTMLElement>(id: string) => document.getElementById(id) as T
const countrySelect = () => screen.getByLabelText('toll.country *')
const systemSelect = () => screen.getByLabelText('toll.tollSystem *')
const nameInput = () => screen.getByLabelText('toll.tollSystemName *')
const tagOf = (toll_system: string): TollTag =>
  ({ id: 4, vin: 'V1', toll_system, tag_number: 'PP123', status: 'active', notes: '' }) as unknown as TollTag

async function fillTagNumber(user: ReturnType<typeof userEvent.setup>) {
  await user.clear(screen.getByLabelText('toll.tagNumber *'))
  await user.type(screen.getByLabelText('toll.tagNumber *'), '0012345678')
}

// M1: fill via the LABEL→control association (getByLabelText) with async userEvent: realistic
// typing/selection, never fireEvent.change, so a dropped Field htmlFor/id link fails the test.
// Reading a control's value by id is fine. The i18n mock echoes keys, so Field renders these exact
// accessible names (label + ' *' on required fields).
describe('TollTagForm: routing + exact payload (SDQ-C)', () => {
  it('create submits the COMPLETE payload INCLUDING vin, and NEVER calls update', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), 'E-ZPass')
    await fillTagNumber(user)
    await user.type(screen.getByLabelText('common:notes'), 'primary tag')
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // Country and the typed name are form-only. Only toll_system reaches the API.
    expect(createMutateAsync.mock.calls[0][0]).toStrictEqual({
      toll_system: 'E-ZPass',
      tag_number: '0012345678',
      status: 'active',
      notes: 'primary tag',
      vin: 'V1',
    })
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('edit submits the UPDATE payload, routing id + edited field, NO vin, and NEVER calls create', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={{ ...tagOf('SunPass'), tag_number: 'ABC', status: 'inactive' } as TollTag} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('toll.tagNumber *'))
    await user.type(screen.getByLabelText('toll.tagNumber *'), 'XYZ')
    await user.click(screen.getByRole('button', { name: 'toll.updateTag' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    expect(updateMutateAsync.mock.calls[0][0]).toStrictEqual({
      id: 4,
      toll_system: 'SunPass',
      tag_number: 'XYZ',
      status: 'inactive',
      notes: '',
    })
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('the Field labels resolve to the controls carrying the expected ids', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(countrySelect()).toHaveAttribute('id', 'toll_country')
    expect(systemSelect()).toHaveAttribute('id', 'toll_system')
    expect(screen.getByLabelText('toll.tagNumber *')).toHaveAttribute('id', 'tag_number')
    await user.selectOptions(systemSelect(), OTHER)
    expect(nameInput()).toHaveAttribute('id', 'toll_system_other')
  })
})

describe('TollTagForm: country, then toll system', () => {
  it('a new tag starts on the guessed country with no toll system, and will not save without one', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLSelectElement>('toll_country').value).toBe('US')
    expect(control<HTMLSelectElement>('toll_system').value).toBe('')
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    expect(await screen.findByText('common:validation.tollTag.systemRequired')).toBeInTheDocument()
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('with no single country to guess, the toll system waits for one', async () => {
    currency.code = 'GBP'
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLSelectElement>('toll_country').value).toBe('')
    expect(systemSelect()).toBeDisabled()
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    expect(await screen.findByText('common:validation.tollTag.countryRequired')).toBeInTheDocument()
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('changing country clears a system the new country does not list', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), 'E-ZPass')
    await user.selectOptions(countrySelect(), 'MY')
    expect(control<HTMLSelectElement>('toll_system').value).toBe('')
    const offered = [...control<HTMLSelectElement>('toll_system').options].map((o) => o.value)
    expect(offered).toContain('Touch \'n Go RFID')
    expect(offered).not.toContain('E-ZPass')
    // Cleared in form state, not just hidden: going back doesn't bring E-ZPass back.
    await user.selectOptions(countrySelect(), 'US')
    expect(control<HTMLSelectElement>('toll_system').value).toBe('')
    await user.selectOptions(countrySelect(), 'MY')
    await user.selectOptions(systemSelect(), 'Touch \'n Go RFID')
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ toll_system: 'Touch \'n Go RFID' })
  })

  it('country Other focuses the name field and saves the tidied typed name', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(countrySelect(), OTHER)
    await waitFor(() => expect(nameInput()).toHaveFocus())
    expect(systemSelect()).toBeDisabled()
    expect(control<HTMLSelectElement>('toll_system').value).toBe(OTHER)
    await user.type(nameInput(), '  Via   Verde ')
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ toll_system: 'Via Verde' })
  })

  it('a typed name that is on the list says so and saves the listed spelling', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), OTHER)
    expect(control('toll_system_other-hint')).toHaveTextContent('toll.tollSystemNameHint')
    await user.type(nameInput(), 'ezpass')
    expect(control('toll_system_other-hint')).toHaveTextContent('toll.tollSystemSavesAs')
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ toll_system: 'E-ZPass' })
  })

  it('Other with nothing typed will not save', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), OTHER)
    await fillTagNumber(user)
    await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
    expect(await screen.findByText('common:validation.tollTag.systemNameRequired')).toBeInTheDocument()
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('TollTagForm: tags saved off the list', () => {
  async function saveUntouched(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('button', { name: 'toll.updateTag' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    return updateMutateAsync.mock.calls[0][0]
  }

  it('an off-list name opens on Other with the name filled in and re-saves unchanged', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('PikePass')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLSelectElement>('toll_country').value).toBe('US')
    expect(control<HTMLSelectElement>('toll_system').value).toBe(OTHER)
    expect(control<HTMLInputElement>('toll_system_other').value).toBe('PikePass')
    // setFocus focuses on a setTimeout, so let one pass before checking it didn't.
    await new Promise((r) => setTimeout(r, 0))
    expect(nameInput()).not.toHaveFocus()
    expect(await saveUntouched(user)).toMatchObject({ toll_system: 'PikePass' })
  })

  it('the old literal "Other" opens the same way and re-saves unchanged', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('Other')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLInputElement>('toll_system_other').value).toBe('Other')
    expect(await saveUntouched(user)).toMatchObject({ toll_system: 'Other' })
  })

  it('with no country to guess, an off-list name opens on country Other', async () => {
    currency.code = 'GBP'
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('PikePass')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLSelectElement>('toll_country').value).toBe(OTHER)
    expect(await saveUntouched(user)).toMatchObject({ toll_system: 'PikePass' })
  })

  it('a loose spelling of a listed system opens on it and saves the listed spelling', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('sunpass ')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(control<HTMLSelectElement>('toll_system').value).toBe('SunPass')
    expect(await saveUntouched(user)).toMatchObject({ toll_system: 'SunPass' })
  })

  it('switching to a listed system saves it, not the hidden name', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('PikePass')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), 'SunPass')
    expect(screen.queryByLabelText('toll.tollSystemName *')).toBeNull()
    expect(await saveUntouched(user)).toStrictEqual({
      id: 4, toll_system: 'SunPass', tag_number: 'PP123', status: 'active', notes: '',
    })
  })

  it('switching away from Other and back brings the saved name back', async () => {
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('PikePass')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(systemSelect(), 'SunPass')
    await user.selectOptions(systemSelect(), OTHER)
    expect(control<HTMLInputElement>('toll_system_other').value).toBe('PikePass')
    expect(await saveUntouched(user)).toMatchObject({ toll_system: 'PikePass' })
  })
})

describe('TollTagForm: review focus', () => {
  it('a language change while open keeps the country, system and typed values, and renames the options', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(countrySelect(), 'MY')
    await user.selectOptions(systemSelect(), 'Touch \'n Go RFID')
    await fillTagNumber(user)
    // The global mock hands every caller the same i18n object.
    const { i18n } = useTranslation()
    // Malay, because its order differs from English (Italian's doesn't).
    i18n.language = 'ms'
    try {
      rerender(<TollTagForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
      expect(control<HTMLSelectElement>('toll_country').value).toBe('MY')
      expect(control<HTMLSelectElement>('toll_system').value).toBe('Touch \'n Go RFID')
      expect(control<HTMLInputElement>('tag_number').value).toBe('0012345678')
      const countries = [...control<HTMLSelectElement>('toll_country').options].filter((o) => o.value !== '' && o.value !== OTHER)
      expect(countries.map((o) => o.text)).toEqual(['Amerika Syarikat', 'Itali', 'Malaysia'])
      await user.click(screen.getByRole('button', { name: 'toll.addTag' }))
      await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
      expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ toll_system: 'Touch \'n Go RFID', tag_number: '0012345678' })
    } finally {
      i18n.language = 'en'
    }
  })

  it('a server error on the toll system shows under the name field when the name is in use', async () => {
    updateMutateAsync.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: [{ type: 'string_too_long', loc: ['body', 'toll_system'], msg: 'String should have at most 50 characters' }] },
      },
    })
    const user = userEvent.setup()
    render(<TollTagForm vin="V1" tag={tagOf('PikePass')} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'toll.updateTag' }))
    await waitFor(() => expect(control('toll_system_other-error')).not.toBeNull())
    expect(control('toll_system_other-error')).toHaveTextContent(/at most 50 characters/)
    expect(control('toll_system-error')).toBeNull()
  })
})
