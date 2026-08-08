import { useState, useMemo, useRef, useEffect, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Save, Plus, AlertTriangle, Paperclip } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { toast } from 'sonner'
import type { ServiceVisit, ServiceVisitCreate, ServiceVisitFormData, ServiceVisitFormLineItem, ServiceLineItemCreate, ServiceLineItemUpdate, ServiceCategory, SupplyUsedEntry } from '../types/serviceVisit'
import type { Vehicle, VehicleType } from '../types/vehicle'
import { NON_MOTORIZED_TYPES } from '../schemas/vehicle'
import type { Supply } from '../types/supplies'
import type { UnitSystem } from '../utils/units'
import { SERVICE_CATEGORIES } from '../schemas/serviceVisit'
import VendorSearch from './VendorSearch'
import LineItemEditor from './LineItemEditor'
import ServiceVisitAttachmentUpload from './ServiceVisitAttachmentUpload'
import ServiceVisitAttachmentList from './ServiceVisitAttachmentList'
import { useCreateServiceVisit, useUpdateServiceVisit } from '../hooks/queries/useServiceVisits'
import { useSupplies } from '../hooks/queries/useSupplies'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useLatestMileage } from '../hooks/useLatestMileage'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'
import { canonicalToDisplay, displayToCanonical } from '../utils/supplyUnits'
import { getUsageTracking } from '../utils/usageTracking'
import api from '../services/api'
import { Button, Field, Input, Textarea, Mono } from './ui'
import { formatCurrency, formatCurrencyZero } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'

// Shared by the edit-hydration effect (canonical -> display, via
// canonicalToDisplay) and mapSuppliesUsedForSubmit (display -> canonical, via
// displayToCanonical) — same shape, same "drop what can't be resolved"
// fallback, opposite direction. A miss here almost never means the supply was
// hard-deleted (delete_supply only allows that for supplies with zero usage
// history); it's far more likely a vin-repin moved it out of this vehicle's
// scope. Either way, dropping silently is the least-bad option available
// without turning a units-conversion helper into a place that also owns
// user-facing warnings.
function convertSupplyUsages(
  usages: { supply_id: number; quantity: number | string }[],
  suppliesById: Map<number, Supply>,
  system: UnitSystem,
  convert: (value: number, unitType: Supply['unit_type'], system: UnitSystem) => number,
): SupplyUsedEntry[] {
  return usages.reduce<SupplyUsedEntry[]>((acc, usage) => {
    const supply = suppliesById.get(usage.supply_id)
    if (!supply) return acc
    acc.push({ supply_id: usage.supply_id, quantity: convert(Number(usage.quantity), supply.unit_type, system) })
    return acc
  }, [])
}

interface ServiceVisitFormProps {
  vin: string
  vehicleType?: VehicleType
  visit?: ServiceVisit
  onClose: () => void
  onSuccess: () => void
}

const createEmptyLineItem = (tempId: number): ServiceVisitFormLineItem => ({
  tempId,
  description: '',
  category: '',
  cost: undefined,
  notes: '',
  is_inspection: false,
  inspection_result: '',
  inspection_severity: '',
  triggered_by_inspection_id: undefined,
  supplies_used: [],
})

const NON_MOTORIZED: readonly string[] = NON_MOTORIZED_TYPES

