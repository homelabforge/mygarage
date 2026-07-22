import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import OfflineBanner from '../OfflineBanner'
import * as onlineStatus from '../../hooks/useOnlineStatus'

vi.mock('../../hooks/useOnlineStatus')

afterEach(() => vi.restoreAllMocks())

describe('OfflineBanner', () => {
  it('renders nothing while online', () => {
    vi.spyOn(onlineStatus, 'useOnlineStatus').mockReturnValue(true)
    const { container } = render(<OfflineBanner />)
    expect(container).toBeEmptyDOMElement()
  })

  it('uses warning tokens, never the raw amber palette, when offline', () => {
    vi.spyOn(onlineStatus, 'useOnlineStatus').mockReturnValue(false)
    render(<OfflineBanner />)
    const banner = screen.getByText('offlineBanner.message').closest('div')?.parentElement
    expect(banner).toHaveClass('bg-warning', 'text-on-status')
    expect(banner?.className).not.toMatch(/-(amber|yellow)-\d/)
    expect(banner?.className).not.toMatch(/text-white/)
  })
})
