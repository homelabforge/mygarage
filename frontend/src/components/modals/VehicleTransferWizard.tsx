/**
 * Vehicle Transfer Wizard - 3-step vehicle ownership transfer
 * Step 1: Select Recipient
 * Step 2: Select Data (audit purposes)
 * Step 3: Confirm Transfer
 */

import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { ChevronLeft, ChevronRight, Check, AlertTriangle, User, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Stepper, Drawer, Button } from '@/components/ui'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { familyService } from '@/services/familyService'
import type { EligibleRecipient, VehicleTransferResponse } from '@/types/family'
import { formatRelationship } from '@/types/family'
import { vinForDisplay } from '@/utils/vehicleIdentifier'

interface VehicleTransferWizardProps {
  isOpen: boolean
  onClose: () => void
  vin: string
  vehicleNickname: string
  onTransferComplete: (transfer: VehicleTransferResponse) => void
}

/** Sentinel the user must type to unlock the transfer. Not user-facing copy — do not translate. */
const CONFIRM_KEYWORD = 'TRANSFER'

const DATA_CATEGORIES = [
  {
    key: 'service_records',
    labelKey: 'modal.transfer.dataServiceRecords',
    descKey: 'modal.transfer.dataServiceRecordsDesc',
  },
  { key: 'fuel_logs', labelKey: 'modal.transfer.dataFuelLogs', descKey: 'modal.transfer.dataFuelLogsDesc' },
  { key: 'documents', labelKey: 'modal.transfer.dataDocuments', descKey: 'modal.transfer.dataDocumentsDesc' },
  {
    key: 'maintenance',
    labelKey: 'modal.transfer.dataMaintenance',
    descKey: 'modal.transfer.dataMaintenanceDesc',
  },
  { key: 'notes', labelKey: 'modal.transfer.dataNotes', descKey: 'modal.transfer.dataNotesDesc' },
  { key: 'expenses', labelKey: 'modal.transfer.dataExpenses', descKey: 'modal.transfer.dataExpensesDesc' },
  { key: 'photos', labelKey: 'modal.transfer.dataPhotos', descKey: 'modal.transfer.dataPhotosDesc' },
] as const

