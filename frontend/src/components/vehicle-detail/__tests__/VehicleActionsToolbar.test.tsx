import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '../../../__tests__/test-utils'

const h = vi.hoisted(() => ({ authMode: 'local' }))

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ authMode: h.authMode }),
}))

import VehicleActionsToolbar from '../VehicleActionsToolbar'

beforeEach(() => {
  h.authMode = 'local'
})

function setup(overrides: Partial<ComponentProps<typeof VehicleActionsToolbar>> = {}) {
  const props: ComponentProps<typeof VehicleActionsToolbar> = {
    isAdmin: true, importing: false, exporting: false, isOnline: true,
    showFuelAction: true, hasStandardEquipment: true, hasOptionalEquipment: true,
    onLogService: vi.fn(), onAddFuel: vi.fn(), onReminder: vi.fn(),
    onEditEquipment: vi.fn(), onEdit: vi.fn(), onAnalytics: vi.fn(),
    onImport: vi.fn(), onExport: vi.fn(), onOpenModal: vi.fn(), onOpenMobileMenu: vi.fn(),
    ...overrides,
  }
  render(<VehicleActionsToolbar {...props} />)
  return props
}

// Phone and desktop each render the routine actions and CSS picks one; jsdom
// sees both, so desktop checks skip the phone group.
const phoneRow = (): HTMLElement => screen.getByRole('group', { name: 'detail.hero.quickActions' })
function desktopAction(name: string): HTMLElement {
  const desktop = screen.getAllByRole('button', { name }).filter((el) => !phoneRow().contains(el))
  expect(desktop).toHaveLength(1)
  return desktop[0]
}

describe('VehicleActionsToolbar', () => {
  it('renders every required title attribute (G6/B8)', () => {
    setup()
    for (const title of [
      'detail.misc.importTooltip', 'detail.exportTooltip', 'detail.analyticsTooltip',
      'detail.shareTooltip', 'detail.editVehicle', 'detail.misc.transferTooltip',
      'detail.removeVehicle',
    ]) {
      expect(screen.getByTitle(title)).toBeInTheDocument()
    }
  })

  it('fires the tab-switch and equipment callbacks on click (SDQ-1/2)', () => {
    const props = setup()
    fireEvent.click(desktopAction('detail.hero.logService'))
    fireEvent.click(desktopAction('detail.hero.addFuel'))
    fireEvent.click(desktopAction('detail.hero.reminder'))
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.standard' }))
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.optional' }))
    expect(props.onLogService).toHaveBeenCalledTimes(1)
    expect(props.onAddFuel).toHaveBeenCalledTimes(1)
    expect(props.onReminder).toHaveBeenCalledTimes(1)
    expect(props.onEditEquipment).toHaveBeenCalledWith('standard')
    expect(props.onEditEquipment).toHaveBeenCalledWith('optional')
  })

  // G2c-53 (D2): phones get the same three one-tap actions beside Actions,
  // away from Remove, calling the same callbacks as the desktop row.
  it('gives phones a one-tap Log Service / Add Fuel / Reminder row (G2c-53)', () => {
    const props = setup()
    const row = within(phoneRow())
    fireEvent.click(row.getByRole('button', { name: 'detail.hero.logService' }))
    fireEvent.click(row.getByRole('button', { name: 'detail.hero.addFuel' }))
    fireEvent.click(row.getByRole('button', { name: 'detail.hero.reminder' }))
    expect(props.onLogService).toHaveBeenCalledTimes(1)
    expect(props.onAddFuel).toHaveBeenCalledTimes(1)
    expect(props.onReminder).toHaveBeenCalledTimes(1)
    // Phone only, and the Actions trigger sits in the same strip.
    const strip = phoneRow().parentElement as HTMLElement
    expect(strip).toHaveClass('md:hidden')
    expect(within(strip).getByRole('button', { name: 'detail.actions' })).toBeInTheDocument()
    expect(within(strip).queryByRole('button', { name: 'detail.remove' })).not.toBeInTheDocument()
  })

  it('leaves Add Fuel out of the phone row when showFuelAction is false (G2c-53)', () => {
    setup({ showFuelAction: false })
    const row = within(phoneRow())
    expect(row.getByRole('button', { name: 'detail.hero.logService' })).toBeInTheDocument()
    expect(row.queryByRole('button', { name: 'detail.hero.addFuel' })).not.toBeInTheDocument()
  })

  it('hides Add Fuel when showFuelAction is false', () => {
    setup({ showFuelAction: false })
    expect(screen.queryByRole('button', { name: 'detail.hero.addFuel' })).not.toBeInTheDocument()
  })

  it('hides the whole Equipment group when neither list exists (B7)', () => {
    setup({ hasStandardEquipment: false, hasOptionalEquipment: false })
    expect(screen.queryByText('detail.hero.equipment')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.hero.standard' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.hero.optional' })).not.toBeInTheDocument()
  })

  it('shows only Standard when only standard equipment exists (B7)', () => {
    setup({ hasStandardEquipment: true, hasOptionalEquipment: false })
    expect(screen.getByRole('button', { name: 'detail.hero.standard' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.hero.optional' })).not.toBeInTheDocument()
  })

  // With sign-in off there's no user to share as, and the server 400s the
  // share anyway (A-12). isAdmin is false there too, so Transfer stays gone.
  it('hides Share and Transfer with sign-in off (A-12)', () => {
    h.authMode = 'none'
    setup({ isAdmin: false })
    expect(screen.queryByRole('button', { name: 'detail.share' })).not.toBeInTheDocument()
    expect(screen.queryByTitle('detail.shareTooltip')).not.toBeInTheDocument()
    expect(screen.queryByTitle('detail.misc.transferTooltip')).not.toBeInTheDocument()
  })

  it.each(['local', 'oidc'])('shows Share with auth mode %s and opens the sharing modal', (mode) => {
    h.authMode = mode
    const props = setup({ isAdmin: false })
    fireEvent.click(screen.getByRole('button', { name: 'detail.share' }))
    expect(props.onOpenModal).toHaveBeenCalledWith('sharing')
  })
})
