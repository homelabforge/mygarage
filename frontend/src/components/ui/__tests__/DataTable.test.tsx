import { describe, it, expect } from 'vitest'
import { Box } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import DataTable from '../DataTable'
import EmptyState from '../EmptyState'

interface Row {
  id: string
  date: string
  cost: number
}

const COLUMNS = [
  { id: 'date', header: 'Date', render: (r: Row) => r.date },
  { id: 'cost', header: 'Cost', align: 'right' as const, mono: true, render: (r: Row) => r.cost },
]

const ROWS: Row[] = [
  { id: '1', date: 'Jul 13, 2026', cost: 62.4 },
  { id: '2', date: 'Jun 30, 2026', cost: 58.1 },
]

describe('DataTable', () => {
  it('renders a table with an accessible caption', () => {
    render(<DataTable caption="Fuel records" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />)
    expect(screen.getByRole('table', { name: 'Fuel records' })).toBeInTheDocument()
  })

  it('renders one header cell per column', () => {
    render(<DataTable caption="Fuel" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />)
    expect(screen.getAllByRole('columnheader')).toHaveLength(2)
  })

  it('renders one row per datum', () => {
    render(<DataTable caption="Fuel" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />)
    // +1 for the header row.
    expect(screen.getAllByRole('row')).toHaveLength(ROWS.length + 1)
  })

  it('renders mono columns in the mono family', () => {
    render(<DataTable caption="Fuel" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />)
    expect(screen.getByText('62.4')).toHaveClass('font-mono')
  })

  it('renders the empty state inside the table body when there are no rows', () => {
    render(
      <DataTable
        caption="Fuel"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r: Row) => r.id}
        emptyState={<EmptyState icon={Box} title="No records" size="sm" />}
      />,
    )
    expect(screen.getByRole('heading', { name: 'No records' })).toBeInTheDocument()
    expect(screen.getByRole('cell')).toHaveAttribute('colspan', '2')
  })
})
