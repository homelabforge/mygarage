import { useState } from 'react'
import { X, Save } from 'lucide-react'
import type { TSB, TSBCreate, TSBUpdate } from '../types/tsb'
import { toast } from 'sonner'
import api from '../services/api'

interface TSBFormProps {
  vin: string
  tsb?: TSB
  onClose: () => void
  onSuccess: () => void
}

export default function TSBForm({ vin, tsb, onClose, onSuccess }: TSBFormProps) {
  const isEdit = !!tsb
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [formData, setFormData] = useState({
    tsb_number: tsb?.tsb_number || '',
    component: tsb?.component || '',
    summary: tsb?.summary || '',
    status: tsb?.status || 'pending',
    source: tsb?.source || 'manual',
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target
    setFormData(prev => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      // Validation
      if (!formData.component.trim()) {
        throw new Error('Component is required')
      }
      if (!formData.summary.trim()) {
        throw new Error('Summary is required')
      }

      const url = isEdit ? `/tsbs/${tsb.id}` : `/tsbs`

      if (isEdit) {
        const payload: TSBUpdate = {
          tsb_number: formData.tsb_number.trim() || undefined,
          component: formData.component.trim(),
          summary: formData.summary.trim(),
          status: formData.status as TSB['status'],
        }
        await api.put(url, payload)
        toast.success('TSB updated successfully')
      } else {
        const payload: TSBCreate = {
          vin,
          tsb_number: formData.tsb_number.trim() || undefined,
          component: formData.component.trim(),
          summary: formData.summary.trim(),
          status: formData.status as TSB['status'],
          source: formData.source as 'manual' | 'nhtsa',
        }
        await api.post(url, payload)
        toast.success('TSB added successfully')
      }

      onSuccess()
      onClose()
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An error occurred'
      setError(errorMessage)
      toast.error(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit TSB' : 'Add TSB'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="tsb_number" className="block text-sm font-medium text-garage-text mb-1">
                TSB Number
              </label>
              <input
                type="text"
                id="tsb_number"
                name="tsb_number"
                value={formData.tsb_number}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text font-mono"
                placeholder="e.g., 21-034-19"
                disabled={isSubmitting}
              />
            </div>

            <div>
              <label htmlFor="status" className="block text-sm font-medium text-garage-text mb-1">
                Status
              </label>
              <select
                id="status"
                name="status"
                value={formData.status}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                disabled={isSubmitting}
              >
                <option value="pending">Pending</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="applied">Applied</option>
                <option value="not_applicable">Not Applicable</option>
                <option value="ignored">Ignored</option>
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="component" className="block text-sm font-medium text-garage-text mb-1">
              Component <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              id="component"
              name="component"
              value={formData.component}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              placeholder="e.g., Transmission, Engine, Brake System"
              disabled={isSubmitting}
              required
            />
          </div>

          <div>
            <label htmlFor="summary" className="block text-sm font-medium text-garage-text mb-1">
              Summary <span className="text-danger">*</span>
            </label>
            <textarea
              id="summary"
              name="summary"
              value={formData.summary}
              onChange={handleChange}
              rows={6}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              placeholder="Describe the issue and recommended fix..."
              disabled={isSubmitting}
              required
            />
          </div>

          {!isEdit && (
            <div>
              <label htmlFor="source" className="block text-sm font-medium text-garage-text mb-1">
                Source
              </label>
              <select
                id="source"
                name="source"
                value={formData.source}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                disabled={isSubmitting}
              >
                <option value="manual">Manual Entry</option>
                <option value="nhtsa">NHTSA</option>
              </select>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-4 border-t border-garage-border">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 border border-garage-border rounded-md hover:bg-garage-bg transition-colors text-garage-text"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 px-4 py-2 btn btn-primary rounded-md transition-colors disabled:opacity-50"
              disabled={isSubmitting}
            >
              <Save size={16} />
              {isSubmitting ? 'Saving...' : 'Save TSB'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