export default function VehicleTransferWizard({
  isOpen,
  onClose,
  vin,
  vehicleNickname,
  onTransferComplete,
}: VehicleTransferWizardProps) {
  const { t } = useTranslation('forms')
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
    maintenance: true,
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
        toast.error(t('modal.failedToLoadRecipients'))
      } finally {
        setLoadingRecipients(false)
      }
    }

    loadRecipients()
  }, [isOpen, vin, t])

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
        maintenance: true,
        notes: true,
        expenses: true,
        photos: true,
      })
      setError(null)
    }
  }, [isOpen])

  // Step captions (Recipient/Data/Confirm). Stepper itself doesn't render a
  // description — the current step's shows up in the header caption below,
  // mirroring VehicleWizard's stepProgress pattern.
  const steps = [
    { number: 1, title: t('modal.transfer.stepRecipient'), description: t('modal.transfer.stepRecipientDesc') },
    { number: 2, title: t('modal.transfer.stepData'), description: t('modal.transfer.stepDataDesc') },
    { number: 3, title: t('modal.transfer.stepConfirm'), description: t('modal.transfer.stepConfirmDesc') },
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
    if (currentStep === 3) return confirmText.toUpperCase() === CONFIRM_KEYWORD
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

      toast.success(
        t('modal.transfer.transferSuccess', {
          name: selectedRecipient.full_name || selectedRecipient.username,
        })
      )
      onTransferComplete(result)
      onClose()
    } catch (err) {
      const message = getActionErrorMessage(err, t('modal.transferAction'))
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Drawer
      open={isOpen}
      onClose={onClose}
      title={t('modal.transferVehicle')}
      width="md"
      closeLabel={t('common:close')}
      footer={
        <div className="flex w-full items-center justify-between">
          <Button variant="ghost" icon={ChevronLeft} onClick={currentStep === 1 ? onClose : handlePrevious}>
            {currentStep === 1 ? t('common:cancel') : t('common:back')}
          </Button>
          {currentStep < 3 ? (
            <Button variant="primary" iconRight={ChevronRight} disabled={!canProceed()} onClick={handleNext}>
              {t('common:next')}
            </Button>
          ) : (
            // Bespoke warning-fill button (G4 (e)): Button has no warning/success
            // variant, and it swaps both icon (Check<->spinner) and label
            // (transferVehicle<->transferring) on loading.
            <button
              type="button"
              onClick={handleTransfer}
              disabled={!canProceed() || loading}
              className="ui-focus-ring ui-motion inline-flex h-btn-md items-center gap-2 rounded-control bg-warning px-4 text-sm font-semibold text-on-status hover:bg-warning/90 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              {loading ? (
                <>
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  {t('modal.transferring')}
                </>
              ) : (
                <>
                  <Check aria-hidden="true" className="h-4 w-4" />
                  {t('modal.transferVehicle')}
                </>
              )}
            </button>
          )}
        </div>
      }
    >
      {/* First body row: nickname + step-progress subtitle */}
      <p className="text-sm font-medium text-text">{vehicleNickname}</p>
      <p className="mt-1 text-sm text-text-mute">
        {t('modal.transfer.stepProgress', {
          current: currentStep,
          total: steps.length,
          description: steps[currentStep - 1].description,
        })}
      </p>

      {/* Step indicator */}
      <div className="mt-4">
        <Stepper
          steps={steps}
          current={currentStep}
          label={t('modal.transfer.progressLabel')}
          valueText={t('modal.transfer.stepOf', { current: currentStep, total: steps.length })}
        />
      </div>

      {/* Content */}
      <div className="mt-6">
          {/* Step 1: Select Recipient */}
          {currentStep === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-text mb-2">
                  {t('modal.selectNewOwner')}
                </label>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('modal.searchByUsernameOrName')}
                  className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-text focus:outline-none focus:ring-2 focus:ring-(--accent-solid)"
                />
              </div>

              {loadingRecipients ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 text-(--accent-fg) animate-spin" />
                </div>
              ) : filteredRecipients.length === 0 ? (
                <div className="text-center py-8 text-text-mute">
                  {searchQuery ? t('modal.noUsersFound') : t('modal.noEligibleRecipients')}
                </div>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {filteredRecipients.map((recipient) => (
                    <button
                      key={recipient.id}
                      onClick={() => setSelectedRecipient(recipient)}
                      className={`w-full p-3 rounded-lg border transition-colors flex items-center gap-3 ${
                        selectedRecipient?.id === recipient.id
                          ? 'border-(--accent-line) bg-(--accent-soft)'
                          : 'border-border hover:bg-surface-2'
                      }`}
                    >
                      <div className="w-10 h-10 rounded-full bg-border flex items-center justify-center">
                        <User className="w-5 h-5 text-text-mute" />
                      </div>
                      <div className="flex-1 text-left">
                        <p className="font-medium text-text">
                          {recipient.full_name || recipient.username}
                        </p>
                        <p className="text-sm text-text-mute">@{recipient.username}</p>
                      </div>
                      {recipient.relationship && (
                        <span className="px-2 py-1 text-xs bg-info/20 text-info rounded">
                          {formatRelationship(recipient.relationship, null, t)}
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
                <p className="text-sm text-text">
                  <strong>{t('modal.transfer.auditNoteLabel')}</strong>{' '}
                  {t('modal.transfer.auditNoteDesc')}
                </p>
              </div>

              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="font-medium text-text">{t('modal.includeAllData')}</span>
                <button
                  onClick={toggleAllData}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    allDataSelected ? 'bg-(--accent-solid)' : 'bg-danger'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-on-status transition-transform ${
                      allDataSelected ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div className="space-y-2">
                {DATA_CATEGORIES.map((category) => (
                  <label
                    key={category.key}
                    className="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-surface-2 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={dataIncluded[category.key]}
                      onChange={(e) =>
                        setDataIncluded({ ...dataIncluded, [category.key]: e.target.checked })
                      }
                      className="w-4 h-4 text-(--accent-fg) bg-surface-2 border-border rounded focus:ring-(--accent-solid) focus:ring-2"
                    />
                    <div className="flex-1">
                      <p className="font-medium text-text">{t(category.labelKey)}</p>
                      <p className="text-sm text-text-mute">{t(category.descKey)}</p>
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
                  <p className="font-medium text-text">{t('modal.confirmTransfer')}</p>
                  <p className="text-sm text-text-mute mt-1">
                    {t('modal.transfer.confirmOwnershipWarning', {
                      vehicle: vehicleNickname,
                      recipient: selectedRecipient?.full_name || selectedRecipient?.username || '',
                    })}
                  </p>
                </div>
              </div>

              {/* Summary */}
              <div className="space-y-3">
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-text-mute">{t('modal.vehicle')}</span>
                  <span className="font-medium text-text">{vehicleNickname}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-text-mute">{t('modal.transfer.vin')}</span>
                  <span className="font-mono text-text">{vinForDisplay(vin) ?? '-'}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-text-mute">{t('modal.newOwner')}</span>
                  <span className="font-medium text-text">
                    {selectedRecipient?.full_name || selectedRecipient?.username}
                  </span>
                </div>
                <div className="flex justify-between py-2 border-b border-border">
                  <span className="text-text-mute">{t('modal.dataIncluded')}</span>
                  <span className="text-text">
                    {t('modal.transfer.categoriesCount', {
                      selected: Object.values(dataIncluded).filter(Boolean).length,
                      total: DATA_CATEGORIES.length,
                    })}
                  </span>
                </div>
              </div>

              {/* Transfer Notes */}
              <div>
                <label className="block text-sm font-medium text-text mb-1.5">
                  {t('modal.transferNotes')}
                </label>
                <textarea
                  value={transferNotes}
                  onChange={(e) => setTransferNotes(e.target.value)}
                  placeholder={t('modal.transferNotesPlaceholder')}
                  rows={3}
                  maxLength={1000}
                  className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-text focus:outline-none focus:ring-2 focus:ring-(--accent-solid) resize-none"
                />
              </div>

              {/* Confirmation Input */}
              <div>
                <label className="block text-sm font-medium text-text mb-1.5">
                  {t('modal.transfer.typeToConfirm', { word: CONFIRM_KEYWORD })}
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={CONFIRM_KEYWORD}
                  className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-text focus:outline-none focus:ring-2 focus:ring-(--accent-solid) font-mono"
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
    </Drawer>
  )
}
