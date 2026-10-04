import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Plus, Edit, Trash2, Save, Package, AlertTriangle, History, ChevronDown, LayoutGrid, List } from 'lucide-react'
import { toast } from 'sonner'
import {
  useSupplies,
  useCreateSupply,
  useUpdateSupply,
  useDeleteSupply,
} from '@/hooks/queries/useSupplies'
import { useQuickEntryVehicles } from '@/hooks/queries/useQuickEntryVehicles'
import { vehicleLabel } from '@/utils/vehicleLabel'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useCurrencyPreference } from '@/hooks/useCurrencyPreference'
import {
  costDecimals, displayDecimals, supplyDisplayUnit, toDisplay, unitCostToDisplay, unitLabel,
  type SupplyUnit, type SupplyVolumeUnit,
} from '@/utils/supplyUnits'
import { UNIT_OPTION_LABELS, type VolumeUnit } from '@/types/units'
import {
  canonicalCategories, filterSupplies, groupSupplies, isOutOfStock, sortSupplies,
  type SupplyFilters, type SupplyGroup,
} from '@/utils/supplyListView'
import { readSuppliesView, rememberSuppliesView, type SuppliesViewPrefs } from '@/utils/suppliesViewStore'
import { makeSupplySchema, SUPPLY_UNIT_TYPES, type SupplyFormData } from '@/schemas/supplies'
import {
  Select, Field, Input, Textarea, Checkbox, Button, SearchField, Chip, Dropdown, DataTable,
  type DropdownItem, type DataTableColumn,
} from '@/components/ui'
import FormModalWrapper from '@/components/FormModalWrapper'
import SupplyHistoryModal from '@/components/SupplyHistoryModal'
import BarcodeScanButton from '@/components/BarcodeScanButton'
import type { Supply, SupplyCreate, SupplyUpdate } from '@/types/supplies'
import { getActiveLocale } from '@/constants/i18n'
import { applyServerErrors } from '@/hooks/useApiFormErrors'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

