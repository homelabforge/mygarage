import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import EditProviderModal from '../EditProviderModal'
import AddProviderModal from '../AddProviderModal'

const provider = { name: 'tomtom', display_name: 'TomTom', enabled: true, api_key_masked: null }

describe('POI provider modals — Drawer conversion', () => {
  it('EditProviderModal renders a labelled dialog with the footer Save action', () => {
    render(<EditProviderModal isOpen provider={provider as never} onClose={vi.fn()} onSave={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'modal.editProvider' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'editProviderModal.save' })).toBeInTheDocument()
  })

  it('AddProviderModal renders a labelled dialog on the provider-select step', () => {
    render(<AddProviderModal isOpen onClose={vi.fn()} onProviderAdded={vi.fn()} />)
    // SELECT step has no footer by design (judgment call #9) — the provider cards are the actions.
    expect(screen.getByRole('dialog', { name: 'modal.selectPoiProvider' })).toBeInTheDocument()
  })
})
