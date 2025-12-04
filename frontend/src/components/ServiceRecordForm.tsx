import { useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import { toast } from 'sonner'
import type { ServiceRecord, ServiceRecordCreate, ServiceRecordUpdate, ServiceType } from '../types/service'
import type { AddressBookEntry } from '../types/addressBook'
import { serviceRecordSchema, type ServiceRecordFormData, SERVICE_TYPES } from '../schemas/service'
import { FormError } from './FormError'
import ServiceAttachmentUpload from './ServiceAttachmentUpload'
import ServiceAttachmentList from './ServiceAttachmentList'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import api from '../services/api'

interface ServiceRecordFormProps {
  vin: string
  record?: ServiceRecord
  onClose: () => void
  onSuccess: () => void
}

export default function ServiceRecordForm({ vin, record, onClose, onSuccess }: ServiceRecordFormProps) {
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const [attachmentRefreshTrigger, setAttachmentRefreshTrigger] = useState(0)

  // Helper to format date for input[type="date"] without timezone issues
  const formatDateForInput = (dateString?: string): string => {
    if (!dateString) {
      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
    // If it's already in YYYY-MM-DD format, return as-is
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      return dateString
    }
    // Otherwise parse and format without timezone conversion
    const date = new Date(dateString + 'T00:00:00')
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<ServiceRecordFormData>({
    resolver: zodResolver(serviceRecordSchema) as Resolver<ServiceRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      mileage: record?.mileage ?? undefined,
      description: record?.description || '',
      cost: record?.cost ?? undefined,
      notes: record?.notes || '',
      vendor_name: record?.vendor_name || '',
      vendor_location: record?.vendor_location || '',
      service_type: record?.service_type ?? undefined,
      insurance_claim: record?.insurance_claim || '',
    },
  })

  // Watch fields needed for controlled components
  const description = watch('description')
  const vendor_name = watch('vendor_name')

  const [createReminder, setCreateReminder] = useState(false)
  const [reminderData, setReminderData] = useState({
    due_mileage: '',
    due_date: '',
    description: '',
  })

  const handleAddressBookSelect = (entry: AddressBookEntry | null) => {
    if (entry) {
      // Auto-populate vendor fields from address book entry
      const locationParts = []
      if (entry.address) locationParts.push(entry.address)
      if (entry.city && entry.state) locationParts.push(`${entry.city}, ${entry.state}`)
      else if (entry.city) locationParts.push(entry.city)
      else if (entry.state) locationParts.push(entry.state)

      setValue('vendor_name', entry.business_name || entry.name || '')
      setValue('vendor_location', locationParts.join(', ') || '')
    }
  }

  const onSubmit = async (data: ServiceRecordFormData) => {
    setError(null)

    try {
      // Zod has already validated and coerced mileage and cost - no parseFloat/parseInt/isNaN needed!
      const payload: ServiceRecordCreate | ServiceRecordUpdate = {
        vin,
        date: data.date,
        mileage: data.mileage,
        description: data.description,
        cost: data.cost,
        notes: data.notes,
        vendor_name: data.vendor_name,
        vendor_location: data.vendor_location,
        service_type: data.service_type as ServiceType,
        insurance_claim: data.insurance_claim,
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/service/${record.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/service`, payload)
      }

      // If creating a reminder, create it now
      if (createReminder && (reminderData.due_mileage || reminderData.due_date)) {
        try {
          // Validate reminder mileage
          const reminderMileage = reminderData.due_mileage ? parseInt(reminderData.due_mileage) : undefined
          if (reminderData.due_mileage && isNaN(reminderMileage as number)) {
            toast.error('Invalid reminder mileage value')
            // Continue without creating reminder
          } else {
            const reminderPayload = {
              vin: vin,
              description: reminderData.description || `Next ${data.description}`,
              due_date: reminderData.due_date || undefined,
              due_mileage: reminderMileage,
              is_recurring: false,
              notes: `Auto-created from service record on ${data.date}`,
            }

            try {
              await api.post(`/vehicles/${vin}/reminders`, reminderPayload)
            } catch {
              // Don't fail the whole operation if reminder creation fails
            }
          }
        } catch {
          // Don't fail the whole operation if reminder creation fails
        }
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-full sm:max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Service Record' : 'Add Service Record'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
                Date <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="date"
                {...register('date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.date} />
            </div>

            <div>
              <label htmlFor="mileage" className="block text-sm font-medium text-garage-text mb-1">
                Mileage
              </label>
              <input
                type="number"
                id="mileage"
                {...register('mileage')}
                min="0"
                placeholder="45000"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.mileage ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage} />
            </div>
          </div>

          <div>
            <label htmlFor="service_type" className="block text-sm font-medium text-garage-text mb-1">
              Service Type
            </label>
            <select
              id="service_type"
              {...register('service_type')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.service_type ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            >
              <option value="" className="bg-garage-bg text-garage-text">Select type</option>
              {SERVICE_TYPES.map((type) => (
                <option key={type} value={type} className="bg-garage-bg text-garage-text">{type}</option>
              ))}
            </select>
            <FormError error={errors.service_type} />
          </div>

          <div>
            <label htmlFor="description" className="block text-sm font-medium text-garage-text mb-1">
              Description <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              id="description"
              {...register('description')}
              placeholder="Oil change and tire rotation"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.description ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.description} />
          </div>

          <div>
            <label htmlFor="cost" className="block text-sm font-medium text-garage-text mb-1">
              Cost
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="cost"
                {...register('cost')}
                min="0"
                step="0.01"
                placeholder="89.99"
                className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.cost ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
            </div>
            <FormError error={errors.cost} />
          </div>

          <div>
            <label htmlFor="vendor_name" className="block text-sm font-medium text-garage-text mb-1">
              Vendor/Shop Name
            </label>
            <AddressBookAutocomplete
              id="vendor_name"
              value={vendor_name ?? ""}
              onChange={(value) => setValue('vendor_name', value)}
              onSelectEntry={handleAddressBookSelect}
              placeholder="Type to search vendors..."
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
          </div>

          <div>
            <label htmlFor="vendor_location" className="block text-sm font-medium text-garage-text mb-1">
              Location
            </label>
            <input
              type="text"
              id="vendor_location"
              {...register('vendor_location')}
              placeholder="123 Main St"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.vendor_location ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.vendor_location} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder="Additional notes about this service..."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div>
            <label htmlFor="insurance_claim" className="block text-sm font-medium text-garage-text mb-1">
              Insurance Claim Number
            </label>
            <input
              type="text"
              id="insurance_claim"
              {...register('insurance_claim')}
              placeholder="Claim #12345"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.insurance_claim ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.insurance_claim} />
            <p className="text-xs text-garage-text-muted mt-1">
              Optional - typically used for Collision service type
            </p>
          </div>

          <div className="border-t border-garage-border pt-4 mt-4">
            <label className="flex items-center gap-2 mb-3">
              <input
                type="checkbox"
                checked={createReminder}
                onChange={(e) => setCreateReminder(e.target.checked)}
                className="w-4 h-4 text-primary focus:ring-2 focus:ring-primary border-garage-border rounded"
              />
              <span className="text-sm font-medium text-garage-text">Create reminder for next service</span>
            </label>

            {createReminder && (
              <div className="ml-6 space-y-3 pl-4 border-l-2 border-primary/30">
                <div>
                  <label htmlFor="reminder_mileage" className="block text-sm font-medium text-garage-text mb-1">
                    Due at odometer (miles)
                  </label>
                  <input
                    type="number"
                    id="reminder_mileage"
                    min="0"
                    value={reminderData.due_mileage}
                    onChange={(e) => setReminderData({ ...reminderData, due_mileage: e.target.value })}
                    placeholder="55000"
                    className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>

                <div>
                  <label htmlFor="reminder_date" className="block text-sm font-medium text-garage-text mb-1">
                    Due by date
                  </label>
                  <input
                    type="date"
                    id="reminder_date"
                    value={reminderData.due_date}
                    onChange={(e) => setReminderData({ ...reminderData, due_date: e.target.value })}
                    className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>

                <div>
                  <label htmlFor="reminder_description" className="block text-sm font-medium text-garage-text mb-1">
                    Reminder description
                  </label>
                  <input
                    type="text"
                    id="reminder_description"
                    value={reminderData.description}
                    onChange={(e) => setReminderData({ ...reminderData, description: e.target.value })}
                    placeholder={`Next ${description || 'service'}`}
                    className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                  />
                </div>
              </div>
            )}
          </div>

          {isEdit && record && (
            <div className="border-t border-garage-border pt-4 mt-4">
              <h3 className="text-sm font-semibold text-garage-text mb-3">Attachments</h3>

              <ServiceAttachmentUpload
                recordId={record.id}
                onUploadSuccess={() => setAttachmentRefreshTrigger(prev => prev + 1)}
              />

              <div className="mt-4">
                <ServiceAttachmentList
                  recordId={record.id}
                  refreshTrigger={attachmentRefreshTrigger}
                />
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
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
