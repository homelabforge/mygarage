import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor, screen, within } from '../../__tests__/test-utils' // selects by id (i18n mock renders keys)
import AddressBook, { AddressBookForm, displayCategory } from '../AddressBook'
import { validationError } from '../../__tests__/serverErrors'

// vi.mock is hoisted above module-level consts, so spies must be created with vi.hoisted.
const { get, post, put, del } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }))
vi.mock('../../services/api', () => ({ default: { get, post, put, delete: del } }))

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ data: { entries: [] } })
  post.mockResolvedValue({ data: {} })
  put.mockResolvedValue({ data: {} })
  del.mockResolvedValue({ data: {} })
})

// The form portals through the Drawer, so query the document, not a container.
const formEl = () => document.getElementById('address-book-form') as HTMLFormElement
const categorySelect = () => document.getElementById('category') as HTMLSelectElement
const businessInput = () => document.getElementById('business_name') as HTMLInputElement
const buttonWithText = (text: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes(text))

describe('displayCategory', () => {
  it('uses the manual category when set', () => {
    expect(displayCategory({ category: 'Service', poi_category: null })).toBe('Service')
  })
  it('derives Gas Station / RV Park from the POI type when there is no manual category', () => {
    expect(displayCategory({ category: null, poi_category: 'gas_station' })).toBe('Gas Station')
    expect(displayCategory({ category: '', poi_category: 'rv_shop' })).toBe('RV Park')
    expect(displayCategory({ category: null, poi_category: 'rv_park' })).toBe('RV Park')
  })
  it('files an auto shop under Service; only ev_charging and propane have no chip', () => {
    expect(displayCategory({ category: null, poi_category: 'auto_shop' })).toBe('Service')
    expect(displayCategory({ category: null, poi_category: 'ev_charging' })).toBe('')
    expect(displayCategory({ category: null, poi_category: 'propane' })).toBe('')
    expect(displayCategory({ category: '   ', poi_category: null })).toBe('')
  })

  // The POI Finder and the old fill-up quick add wrote a lowercase 'service' for
  // every place they saved, which matched no chip (#194).
  describe('a place saved before as lowercase service', () => {
    it('follows its POI type to the chip it belongs in', () => {
      expect(displayCategory({ category: 'service', poi_category: 'gas_station' })).toBe('Gas Station')
      expect(displayCategory({ category: 'service', poi_category: 'auto_shop' })).toBe('Service')
    })

    it('is Service when it has no POI type', () => {
      expect(displayCategory({ category: 'service', poi_category: null })).toBe('Service')
    })

    it('has no chip for a POI type without one, like an EV charger the POI Finder saves now', () => {
      expect(displayCategory({ category: 'service', poi_category: 'ev_charging' })).toBe('')
    })

    it('guard: a chip someone picked wins over the POI type (mutant: rule 1 ignores case)', () => {
      expect(displayCategory({ category: 'Service', poi_category: 'gas_station' })).toBe('Service')
    })
  })

  it('matches a chip ignoring case and surrounding spaces', () => {
    expect(displayCategory({ category: ' gas station ', poi_category: null })).toBe('Gas Station')
  })

  it('guard: keeps a custom category as typed (mutant: a category matching no chip returns empty)', () => {
    expect(displayCategory({ category: 'Body Shop', poi_category: null })).toBe('Body Shop')
  })
})

describe('AddressBook page: category chips', () => {
  it('shows a gas station the POI Finder saved as lowercase service under the Gas Station chip', async () => {
    get.mockResolvedValue({
      data: { entries: [{ id: 9, business_name: 'Corner Fuel', category: 'service', poi_category: 'gas_station' }] },
    })
    render(<AddressBook />)
    expect(await screen.findByText('Corner Fuel')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'common:addressBook.categoryGasStation' }))

    expect(screen.queryByText('Corner Fuel')).toBeInTheDocument()
  })
})

/**
 * Issue #179: the chevron button's `after:absolute after:inset-0` stretched a
 * pseudo-element over the whole contact card, so a long-press on a phone hit
 * the button and the address, phone and email couldn't be selected. The card
 * now goes through ClickableCard, which puts the handler on the card itself.
 *
 * jsdom has no layout and no long-press, so these pin STRUCTURE and HANDLERS
 * only: nothing stretched over the content, the click handled by the card, a
 * selection-end click ignored, the links left alone. Whether the text is
 * really on top in a browser is the E2E half (G9).
 */
