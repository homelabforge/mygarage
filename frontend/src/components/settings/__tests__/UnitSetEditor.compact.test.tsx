/**
 * The unit editor inside Quick Settings (`compact`).
 *
 * A 400 px drawer cannot take the page layout. Eleven selects left open push
 * every other preference out of sight, so under Custom they sit in an
 * accordion that stays closed until asked for. And the "a preset clears your
 * custom units" warning cannot be a full-screen overlay opened from inside a
 * drawer, so in compact mode it appears in place, under the buttons.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IMPERIAL_UNITS } from '@/__tests__/factories'
import { UNIT_OPTION_LABELS, type UnitPreference } from '@/types/units'
import UnitSetEditor from '../UnitSetEditor'
import { answerConfirm, withConfirm } from '../../../__tests__/confirmHelpers'

function renderEditor(preference: UnitPreference, compact = true) {
  const onSelect = vi.fn()
  const view = render(
    <UnitSetEditor compact={compact} preference={preference} units={IMPERIAL_UNITS} onSelect={onSelect} />,
    { wrapper: withConfirm },
  )
  const rerender = (next: UnitPreference): void =>
    view.rerender(
      <UnitSetEditor compact={compact} preference={next} units={IMPERIAL_UNITS} onSelect={onSelect} />,
    )
  return { onSelect, rerender }
}

const accordion = (): HTMLElement => screen.getByRole('button', { name: 'units.customToggle' })
const pressure = (): HTMLElement => screen.getByLabelText(UNIT_OPTION_LABELS.pressure.labelKey)

describe('UnitSetEditor, compact', () => {
  it('offers the accordion only once Custom is the choice', () => {
    const { rerender } = renderEditor('imperial')
    expect(screen.queryByRole('button', { name: 'units.customToggle' })).toBeNull()

    rerender('custom')

    expect(accordion()).toBeInTheDocument()
  })

  it('keeps the eleven quantities closed until asked, and closes them again', async () => {
    renderEditor('custom')

    // Closed: announced as collapsed, the selects cannot take focus, and the
    // panel's row is zero height. jsdom computes no layout, so the height is
    // asserted as the class that sets it; e2e/settings.spec.ts checks the
    // selects are really hidden in a browser.
    const panel = (): HTMLElement => document.getElementById(accordion().getAttribute('aria-controls') ?? '')!
    expect(accordion()).toHaveAttribute('aria-expanded', 'false')
    expect(pressure().closest('[inert]')).not.toBeNull()
    expect(panel()).toHaveClass('grid-rows-[0fr]')

    await userEvent.click(accordion())
    expect(accordion()).toHaveAttribute('aria-expanded', 'true')
    expect(pressure().closest('[inert]')).toBeNull()
    expect(panel()).toHaveClass('grid-rows-[1fr]')

    await userEvent.click(accordion())
    expect(accordion()).toHaveAttribute('aria-expanded', 'false')
    expect(pressure().closest('[inert]')).not.toBeNull()
  })

  it('opens the accordion when Custom is picked', async () => {
    const { onSelect, rerender } = renderEditor('imperial')

    await userEvent.click(screen.getByRole('button', { name: 'units.custom' }))
    rerender('custom')

    expect(onSelect).toHaveBeenCalledWith({ unit_preference: 'custom', units: IMPERIAL_UNITS })
    expect(accordion()).toHaveAttribute('aria-expanded', 'true')
  })

  it('asks in place, not in an overlay, before a preset clears custom units', async () => {
    const { onSelect } = renderEditor('custom')

    await userEvent.click(screen.getByRole('button', { name: 'units.metric' }))

    expect(screen.getByText('units.presetConfirmMessage').closest('.fixed')).toBeNull()
    expect(onSelect).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'units.presetConfirmAction' }))
    expect(onSelect).toHaveBeenCalledWith({ unit_preference: 'metric', units: null })
    expect(screen.queryByText('units.presetConfirmMessage')).toBeNull()
  })

  it('writes nothing when the in-place warning is cancelled', async () => {
    const { onSelect } = renderEditor('custom')

    await userEvent.click(screen.getByRole('button', { name: 'units.imperial' }))
    await userEvent.click(screen.getByRole('button', { name: 'common:cancel' }))

    expect(onSelect).not.toHaveBeenCalled()
    expect(screen.queryByText('units.presetConfirmMessage')).toBeNull()
  })
})

describe('UnitSetEditor, page layout', () => {
  it('shows the Custom grid open, with no accordion', () => {
    renderEditor('custom', false)

    expect(screen.queryByRole('button', { name: 'units.customToggle' })).toBeNull()
    expect(pressure().closest('[inert]')).toBeNull()
  })

  it("sizes the grid by the editor's own width, not the screen's", () => {
    // A breakpoint on the SCREEN put two columns into the 400 px drawer on any
    // desktop. A container query keys it to the editor: one column in the
    // drawer, two on the wide settings card.
    renderEditor('custom', false)

    const grid = pressure().closest('.grid')
    expect(grid).toHaveClass('@md:grid-cols-2')
    expect(grid).not.toHaveClass('sm:grid-cols-2')
  })
})

describe('UnitSetEditor, page', () => {
  it('keeps the preset confirm inside the safe area (#305)', async () => {
    renderEditor('custom', false)

    await userEvent.click(screen.getByRole('button', { name: 'units.metric' }))

    // The page asks through the app's confirm, and that dialog owns the safe area now.
    const dialog = await screen.findByRole('alertdialog', { name: 'units.presetConfirmTitle' })
    expect(dialog.closest('.modal-safe-pad')).not.toBeNull()
  })

  it('asks through the app confirm, with the consequence under the question', async () => {
    const { onSelect } = renderEditor('custom', false)

    await userEvent.click(screen.getByRole('button', { name: 'units.metric' }))

    const dialog = await screen.findByRole('alertdialog', { name: 'units.presetConfirmTitle' })
    expect(dialog).toHaveAccessibleDescription('units.presetConfirmMessage')
    expect(onSelect).not.toHaveBeenCalled()
    await answerConfirm('confirm', 'units.presetConfirmTitle')
    expect(onSelect).toHaveBeenCalledWith({ unit_preference: 'metric', units: null })
  })

  it('a cancelled preset confirm writes nothing', async () => {
    const { onSelect } = renderEditor('custom', false)

    await userEvent.click(screen.getByRole('button', { name: 'units.metric' }))
    await answerConfirm('cancel', 'units.presetConfirmTitle')

    expect(onSelect).not.toHaveBeenCalled()
  })
})
