import { useTranslation } from 'react-i18next'
import { Plus, Trash2 } from 'lucide-react'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { supplyUnitLabel } from '../utils/supplyUnits'
import type { SupplyUsedEntry } from '../types/serviceVisit'
import type { Supply } from '../types/supplies'

interface SupplyUsedPickerProps {
  value: SupplyUsedEntry[]
  onChange: (next: SupplyUsedEntry[]) => void
  // The visit's vehicle VIN — scopes the ADDABLE options to shared + this-vehicle
  // supplies (an existing hydrated row for any other supply still resolves its
  // name from the full `supplies` list below).
  vin: string
  // Full (active + archived, UNFILTERED by vin) list, resolved once by ServiceVisitForm and
  // threaded down — NOT fetched here. A second independent useSupplies() call
  // in this component would race the parent's: a usage added against a supply
  // the parent's own lookup hasn't resolved yet would silently vanish from the
  // submit payload (mapSuppliesUsedForSubmit can't convert what it can't find).
  supplies: Supply[]
  disabled?: boolean
}

/**
 * Consume-picker for a service line item: which supplies (fluids, filters,
 * parts) were used, and how much, in the user's DISPLAY units. The caller
 * (LineItemEditor -> ServiceVisitForm) owns display<->canonical conversion —
 * this component only ever reads/writes display-unit quantities.
 */
export default function SupplyUsedPicker({
  value,
  onChange,
  vin,
  supplies,
  disabled = false,
}: SupplyUsedPickerProps) {
  const { t } = useTranslation('forms')
  const { system } = useUnitPreference()
  const suppliesById = new Map(supplies.map((s) => [s.id, s]))
  const usedSupplyIds = new Set(value.map((row) => row.supply_id))
  // Only ACTIVE supplies can be picked for a NEW usage row. An archived supply
  // already in use (via edit-hydration) stays selectable in its own row below
  // — see rowOptions — so past usage isn't orphaned, but it's never offered as
  // a fresh choice.
  // Addable = ACTIVE and shared (vin null) or pinned to THIS vehicle, and not
  // already used. (The full `supplies` list is vin-unfiltered so existing rows
  // resolve names; but a supply pinned to another vehicle must never be OFFERED
  // — the backend would reject it — so scope the addable set here.)
  const addableSupplies = supplies.filter(
    (s) => s.is_active && (s.vin == null || s.vin === vin) && !usedSupplyIds.has(s.id),
  )

  const handleAddRow = () => {
    const firstAvailable = addableSupplies[0]
    if (!firstAvailable) return
    onChange([...value, { supply_id: firstAvailable.id, quantity: 0 }])
  }

  const handleSupplyChange = (rowIndex: number, supplyId: number) => {
    onChange(value.map((row, i) => (i === rowIndex ? { ...row, supply_id: supplyId } : row)))
  }

  const handleQuantityChange = (rowIndex: number, quantity: number) => {
    onChange(value.map((row, i) => (i === rowIndex ? { ...row, quantity } : row)))
  }

  const handleRemoveRow = (rowIndex: number) => {
    onChange(value.filter((_, i) => i !== rowIndex))
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-garage-text">{t('service.suppliesUsed')}</label>
        <button
          type="button"
          onClick={handleAddRow}
          disabled={disabled || addableSupplies.length === 0}
          className="flex items-center gap-1 text-sm text-primary hover:text-primary/80 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" />
          {t('service.suppliesAddRow')}
        </button>
      </div>

      {value.length === 0 ? (
        <p className="text-xs text-garage-text-muted">{t('service.suppliesNone')}</p>
      ) : (
        <div className="space-y-2">
          {value.map((row, rowIndex) => {
            const supply = suppliesById.get(row.supply_id)
            const unitType = supply?.unit_type ?? 'count'
            const unitLabel = supplyUnitLabel(unitType, system)
            // Row's own select keeps its current supply as an option even if it's
            // archived (not in addableSupplies) or — defensively — also picked by
            // another row (shouldn't happen via handleAddRow, but a hydrated or
            // hand-edited value could carry a duplicate).
            const rowOptions = supplies.filter((s) => s.id === row.supply_id || (s.is_active && !usedSupplyIds.has(s.id)))

            return (
              <div key={rowIndex} className="flex items-center gap-2">
                <select
                  value={row.supply_id}
                  onChange={(e) => handleSupplyChange(rowIndex, Number(e.target.value))}
                  disabled={disabled}
                  aria-label={t('service.suppliesUsed')}
                  className="flex-1 px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                >
                  {supply == null && <option value={row.supply_id}>{`#${row.supply_id}`}</option>}
                  {rowOptions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <div className="w-28 flex items-center gap-1">
                  <input
                    type="number"
                    value={row.quantity}
                    onChange={(e) =>
                      handleQuantityChange(rowIndex, e.target.value ? parseFloat(e.target.value) : 0)
                    }
                    min="0"
                    step={unitType === 'count' ? '1' : '0.01'}
                    disabled={disabled}
                    aria-label={t('service.suppliesQuantity')}
                    className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                  {unitLabel && <span className="text-xs text-garage-text-muted flex-shrink-0">{unitLabel}</span>}
                </div>
                <button
                  type="button"
                  onClick={() => handleRemoveRow(rowIndex)}
                  disabled={disabled}
                  aria-label={t('service.suppliesRemoveRow')}
                  title={t('service.suppliesRemoveRow')}
                  className="p-1 text-danger hover:bg-danger/10 rounded disabled:opacity-50"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
