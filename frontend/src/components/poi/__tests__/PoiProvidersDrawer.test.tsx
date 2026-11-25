/**
 * The search providers sidecar on Find POI (moved from Settings > Integrations
 * > Shop Finder). Add and Edit open over it, so they must be nested: a drawer
 * opened from inside another one without it sits behind the first, inert.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const api = vi.hoisted(() => ({ get: vi.fn(), delete: vi.fn() }))
vi.mock('@/services/api', () => ({ default: api }))
vi.mock('@/components/modals/AddProviderModal', () => ({
  default: ({ isOpen, nested }: { isOpen: boolean; nested?: boolean }) =>
    isOpen ? <p>add provider{nested ? ' (nested)' : ''}</p> : null,
}))
vi.mock('@/components/modals/EditProviderModal', () => ({
  default: ({
    isOpen,
    nested,
    provider,
  }: {
    isOpen: boolean
    nested?: boolean
    provider: { display_name: string } | null
  }) => (isOpen ? <p>edit {provider?.display_name}{nested ? ' (nested)' : ''}</p> : null),
}))

import PoiProvidersDrawer from '../PoiProvidersDrawer'
import { answerConfirm, escapeConfirm, withConfirm } from '../../../__tests__/confirmHelpers'

const PROVIDERS = [
  {
    name: 'osm',
    display_name: 'OpenStreetMap',
    enabled: true,
    is_default: true,
    api_usage: 12,
    api_limit: null,
    priority: 0,
  },
  {
    name: 'tomtom',
    display_name: 'TomTom Places API',
    enabled: true,
    is_default: false,
    api_usage: 3,
    api_limit: 2500,
    priority: 1,
  },
  {
    name: 'google',
    display_name: 'Google Places',
    enabled: false,
    is_default: false,
    api_usage: 0,
    api_limit: null,
    priority: 2,
  },
]

const renderDrawer = (open = true) => render(<PoiProvidersDrawer open={open} onClose={vi.fn()} />, { wrapper: withConfirm })

const rowOf = (name: string): HTMLElement => screen.getByText(name).closest('tr') as HTMLElement

beforeEach(() => {
  vi.clearAllMocks()
  api.get.mockResolvedValue({ data: { providers: PROVIDERS } })
  api.delete.mockResolvedValue({})
})

describe('PoiProvidersDrawer', () => {
  it('lists each provider with its state named in text and its usage', async () => {
    renderDrawer()

    expect(await screen.findByRole('dialog', { name: 'integrations.searchProviders' })).toBeInTheDocument()
    expect(await screen.findByText('TomTom Places API')).toBeInTheDocument()
    expect(rowOf('TomTom Places API')).toHaveTextContent('integrations.statusActive')
    expect(rowOf('Google Places')).toHaveTextContent('integrations.statusInactive')
    expect(rowOf('TomTom Places API')).toHaveTextContent('3/2500')
    expect(rowOf('Google Places')).toHaveTextContent('0/integrationsTab.unlimited')
  })

  it('does not fetch while closed', () => {
    renderDrawer(false)

    expect(api.get).not.toHaveBeenCalled()
  })

  it('offers no remove on the default provider', async () => {
    renderDrawer()
    await screen.findByText('TomTom Places API')

    // One remove per non-default row: TomTom and Google.
    expect(screen.getAllByRole('button', { name: 'integrationsTab.remove' })).toHaveLength(2)
  })

  it('opens Edit over the sidecar, not behind it', async () => {
    renderDrawer()
    await screen.findByText('TomTom Places API')

    fireEvent.click(screen.getAllByRole('button', { name: 'integrationsTab.edit' })[1])

    expect(screen.getByText('edit TomTom Places API (nested)')).toBeInTheDocument()
  })

  it('opens Add over the sidecar, not behind it', async () => {
    renderDrawer()
    await screen.findByText('TomTom Places API')

    fireEvent.click(screen.getByRole('button', { name: 'integrations.addService' }))

    expect(screen.getByText('add provider (nested)')).toBeInTheDocument()
  })

  it('removes a provider after confirming, then reloads the list', async () => {
    renderDrawer()
    await screen.findByText('TomTom Places API')

    fireEvent.click(screen.getAllByRole('button', { name: 'integrationsTab.remove' })[0])
    await answerConfirm('confirm', 'integrationsTab.confirmRemoveProvider')

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/settings/poi-providers/tomtom'))
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('integrations.providerRemoved')).toBeInTheDocument()
  })

  it('opens again without the last visit\'s note', async () => {
    const { rerender } = render(<PoiProvidersDrawer open onClose={vi.fn()} />, { wrapper: withConfirm })
    await screen.findByText('TomTom Places API')
    fireEvent.click(screen.getAllByRole('button', { name: 'integrationsTab.remove' })[0])
    await answerConfirm('confirm', 'integrationsTab.confirmRemoveProvider')
    expect(await screen.findByText('integrations.providerRemoved')).toBeInTheDocument()

    rerender(<PoiProvidersDrawer open={false} onClose={vi.fn()} />)
    rerender(<PoiProvidersDrawer open onClose={vi.fn()} />)

    await waitFor(() => expect(screen.queryByText('integrations.providerRemoved')).not.toBeInTheDocument())
  })

  it('keeps a provider when the removal is not confirmed', async () => {
    renderDrawer()
    await screen.findByText('TomTom Places API')

    fireEvent.click(screen.getAllByRole('button', { name: 'integrationsTab.remove' })[0])
    await answerConfirm('cancel', 'integrationsTab.confirmRemoveProvider')

    expect(api.delete).not.toHaveBeenCalled()
  })

  // Regression pin: Escape on the remove confirm must not close the drawer.
  it('Escape closes the remove confirm and leaves the drawer open', async () => {
    const onClose = vi.fn()
    render(<PoiProvidersDrawer open onClose={onClose} />, { wrapper: withConfirm })
    await screen.findByText('TomTom Places API')

    fireEvent.click(screen.getAllByRole('button', { name: 'integrationsTab.remove' })[0])
    await escapeConfirm('integrationsTab.confirmRemoveProvider')

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'integrations.searchProviders' })).toBeInTheDocument()
    expect(api.delete).not.toHaveBeenCalled()
  })

  it('says so when the list cannot load', async () => {
    api.get.mockRejectedValue(new Error('down'))
    renderDrawer()

    expect(await screen.findByRole('alert')).toHaveTextContent('integrations.loadProvidersError')
  })
})
