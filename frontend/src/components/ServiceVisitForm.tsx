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
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useLatestMileage } from '../hooks/useLatestMileage'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { readNumber } from '../utils/decimalSafe'
import { canonicalToDisplay, displayToCanonical } from '../utils/supplyUnits'
import { getUsageTracking } from '../utils/usageTracking'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { applyControlledFieldErrors } from '../hooks/useApiFormErrors'
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
// units-exempt(binary-conversion): R3 supplies deferral, at the DECLARATION. ★ THE ONE TASK 8's REPORT CELEBRATED HALF OF: the gate saw the fourth ARGUMENT of this function (`canonicalToDisplay` / `displayToCanonical` passed as values) and could not see this function, which is the local binary helper that consumes it. It threads the collapsed `system` down to `canonicalToDisplay` / `supplyUnitLabel`, which carry the same ruling at their own declarations in `utils/supplyUnits.ts`: D8 gave supplies a qt/L vocabulary `UnitSet` cannot express, so there is nothing resolved for this to read instead. Owner: deferred, pending the D8 amendment. Expires with the three legs in supplyUnits.ts, never alone.
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
  // ★ `system` survives here for the SUPPLY quantities only. Spec D8 exempts
  // supplies from the resolved set (a quart is not one of the ten quantities),
  // and `canonicalToDisplay` / `displayToCanonical` still take the binary
  // answer. Plan 3b ruling R3 gave that decision to task 5, which RULED IT:
  // all three legs of `utils/supplyUnits.ts` are exempt, because D8's qt/L
  // vocabulary is not in `UnitSet` and so `units` holds nothing they could
  // read. They track `unit_preference` deliberately and move together. Read
  // that file's header before changing this line; the exemption is owned by a
  // D8 amendment now, not by a task. The odometer below reads `u.distance`
  // instead, which is what this form was getting wrong.
  const { system } = useUnitPreference()
  const u = useUnitFormat()
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [attachmentRefreshKey, setAttachmentRefreshKey] = useState(0)
  const nextTempIdRef = useRef(-1)

  const assignTempId = () => {
    const id = nextTempIdRef.current
    nextTempIdRef.current--
    return id
  }

  /**
   * The canonical origin of the odometer reading, seeded once.
   *
   * The reading used to be read and written on `useUnitPreference().system`,
   * which spec D8 collapses from VOLUME: a `{volume: 'L', distance: 'mi'}`
   * account typed miles into a field labelled `km` and stored them verbatim.
   *
   * The origin is what stops an untouched save from rewriting it: 72420.5 km
   * displays as 45000 mi and 45000 mi converts back to 72420.3 km. Seeded
   * through a lazy `useState` for the same reason `formData` is, and before it,
   * because the form's initial odometer is read out of this origin's display.
   */
  const [odometerOrigin] = useState<UnitFieldOrigin>(() =>
    seedUnitField(readNumber(visit?.odometer_km), u.distance)
  )

  // Form state
  const [formData, setFormData] = useState<ServiceVisitFormData>(() => {
    const today = new Date()
    const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

    if (visit) {
      return {
        vendor_id: visit.vendor_id ?? undefined,
        date: visit.date.split('T')[0],
        odometer_km: readNumber(odometerOrigin.display),
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

  /**
   * The replacement for the form's native constraints.
   *
   * `noValidate` on the form means the browser no longer enforces `required`,
   * `min` or `step`, so each has an equivalent here. This is not optional
   * belt-and-braces: without the date check, `noValidate` would let a blank
   * date reach the API, turning a silent no-op into a silent bad write.
   *
   * Returns a field-keyed map so errors render inline on the offending
   * control via `<Field error=...>`, rather than as one banner that does not
   * say which input is wrong.
   */
  const validateFields = (): Record<string, string> => {
    const errors: Record<string, string> = {}

    if (!formData.date) {
      errors.date = t('common:required')
    }

    // `min="0"` equivalents. Checked with `< 0` rather than `!(x >= 0)` so an
    // empty optional field stays valid.
    const nonNegative: [keyof ServiceVisitFormData, string][] = [
      ['odometer_km', 'odometer_km'],
      ['engine_hours', 'engine_hours'],
      ['tax_amount', 'tax_amount'],
      ['shop_supplies', 'shop_supplies'],
      ['misc_fees', 'misc_fees'],
    ]
    for (const [field, key] of nonNegative) {
      const raw = formData[field]
      if (raw === undefined || raw === null || raw === '') continue
      const value = typeof raw === 'string' ? parseFloat(raw) : (raw as number)
      if (Number.isNaN(value)) {
        errors[key] = t('common:mustBeANumber')
      } else if (value < 0) {
        errors[key] = t('common:mustNotBeNegative')
      }
    }

    // `step` equivalents. The browser rejected a value that was not a whole
    // multiple of the step; the user-visible meaning is a decimal-place limit,
    // so that is what the message says.
    const decimals: [keyof ServiceVisitFormData, string, number][] = [
      ['odometer_km', 'odometer_km', 1],
      ['engine_hours', 'engine_hours', 1],
      ['tax_amount', 'tax_amount', 2],
      ['shop_supplies', 'shop_supplies', 2],
      ['misc_fees', 'misc_fees', 2],
    ]
    for (const [field, key, places] of decimals) {
      if (errors[key]) continue
      const raw = formData[field]
      if (raw === undefined || raw === null || raw === '') continue
      const text = String(raw)
      const fraction = text.includes('.') ? text.split('.')[1].length : 0
      if (fraction > places) {
        errors[key] = t('common:tooManyDecimals', { count: places })
      }
    }

    return errors
  }

  /**
   * The nested components' native constraints, enforced here.
   *
   * `LineItemEditor` and `SupplyUsedPicker` render INSIDE this form, so their
   * `min`/`step` attributes abort ITS submit -- and they sit in per-line-item
   * sections that may be collapsed or scrolled away, which is precisely where
   * the browser cannot focus the offending control and the failure is silent.
   * They are also the fields a user is most likely to fumble.
   *
   * Their data lives in this component's `formData.line_items`, so the check
   * belongs here rather than in components that have no error-display path.
   * Reported through `setError` as a banner, matching how the existing
   * description and inspection checks already report per-line-item problems.
   */
  const validateLineItems = (): string | null => {
    for (const [i, item] of formData.line_items.entries()) {
      const n = i + 1
      if (item.cost !== undefined && item.cost !== null) {
        if (Number.isNaN(item.cost)) return t('service.lineItemCostInvalid', { number: n })
        if (item.cost < 0) return t('service.lineItemCostNegative', { number: n })
        const text = String(item.cost)
        if (text.includes('.') && text.split('.')[1].length > 2) {
          return t('service.lineItemCostDecimals', { number: n })
        }
      }
      // The replaced `min="1"` sat on the DISPLAY value, while
      // `due_mileage_km` is canonical km (LineItemEditor converts on change).
      // Comparing canonical km against a bare 1 would silently loosen the
      // floor for an imperial account from 1 mi to 1 km, so the threshold is
      // converted into the same space the constraint was written in.
      const km = item.reminderDraft?.due_mileage_km
      const minimumKm = u.distance.toCanonical(1) ?? 1
      if (km != null && !Number.isNaN(Number(km)) && Number(km) < minimumKm) {
        return t('service.reminderIntervalTooSmall', { number: n })
      }
      for (const usage of item.supplies_used ?? []) {
        if (Number.isNaN(usage.quantity) || usage.quantity < 0) {
          return t('service.supplyQuantityInvalid', { number: n })
        }
        // The replaced `step` was `'1'` for count-type supplies and `'0.01'`
        // otherwise, so a count could not take a fraction. The backend only
        // enforces `gt=0` (schemas/supply.py:75), so dropping this check
        // rather than moving it would let "2.5 oil filters" through.
        if (suppliesById.get(usage.supply_id)?.unit_type === 'count' && !Number.isInteger(usage.quantity)) {
          return t('service.supplyQuantityWholeNumber', { number: n })
        }
      }
    }
    return null
  }

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setFieldErrors({})

    // On edit, refuse to submit until the supplies list has loaded and hydrated.
    // Otherwise supplies_used is still [] and the backend (which replaces a line
    // item's usages from the submitted list) would silently delete every logged
    // usage on this visit — the wipe-on-edit failure via a slow/failed fetch.
    if (isEdit && !editHydrated) {
      setError(suppliesError ? t('service.suppliesLoadFailed') : t('service.suppliesLoading'))
      return
    }

    // Validate. Field-level constraints first: these replace the native
    // `required`/`min`/`step` attributes the form no longer carries, and they
    // render inline on the control rather than as a banner.
    const fieldLevel = validateFields()
    if (Object.keys(fieldLevel).length > 0) {
      setFieldErrors(fieldLevel)
      return
    }

    const lineItemProblem = validateLineItems()
    if (lineItemProblem) {
      setError(lineItemProblem)
      return
    }

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
      // Back through `units.distance`, and an untouched field returns the
      // canonical value it was seeded from rather than a re-conversion of a
      // rounded display.
      const odometerKm =
        canonicalFromUnitField(
          String(formData.odometer_km ?? ''),
          odometerOrigin,
          u.distance
        ) ?? undefined

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
      // Render targets: date, odometer_km, engine_hours, insurance_claim_number,
      // notes, tax_amount, shop_supplies, misc_fees. vendor_id and line_items
      // have no fieldErrors-wired Field, so a problem addressed to either must
      // fall through to the banner below.
      const { attached, unhandled, errorsByField } = applyControlledFieldErrors(err, [
        'date',
        'odometer_km',
        'engine_hours',
        'insurance_claim_number',
        'notes',
        'tax_amount',
        'shop_supplies',
        'misc_fees',
      ])
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('service.saveAction')))
      }
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
        <form
          id="service-visit-form"
          onSubmit={handleSubmit}
          // Native constraints abort submit and try to focus the offending
          // control. Inside a collapsed or scrolled-away section the browser
          // cannot focus it, so Save silently does nothing. Every constraint
          // that used to live on an input is enforced by validateForm below.
          noValidate
          className="p-6 space-y-6"
        >
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
              <Field id="service-date" label={t('common:date')} required error={fieldErrors.date}>
                <Input
                  type="date"
                  id="service-date"
                  value={formData.date}
                  onChange={(e) => handleFieldChange('date', e.target.value)}
                  disabled={submitting}
                />
              </Field>

              {isMotorized && tracksDistance && (
                <Field id="service-odometer" label={t('common:mileage')} unit={u.distance.label} error={fieldErrors.odometer_km}>
                  <Input
                    type="number"
                    id="service-odometer"
                    mono
                    value={formData.odometer_km ?? ''}
                    onChange={(e) => handleFieldChange('odometer_km', e.target.value ? parseFloat(e.target.value) : undefined)}
                    /* One example reading (72420 km) rendered in the client's
                       own distance unit, rather than one of two literals chosen
                       by a collapsed system. It reproduces both shipped hints
                       exactly and needs no new branch for a distance token
                       added later. */
                    placeholder={u.distance.toInputValue(72420)}
                    disabled={submitting}
                  />
                </Field>
              )}
            </div>

            {/* Task 14 — engine-hours reading (hour-metered vehicles). Dimensionless:
                NO unit conversion regardless of system, unlike odometer_km above. */}
            {isMotorized && tracksHours && (
              <Field id="service-engine-hours" label={t('common:engineHours')} unit="hr" error={fieldErrors.engine_hours}>
                <Input
                  type="number"
                  id="service-engine-hours"
                  mono
                  value={formData.engine_hours ?? ''}
                  onChange={(e) => handleFieldChange('engine_hours', e.target.value ? parseFloat(e.target.value) : undefined)}
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

            <Field id="insurance-claim" label={t('service.insuranceClaim')} error={fieldErrors.insurance_claim_number}>
              <Input
                type="text"
                id="insurance-claim"
                value={formData.insurance_claim_number}
                onChange={(e) => handleFieldChange('insurance_claim_number', e.target.value)}
                placeholder="Claim #12345"
                disabled={submitting}
              />
            </Field>

            <Field id="visit-notes" label={t('service.visitNotes')} error={fieldErrors.notes}>
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
              <Field id="tax-amount" label={t('service.tax')} error={fieldErrors.tax_amount}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="tax-amount"
                    value={formData.tax_amount ?? ''}
                    onChange={(e) => handleFieldChange('tax_amount', e.target.value ? parseFloat(e.target.value) : undefined)}
                    placeholder="0.00"
                    disabled={submitting}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums"
                  />
                </div>
              </Field>
              <Field id="shop-supplies" label={t('service.shopSupplies')} error={fieldErrors.shop_supplies}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="shop-supplies"
                    value={formData.shop_supplies ?? ''}
                    onChange={(e) => handleFieldChange('shop_supplies', e.target.value ? parseFloat(e.target.value) : undefined)}
                    placeholder="0.00"
                    disabled={submitting}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums"
                  />
                </div>
              </Field>
              <Field id="misc-fees" label={t('service.miscFees')} error={fieldErrors.misc_fees}>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    id="misc-fees"
                    value={formData.misc_fees ?? ''}
                    onChange={(e) => handleFieldChange('misc_fees', e.target.value ? parseFloat(e.target.value) : undefined)}
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
