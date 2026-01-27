import { useState, useEffect, useMemo } from 'react'
import { X, Save, Plus, AlertTriangle, Paperclip } from 'lucide-react'
import { toast } from 'sonner'
import type { ServiceVisit, ServiceVisitCreate, ServiceVisitFormData, ServiceVisitFormLineItem } from '../types/serviceVisit'
import type { MaintenanceScheduleItem } from '../types/maintenanceSchedule'
import type { ServiceCategory } from '../types/service'
import { SERVICE_CATEGORIES } from '../schemas/service'
import VendorSearch from './VendorSearch'
import LineItemEditor from './LineItemEditor'
import ServiceVisitAttachmentUpload from './ServiceVisitAttachmentUpload'
import ServiceVisitAttachmentList from './ServiceVisitAttachmentList'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

interface ServiceVisitFormProps {
  vin: string
  visit?: ServiceVisit
  preselectedScheduleItem?: MaintenanceScheduleItem
  onClose: () => void
  onSuccess: () => void
}

const createEmptyLineItem = (): ServiceVisitFormLineItem => ({
  description: '',
  cost: undefined,
  notes: '',
  is_inspection: false,
  inspection_result: '',
  inspection_severity: '',
  schedule_item_id: undefined,
  triggered_by_inspection_id: undefined,
})

