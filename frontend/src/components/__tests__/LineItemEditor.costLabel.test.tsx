import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { screen, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import type { ServiceVisitFormLineItem } from '../../types/serviceVisit'

vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ formatCurrency: (n: number) => `$${n}` }),
}))
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
}))

import LineItemEditor from '../LineItemEditor'

/**
 * The line cost is what the shop charged, parts and labor (#302/#306/#307).
 * It used to say "Labor / shop cost", which sent dealer parts through the
 * Supplies picker instead. Supplies are the household's own stock.
 */

const item: ServiceVisitFormLineItem = {
  tempId: -1,
  description: 'Oil change',
  category: 'Maintenance',
  cost: undefined,
  notes: '',
  is_inspection: false,
  inspection_result: '',
  inspection_severity: '',
  triggered_by_inspection_id: undefined,
  is_recall: false,
  recall_id: null,
  is_warranty: false,
  warranty_id: null,
  supplies_used: [],
}

function renderEditor({ index = 0, partsCost = 0 }: { index?: number; partsCost?: number } = {}): void {
  render(
    <LineItemEditor
      item={item}
      index={index}
      partsCost={partsCost}
      vin="V1"
      supplies={[]}
      unitsBySupplyId={new Map()}
      failedInspections={[]}
      onChange={vi.fn()}
      onRemove={vi.fn()}
      categories={['Maintenance']}
    />,
  )
}

const LOCALES = resolve(__dirname, '..', '..', 'locales', 'en')
const en = (ns: string): Record<string, unknown> =>
  JSON.parse(readFileSync(resolve(LOCALES, `${ns}.json`), 'utf8')) as Record<string, unknown>
const at = (bundle: Record<string, unknown>, key: string): unknown =>
  key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], bundle)

describe('LineItemEditor line cost says parts and labor', () => {
  it('labels the cost field from the parts + labor key', () => {
    renderEditor()
    expect(screen.getByLabelText('lineItemEditor.costPartsLabor')).toHaveAttribute('id', 'line-item-0-cost')
    expect(screen.queryByText('lineItemEditor.cost')).not.toBeInTheDocument()
  })

  it('says under Supplies Used that supplies come from your own stock', () => {
    renderEditor()
    const heading = screen.getByText('service.suppliesUsed')
    // The picker's own block: heading row, then the hint, then the rows.
    const picker = heading.closest('div.space-y-2') as HTMLElement
    expect(within(picker).getByText('service.suppliesOwnStockHint')).toBeInTheDocument()
  })

  it('captions the supplies under the cost as Supplies, not Parts', () => {
    renderEditor({ partsCost: 9.52 })
    expect(screen.getByText('lineItemEditor.suppliesCost')).toBeInTheDocument()
    expect(screen.queryByText('lineItemEditor.partsCost')).not.toBeInTheDocument()
  })
})

describe('line cost copy (English)', () => {
  it('reads "Cost (parts + labor)" and the hint sends shop parts to the cost', () => {
    const vehicles = en('vehicles')
    expect(at(vehicles, 'lineItemEditor.costPartsLabor')).toBe('Cost (parts + labor)')
    expect(at(en('forms'), 'service.suppliesOwnStockHint')).toBe(
      'Supplies come out of your own stock. Parts the shop supplied go in the cost.',
    )
    // The read views say the same thing as the editor.
    expect(at(vehicles, 'serviceList.detail.partsLabor')).toBe('Parts + labor')
    expect(at(vehicles, 'serviceList.partsLaborCost')).toBe('Parts + labor {{amount}}')
  })

  it('calls the supply side Supplies wherever it sits beside parts + labor', () => {
    const vehicles = en('vehicles')
    expect(at(vehicles, 'lineItemEditor.suppliesCost')).toBe('Supplies: {{amount}}')
    expect(at(vehicles, 'serviceList.suppliesCost')).toBe('Supplies {{amount}}')
    expect(at(vehicles, 'serviceList.detail.suppliesCost')).toBe('Supplies')
    expect(at(en('forms'), 'service.suppliesTotal')).toBe('Supplies')
  })

  it('drops the labor-only keys nothing reads any more', () => {
    const vehicles = en('vehicles')
    expect(at(vehicles, 'serviceList.laborCost')).toBeUndefined()
    expect(at(vehicles, 'serviceList.detail.labor')).toBeUndefined()
  })

  it('leaves the old key alone, so the 8 translated locales do not change meaning (regression control)', () => {
    expect(at(en('vehicles'), 'lineItemEditor.cost')).toBe('Labor / shop cost')
  })
})