describe('AddressBook page: the contact card keeps its text selectable (#179)', () => {
  const CONTACT = {
    id: 21,
    business_name: 'Summit Auto',
    name: 'Dana Reyes',
    category: 'Service',
    poi_category: null,
    email: 'desk@summit.test',
    phone: '555-0142',
    website: 'https://summit.test',
    address: '12 Main St',
    city: 'Boulder',
    state: 'CO',
    zip_code: '80301',
    notes: null,
  }
  const EDITOR = 'addressBook.editContact'
  const EDIT_BUTTON = 'addressBook.editContactNamed'

  beforeEach(() => {
    get.mockResolvedValue({ data: { entries: [CONTACT] } })
  })

  async function contactCard(): Promise<HTMLElement> {
    const card = (await screen.findByText('Summit Auto')).closest<HTMLElement>('.rounded-card')
    if (card === null) throw new Error('contact card not found')
    return card
  }

  const editorIsShut = (): void => {
    // hidden: true so a drawer the page made inert still counts as open.
    expect(screen.queryByRole('dialog', { name: EDITOR, hidden: true })).not.toBeInTheDocument()
  }

  it('no stretched link covers the contact card', async () => {
    // RED before G6: the chevron button carries `after:absolute after:inset-0`
    // and the three links sit on `relative z-10` to clear it. Now the only
    // positioned, lifted thing is ClickableCard's focus chip in the corner.
    // This pins the classes; how they paint is the browser's half.
    render(<AddressBook />)
    const card = await contactCard()
    const chip = within(card).getByRole('button', { name: EDIT_BUTTON }).parentElement as HTMLElement

    const everything = [card, ...Array.from(card.querySelectorAll<Element>('*'))]
    const tokensOf = (el: Element): string[] => (el.getAttribute('class') ?? '').split(/\s+/)
    const has = (el: Element, utility: RegExp): boolean => tokensOf(el).some((token) => utility.test(token))

    expect(everything.filter((el) => has(el, /^(?:[\w-]+:)*inset-0$/))).toEqual([])
    expect(everything.filter((el) => has(el, /^(?:[\w-]+:)*absolute$/))).toEqual([chip])
    expect(everything.filter((el) => has(el, /^(?:[\w-]+:)*z-\d+$/))).toEqual([chip])
  })

  it('clicking the address opens the editor', async () => {
    // RED before G6: the chevron button was a cousin of the address, not an
    // ancestor, so a click on the address text bubbled through divs with no
    // handler. jsdom does no hit-testing, so this is the handler half.
    render(<AddressBook />)
    await contactCard()
    editorIsShut()

    fireEvent.click(screen.getByText('12 Main St'))

    expect(screen.getByRole('dialog', { name: EDITOR })).toBeInTheDocument()
    expect(businessInput().value).toBe('Summit Auto')
  })

  it('the email, phone and website links do not open the editor', async () => {
    // Guard: the links sat on z-10 clear of the stretched button, so before
    // G6 their clicks never reached it either. Mutant that kills it: drop
    // cameFromNestedControl from ClickableCard's handler, and each link click
    // bubbles to the card and opens the editor on the way out. The last click
    // is RED before G6 and keeps the rest from passing on a dead card.
    render(<AddressBook />)
    const card = await contactCard()
    const links = [
      within(card).getByRole('link', { name: 'desk@summit.test' }),
      within(card).getByRole('link', { name: '555-0142' }),
      within(card).getByRole('link', { name: 'https://summit.test' }),
    ]

    for (const link of links) {
      // jsdom can't follow mailto:, tel: or another site and logs about it.
      // The card never looks at defaultPrevented, so this hides nothing.
      link.addEventListener('click', (event) => event.preventDefault())
      fireEvent.click(link)
      editorIsShut()
    }

    fireEvent.click(screen.getByText('12 Main St'))
    expect(screen.getByRole('dialog', { name: EDITOR })).toBeInTheDocument()
  })

  it('ending a selection on the address does not open the editor', async () => {
    // The first half is a guard (no handler on the card before G6, so nothing
    // opened). Mutant that kills it: skip isSelectingText in ClickableCard's
    // handler. The second half is RED before G6 and keeps the first from
    // passing on a card that never opens anything.
    render(<AddressBook />)
    await contactCard()
    const selection = vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      toString: () => '12 Main St',
    } as unknown as Selection)
    try {
      fireEvent.click(screen.getByText('12 Main St'))
      editorIsShut()
    } finally {
      selection.mockRestore()
    }

    fireEvent.click(screen.getByText('12 Main St'))
    expect(screen.getByRole('dialog', { name: EDITOR })).toBeInTheDocument()
  })

  it('the edit action is reachable by a button named addressBook.editContactNamed', async () => {
    // Guard: the chevron was a button by this name before G6, and the name
    // moves to ClickableCard's keyboard button. Mutant that kills it: hand
    // ClickableCard an empty label. getByRole also wants exactly ONE, so a
    // chevron left behind as a second button by the same name fails too.
    render(<AddressBook />)
    const button = within(await contactCard()).getByRole('button', { name: EDIT_BUTTON })

    button.focus()
    expect(button).toHaveFocus()
    fireEvent.click(button)

    expect(screen.getByRole('dialog', { name: EDITOR })).toBeInTheDocument()
    expect(businessInput().value).toBe('Summit Auto')
  })
})