export default function ServiceVisitForm({
  vin,
  visit,
  preselectedScheduleItem,
  onClose,
  onSuccess,
}: ServiceVisitFormProps) {
  const isEdit = !!visit
  const { system } = useUnitPreference()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [scheduleItems, setScheduleItems] = useState<MaintenanceScheduleItem[]>([])
  const [attachmentRefreshKey, setAttachmentRefreshKey] = useState(0)

  // Form state
  const [formData, setFormData] = useState<ServiceVisitFormData>(() => {
    const today = new Date()
    const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

    if (visit) {
      return {
        vendor_id: visit.vendor_id,
        date: visit.date.split('T')[0],
        mileage: system === 'metric' && visit.mileage ? UnitConverter.milesToKm(Number(visit.mileage)) ?? Number(visit.mileage) : visit.mileage ? Number(visit.mileage) : undefined,
        notes: visit.notes || '',
        service_category: visit.service_category || '',
        insurance_claim_number: visit.insurance_claim_number || '',
        tax_amount: visit.tax_amount !== undefined && visit.tax_amount !== null ? Number(visit.tax_amount) : undefined,
        shop_supplies: visit.shop_supplies !== undefined && visit.shop_supplies !== null ? Number(visit.shop_supplies) : undefined,
        misc_fees: visit.misc_fees !== undefined && visit.misc_fees !== null ? Number(visit.misc_fees) : undefined,
        line_items: visit.line_items.map((item) => ({
          description: item.description,
          cost: item.cost !== undefined && item.cost !== null ? Number(item.cost) : undefined,
          notes: item.notes || '',
          is_inspection: item.is_inspection,
          inspection_result: item.inspection_result || '',
          inspection_severity: item.inspection_severity || '',
          schedule_item_id: item.schedule_item_id,
          triggered_by_inspection_id: item.triggered_by_inspection_id,
        })),
      }
    }

    // New visit with preselected schedule item
    const initialLineItem = createEmptyLineItem()
    if (preselectedScheduleItem) {
      initialLineItem.description = preselectedScheduleItem.name
      initialLineItem.schedule_item_id = preselectedScheduleItem.id
      initialLineItem.is_inspection = preselectedScheduleItem.item_type === 'inspection'
    }

    return {
      vendor_id: undefined,
      date: dateStr,
      mileage: undefined,
      notes: '',
      service_category: '',
      insurance_claim_number: '',
      tax_amount: undefined,
      shop_supplies: undefined,
      misc_fees: undefined,
      line_items: [initialLineItem],
    }
  })

  // Load schedule items for linking
  useEffect(() => {
    api
      .get(`/vehicles/${vin}/maintenance-schedule`)
      .then((response) => {
        setScheduleItems(response.data.items || [])
      })
      .catch(() => {
        // Ignore error, schedule items are optional
      })
  }, [vin])

  // Calculate subtotal and total cost
  const subtotal = useMemo(() => {
    return formData.line_items.reduce((sum, item) => sum + (item.cost || 0), 0)
  }, [formData.line_items])

  const totalCost = useMemo(() => {
    return subtotal + (formData.tax_amount || 0) + (formData.shop_supplies || 0) + (formData.misc_fees || 0)
  }, [subtotal, formData.tax_amount, formData.shop_supplies, formData.misc_fees])

  // Get failed inspections from current line items (for linking repairs)
  const failedInspections = useMemo(() => {
    return formData.line_items
      .map((item, idx) => ({
        id: idx,
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
    setFormData((prev) => ({
      ...prev,
      line_items: [...prev.line_items, createEmptyLineItem()],
    }))
  }

  const handleRemoveLineItem = (index: number) => {
    if (formData.line_items.length <= 1) {
      toast.error('At least one line item is required')
      return
    }
    setFormData((prev) => ({
      ...prev,
      line_items: prev.line_items.filter((_, i) => i !== index),
    }))
  }

  const handleAddRepairFromInspection = (inspectionIndex: number) => {
    const inspection = formData.line_items[inspectionIndex]
    const repairItem = createEmptyLineItem()
    repairItem.description = `Repair: ${inspection.description}`
    repairItem.triggered_by_inspection_id = inspectionIndex
    setFormData((prev) => ({
      ...prev,
      line_items: [...prev.line_items, repairItem],
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    // Validate
    const emptyDescriptions = formData.line_items.some((item) => !item.description.trim())
    if (emptyDescriptions) {
      setError('All line items must have a description')
      return
    }

    const inspectionsMissingResult = formData.line_items.some(
      (item) => item.is_inspection && !item.inspection_result
    )
    if (inspectionsMissingResult) {
      setError('All inspection items must have a result')
      return
    }

    setSubmitting(true)
    try {
      // Convert mileage from user's unit system to imperial
      // Mileage must be rounded to integer - backend stores as INT
      const convertedMileage = system === 'metric' && formData.mileage
        ? UnitConverter.kmToMiles(formData.mileage)
        : formData.mileage
      const mileage = convertedMileage != null ? Math.round(convertedMileage) : undefined

      const payload: ServiceVisitCreate = {
        vendor_id: formData.vendor_id,
        date: formData.date,
        mileage,
        notes: formData.notes || undefined,
        service_category: (formData.service_category as ServiceCategory) || undefined,
        insurance_claim_number: formData.insurance_claim_number || undefined,
        tax_amount: formData.tax_amount,
        shop_supplies: formData.shop_supplies,
        misc_fees: formData.misc_fees,
        line_items: formData.line_items.map((item) => ({
          description: item.description,
          cost: item.cost,
          notes: item.notes || undefined,
          is_inspection: item.is_inspection,
          inspection_result: item.inspection_result || undefined,
          inspection_severity: item.inspection_severity || undefined,
          schedule_item_id: item.schedule_item_id,
          triggered_by_inspection_id: item.triggered_by_inspection_id,
        })),
      }

      if (isEdit && visit) {
        await api.put(`/vehicles/${vin}/service-visits/${visit.id}`, payload)
        toast.success('Service visit updated')
      } else {
        await api.post(`/vehicles/${vin}/service-visits`, payload)
        toast.success('Service visit created')
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-full sm:max-w-3xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg z-10">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Service Visit' : 'Log Service Visit'}
          </h2>
          <button onClick={onClose} className="text-garage-text-muted hover:text-garage-text">
            <X className="w-5 h-5" />
          </button>
        </div>

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
              Visit Details
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">
                  Date <span className="text-danger">*</span>
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

              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">
                  Mileage ({UnitFormatter.getDistanceUnit(system)})
                </label>
                <input
                  type="number"
                  value={formData.mileage ?? ''}
                  onChange={(e) => handleFieldChange('mileage', e.target.value ? parseFloat(e.target.value) : undefined)}
                  min="0"
                  placeholder={system === 'imperial' ? '45000' : '72420'}
                  disabled={submitting}
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">Vendor/Shop</label>
              <VendorSearch
                value={formData.vendor_id}
                onSelect={(vendor) => handleFieldChange('vendor_id', vendor?.id)}
                disabled={submitting}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">Category</label>
                <select
                  value={formData.service_category}
                  onChange={(e) => handleFieldChange('service_category', e.target.value)}
                  disabled={submitting}
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                >
                  <option value="">Select category...</option>
                  {SERVICE_CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">
                  Insurance Claim #
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
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">Visit Notes</label>
              <textarea
                value={formData.notes}
                onChange={(e) => handleFieldChange('notes', e.target.value)}
                placeholder="Overall notes about this visit..."
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
                Services Performed
              </h3>
              <button
                type="button"
                onClick={handleAddLineItem}
                disabled={submitting}
                className="flex items-center gap-1 text-sm text-primary hover:text-primary/80"
              >
                <Plus className="w-4 h-4" />
                Add Item
              </button>
            </div>

            <div className="space-y-3">
              {formData.line_items.map((item, index) => (
                <div key={index}>
                  <LineItemEditor
                    item={item}
                    index={index}
                    scheduleItems={scheduleItems}
                    failedInspections={failedInspections.filter((fi) => fi.id !== index)}
                    onChange={handleLineItemChange}
                    onRemove={handleRemoveLineItem}
                    disabled={submitting}
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
                        Add repair for this inspection
                      </button>
                    )}
                </div>
              ))}
            </div>
          </div>

          {/* Tax & Fees */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
              Tax & Fees
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">Tax</label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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
                <label className="block text-sm font-medium text-garage-text mb-1">Shop Supplies</label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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
                <label className="block text-sm font-medium text-garage-text mb-1">Misc Fees</label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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
              <span>Subtotal:</span>
              <span>${subtotal.toFixed(2)}</span>
            </div>
            {(formData.tax_amount || formData.shop_supplies || formData.misc_fees) && (
              <>
                {formData.tax_amount && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>Tax:</span>
                    <span>${formData.tax_amount.toFixed(2)}</span>
                  </div>
                )}
                {formData.shop_supplies && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>Shop Supplies:</span>
                    <span>${formData.shop_supplies.toFixed(2)}</span>
                  </div>
                )}
                {formData.misc_fees && (
                  <div className="flex items-center justify-end gap-2 text-sm text-garage-text-muted">
                    <span>Misc Fees:</span>
                    <span>${formData.misc_fees.toFixed(2)}</span>
                  </div>
                )}
              </>
            )}
            <div className="flex items-center justify-end gap-2">
              <span className="text-sm text-garage-text-muted">Total Cost:</span>
              <span className="text-lg font-semibold text-garage-text">${totalCost.toFixed(2)}</span>
            </div>
          </div>

          {/* Attachments (only in edit mode) */}
          {isEdit && visit && (
            <div className="space-y-4 pt-4 border-t border-garage-border">
              <div className="flex items-center gap-2">
                <Paperclip className="w-4 h-4 text-garage-text-muted" />
                <h3 className="text-sm font-semibold text-garage-text-muted uppercase tracking-wide">
                  Attachments
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
              <span>{submitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn btn-primary rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