export default function ServiceVisitForm({
  vin,
  vehicleType,
  visit,
  onClose,
  onSuccess,
}: ServiceVisitFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!visit
  const { system } = useUnitPreference()
  const { currencyCode, locale } = useCurrencyPreference()
  const createMutation = useCreateServiceVisit(vin)
  const updateMutation = useUpdateServiceVisit(vin)
  const isMotorized = !vehicleType || !NON_MOTORIZED.includes(vehicleType)
  const { data: currentMileage } = useLatestMileage(vin)
  // Task 14 — which usage dimension(s) this vehicle tracks, driving the
  // odometer vs. engine-hours field visibility below. Defaults mirror
  // getUsageTracking's own distance-primary default so the form doesn't
  // flash the wrong field before the vehicle fetch resolves. `vehicleType`
  // arrives as a prop (ServiceTab already fetches the vehicle), but
  // usage_unit/secondary_usage_enabled don't — mirrors FuelRecordForm's own
  // independent `/vehicles/{vin}` fetch (Task 13) rather than threading a
  // new prop through ServiceTab.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  useEffect(() => {
    const fetchVehicleUsage = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
        setVehicleUsageUnit(vehicleData.usage_unit || 'distance')
        setVehicleSecondaryUsageEnabled(!!vehicleData.secondary_usage_enabled)
      } catch {
        // Silent fail - non-critical for field visibility
      }
    }
    fetchVehicleUsage()
  }, [vin])
  const { tracksDistance, tracksHours } = getUsageTracking({
    usage_unit: vehicleUsageUnit,
    secondary_usage_enabled: vehicleSecondaryUsageEnabled,
  })
  // UNFILTERED (include archived, NO vin scope): this lookup backs cost-breakdown,
  // edit-hydration and the submit map, all of which must resolve EVERY consumed
  // supply — including one later archived OR repinned to a different vehicle. A
  // vin-scoped fetch here would drop such a usage on hydrate/submit, and the
  // backend's wholesale-replace would then silently delete the historical row.
  // The picker (SupplyUsedPicker) re-applies the vin scope for its ADDABLE options,
  // so only shared/this-vehicle supplies can be newly added.
  const { data: suppliesData, isSuccess: suppliesLoaded, isError: suppliesError } =
    useSupplies(true)
  const supplies = useMemo(() => suppliesData?.supplies ?? [], [suppliesData])
  const suppliesById = useMemo(() => {
    const map = new Map<number, Supply>()
    for (const s of supplies) map.set(s.id, s)
    return map
  }, [supplies])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [attachmentRefreshKey, setAttachmentRefreshKey] = useState(0)
  const nextTempIdRef = useRef(-1)

  const assignTempId = () => {
    const id = nextTempIdRef.current
    nextTempIdRef.current--
    return id
  }

  // Form state
  const [formData, setFormData] = useState<ServiceVisitFormData>(() => {
    const today = new Date()
    const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

    if (visit) {
      return {
        vendor_id: visit.vendor_id ?? undefined,
        date: visit.date.split('T')[0],
        odometer_km: visit.odometer_km != null
          ? (system === 'imperial'
              ? UnitConverter.kmToMiles(Number(visit.odometer_km)) ?? Number(visit.odometer_km)
              : Number(visit.odometer_km))
          : undefined,
        // Task 14 — dimensionless engine-hours reading. NO unit conversion
        // regardless of system, unlike odometer_km above.
        engine_hours: visit.engine_hours != null ? Number(visit.engine_hours) : undefined,
        notes: visit.notes || '',
        insurance_claim_number: visit.insurance_claim_number || '',
        tax_amount: visit.tax_amount !== undefined && visit.tax_amount !== null ? Number(visit.tax_amount) : undefined,
        shop_supplies: visit.shop_supplies !== undefined && visit.shop_supplies !== null ? Number(visit.shop_supplies) : undefined,
        misc_fees: visit.misc_fees !== undefined && visit.misc_fees !== null ? Number(visit.misc_fees) : undefined,
        line_items: visit.line_items.map((item) => ({
          id: item.id,
          tempId: undefined,
          description: item.description,
          category: (item.category as ServiceCategory) || '',
          cost: item.cost !== undefined && item.cost !== null ? Number(item.cost) : undefined,
          notes: item.notes || '',
          is_inspection: item.is_inspection,
          inspection_result: item.inspection_result || '',
          inspection_severity: item.inspection_severity || '',
          triggered_by_inspection_id: item.triggered_by_inspection_id ?? undefined,
          // Hydrated from visit.line_items[*].supply_usages once the supplies
          // list loads (see the hydration effect below) — supply_usages carries
          // canonical quantities and needs each supply's unit_type to convert.
          supplies_used: [],
        })),
      }
    }

    const initialLineItem = createEmptyLineItem(assignTempId())

    return {
      vendor_id: undefined,
      date: dateStr,
      odometer_km: undefined,
      engine_hours: undefined,
      notes: '',
      insurance_claim_number: '',
      tax_amount: undefined,
      shop_supplies: undefined,
      misc_fees: undefined,
      line_items: [initialLineItem],
    }
  })

  // Hydrate supplies_used from visit.line_items[*].supply_usages once the
  // supplies list has loaded. This can't happen in the formData initializer
  // above because useSupplies() resolves asynchronously and supply_usages
  // carries canonical quantities — converting to the user's display units
  // needs each supply's unit_type, which only the loaded list provides.
  //
  // MANDATORY: the backend replaces a line item's usages with whatever
  // supplies_used is submitted (diffed by supply_id). If this hydration is
  // skipped, editing any field on an existing visit silently wipes its
  // logged supply usages on save.
  const suppliesHydratedRef = useRef(false)
  const [editHydrated, setEditHydrated] = useState(false)
  useEffect(() => {
    if (!isEdit || !visit || suppliesHydratedRef.current || !suppliesLoaded) return
    suppliesHydratedRef.current = true
    setFormData((prev) => ({
      ...prev,
      line_items: prev.line_items.map((item) => {
        const responseItem = visit.line_items.find((li) => li.id === item.id)
        const usages = responseItem?.supply_usages
        if (!usages || usages.length === 0) return item
        return { ...item, supplies_used: convertSupplyUsages(usages, suppliesById, system, canonicalToDisplay) }
      }),
    }))
    setEditHydrated(true)
  }, [isEdit, visit, suppliesLoaded, suppliesById, system])

  // Calculate subtotal and total cost
  const subtotal = useMemo(() => {
    return formData.line_items.reduce((sum, item) => sum + (item.cost || 0), 0)
  }, [formData.line_items])

  // Informational estimate only — the authoritative cost snapshot (frozen at
  // each usage's unit_cost_snapshot) is computed server-side.
  const partsSupplies = useMemo(() => {
    let total = 0
    for (const item of formData.line_items) {
      for (const usage of item.supplies_used ?? []) {
        const supply = suppliesById.get(usage.supply_id)
        if (!supply) continue
        const unitCost = supply.avg_unit_cost != null ? Number(supply.avg_unit_cost) : 0
        const canonicalQty = displayToCanonical(usage.quantity, supply.unit_type, system)
        total += unitCost * canonicalQty
      }
    }
    return total
  }, [formData.line_items, suppliesById, system])

  const totalCost = useMemo(() => {
    return (
      subtotal +
      (formData.tax_amount || 0) +
      (formData.shop_supplies || 0) +
      (formData.misc_fees || 0) +
      partsSupplies
    )
  }, [subtotal, formData.tax_amount, formData.shop_supplies, formData.misc_fees, partsSupplies])

  // Get failed inspections from current line items (for linking repairs)
  // Use tempId or id as the identifier — NOT array index
  const failedInspections = useMemo(() => {
    return formData.line_items
      .map((item) => ({
        refId: item.id ?? item.tempId ?? 0,
        description: item.description,
        failed: item.is_inspection && (item.inspection_result === 'failed' || item.inspection_result === 'needs_attention'),
      }))
      .filter((item) => item.failed)
  }, [formData.line_items])

  const handleFieldChange = (field: keyof ServiceVisitFormData, value: unknown) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const handleLineItemChange = (index: number, field: keyof ServiceVisitFormLineItem, value: unknown) => {
    setFormData((prev) => ({
      ...prev,
      line_items: prev.line_items.map((item, i) => (i === index ? { ...item, [field]: value } : item)),
    }))
  }

  const handleAddLineItem = () => {
    const tempId = assignTempId()
    setFormData((prev) => ({
      ...prev,
      line_items: [...prev.line_items, createEmptyLineItem(tempId)],
    }))
  }

  const handleRemoveLineItem = (index: number) => {
    if (formData.line_items.length <= 1) {
      toast.error(t('service.atLeastOneLineItem'))
      return
    }
    setFormData((prev) => ({
      ...prev,
      line_items: prev.line_items.filter((_, i) => i !== index),
    }))
  }

  const handleAddRepairFromInspection = (inspectionIndex: number) => {
    const inspection = formData.line_items[inspectionIndex]
    const tempId = assignTempId()
    const repairItem = createEmptyLineItem(tempId)
    repairItem.description = `Repair: ${inspection.description}`
    repairItem.category = inspection.category
    // Reference by id if saved, tempId if unsaved
    repairItem.triggered_by_inspection_id = inspection.id ?? inspection.tempId
    setFormData((prev) => ({
      ...prev,
      line_items: [...prev.line_items, repairItem],
    }))
  }

  // Display -> canonical for the wire payload.
  const mapSuppliesUsedForSubmit = (item: ServiceVisitFormLineItem): SupplyUsedEntry[] =>
    convertSupplyUsages(item.supplies_used ?? [], suppliesById, system, displayToCanonical)

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

    // On edit, refuse to submit until the supplies list has loaded and hydrated.
    // Otherwise supplies_used is still [] and the backend (which replaces a line
    // item's usages from the submitted list) would silently delete every logged
    // usage on this visit — the wipe-on-edit failure via a slow/failed fetch.
    if (isEdit && !editHydrated) {
      setError(suppliesError ? t('service.suppliesLoadFailed') : t('service.suppliesLoading'))
      return
    }

    // Validate
    const emptyDescriptions = formData.line_items.some((item) => !item.description.trim())
    if (emptyDescriptions) {
      setError(t('service.allLineItemsNeedDescription'))
      return
    }

    const inspectionsMissingResult = formData.line_items.some(
      (item) => item.is_inspection && !item.inspection_result
    )
    if (inspectionsMissingResult) {
      setError(t('service.allInspectionsNeedResult'))
      return
    }

    setSubmitting(true)
    try {
      // Convert user-entered odometer to canonical km for the API.
      const odometerKm = toCanonicalKm(formData.odometer_km, system) ?? undefined

      // Reminder due_mileage_km interval is already canonical km (LineItemEditor
      // converts on input). Add to current km baseline for absolute target.
      const toAbsoluteKm = (interval: number | string | null | undefined): number | undefined => {
        if (interval == null) return undefined
        const num = typeof interval === 'string' ? parseFloat(interval) : interval
        if (isNaN(num)) return undefined
        return currentMileage ? currentMileage + num : num
      }

      if (isEdit && visit) {
        // Diff-based update — include id for existing items, temp_id for new
        const updateLineItems: ServiceLineItemUpdate[] = formData.line_items.map((item) => ({
          id: item.id,
          temp_id: item.id ? undefined : item.tempId,
          description: item.description,
          category: (item.category as ServiceCategory) || undefined,
          cost: item.cost,
          notes: item.notes || undefined,
          is_inspection: item.is_inspection,
          inspection_result: item.inspection_result || undefined,
          inspection_severity: item.inspection_severity || undefined,
          triggered_by_inspection_id: item.triggered_by_inspection_id,
          // ALWAYS sent (even []) — the backend replaces a line item's usages
          // wholesale from this field, so omitting it for an existing item
          // that was never touched here would wipe its logged usages.
          supplies_used: mapSuppliesUsedForSubmit(item),
          // Reminder only for new items (no id) that have an enabled draft
          reminder: !item.id && item.reminderDraft?.enabled ? {
            title: item.reminderDraft.title,
            reminder_type: item.reminderDraft.reminder_type,
            due_date: item.reminderDraft.due_date,
            due_mileage_km: toAbsoluteKm(item.reminderDraft.due_mileage_km),
            notes: item.reminderDraft.notes,
          } : undefined,
        }))

        await updateMutation.mutateAsync({
          id: visit.id,
          vendor_id: formData.vendor_id,
          date: formData.date,
          odometer_km: odometerKm,
          // Dimensionless — submitted verbatim, no canonical conversion
          // (mirrors FuelRecordForm's engine_hours submit).
          engine_hours: formData.engine_hours,
          notes: formData.notes || undefined,
          insurance_claim_number: formData.insurance_claim_number || undefined,
          tax_amount: formData.tax_amount,
          shop_supplies: formData.shop_supplies,
          misc_fees: formData.misc_fees,
          line_items: updateLineItems,
        })
        toast.success(t('service.visitUpdated'))
      } else {
        // Create — map to ServiceLineItemCreate with temp_id + reminder
        const createLineItems: ServiceLineItemCreate[] = formData.line_items.map((item) => ({
          description: item.description,
          category: (item.category as ServiceCategory) || undefined,
          cost: item.cost,
          notes: item.notes || undefined,
          is_inspection: item.is_inspection,
          inspection_result: item.inspection_result || undefined,
          inspection_severity: item.inspection_severity || undefined,
          triggered_by_inspection_id: item.triggered_by_inspection_id,
          temp_id: item.tempId,
          supplies_used: mapSuppliesUsedForSubmit(item),
          reminder: item.reminderDraft?.enabled ? {
            title: item.reminderDraft.title,
            reminder_type: item.reminderDraft.reminder_type,
            due_date: item.reminderDraft.due_date,
            due_mileage_km: toAbsoluteKm(item.reminderDraft.due_mileage_km),
            notes: item.reminderDraft.notes,
          } : undefined,
        }))

        const payload: ServiceVisitCreate = {
          vendor_id: formData.vendor_id,
          date: formData.date,
          odometer_km: odometerKm,
          // Dimensionless — submitted verbatim, no canonical conversion.
          engine_hours: formData.engine_hours,
          notes: formData.notes || undefined,
          insurance_claim_number: formData.insurance_claim_number || undefined,
          tax_amount: formData.tax_amount,
          shop_supplies: formData.shop_supplies,
          misc_fees: formData.misc_fees,
          line_items: createLineItems,
        }

        await createMutation.mutateAsync(payload)
        toast.success(t('service.visitCreated'))
      }

      // Reset temp ID counter after successful submit
      nextTempIdRef.current = -1

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common:error'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('service.editTitle') : t('service.createTitle')}
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            {t('common:cancel')}
          </Button>
          <Button
            type="submit"
            form="service-visit-form"
            variant="primary"
            icon={Save}
            loading={submitting}
            disabled={submitting || (isEdit && !editHydrated)}
          >
            {submitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="service-visit-form" onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3 flex items-center gap-2">
              <AlertTriangle aria-hidden="true" className="w-5 h-5 text-danger" />
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {/* Visit Details */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-text-mute uppercase tracking-wide">{t('service.visitDetails')}</h3>

            <div className={`grid grid-cols-1 ${isMotorized ? 'md:grid-cols-2' : ''} gap-4`}>
              <Field id="service-date" label={t('common:date')} required>
                <Input
                  type="date"
                  id="service-date"
                  value={formData.date}
                  onChange={(e) => handleFieldChange('date', e.target.value)}
                  required
                  disabled={submitting}
                />
              </Field>

              {isMotorized && tracksDistance && (
                <Field id="service-odometer" label={t('common:mileage')} unit={UnitFormatter.getDistanceUnit(system)}>
                  <Input
                    type="number"
                    id="service-odometer"
                    mono
                    value={formData.odometer_km ?? ''}
                    onChange={(e) => handleFieldChange('odometer_km', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.1"
                    placeholder={system === 'imperial' ? '45000' : '72420'}
                    disabled={submitting}
                  />
                </Field>
              )}
            </div>

            {/* Task 14 — engine-hours reading (hour-metered vehicles). Dimensionless:
                NO unit conversion regardless of system, unlike odometer_km above. */}
            {isMotorized && tracksHours && (
              <Field id="service-engine-hours" label={t('common:engineHours')} unit="hr">
                <Input
                  type="number"
                  id="service-engine-hours"
                  mono
                  value={formData.engine_hours ?? ''}
                  onChange={(e) => handleFieldChange('engine_hours', e.target.value ? parseFloat(e.target.value) : undefined)}
                  min="0"
                  step="0.1"
                  placeholder="812.4"
                  disabled={submitting}
                />
              </Field>
            )}

            <div className="mb-4">
              <label className="mb-1 block text-sm font-medium text-text">{t('service.vendorShop')}</label>
              <VendorSearch
                value={formData.vendor_id}
                onSelect={(vendor) => handleFieldChange('vendor_id', vendor?.id)}
                disabled={submitting}
              />
            </div>

            <Field id="insurance-claim" label={t('service.insuranceClaim')}>
              <Input
                type="text"
                id="insurance-claim"
                value={formData.insurance_claim_number}
                onChange={(e) => handleFieldChange('insurance_claim_number', e.target.value)}
                placeholder="Claim #12345"
                disabled={submitting}
              />
            </Field>

            <Field id="visit-notes" label={t('service.visitNotes')}>
              <Textarea
                id="visit-notes"
                rows={2}
                value={formData.notes}
                onChange={(e) => handleFieldChange('notes', e.target.value)}
                placeholder={t('service.visitNotesPlaceholder')}
                disabled={submitting}
              />
            </Field>
          </div>

          {/* Line Items */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-mute uppercase tracking-wide">{t('service.servicesPerformed')}</h3>
              <Button variant="ghost" size="sm" icon={Plus} onClick={handleAddLineItem} disabled={submitting}>
                {t('service.addItem')}
              </Button>
            </div>

            <div className="space-y-3">
              {formData.line_items.map((item, index) => (
                <div key={item.id ?? item.tempId ?? index}>
                  <LineItemEditor
                    item={item}
                    index={index}
                    vin={vin}
                    supplies={supplies}
                    failedInspections={failedInspections.filter((fi) => fi.refId !== (item.id ?? item.tempId ?? 0))}
                    onChange={handleLineItemChange}
                    onRemove={handleRemoveLineItem}
                    disabled={submitting}
                    categories={SERVICE_CATEGORIES as unknown as string[]}
                    isNewItem={!item.id}
                    currentMileage={currentMileage}
                  />
                  {/* Quick action to add repair from failed inspection */}
                  {item.is_inspection &&
                    (item.inspection_result === 'failed' || item.inspection_result === 'needs_attention') && (
                      <Button variant="ghost" size="sm" icon={Plus} onClick={() => handleAddRepairFromInspection(index)} className="mt-2 ml-4">
                        {t('service.addRepairForInspection')}
                      </Button>
                    )}
                </div>
              ))}
            </div>
          </div>

          {/* Tax & Fees */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-text-mute uppercase tracking-wide">{t('service.taxAndFees')}</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Field id="tax-amount" label={t('service.tax')}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="tax-amount"
                    value={formData.tax_amount ?? ''}
                    onChange={(e) => handleFieldChange('tax_amount', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums"
                  />
                </div>
              </Field>
              <Field id="shop-supplies" label={t('service.shopSupplies')}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="shop-supplies"
                    value={formData.shop_supplies ?? ''}
                    onChange={(e) => handleFieldChange('shop_supplies', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums"
                  />
                </div>
              </Field>
              <Field id="misc-fees" label={t('service.miscFees')}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="misc-fees"
                    value={formData.misc_fees ?? ''}
                    onChange={(e) => handleFieldChange('misc_fees', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums"
                  />
                </div>
              </Field>
            </div>
          </div>

          {/* Total */}
          <div className="space-y-2 pt-4 border-t border-border">
            <div className="flex items-center justify-end gap-2 text-sm text-text-mute">
              <span>{t('service.subtotal')}:</span>
              <Mono>{formatCurrencyZero(subtotal, { currencyCode, locale })}</Mono>
            </div>
            {(formData.tax_amount || formData.shop_supplies || formData.misc_fees || partsSupplies > 0) && (
              <>
                {formData.tax_amount && (
                  <div className="flex items-center justify-end gap-2 text-sm text-text-mute">
                    <span>{t('service.tax')}:</span>
                    <Mono>{formatCurrency(formData.tax_amount, { currencyCode, locale })}</Mono>
                  </div>
                )}
                {formData.shop_supplies && (
                  <div className="flex items-center justify-end gap-2 text-sm text-text-mute">
                    <span>{t('service.shopSupplies')}:</span>
                    <Mono>{formatCurrency(formData.shop_supplies, { currencyCode, locale })}</Mono>
                  </div>
                )}
                {formData.misc_fees && (
                  <div className="flex items-center justify-end gap-2 text-sm text-text-mute">
                    <span>{t('service.miscFees')}:</span>
                    <Mono>{formatCurrency(formData.misc_fees, { currencyCode, locale })}</Mono>
                  </div>
                )}
                {partsSupplies > 0 && (
                  <div className="flex items-center justify-end gap-2 text-sm text-text-mute">
                    <span>{t('service.partsSupplies')}:</span>
                    <Mono>{formatCurrency(partsSupplies, { currencyCode, locale })}</Mono>
                  </div>
                )}
              </>
            )}
            <div className="flex items-center justify-end gap-2">
              <span className="text-sm text-text-mute">{t('common:totalCost')}:</span>
              <Mono size="lg" weight="bold">{formatCurrencyZero(totalCost, { currencyCode, locale })}</Mono>
            </div>
          </div>

          {/* Attachments (only in edit mode) */}
          {isEdit && visit && (
            <div className="space-y-4 pt-4 border-t border-border">
              <div className="flex items-center gap-2">
                <Paperclip aria-hidden="true" className="w-4 h-4 text-text-mute" />
                <h3 className="text-sm font-semibold text-text-mute uppercase tracking-wide">{t('service.attachments')}</h3>
              </div>
              <ServiceVisitAttachmentList visitId={visit.id} refreshTrigger={attachmentRefreshKey} />
              <ServiceVisitAttachmentUpload visitId={visit.id} onUploadSuccess={() => setAttachmentRefreshKey((k) => k + 1)} />
            </div>
          )}
          {isEdit && !editHydrated && (
            <p className="text-sm text-text-mute">
              {suppliesError ? t('service.suppliesLoadFailed') : t('service.suppliesLoading')}
            </p>
          )}
        </form>
    </FormModalWrapper>
  )
}