describe('AddressBookForm — category (no more gas-station checkbox)', () => {
  it('drops the gas-station checkbox entirely', () => {
    render(<AddressBookForm entry={{ id: 1, business_name: 'Shell', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(document.getElementById('poi_gas_station')).toBeNull()
  })

  it('pre-selects "Gas Station" for a poi_category=gas_station entry with no manual category', () => {
    render(<AddressBookForm entry={{ id: 1, business_name: 'Shell', category: null, poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('Gas Station')
  })

  it('pre-selects "RV Park" for an rv_shop POI entry', () => {
    render(<AddressBookForm entry={{ id: 2, business_name: 'Riverside', category: null, poi_category: 'rv_shop' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('RV Park')
  })

  it('uses the manual category when one is set', () => {
    render(<AddressBookForm entry={{ id: 3, business_name: 'Summit', category: 'Service', poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('Service')
  })
})

describe('AddressBookForm: submit leaves poi_category out unless it re-files a gas station', () => {
  it('editing a POI entry omits poi_category (backend preserves the discovery value) and keeps category', async () => {
    render(<AddressBookForm entry={{ id: 3, business_name: 'Joe Auto', category: 'Service', poi_category: 'auto_shop' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    const body = put.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect('poi_category' in body).toBe(false)
    // Untouched, so not sent at all: omitted keeps it.
    expect('category' in body).toBe(false)
  })

  it('adding routes to create with the chosen category and no poi_category', async () => {
    render(<AddressBookForm entry={null} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(businessInput(), { target: { value: 'New Fuel' } })
    fireEvent.change(categorySelect(), { target: { value: 'Gas Station' } })
    fireEvent.submit(formEl())
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(put).not.toHaveBeenCalled()
    const body = post.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.business_name).toBe('New Fuel')
    expect(body.category).toBe('Gas Station')
    expect('poi_category' in body).toBe(false)
  })
})

describe('AddressBookForm: a gas station filed under another chip stops being one (#194)', () => {
  const lastPut = () => put.mock.calls.at(-1)?.[1] as Record<string, unknown>
  const save = async (): Promise<void> => {
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
  }

  it('clears the gas_station tag when another chip is picked', async () => {
    // The backend keeps the tag unless told, so the page said Service while the
    // fill-up still offered it and vendor sync skipped it.
    render(<AddressBookForm entry={{ id: 1, business_name: 'Shell', category: null, poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(categorySelect(), { target: { value: 'Service' } })
    await save()
    expect(lastPut().category).toBe('Service')
    expect(lastPut()).toHaveProperty('poi_category', null)
  })

  it('clears it on a save of a station already filed under another chip', async () => {
    render(<AddressBookForm entry={{ id: 2, business_name: 'Corner Shop', category: 'Service', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('Service')
    await save()
    expect(lastPut()).toHaveProperty('poi_category', null)
    expect('category' in lastPut()).toBe(false)
  })

  it('clears it under a custom category too, which the page shows instead of Gas Station', async () => {
    render(<AddressBookForm entry={{ id: 3, business_name: 'Tow Stop', category: 'Towing', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('Towing')
    await save()
    expect(lastPut()).toHaveProperty('poi_category', null)
  })

  it('guard: keeps the tag while Gas Station stays picked (mutant: clear any gas_station tag)', async () => {
    render(<AddressBookForm entry={{ id: 4, business_name: 'Shell', category: null, poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    await save()
    expect('poi_category' in lastPut()).toBe(false)
  })

  it('guard: keeps the tag when the category is emptied, since it still reads Gas Station (mutant: clear unless the value is Gas Station)', async () => {
    render(<AddressBookForm entry={{ id: 5, business_name: 'Corner Shop', category: 'Service', poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(categorySelect(), { target: { value: '' } })
    await save()
    expect(lastPut().category).toBeNull()
    expect('poi_category' in lastPut()).toBe(false)
  })

  it.each(['auto_shop', 'rv_shop', 'ev_charging', 'propane'])(
    'guard: a %s tag stays whatever chip is picked (mutant: clear any tag when the chip is not Gas Station)',
    async (poi) => {
      render(<AddressBookForm entry={{ id: 6, business_name: 'Somewhere', category: null, poi_category: poi } as never} onClose={() => {}} onSuccess={() => {}} />)
      fireEvent.change(categorySelect(), { target: { value: 'Dealer' } })
      await save()
      expect(lastPut().category).toBe('Dealer')
      expect('poi_category' in lastPut()).toBe(false)
    },
  )
})

describe('AddressBookForm — delete + notes placeholder', () => {
  it('deletes via the footer Delete button (edit mode) after confirm', async () => {
    const onSuccess = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<AddressBookForm entry={{ id: 7, business_name: 'Old Shop' } as never} onClose={() => {}} onSuccess={onSuccess} />)
    const btn = buttonWithText('common:delete')
    expect(btn).toBeTruthy()
    fireEvent.click(btn as HTMLButtonElement)
    await waitFor(() => expect(del).toHaveBeenCalledWith('/address-book/7'))
    expect(onSuccess).toHaveBeenCalled()
  })

  it('renders a real notes placeholder (guards the [object Object] regression)', () => {
    render(<AddressBookForm entry={null} onClose={() => {}} onSuccess={() => {}} />)
    const notes = document.getElementById('notes') as HTMLTextAreaElement
    expect(notes.placeholder).toBe('addressBook.notesPlaceholder')
    expect(notes.placeholder).not.toContain('object Object')
  })
})

describe('AddressBookForm: an untouched edit writes nothing it did not load', () => {
  const lastPut = () => put.mock.calls.at(-1)?.[1] as Record<string, unknown>

  it('keeps a custom stored category as the selected option and does not post it', async () => {
    render(<AddressBookForm entry={{ id: 4, business_name: 'Shine Co', category: 'Detailer', poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    expect(categorySelect().value).toBe('Detailer')
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect('category' in lastPut()).toBe(false)
  })

  it('does not post a category derived from the POI type', async () => {
    render(<AddressBookForm entry={{ id: 1, business_name: 'Shell', category: null, poi_category: 'gas_station' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect('category' in lastPut()).toBe(false)
  })

  it('does not rewrite where the entry came from', async () => {
    render(<AddressBookForm entry={{ id: 5, business_name: 'Found It', category: null, poi_category: null, source: 'osm' } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect('source' in lastPut()).toBe(false)
  })

  it('posts a changed category, and null for a cleared one', async () => {
    render(<AddressBookForm entry={{ id: 3, business_name: 'Summit', category: 'Service', poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(categorySelect(), { target: { value: '' } })
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(lastPut().category).toBeNull()
  })

  it('sends an emptied email, which the server stores as cleared', async () => {
    render(<AddressBookForm entry={{ id: 6, business_name: 'Mail Co', email: 'a@b.co', category: null, poi_category: null } as never} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(document.getElementById('email') as HTMLInputElement, { target: { value: '' } })
    fireEvent.submit(formEl())
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(lastPut().email).toBe('')
  })

  it('still marks a new entry as manual', async () => {
    render(<AddressBookForm entry={null} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(businessInput(), { target: { value: 'New Place' } })
    fireEvent.submit(formEl())
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect((post.mock.calls.at(-1)?.[1] as Record<string, unknown>).source).toBe('manual')
  })
})

describe('AddressBookForm: a rejected save', () => {
  const banner = (): HTMLElement | null => screen.queryByText(/^Failed to addressBook\.saveAction\./)
  const openAdd = (): void => {
    render(<AddressBookForm entry={null} onClose={() => {}} onSuccess={() => {}} />)
    fireEvent.change(businessInput(), { target: { value: 'Corner Fuel' } })
  }

  it('a non-422 failure shows the banner and no field error', async () => {
    post.mockRejectedValueOnce(new Error('Network Error'))
    openAdd()
    fireEvent.submit(formEl())

    expect(await screen.findByText('Failed to addressBook.saveAction. Network Error')).toBeInTheDocument()
    expect(document.getElementById('business_name-error')).toBeNull()
  })

  it('a 422 on business_name shows under it and no banner', async () => {
    post.mockRejectedValueOnce(validationError({ business_name: 'String should have at most 150 characters' }))
    openAdd()
    fireEvent.submit(formEl())

    await waitFor(() => expect(document.getElementById('business_name-error')).not.toBeNull())
    expect(document.getElementById('business_name-error')).toHaveTextContent('String should have at most 150 characters')
    expect(banner()).toBeNull()
  })
})
