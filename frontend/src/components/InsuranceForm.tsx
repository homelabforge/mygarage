import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save, FileUp } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'
import type { InsurancePolicy, InsurancePolicyCreate, InsurancePolicyUpdate } from '../types/insurance'
import { insuranceSchema, type InsuranceFormData, POLICY_TYPES, PREMIUM_FREQUENCIES } from '../schemas/insurance'
import { FormError } from './FormError'
import InsurancePDFUpload from './InsurancePDFUpload'

interface InsuranceFormProps {
  vin: string
  record?: InsurancePolicy
  onClose: () => void
  onSuccess: () => void
}

export default function InsuranceForm({ vin, record, onClose, onSuccess }: InsuranceFormProps) {
  const isEdit = !!record
  const [showPDFUpload, setShowPDFUpload] = useState(false)
  const [autoFilledFields, setAutoFilledFields] = useState<Set<string>>(new Set())

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
  } = useForm<InsuranceFormData>({
    resolver: zodResolver(insuranceSchema),
    defaultValues: {
      provider: record?.provider || '',
      policy_number: record?.policy_number || '',
      policy_type: record?.policy_type || '',
      start_date: formatDateForInput(record?.start_date),
      end_date: formatDateForInput(record?.end_date === '' || record?.end_date === null ? undefined : record?.end_date),
      premium_amount: record?.premium_amount ?? undefined,
      premium_frequency: record?.premium_frequency ?? undefined,
      deductible: record?.deductible ?? undefined,
      coverage_limits: record?.coverage_limits ?? undefined,
      notes: record?.notes ?? undefined,
    },
  })

  const handlePDFDataExtracted = (extractedData: Partial<InsurancePolicyCreate>) => {
    // Track which fields were auto-filled
    const filledFields = new Set<string>()
    Object.keys(extractedData).forEach(key => {
      if (extractedData[key as keyof typeof extractedData]) {
        filledFields.add(key)
      }
    })
    setAutoFilledFields(filledFields)

    // Update form data using setValue for each extracted field
    if (extractedData.provider) setValue('provider', extractedData.provider)
    if (extractedData.policy_number) setValue('policy_number', extractedData.policy_number)
    if (extractedData.policy_type) setValue('policy_type', extractedData.policy_type)
    if (extractedData.start_date) setValue('start_date', extractedData.start_date)
    if (extractedData.end_date) setValue('end_date', extractedData.end_date)
    if (extractedData.premium_amount) setValue('premium_amount', extractedData.premium_amount)
    if (extractedData.premium_frequency) setValue('premium_frequency', extractedData.premium_frequency)
    if (extractedData.deductible) setValue('deductible', extractedData.deductible)
    if (extractedData.coverage_limits) setValue('coverage_limits', extractedData.coverage_limits)
    if (extractedData.notes) setValue('notes', extractedData.notes)
  }

  const onSubmit = async (data: InsuranceFormData) => {
    try {
      const payload: InsurancePolicyCreate | InsurancePolicyUpdate = {
        provider: data.provider,
        policy_number: data.policy_number,
        policy_type: data.policy_type,
        start_date: data.start_date,
        end_date: data.end_date,
        premium_amount: data.premium_amount,
        premium_frequency: data.premium_frequency,
        deductible: data.deductible,
        coverage_limits: data.coverage_limits,
        notes: data.notes,
      }

      const url = isEdit
        ? `/vehicles/${vin}/insurance/${record.id}`
        : `/vehicles/${vin}/insurance`

      if (isEdit) {
        await api.put(url, payload)
      } else {
        await api.post(url, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save insurance policy')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Insurance Policy' : 'Add Insurance Policy'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">

          {/* PDF Import Button - Only show on create */}
          {!isEdit && (
            <div className="mb-4">
              <button
                type="button"
                onClick={() => setShowPDFUpload(true)}
                className="btn btn-secondary w-full flex items-center justify-center gap-2"
              >
                <FileUp size={18} />
                Import from PDF
              </button>
              <p className="text-xs text-garage-text-muted mt-2 text-center">
                Upload your insurance policy PDF to auto-fill this form
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="provider" className="block text-sm font-medium text-garage-text mb-1">
                Provider <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                id="provider"
                {...register('provider')}
                disabled={isSubmitting}
                className={`input w-full ${autoFilledFields.has('provider') ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-300 dark:border-blue-700' : ''}`}
                placeholder="e.g., State Farm, GEICO"
              />
              <FormError error={errors.provider} />
            </div>

            <div>
              <label htmlFor="policy_number" className="block text-sm font-medium text-garage-text mb-1">
                Policy Number <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                id="policy_number"
                {...register('policy_number')}
                disabled={isSubmitting}
                className="input w-full"
                placeholder="e.g., INS-12345"
              />
              <FormError error={errors.policy_number} />
            </div>
          </div>

          <div>
            <label htmlFor="policy_type" className="block text-sm font-medium text-garage-text mb-1">
              Policy Type <span className="text-danger">*</span>
            </label>
            <select
              id="policy_type"
              {...register('policy_type')}
              disabled={isSubmitting}
              className="input w-full"
            >
              <option value="">Select type...</option>
              {POLICY_TYPES.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
            <FormError error={errors.policy_type} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="start_date" className="block text-sm font-medium text-garage-text mb-1">
                Start Date <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="start_date"
                {...register('start_date')}
                disabled={isSubmitting}
                className="input w-full"
              />
              <FormError error={errors.start_date} />
            </div>

            <div>
              <label htmlFor="end_date" className="block text-sm font-medium text-garage-text mb-1">
                End Date <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="end_date"
                {...register('end_date')}
                disabled={isSubmitting}
                className="input w-full"
              />
              <FormError error={errors.end_date} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="premium_amount" className="block text-sm font-medium text-garage-text mb-1">
                Premium Amount
              </label>
              <input
                type="number"
                id="premium_amount"
                {...register('premium_amount', { valueAsNumber: true })}
                disabled={isSubmitting}
                className="input w-full"
                placeholder="e.g., 150.00"
                step="0.01"
              />
              <FormError error={errors.premium_amount} />
            </div>

            <div>
              <label htmlFor="premium_frequency" className="block text-sm font-medium text-garage-text mb-1">
                Premium Frequency
              </label>
              <select
                id="premium_frequency"
                {...register('premium_frequency')}
                disabled={isSubmitting}
                className="input w-full"
              >
                <option value="">Select frequency...</option>
                {PREMIUM_FREQUENCIES.map((freq) => (
                  <option key={freq} value={freq}>{freq}</option>
                ))}
              </select>
              <FormError error={errors.premium_frequency} />
            </div>
          </div>

          <div>
            <label htmlFor="deductible" className="block text-sm font-medium text-garage-text mb-1">
              Deductible
            </label>
            <input
              type="number"
              id="deductible"
              {...register('deductible', { valueAsNumber: true })}
              disabled={isSubmitting}
              className="input w-full"
              placeholder="e.g., 500.00"
              step="0.01"
            />
            <FormError error={errors.deductible} />
          </div>

          <div>
            <label htmlFor="coverage_limits" className="block text-sm font-medium text-garage-text mb-1">
              Coverage Limits
            </label>
            <textarea
              id="coverage_limits"
              {...register('coverage_limits')}
              disabled={isSubmitting}
              className="input w-full"
              rows={3}
              placeholder="e.g., 100/300/100 Bodily Injury/Property Damage"
            />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              {...register('notes')}
              disabled={isSubmitting}
              className="input w-full"
              rows={2}
              placeholder="Additional notes..."
            />
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isSubmitting}
            >
              <Save size={16} />
              {isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      </div>

      {/* PDF Upload Modal */}
      {showPDFUpload && (
        <InsurancePDFUpload
          vin={vin}
          onDataExtracted={handlePDFDataExtracted}
          onClose={() => setShowPDFUpload(false)}
        />
      )}
    </div>
  )
}
