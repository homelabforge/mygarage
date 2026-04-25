import { useState, useMemo, useRef, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Save, Plus, AlertTriangle, Paperclip } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { toast } from 'sonner'
import type { ServiceVisit, ServiceVisitCreate, ServiceVisitFormData, ServiceVisitFormLineItem, ServiceLineItemCreate, ServiceLineItemUpdate, ServiceCategory } from '../types/serviceVisit'
import type { VehicleType } from '../types/vehicle'
import { SERVICE_CATEGORIES } from '../schemas/serviceVisit'
import VendorSearch from './VendorSearch'
import LineItemEditor from './LineItemEditor'
import ServiceVisitAttachmentUpload from './ServiceVisitAttachmentUpload'
import ServiceVisitAttachmentList from './ServiceVisitAttachmentList'
import { useCreateServiceVisit, useUpdateServiceVisit } from '../hooks/queries/useServiceVisits'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useLatestMileage } from '../hooks/useLatestMileage'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'

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
})

const NON_MOTORIZED_TYPES: VehicleType[] = ['Trailer', 'FifthWheel', 'TravelTrailer']

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
  const createMutation = useCreateServiceVisit(vin)
  const updateMutation = useUpdateServiceVisit(vin)
  const isMotorized = !vehicleType || !NON_MOTORIZED_TYPES.includes(vehicleType)
  const { data: currentMileage } = useLatestMileage(vin)
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
        })),
      }
    }

    const initialLineItem = createEmptyLineItem(assignTempId())

    return {
      vendor_id: undefined,
      date: dateStr,
      odometer_km: undefined,
      notes: '',
      insurance_claim_number: '',
      tax_amount: undefined,
      shop_supplies: undefined,
      misc_fees: undefined,
      line_items: [initialLineItem],
    }
  })

  // Calculate subtotal and total cost
  const subtotal = useMemo(() => {
    return formData.line_items.reduce((sum, item) => sum + (item.cost || 0), 0)
  }, [formData.line_items])

  const totalCost = useMemo(() => {
    return subtotal + (formData.tax_amount || 0) + (formData.shop_supplies || 0) + (formData.misc_fees || 0)
  }, [subtotal, formData.tax_amount, formData.shop_supplies, formData.misc_fees])

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

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

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
    <FormModalWrapper title={isEdit ? t('service.editTitle') : t('service.createTitle')} onClose={onClose} maxWidth="max-w-full sm:max-w-3xl">
        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-danger" />
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {/* Visit Details */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
              {t('service.visitDetails')}
            </h3>

            <div className={`grid grid-cols-1 ${isMotorized ? 'md:grid-cols-2' : ''} gap-4`}>
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">
                  {t('common:date')} <span className="text-danger">*</span>
                </label>
                <input
                  type="date"
                  value={formData.date}
                  onChange={(e) => handleFieldChange('date', e.target.value)}
                  required
                  disabled={submitting}
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
              </div>

              {isMotorized && (
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-1">
                    {t('common:mileage')} ({UnitFormatter.getDistanceUnit(system)})
                  </label>
                  <input
                    type="number"
                    value={formData.odometer_km ?? ''}
                    onChange={(e) => handleFieldChange('odometer_km', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.1"
                    placeholder={system === 'imperial' ? '45000' : '72420'}
                    disabled={submitting}
                    className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">{t('service.vendorShop')}</label>
              <VendorSearch
                value={formData.vendor_id}
                onSelect={(vendor) => handleFieldChange('vendor_id', vendor?.id)}
                disabled={submitting}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                {t('service.insuranceClaim')}
              </label>
              <input
                type="text"
                value={formData.insurance_claim_number}
                onChange={(e) => handleFieldChange('insurance_claim_number', e.target.value)}
                placeholder="Claim #12345"
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">{t('service.visitNotes')}</label>
              <textarea
                value={formData.notes}
                onChange={(e) => handleFieldChange('notes', e.target.value)}
                placeholder={t('service.visitNotesPlaceholder')}
                rows={2}
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
            </div>
          </div>

          {/* Line Items */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
                {t('service.servicesPerformed')}
              </h3>
              <button
                type="button"
                onClick={handleAddLineItem}
                disabled={submitting}
                className="flex items-center gap-1 text-sm text-primary hover:text-primary/80"
              >
                <Plus className="w-4 h-4" />
                {t('service.addItem')}
              </button>
            </div>

            <div className="space-y-3">
              {formData.line_items.map((item, index) => (
                <div key={item.id ?? item.tempId ?? index}>
                  <LineItemEditor
                    item={item}
                    index={index}
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
                      <button
                        type="button"
                        onClick={() => handleAddRepairFromInspection(index)}
                        className="mt-2 ml-4 text-sm text-primary hover:text-primary/80 flex items-center gap-1"
                      >
                        <Plus className="w-3 h-3" />
                        {t('service.addRepairForInspection')}
                      </button>
                    )}
                </div>
              ))}
            </div>
          </div>

          {/* Tax & Fees */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
              {t('service.taxAndFees')}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('service.tax')}</label>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    value={formData.tax_amount ?? ''}
                    onChange={(e) => handleFieldChange('tax_amount', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="w-full pl-7 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('service.shopSupplies')}</label>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    value={formData.shop_supplies ?? ''}
                    onChange={(e) => handleFieldChange('shop_supplies', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="w-full pl-7 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('service.miscFees')}</label>
                <div className="relative">
                  <CurrencyInputPrefix />
                  <input
                    type="number"
                    value={formData.misc_fees ?? ''}
                    onChange={(e) => handleFieldChange('misc_fees', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    disabled={submitting}
                    className="w-full pl-7 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Total */}
          <div className="space-y-2 pt-4 border-t border-garage-border">
            <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
              <span>{t('service.subtotal')}:</span>
              <span>${subtotal.toFixed(2)}</span>
            </div>
            {(formData.tax_amount || formData.shop_supplies || formData.misc_fees) && (
              <>
                {formData.tax_amount && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>{t('service.tax')}:</span>
                    <span>${formData.tax_amount.toFixed(2)}</span>
                  </div>
                )}
                {formData.shop_supplies && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>{t('service.shopSupplies')}:</span>
                    <span>${formData.shop_supplies.toFixed(2)}</span>
                  </div>
                )}
                {formData.misc_fees && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>{t('service.miscFees')}:</span>
                    <span>${formData.misc_fees.toFixed(2)}</span>
                  </div>
                )}
              </>
            )}
            <div className="flex items-center justify-end gap-2">
              <span className="text-sm text-garage-text-muted">{t('common:totalCost')}:</span>
              <span className="text-lg font-semibold text-garage-text">${totalCost.toFixed(2)}</span>
            </div>
          </div>

          {/* Attachments (only in edit mode) */}
          {isEdit && visit && (
            <div className="space-y-4 pt-4 border-t border-garage-border">
              <div className="flex items-center gap-2">
                <Paperclip className="w-4 h-4 text-garage-text-muted" />
                <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
                  {t('service.attachments')}
                </h3>
              </div>

              <ServiceVisitAttachmentList
                visitId={visit.id}
                refreshTrigger={attachmentRefreshKey}
              />

              <ServiceVisitAttachmentUpload
                visitId={visit.id}
                onUploadSuccess={() => setAttachmentRefreshKey((k) => k + 1)}
              />
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{submitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn btn-primary rounded-lg transition-colors"
            >
              {t('common:cancel')}
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
