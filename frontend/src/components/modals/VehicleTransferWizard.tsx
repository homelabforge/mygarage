/**
 * Vehicle Transfer Wizard - 3-step vehicle ownership transfer
 * Step 1: Select Recipient
 * Step 2: Select Data (audit purposes)
 * Step 3: Confirm Transfer
 */

import { useState, useEffect } from 'react'
import { X, ChevronLeft, ChevronRight, Check, AlertTriangle, User, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { familyService } from '@/services/familyService'
import type { EligibleRecipient, VehicleTransferResponse } from '@/types/family'
import { formatRelationship } from '@/types/family'

interface VehicleTransferWizardProps {
  isOpen: boolean
  onClose: () => void
  vin: string
  vehicleNickname: string
  onTransferComplete: (transfer: VehicleTransferResponse) => void
}

const DATA_CATEGORIES = [
  { key: 'service_records', label: 'Service Records', description: 'Maintenance and repair history' },
  { key: 'fuel_logs', label: 'Fuel Logs', description: 'Fuel fill-up records' },
  { key: 'documents', label: 'Documents', description: 'Uploaded documents and files' },
  { key: 'reminders', label: 'Reminders', description: 'Scheduled maintenance reminders' },
  { key: 'notes', label: 'Notes', description: 'Vehicle notes and annotations' },
  { key: 'expenses', label: 'Expenses', description: 'Cost tracking records' },
  { key: 'photos', label: 'Photos', description: 'Vehicle photo gallery' },
] as const

export default function VehicleTransferWizard({
  isOpen,
  onClose,
  vin,
  vehicleNickname,
  onTransferComplete,
}: VehicleTransferWizardProps) {
  const [currentStep, setCurrentStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingRecipients, setLoadingRecipients] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Recipients list
  const [recipients, setRecipients] = useState<EligibleRecipient[]>([])
  const [selectedRecipient, setSelectedRecipient] = useState<EligibleRecipient | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Data selection (all true by default for audit)
  const [dataIncluded, setDataIncluded] = useState<Record<string, boolean>>({
    service_records: true,
    fuel_logs: true,
    documents: true,
    reminders: true,
    notes: true,
    expenses: true,
    photos: true,
  })

  // Transfer notes
  const [transferNotes, setTransferNotes] = useState('')
  const [confirmText, setConfirmText] = useState('')

  // Load eligible recipients
  useEffect(() => {
    if (!isOpen) return

    const loadRecipients = async () => {
      setLoadingRecipients(true)
      try {
        const data = await familyService.getEligibleRecipients(vin)
        setRecipients(data)
      } catch (err) {
        console.error('Failed to load eligible recipients:', err)
        toast.error('Failed to load eligible recipients')
      } finally {
        setLoadingRecipients(false)
      }
    }

    loadRecipients()
  }, [isOpen, vin])

  // Reset state when modal opens/closes
  useEffect(() => {
    if (!isOpen) {
      setCurrentStep(1)
      setSelectedRecipient(null)
      setSearchQuery('')
      setTransferNotes('')
      setConfirmText('')
      setDataIncluded({
        service_records: true,
        fuel_logs: true,
        documents: true,
        reminders: true,
        notes: true,
        expenses: true,
        photos: true,
      })
      setError(null)
    }
  }, [isOpen])

  const steps = [
    { number: 1, title: 'Recipient', description: 'Select new owner' },
    { number: 2, title: 'Data', description: 'Select included data' },
    { number: 3, title: 'Confirm', description: 'Review & confirm' },
  ]

  // Filter recipients by search
  const filteredRecipients = recipients.filter(
    (r) =>
      r.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.full_name?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  // Check if all data is selected
  const allDataSelected = Object.values(dataIncluded).every(Boolean)

  // Toggle all data
  const toggleAllData = () => {
    const newValue = !allDataSelected
    const updated: Record<string, boolean> = {}
    DATA_CATEGORIES.forEach((cat) => {
      updated[cat.key] = newValue
    })
    setDataIncluded(updated)
  }

  // Check if can proceed to next step
  const canProceed = () => {
    if (currentStep === 1) return selectedRecipient !== null
    if (currentStep === 2) return true // Data selection is optional for audit
    if (currentStep === 3) return confirmText.toUpperCase() === 'TRANSFER'
    return false
  }

  // Handle next step
  const handleNext = () => {
    if (canProceed() && currentStep < 3) {
      setCurrentStep(currentStep + 1)
      setError(null)
    }
  }

  // Handle previous step
  const handlePrevious = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1)
      setError(null)
    }
  }

  // Handle transfer submission
  const handleTransfer = async () => {
    if (!selectedRecipient) return

    setLoading(true)
    setError(null)

    try {
      const result = await familyService.transferVehicle(vin, {
        to_user_id: selectedRecipient.id,
        transfer_notes: transferNotes || null,
        data_included: dataIncluded,
      })

      toast.success(`Vehicle transferred to ${selectedRecipient.full_name || selectedRecipient.username}`)
      onTransferComplete(result)
      onClose()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        setError(detail)
        toast.error(detail)
      } else {
        setError('Failed to transfer vehicle')
        toast.error('Failed to transfer vehicle')
      }
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-garage-text">Transfer Vehicle</h2>
            <p className="text-sm text-garage-text-muted mt-1">{vehicleNickname}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="px-6 py-4 border-b border-garage-border">
          <div className="flex items-center justify-between">
            {steps.map((step, index) => (
              <div key={step.number} className="flex items-center">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                      currentStep > step.number
                        ? 'bg-success text-white'
                        : currentStep === step.number
                          ? 'bg-primary text-white'
                          : 'bg-garage-border text-garage-text-muted'
                    }`}
                  >
                    {currentStep > step.number ? <Check className="w-4 h-4" /> : step.number}
                  </div>
                  <div className="mt-1 text-center">
                    <p className="text-xs font-medium text-garage-text">{step.title}</p>
                    <p className="text-xs text-garage-text-muted">{step.description}</p>
                  </div>
                </div>
                {index < steps.length - 1 && (
                  <div
                    className={`flex-1 h-0.5 mx-4 mt-[-20px] ${
                      currentStep > step.number ? 'bg-success' : 'bg-garage-border'
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Step 1: Select Recipient */}
          {currentStep === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  Select New Owner
                </label>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by username or name..."
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              {loadingRecipients ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 text-primary animate-spin" />
                </div>
              ) : filteredRecipients.length === 0 ? (
                <div className="text-center py-8 text-garage-text-muted">
                  {searchQuery ? 'No users found matching your search.' : 'No eligible recipients.'}
                </div>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {filteredRecipients.map((recipient) => (
                    <button
                      key={recipient.id}
                      onClick={() => setSelectedRecipient(recipient)}
                      className={`w-full p-3 rounded-lg border transition-colors flex items-center gap-3 ${
                        selectedRecipient?.id === recipient.id
                          ? 'border-primary bg-primary/10'
                          : 'border-garage-border hover:bg-garage-bg'
                      }`}
                    >
                      <div className="w-10 h-10 rounded-full bg-garage-border flex items-center justify-center">
                        <User className="w-5 h-5 text-garage-text-muted" />
                      </div>
                      <div className="flex-1 text-left">
                        <p className="font-medium text-garage-text">
                          {recipient.full_name || recipient.username}
                        </p>
                        <p className="text-sm text-garage-text-muted">@{recipient.username}</p>
                      </div>
                      {recipient.relationship && (
                        <span className="px-2 py-1 text-xs bg-info/20 text-info rounded">
                          {formatRelationship(recipient.relationship, null)}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Step 2: Select Data */}
          {currentStep === 2 && (
            <div className="space-y-4">
              <div className="p-3 bg-info/10 border border-info/30 rounded-lg">
                <p className="text-sm text-garage-text">
                  <strong>Note:</strong> All vehicle data stays with the vehicle regardless of these
                  selections. This is for audit purposes to document what data exists at transfer time.
                </p>
              </div>

              <div className="flex items-center justify-between py-2 border-b border-garage-border">
                <span className="font-medium text-garage-text">Include All Data</span>
                <button
                  onClick={toggleAllData}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    allDataSelected ? 'bg-primary' : 'bg-garage-border'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      allDataSelected ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div className="space-y-2">
                {DATA_CATEGORIES.map((category) => (
                  <label
                    key={category.key}
                    className="flex items-center gap-3 p-3 rounded-lg border border-garage-border hover:bg-garage-bg cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={dataIncluded[category.key]}
                      onChange={(e) =>
                        setDataIncluded({ ...dataIncluded, [category.key]: e.target.checked })
                      }
                      className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                    />
                    <div className="flex-1">
                      <p className="font-medium text-garage-text">{category.label}</p>
                      <p className="text-sm text-garage-text-muted">{category.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Step 3: Confirm */}
          {currentStep === 3 && (
            <div className="space-y-4">
              <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg flex gap-3">
                <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-garage-text">Confirm Vehicle Transfer</p>
                  <p className="text-sm text-garage-text-muted mt-1">
                    This action will transfer ownership of <strong>{vehicleNickname}</strong> to{' '}
                    <strong>{selectedRecipient?.full_name || selectedRecipient?.username}</strong>.
                    This action cannot be undone.
                  </p>
                </div>
              </div>

              {/* Summary */}
              <div className="space-y-3">
                <div className="flex justify-between py-2 border-b border-garage-border">
                  <span className="text-garage-text-muted">Vehicle</span>
                  <span className="font-medium text-garage-text">{vehicleNickname}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-garage-border">
                  <span className="text-garage-text-muted">VIN</span>
                  <span className="font-mono text-garage-text">{vin}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-garage-border">
                  <span className="text-garage-text-muted">New Owner</span>
                  <span className="font-medium text-garage-text">
                    {selectedRecipient?.full_name || selectedRecipient?.username}
                  </span>
                </div>
                <div className="flex justify-between py-2 border-b border-garage-border">
                  <span className="text-garage-text-muted">Data Included</span>
                  <span className="text-garage-text">
                    {Object.values(dataIncluded).filter(Boolean).length} of {DATA_CATEGORIES.length}{' '}
                    categories
                  </span>
                </div>
              </div>

              {/* Transfer Notes */}
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1.5">
                  Transfer Notes (Optional)
                </label>
                <textarea
                  value={transferNotes}
                  onChange={(e) => setTransferNotes(e.target.value)}
                  placeholder="Add notes about this transfer..."
                  rows={3}
                  maxLength={1000}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary resize-none"
                />
              </div>

              {/* Confirmation Input */}
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1.5">
                  Type <span className="font-mono bg-garage-bg px-1 rounded">TRANSFER</span> to confirm
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder="TRANSFER"
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                />
              </div>

              {error && (
                <div className="p-3 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border flex items-center justify-between">
          <button
            onClick={currentStep === 1 ? onClose : handlePrevious}
            className="flex items-center gap-2 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            {currentStep === 1 ? 'Cancel' : 'Back'}
          </button>

          {currentStep < 3 ? (
            <button
              onClick={handleNext}
              disabled={!canProceed()}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Next
              <ChevronRight className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleTransfer}
              disabled={!canProceed() || loading}
              className="flex items-center gap-2 px-4 py-2 bg-warning text-black rounded-lg hover:bg-warning/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Transferring...
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Transfer Vehicle
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
