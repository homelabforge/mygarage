import { describe, it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import InsuranceForm from '../InsuranceForm'

describe('InsuranceForm — footer submit association', () => {
  it('clicking the footer Save (outside the <form>) triggers the form submit', async () => {
    render(<InsuranceForm vin="TEST12345678901234" onClose={vi.fn()} onSuccess={vi.fn()} />)
    // Save is in the sticky footer, a sibling of the <form>, wired via form="insurance-form".
    fireEvent.click(screen.getByRole('button', { name: 'common:create' }))
    // Empty required fields -> rhf runs validation only because the submit fired.
    expect(await screen.findByText('Provider is required')).toBeInTheDocument()
  })
})
