import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import * as mobile from '../../utils/mobile'
import * as AuthContext from '../../contexts/AuthContext'
import MobileQuickEntryGate from '../MobileQuickEntryGate'

vi.mock('../../utils/mobile')
vi.mock('../../contexts/AuthContext')

type PartialUser = { id: number; mobile_quick_entry_enabled?: boolean }

function setup(user: PartialUser | null, isMobile: boolean, hasFlag = false) {
  if (hasFlag && user) {
    sessionStorage.setItem(`qe_redirected:${user.id}`, '1')
  }
  vi.spyOn(mobile, 'isMobileBrowser').mockReturnValue(isMobile)
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({ user } as ReturnType<typeof AuthContext.useAuth>)

  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<MobileQuickEntryGate />}>
          <Route index element={<div>Dashboard Content</div>} />
        </Route>
        <Route path="/quick-entry" element={<div>Quick Entry Content</div>} />
      </Routes>
    </MemoryRouter>
  )
}

const mobileUser: PartialUser = { id: 42, mobile_quick_entry_enabled: true }

describe('MobileQuickEntryGate', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.clearAllMocks()
  })

  it('redirects to /quick-entry on mobile with setting enabled and no session flag', () => {
    setup(mobileUser, true)
    expect(screen.getByText('Quick Entry Content')).toBeInTheDocument()
    expect(screen.queryByText('Dashboard Content')).not.toBeInTheDocument()
  })

  it('renders Dashboard when session flag is already set', () => {
    setup(mobileUser, true, true)
    expect(screen.getByText('Dashboard Content')).toBeInTheDocument()
    expect(screen.queryByText('Quick Entry Content')).not.toBeInTheDocument()
  })

  it('renders Dashboard on desktop regardless of setting', () => {
    setup(mobileUser, false)
    expect(screen.getByText('Dashboard Content')).toBeInTheDocument()
  })

  it('renders Dashboard when setting is false', () => {
    setup({ id: 42, mobile_quick_entry_enabled: false }, true)
    expect(screen.getByText('Dashboard Content')).toBeInTheDocument()
  })

  it('renders Dashboard when setting is undefined (never explicitly enabled)', () => {
    setup({ id: 42 }, true)
    expect(screen.getByText('Dashboard Content')).toBeInTheDocument()
  })
})
