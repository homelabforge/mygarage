import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import PageHeader from '../PageHeader'

describe('PageHeader', () => {
  it('renders the title as a level-1 heading', () => {
    render(<PageHeader title="My Garage" />)
    expect(screen.getByRole('heading', { level: 1, name: 'My Garage' })).toBeInTheDocument()
  })

  it('renders subtitle and actions', () => {
    render(
      <PageHeader
        title="My Garage"
        subtitle="Managing 3 vehicle(s)"
        actions={<button>Add Vehicle</button>}
      />,
    )
    expect(screen.getByText('Managing 3 vehicle(s)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Vehicle' })).toBeInTheDocument()
  })
})
