import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Package, Trash2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Drawer, Button, Input, Mono } from '../ui'
import vehicleService from '../../services/vehicleService'
import { formatStickerValue } from '../../utils/formatUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'

export type EquipmentWhich = 'standard' | 'optional'

interface EquipmentDrawerProps {
  open: boolean
  onClose: () => void
  vehicle: Vehicle
  vin: string
  which: EquipmentWhich
  /** Receives the server's updated vehicle after each successful save so the
   *  page stays in sync. */
  onUpdated: (vehicle: Vehicle) => void
}

/** category -> items. A category-less vehicle from the window-sticker importer
 *  stores everything under `items`, which we render as one plain list. */
type Groups = Record<string, string[]>

/** Uncategorized additions land here — the same key the importer uses for a
 *  flat list, so they read as one list rather than a synthetic category. */
const DEFAULT_BUCKET = 'items'

/** Normalize the vehicle's equipment JSON (values may be arrays or scalars)
 *  into an editable category -> string[] map, dropping empty categories so the
 *  rest of the component can treat `groups` as always-clean. */
function normalize(equipment: unknown): Groups {
  const out: Groups = {}
  if (equipment && typeof equipment === 'object') {
    for (const [category, value] of Object.entries(equipment as Record<string, unknown>)) {
      const items = Array.isArray(value)
        ? value.map((item) => String(item))
        : value != null && value !== ''
          ? [String(value)]
          : []
      if (items.length > 0) out[category] = items
    }
  }
  return out
}

/** Final save-boundary guard: a fully-cleared list persists as {}, never as
 *  stale empty buckets. */
function toEquipmentDict(groups: Groups): Record<string, string[]> {
  return Object.fromEntries(Object.entries(groups).filter(([, items]) => items.length > 0))
}

/**
 * Right-anchored sidecar for viewing and editing a vehicle's standard or
 * optional equipment. Opened from the Equipment pills next to the Edit button;
 * replaces the read-only collapsible cards that used to live in the Overview
 * tab. Category grouping is preserved; optional items keep their window-sticker
 * MSRP (shown read-only, never edited here).
 *
 * Each add/delete saves immediately (partial PUT) and hands the updated vehicle
 * back via onUpdated, so "Done" is just a close — nothing is lost on Escape.
 */
export default function EquipmentDrawer({
  open,
  onClose,
  vehicle,
  vin,
  which,
  onUpdated,
}: EquipmentDrawerProps) {
  const { t } = useTranslation('vehicles')
  const { currencyCode, locale } = useCurrencyPreference()
  const [groups, setGroups] = useState<Groups>({})
  const [newItem, setNewItem] = useState('')
  const [saving, setSaving] = useState(false)

  const rawEquip = which === 'standard' ? vehicle.standard_equipment : vehicle.optional_equipment
  // Seed the editable copy only when the drawer opens or the target list
  // changes — keyed on a stringified snapshot so our own post-save vehicle
  // updates (identical data) can't clobber in-flight edits, and object identity
  // churn doesn't reseed on every render.
  const seedKey = useMemo(() => JSON.stringify(rawEquip ?? null), [rawEquip])
  useEffect(() => {
    if (open) {
      setGroups(normalize(rawEquip))
      setNewItem('')
    }
    // rawEquip is intentionally captured via seedKey, not a direct dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, which, seedKey])

  const optionsDetail =
    which === 'optional'
      ? (vehicle.window_sticker_options_detail as Record<string, unknown> | null | undefined)
      : null

  const priceFor = (item: string): string | null =>
    formatStickerValue(optionsDetail?.[item], { currencyCode, locale })

  const persist = async (next: Groups): Promise<void> => {
    const previous = groups
    setGroups(next) // optimistic
    setSaving(true)
    try {
      const payload: VehicleUpdate =
        which === 'standard'
          ? { standard_equipment: toEquipmentDict(next) }
          : { optional_equipment: toEquipmentDict(next) }
      const updated = await vehicleService.update(vin, payload)
      onUpdated(updated)
    } catch {
      setGroups(previous) // revert
      toast.error(t('detail.equipment.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const handleAdd = (): void => {
    const value = newItem.trim()
    if (!value) return
    const bucket = groups[DEFAULT_BUCKET] ?? []
    setNewItem('')
    void persist({ ...groups, [DEFAULT_BUCKET]: [...bucket, value] })
  }

  const handleRemove = (category: string, index: number): void => {
    const remaining = groups[category].filter((_, i) => i !== index)
    const next: Groups = { ...groups }
    if (remaining.length > 0) next[category] = remaining
    else delete next[category]
    void persist(next)
  }

  // groups is kept clean (normalize drops empties, handleRemove deletes an
  // emptied category), so no render-side filter is needed.
  const entries = Object.entries(groups)

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={which === 'standard' ? t('detail.standardEquipment') : t('detail.optionalEquipment')}
      icon={Package}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <div className="w-full space-y-3">
          <div className="flex items-center gap-2">
            <Input
              value={newItem}
              onChange={(e) => setNewItem(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleAdd()
                }
              }}
              placeholder={t('detail.equipment.addPlaceholder')}
              aria-label={t('detail.equipment.addPlaceholder')}
              className="flex-1"
            />
            <Button
              variant="primary"
              icon={Plus}
              onClick={handleAdd}
              disabled={saving || newItem.trim().length === 0}
            >
              {t('detail.equipment.add')}
            </Button>
          </div>
          <Button variant="secondary" className="w-full" onClick={onClose}>
            {t('detail.equipment.done')}
          </Button>
        </div>
      }
    >
      <p className="text-sm text-text-mute mb-4">{t('detail.equipment.editSubtitle')}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-text-mute">{t('detail.equipment.empty')}</p>
      ) : (
        <div className="space-y-4">
          {entries.map(([category, items]) => (
            <div key={category} className="space-y-2">
              {category !== DEFAULT_BUCKET && (
                <p className="text-sm font-medium text-(--accent-fg)">{category}</p>
              )}
              {items.map((item, index) => {
                const price = which === 'optional' ? priceFor(item) : null
                return (
                  <div key={`${category}-${index}`} className="flex items-center gap-2">
                    <div className="flex-1 flex items-center justify-between gap-2 rounded-control border border-border bg-surface-2 px-3 py-2">
                      <span className="text-sm text-text">{item}</span>
                      {price && (
                        <Mono size="sm" tone="muted">
                          {price}
                        </Mono>
                      )}
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      icon={Trash2}
                      aria-label={t('detail.equipment.remove', { item })}
                      onClick={() => handleRemove(category, index)}
                      disabled={saving}
                    />
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </Drawer>
  )
}