export default function Supplies() {
  const { t } = useTranslation('common')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingSupply, setEditingSupply] = useState<Supply | null>(null)
  const [historyTarget, setHistoryTarget] = useState<{
    supply: Supply
    initialForm?: 'purchase' | 'adjustment'
  } | null>(null)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<string | null>(null)
  const [vehicle, setVehicle] = useState<SupplyFilters['vehicle']>('all')
  const [outOfStockOnly, setOutOfStockOnly] = useState(false)
  const [prefs, setPrefs] = useState<SuppliesViewPrefs>(() => readSuppliesView())

  const { data, isLoading, error } = useSupplies(includeArchived)
  const deleteMutation = useDeleteSupply()
  const { system } = useUnitPreference()
  const { formatCurrency } = useCurrencyPreference()
  const { data: quickVehicles = [] } = useQuickEntryVehicles()

  const supplies = useMemo(() => data?.supplies ?? [], [data?.supplies])

  const vehicleLabelFor = (vin: string): string => {
    const known = quickVehicles.find((v) => v.vin === vin)
    return known ? vehicleLabel(known) : vin
  }

  const categories = useMemo(() => canonicalCategories(supplies), [supplies])
  const vins = useMemo(
    () => [...new Set(supplies.map((s) => s.vin).filter((vin): vin is string => vin != null))],
    [supplies],
  )

  const filters: SupplyFilters = { query, category, vehicle, outOfStock: outOfStockOnly }
  const visible = useMemo(
    () => filterSupplies(supplies, filters),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [supplies, query, category, vehicle, outOfStockOnly],
  )
  const anyFilterActive =
    query.trim() !== '' || category !== null || vehicle !== 'all' || outOfStockOnly

  const clearFilters = () => {
    setQuery('')
    setCategory(null)
    setVehicle('all')
    setOutOfStockOnly(false)
  }

  // Write after setState, not inside the updater: updaters must stay pure and
  // StrictMode double-invokes them (same shape as useDashboardSort's choose).
  const updatePrefs = (patch: Partial<SuppliesViewPrefs>) => {
    const next = { ...prefs, ...patch }
    setPrefs(next)
    rememberSuppliesView(next)
  }

  const sortItems: DropdownItem[] = [
    { id: 'name', label: t('supplies.sortByName'), checked: prefs.sort === 'name', onSelect: () => updatePrefs({ sort: 'name' }) },
    { id: 'stock', label: t('supplies.sortByLowestStock'), checked: prefs.sort === 'stock', onSelect: () => updatePrefs({ sort: 'stock' }) },
    { id: 'category', label: t('supplies.sortByCategory'), checked: prefs.sort === 'category', onSelect: () => updatePrefs({ sort: 'category' }) },
  ]
  const groupItems: DropdownItem[] = [
    { id: 'none', label: t('supplies.groupNone'), checked: prefs.group === 'none', onSelect: () => updatePrefs({ group: 'none' }) },
    { id: 'category', label: t('supplies.groupByCategory'), checked: prefs.group === 'category', onSelect: () => updatePrefs({ group: 'category' }) },
    { id: 'vehicle', label: t('supplies.groupByVehicle'), checked: prefs.group === 'vehicle', onSelect: () => updatePrefs({ group: 'vehicle' }) },
  ]
  const sortLabel = sortItems.find((i) => i.checked)?.label ?? ''
  const groupLabel = groupItems.find((i) => i.checked)?.label ?? ''

  const groups: SupplyGroup[] = groupSupplies(
    sortSupplies(visible, prefs.sort),
    prefs.group,
    vehicleLabelFor,
  )

  const groupHeading = (group: SupplyGroup): string => {
    if (group.value === null) {
      return group.kind === 'vehicle' ? t('supplies.sharedVehicle') : t('supplies.noCategory')
    }
    return group.kind === 'vehicle' ? vehicleLabelFor(group.value) : group.value
  }

  const handleAddClick = () => {
    setEditingSupply(null)
    setShowForm(true)
  }

  const handleEditClick = (supply: Supply) => {
    setEditingSupply(supply)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditingSupply(null)
  }

  const handleDelete = (supply: Supply) => {
    if (!confirm(t('supplies.confirmDelete'))) return

    deleteMutation.mutate(supply.id, {
      onSuccess: () => toast.success(t('supplies.deleted')),
      onError: (err) => toast.error(getActionErrorMessage(err, t('supplies.deleteAction'))),
    })
  }

  // The stored token wins; only a supply without one falls back to qt or L by preference.
  const unitFor = (supply: Supply): SupplyUnit => supplyDisplayUnit(supply, system)

  const formatOnHand = (supply: Supply, unit: SupplyUnit): string => {
    const value = toDisplay(Number(supply.on_hand), unit)
    if (unit === 'count') {
      return Math.round(value).toLocaleString(getActiveLocale())
    }
    return `${value.toFixed(displayDecimals(unit))} ${unitLabel(unit)}`
  }

  const avgCostLabel = (unit: SupplyUnit): string => {
    const label = unitLabel(unit)
    return label ? t('supplies.avgCostPerUnit', { unit: label }) : t('supplies.avgUnitCost')
  }

  const avgCostValue = (supply: Supply, unit: SupplyUnit): string =>
    formatCurrency(unitCostToDisplay(supply.avg_unit_cost, unit), { fractionDigits: costDecimals(unit) })

  const quickActions = (supply: Supply) => (
    <>
      <button
        type="button"
        onClick={() => setHistoryTarget({ supply, initialForm: 'purchase' })}
        className="text-xs text-primary hover:underline"
      >
        {t('supplies.history.logPurchase')}
      </button>
      <button
        type="button"
        onClick={() => setHistoryTarget({ supply, initialForm: 'adjustment' })}
        className="text-xs text-primary hover:underline"
      >
        {t('supplies.history.logAdjustment')}
      </button>
    </>
  )

  const renderActions = (supply: Supply) => (
    <>
      <button
        onClick={() => setHistoryTarget({ supply })}
        className="text-garage-text-muted hover:text-primary transition-colors"
        aria-label={t('supplies.viewHistory')}
        title={t('supplies.viewHistory')}
      >
        <History className="w-4 h-4" />
      </button>
      <button
        onClick={() => handleEditClick(supply)}
        className="text-garage-text-muted hover:text-primary transition-colors"
        aria-label={t('common:edit')}
        title={t('common:edit')}
      >
        <Edit className="w-4 h-4" />
      </button>
      <button
        onClick={() => handleDelete(supply)}
        disabled={deleteMutation.isPending && deleteMutation.variables === supply.id}
        className="text-garage-text-muted hover:text-danger transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        aria-label={t('common:delete')}
        title={t('common:delete')}
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </>
  )

  const listColumns: DataTableColumn<Supply>[] = [
    {
      id: 'name',
      header: t('supplies.name'),
      render: (s) => (
        <div>
          <div className="font-medium text-garage-text">{s.name}</div>
          {s.part_number && <div className="text-xs text-garage-text-muted">{s.part_number}</div>}
        </div>
      ),
    },
    { id: 'category', header: t('supplies.category'), render: (s) => s.category ?? '' },
    {
      id: 'vehicle',
      header: t('supplies.vehicle'),
      render: (s) => (s.vin ? vehicleLabelFor(s.vin) : t('supplies.sharedVehicle')),
    },
    {
      id: 'on_hand',
      header: t('supplies.onHand'),
      align: 'right',
      mono: true,
      render: (s) => (
        <span className="inline-flex items-center gap-2">
          {isOutOfStock(s) && (
            <Chip tone={s.is_negative ? 'danger' : 'warning'}>{t('supplies.outOfStock')}</Chip>
          )}
          {formatOnHand(s, unitFor(s))}
        </span>
      ),
    },
    {
      id: 'avg_cost',
      header: t('supplies.avgUnitCost'),
      align: 'right',
      mono: true,
      render: (s) => avgCostValue(s, unitFor(s)),
    },
    {
      id: 'actions',
      header: '',
      align: 'right',
      render: (s) => (
        <div className="flex items-center justify-end gap-3">
          {quickActions(s)}
          <div className="flex gap-2">{renderActions(s)}</div>
        </div>
      ),
    },
  ]

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('supplies.title')}</h1>
        <p className="text-garage-text-muted">{t('supplies.subtitle')}</p>
      </div>

      {/* Controls */}
      <div className="mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
          <SearchField
            value={query}
            onChange={setQuery}
            label={t('supplies.searchSupplies')}
            placeholder={t('supplies.searchSupplies')}
            className="w-full sm:w-56"
          />
          <Select
            aria-label={t('supplies.filterByCategory')}
            value={category ?? ''}
            onChange={(e) => setCategory(e.target.value || null)}
            placeholder={t('supplies.allCategories')}
            options={categories.map((c) => ({ value: c, label: c }))}
            className="sm:w-48"
          />
          <Select
            aria-label={t('supplies.filterByVehicle')}
            value={vehicle}
            onChange={(e) => setVehicle(e.target.value)}
            options={[
              { value: 'all', label: t('supplies.allVehicles') },
              { value: 'shared', label: t('supplies.sharedVehicle') },
              ...vins.map((vin) => ({ value: vin, label: vehicleLabelFor(vin) })),
            ]}
            className="sm:w-48"
          />
          <Chip selected={outOfStockOnly} onClick={() => setOutOfStockOnly((prev) => !prev)}>
            {t('supplies.outOfStock')}
          </Chip>
          <div className="flex-1" />
          <Dropdown
            label={t('supplies.sortSupplies')}
            align="right"
            items={sortItems}
            trigger={
              <>
                {t('supplies.sortTrigger', { label: sortLabel })}
                <ChevronDown aria-hidden="true" className="h-4 w-4" />
              </>
            }
          />
          <Dropdown
            label={t('supplies.groupSupplies')}
            align="right"
            items={groupItems}
            trigger={
              <>
                {t('supplies.groupTrigger', { label: groupLabel })}
                <ChevronDown aria-hidden="true" className="h-4 w-4" />
              </>
            }
          />
          <div className="flex gap-1">
            <button
              type="button"
              aria-label={t('supplies.gridView')}
              aria-pressed={prefs.view === 'grid'}
              onClick={() => updatePrefs({ view: 'grid' })}
              className={`p-2 border rounded-lg transition-colors ${
                prefs.view === 'grid'
                  ? 'bg-primary text-(--accent-on-solid) border-primary'
                  : 'bg-garage-surface text-garage-text border-garage-border hover:border-primary'
              }`}
            >
              <LayoutGrid aria-hidden="true" className="w-4 h-4" />
            </button>
            <button
              type="button"
              aria-label={t('supplies.listView')}
              aria-pressed={prefs.view === 'list'}
              onClick={() => updatePrefs({ view: 'list' })}
              className={`p-2 border rounded-lg transition-colors ${
                prefs.view === 'list'
                  ? 'bg-primary text-(--accent-on-solid) border-primary'
                  : 'bg-garage-surface text-garage-text border-garage-border hover:border-primary'
              }`}
            >
              <List aria-hidden="true" className="w-4 h-4" />
            </button>
          </div>
        </div>

        {anyFilterActive && (
          <div className="flex items-center gap-3 mb-4 text-sm text-garage-text-muted">
            <span>{t('supplies.showingResults', { shown: visible.length, total: supplies.length })}</span>
            <button type="button" onClick={clearFilters} className="text-primary hover:underline">
              {t('supplies.clearFilters')}
            </button>
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <button
            type="button"
            onClick={() => setIncludeArchived((prev) => !prev)}
            className={`px-4 py-2 border rounded-lg transition-colors ${
              includeArchived
                ? 'bg-primary text-(--accent-on-solid) border-primary'
                : 'bg-garage-surface text-garage-text border-garage-border hover:border-primary'
            }`}
          >
            {t('supplies.showArchived')}
          </button>

          <div className="flex-1" />

          <button
            onClick={handleAddClick}
            className="flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg"
          >
            <Plus className="w-5 h-5" />
            {t('supplies.addSupply')}
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
            <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
            <p className="text-sm text-danger">
              {getActionErrorMessage(error, t('supplies.loadAction'))}
            </p>
          </div>
        )}

        {/* Supplies List */}
        {isLoading ? (
          <div className="text-center py-12 text-garage-text-muted">{t('supplies.loading')}</div>
        ) : supplies.length === 0 ? (
          <div className="text-center py-12">
            <Package className="w-16 h-16 text-garage-text-muted mx-auto mb-4" />
            <p className="text-garage-text-muted mb-4">{t('supplies.noSupplies')}</p>
            <button
              onClick={handleAddClick}
              className="inline-flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg"
            >
              <Plus className="w-5 h-5" />
              {t('supplies.addFirstSupply')}
            </button>
          </div>
        ) : visible.length === 0 ? (
          <div className="text-center py-12">
            <Package className="w-16 h-16 text-garage-text-muted mx-auto mb-4" />
            <p className="text-garage-text-muted">{t('supplies.noMatches')}</p>
          </div>
        ) : (
          <div className="space-y-6">
            {groups.map((group) => (
              <div key={group.value === null ? '__trailing__' : `v:${group.value}`}>
                {prefs.group !== 'none' && (
                  <h2 className="text-lg font-semibold text-garage-text mb-3">
                    {groupHeading(group)}{' '}
                    <span className="text-sm font-normal text-garage-text-muted">
                      ({group.supplies.length})
                    </span>
                  </h2>
                )}
                {prefs.view === 'list' ? (
                  <DataTable
                    caption={t('supplies.tableCaption')}
                    columns={listColumns}
                    rows={group.supplies}
                    rowKey={(s) => String(s.id)}
                  />
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {group.supplies.map((supply) => {
                      const unit = unitFor(supply)
                      const archived = supply.is_active === false
                      const stockBorder = supply.is_negative
                        ? 'border-danger/50'
                        : isOutOfStock(supply)
                          ? 'border-warning/50'
                          : 'border-garage-border'
                      return (
                        <div
                          key={supply.id}
                          className={`bg-garage-surface border rounded-lg p-4 transition-colors ${
                            archived ? 'border-garage-border opacity-60' : `${stockBorder} hover:border-primary/50`
                          }`}
                        >
                          <div className="flex items-start justify-between mb-3">
                            <div className="flex-1">
                              <h3 className="font-semibold text-garage-text text-lg">{supply.name}</h3>
                              {archived && (
                                <span className="inline-block px-2 py-0.5 bg-garage-bg text-garage-text-muted rounded text-xs mt-1">
                                  {t('supplies.archived')}
                                </span>
                              )}
                            </div>
                            <div className="flex gap-2">{renderActions(supply)}</div>
                          </div>

                          <div className="space-y-2 text-sm">
                            {supply.category && (
                              <div className="inline-block px-2 py-1 bg-primary/10 text-primary rounded text-xs">
                                {supply.category}
                              </div>
                            )}

                            {supply.part_number && (
                              <div className="text-garage-text-muted">{supply.part_number}</div>
                            )}

                            <div className="text-garage-text-muted text-xs">
                              {supply.vin ? vehicleLabelFor(supply.vin) : t('supplies.sharedVehicle')}
                            </div>

                            {isOutOfStock(supply) && (
                              <div>
                                <Chip tone={supply.is_negative ? 'danger' : 'warning'}>
                                  {t('supplies.outOfStock')}
                                </Chip>
                              </div>
                            )}

                            {supply.barcode && (
                              <div className="text-garage-text-muted font-mono text-xs">
                                {t('supplies.barcode')}: {supply.barcode}
                              </div>
                            )}

                            <div className="flex items-center justify-between">
                              <span className="text-garage-text-muted">{t('supplies.onHand')}</span>
                              <span className="font-medium text-garage-text">{formatOnHand(supply, unit)}</span>
                            </div>

                            <div className="flex items-center justify-between">
                              <span className="text-garage-text-muted">{avgCostLabel(unit)}</span>
                              <span className="font-medium text-garage-text">{avgCostValue(supply, unit)}</span>
                            </div>

                            {supply.is_negative && (
                              <div className="flex items-center gap-2 px-2 py-1 bg-danger/10 text-danger rounded text-xs">
                                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                                <span>{t('supplies.negativeWarning')}</span>
                              </div>
                            )}

                            {supply.notes && (
                              <p className="text-garage-text-muted text-xs mt-2 pt-2 border-t border-garage-border">
                                {supply.notes}
                              </p>
                            )}
                          </div>

                          <div className="flex gap-4 mt-3 pt-3 border-t border-garage-border">
                            {quickActions(supply)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Form Modal */}
      {showForm && (
        <SupplyForm
          supply={editingSupply}
          onClose={handleCloseForm}
          onSuccess={handleCloseForm}
          categorySuggestions={categories}
        />
      )}

      {/* History Modal */}
      {historyTarget && (
        <SupplyHistoryModal
          supply={historyTarget.supply}
          initialForm={historyTarget.initialForm}
          onClose={() => setHistoryTarget(null)}
        />
      )}
    </div>
  )
}

// Form Component

// Litres and gallons reuse the Settings labels as-is; the sizes in between are supply-only keys.
const VOLUME_UNIT_LABELS: Readonly<Record<SupplyVolumeUnit, { readonly labelKey: string }>> = {
  mL: { labelKey: 'common:supplies.volumeUnits.mL' },
  L: UNIT_OPTION_LABELS.volume.options.L,
  fl_oz_us: { labelKey: 'common:supplies.volumeUnits.fl_oz_us' },
  fl_oz_uk: { labelKey: 'common:supplies.volumeUnits.fl_oz_uk' },
  qt_us: { labelKey: 'common:supplies.volumeUnits.qt_us' },
  qt_uk: { labelKey: 'common:supplies.volumeUnits.qt_uk' },
  gal_us: UNIT_OPTION_LABELS.volume.options.gal_us,
  gal_uk: UNIT_OPTION_LABELS.volume.options.gal_uk,
}

// New supplies start in litres for a litre account, quarts of its own gallon otherwise.
// Keyed on the account's volume token so a new one won't compile until it picks a default.
const NEW_SUPPLY_UNIT: Readonly<Record<VolumeUnit, SupplyVolumeUnit>> = {
  L: 'L',
  gal_us: 'qt_us',
  gal_uk: 'qt_uk',
}

interface SupplyFormProps {
  supply?: Supply | null
  onClose: () => void
  onSuccess: () => void
  /** Canonical category spellings offered as datalist suggestions. Free text stays free. */
  categorySuggestions?: string[]
}

export function SupplyForm({ supply, onClose, onSuccess, categorySuggestions = [] }: SupplyFormProps) {
  const { t } = useTranslation('common')
  const isEdit = !!supply
  const [error, setError] = useState<string | null>(null)
  const [isActive, setIsActive] = useState(supply?.is_active ?? true)
  const createMutation = useCreateSupply()
  const updateMutation = useUpdateSupply()
  const { data: vehicles = [] } = useQuickEntryVehicles()
  const { system, units, gallonStandard: flavour } = useUnitPreference()

  // Editing keeps the stored token, or the qt/L a legacy row already shows,
  // so saving untouched pins what the user was looking at.
  const editUnit = supply ? supplyDisplayUnit(supply, system) : null
  const initialUnit: SupplyVolumeUnit | undefined =
    editUnit === null ? NEW_SUPPLY_UNIT[units.volume] : editUnit === 'count' ? undefined : editUnit
  // The account's flavour, plus the starting unit when it's the other one so it stays selectable.
  const flavourUnits: SupplyVolumeUnit[] = ['mL', 'L', `fl_oz_${flavour}`, `qt_${flavour}`, `gal_${flavour}`]
  const unitOptions =
    initialUnit && !flavourUnits.includes(initialUnit) ? [...flavourUnits, initialUnit] : flavourUnits

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeSupplySchema(t), [t])

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<SupplyFormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: supply?.name || '',
      unit_type: supply?.unit_type || 'volume',
      volume_unit: initialUnit,
      part_number: supply?.part_number || '',
      barcode: supply?.barcode || '',
      category: supply?.category || '',
      notes: supply?.notes || '',
      vin: supply?.vin || '',
    },
  })
  const unitType = watch('unit_type')

  const onSubmit = async (data: SupplyFormData) => {
    setError(null)

    try {
      // A count supply never carries a unit (the backend 422s it), and the hidden
      // field still holds one after a switch to count, so the key gets left out.
      if (isEdit && supply) {
        const payload: SupplyUpdate = {
          name: data.name,
          part_number: data.part_number || null,
          barcode: data.barcode || null,
          category: data.category || null,
          notes: data.notes || null,
          vin: data.vin || null,
          is_active: isActive,
          ...(supply.unit_type === 'volume' ? { volume_unit: data.volume_unit } : {}),
        }
        await updateMutation.mutateAsync({ id: supply.id, ...payload })
      } else {
        const payload: SupplyCreate = {
          name: data.name,
          unit_type: data.unit_type,
          ...(data.unit_type === 'volume' ? { volume_unit: data.volume_unit } : {}),
          part_number: data.part_number || undefined,
          barcode: data.barcode || undefined,
          category: data.category || undefined,
          notes: data.notes || undefined,
          vin: data.vin || undefined,
        }
        await createMutation.mutateAsync(payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<SupplyFormData>(setFieldError, err, [
        'name',
        'unit_type',
        'volume_unit',
        'part_number',
        'category',
        'notes',
        'vin',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('supplies.saveAction')))
      }
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('supplies.editSupply') : t('supplies.addSupply')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button
            type="submit"
            form="supply-form"
            variant="primary"
            icon={Save}
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
      <form id="supply-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4 p-6">
        {error && (
          <div className="rounded-lg border border-danger bg-danger/10 p-3">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="name" label={t('supplies.name')} required error={errors.name}>
            <Input
              id="name"
              type="text"
              {...register('name')}
              placeholder={t('suppliesPage.namePlaceholder')}
              invalid={!!errors.name}
              disabled={isSubmitting}
            />
          </Field>

          <Field
            id="unit_type"
            label={t('supplies.unitType')}
            required
            error={errors.unit_type}
            hint={isEdit ? t('supplies.unitTypeImmutable') : undefined}
          >
            <Select
              id="unit_type"
              {...register('unit_type')}
              disabled={isSubmitting || isEdit}
              invalid={!!errors.unit_type}
              options={SUPPLY_UNIT_TYPES.map((unitType) => ({
                value: unitType,
                label: unitType === 'volume' ? t('supplies.unitTypeVolume') : t('supplies.unitTypeCount'),
              }))}
            />
          </Field>
        </div>

        {unitType === 'volume' && (
          <Field
            id="volume_unit"
            label={t('supplies.volumeUnit')}
            error={errors.volume_unit}
            hint={t('supplies.volumeUnitHint')}
          >
            <Select
              id="volume_unit"
              {...register('volume_unit')}
              disabled={isSubmitting}
              invalid={!!errors.volume_unit}
              options={unitOptions.map((unit) => ({ value: unit, label: t(VOLUME_UNIT_LABELS[unit].labelKey) }))}
            />
          </Field>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="part_number" label={t('supplies.partNumber')} error={errors.part_number}>
            <Input
              id="part_number"
              type="text"
              {...register('part_number')}
              invalid={!!errors.part_number}
              disabled={isSubmitting}
            />
          </Field>

          <Field id="category" label={t('supplies.category')} error={errors.category}>
            <Input
              id="category"
              type="text"
              {...register('category')}
              placeholder={t('suppliesPage.categoryPlaceholder')}
              invalid={!!errors.category}
              disabled={isSubmitting}
              list="supply-category-suggestions"
            />
            <datalist id="supply-category-suggestions">
              {categorySuggestions.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
        </div>

        <Field id="barcode" label={t('supplies.barcode')} error={errors.barcode}>
          <div className="flex gap-2 items-start">
            <Input
              id="barcode"
              type="text"
              {...register('barcode')}
              invalid={!!errors.barcode}
              disabled={isSubmitting}
              className="flex-1"
            />
            <BarcodeScanButton
              onScan={(code) => setValue('barcode', code, { shouldDirty: true, shouldValidate: true })}
            />
          </div>
        </Field>

        <Field id="vin" label={t('supplies.vehicle')} error={errors.vin}>
          <Select
            id="vin"
            {...register('vin')}
            disabled={isSubmitting}
            invalid={!!errors.vin}
            placeholder={t('supplies.sharedAcrossVehicles')}
            options={vehicles.map((v) => ({ value: v.vin, label: vehicleLabel(v) }))}
          />
        </Field>

        <Field id="notes" label={t('common:notes')} error={errors.notes}>
          <Textarea id="notes" rows={3} {...register('notes')} invalid={!!errors.notes} disabled={isSubmitting} />
        </Field>

        {isEdit && (
          <Checkbox
            id="is_active"
            label={t('supplies.activeToggle')}
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            disabled={isSubmitting}
          />
        )}
      </form>
    </FormModalWrapper>
  )
}
