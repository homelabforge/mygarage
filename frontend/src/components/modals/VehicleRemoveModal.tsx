/**
 * VehicleRemoveModal Component
 *
 * Two-step modal for removing a vehicle:
 * 1. Mode Selection: Archive (recommended) or Delete Permanently
 * 2a. Archive Form: Reason, price, date, notes, visibility
 * 2b. Delete Confirmation: Type "DELETE" to confirm permanent deletion
 */

import { useTranslation } from 'react-i18next'
import { useEffect, useId, useRef, useState, type ReactElement } from 'react'
import { Archive, Trash2, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { Button, Dialog, NumberInput, Select } from '@/components/ui'
import { FOCUSABLE_SELECTOR, FORM_FIELD_SELECTOR, isRendered } from '@/components/ui/focusTrap'
import { moneyTextError } from '@/schemas/shared'
import { parseOptionalDecimal } from '@/utils/decimalInput'
import type { Vehicle } from '@/types/vehicle'
import { identifierLabel, identifierValue } from '../../utils/vehicleIdentifier'

interface VehicleRemoveModalProps {
  isOpen: boolean
  onClose: () => void
  vehicle: Vehicle | null
  onConfirm: () => void
}

type RemoveMode = 'select' | 'archive' | 'delete'
type ArchiveReason = 'Sold' | 'Totaled' | 'Gifted' | 'Trade-in' | 'Other'

/** Only a sale or a trade-in shows the price and date fields. */
const showsSaleFields = (reason: ArchiveReason): boolean => reason === 'Sold' || reason === 'Trade-in'

export default function VehicleRemoveModal({ isOpen, onClose, vehicle, onConfirm }: VehicleRemoveModalProps): ReactElement | null {
  const { t } = useTranslation('forms')
  const descriptionId = useId()
  const [mode, setMode] = useState<RemoveMode>('select')
  const [loading, setLoading] = useState(false)

  // Archive form state
  const [archiveReason, setArchiveReason] = useState<ArchiveReason>('Sold')
  const [salePrice, setSalePrice] = useState('')
  const [salePriceError, setSalePriceError] = useState<string | undefined>()
  const [saleDate, setSaleDate] = useState('')
  const [notes, setNotes] = useState('')
  const [visible, setVisible] = useState(true)

  // Delete confirmation state
  const [confirmText, setConfirmText] = useState('')

  // The option you click goes away with its step, so focus would drop to the
  // page. Put it where Dialog would on open: first field, else first control.
  const bodyRef = useRef<HTMLDivElement>(null)
  const shownMode = useRef(mode)
  useEffect(() => {
    if (shownMode.current === mode) return
    shownMode.current = mode
    const body = bodyRef.current
    if (!body) return
    const target = [
      ...body.querySelectorAll<HTMLElement>(FORM_FIELD_SELECTOR),
      ...body.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ].find(isRendered)
    target?.focus()
  }, [mode])

  const resetForm = () => {
    setMode('select')
    setArchiveReason('Sold')
    setSalePrice('')
    setSalePriceError(undefined)
    setSaleDate('')
    setNotes('')
    setVisible(true)
    setConfirmText('')
  }

  const handleArchive = async () => {
    if (!vehicle) return
    // The API's money bounds, checked on the field the user can see. A hidden
    // field is neither checked nor sent, whatever was typed before the switch.
    const showsSale = showsSaleFields(archiveReason)
    const priceProblem = showsSale ? moneyTextError(t, salePrice) : undefined
    setSalePriceError(priceProblem)
    if (priceProblem) return

    setLoading(true)
    try {
      await api.post(`/vehicles/${vehicle.vin}/archive`, {
        reason: archiveReason,
        sale_price: showsSale ? parseOptionalDecimal(salePrice) ?? null : null,
        sale_date: showsSale ? saleDate || null : null,
        notes: notes || null,
        visible,
      })

      toast.success(t('modal.remove.archivedSuccess', { name: vehicle.nickname }))
      onConfirm()
      onClose()
      resetForm()
    } catch (error: unknown) {
      toast.error(getActionErrorMessage(error, t('modal.archiveAction')))
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    if (confirmText !== 'DELETE' || !vehicle) return

    setLoading(true)
    try {
      await api.delete(`/vehicles/${vehicle.vin}`)
      toast.success(t('modal.remove.deletedSuccess', { name: vehicle.nickname }))
      onConfirm()
      onClose()
      resetForm()
    } catch (error: unknown) {
      toast.error(getActionErrorMessage(error, t('modal.deleteVehicleAction')))
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    if (!loading) {
      onClose()
      resetForm()
    }
  }

  if (!isOpen || !vehicle) return null

  // Show price/date fields only for Sold and Trade-in
  const showFinancialFields = showsSaleFields(archiveReason)

  // One dialog, three steps: each step names it and brings its own buttons.
  const step = {
    select: {
      title: t('modal.removeVehicle'),
      description: t('modal.chooseHowToRemove', { name: vehicle.nickname }),
      footer: (
        <Button variant="secondary" data-dialog-cancel onClick={handleClose}>
          {t('common:cancel')}
        </Button>
      ),
    },
    archive: {
      title: t('modal.archiveVehicle'),
      description: t('modal.archiveDetails'),
      footer: (
        <>
          <Button variant="secondary" onClick={() => setMode('select')} disabled={loading}>
            {t('common:back')}
          </Button>
          <Button variant="primary" icon={Archive} onClick={handleArchive} disabled={loading}>
            {loading ? t('common:processing') : t('modal.archiveVehicle')}
          </Button>
        </>
      ),
    },
    delete: {
      title: t('modal.deletePermanently'),
      description: t('modal.cannotBeUndone'),
      footer: (
        <>
          <Button variant="secondary" onClick={() => setMode('select')} disabled={loading}>
            {t('common:back')}
          </Button>
          <Button variant="danger" icon={Trash2} onClick={handleDelete} disabled={confirmText !== 'DELETE' || loading}>
            {loading ? t('common:deleting') : t('modal.remove.deleteForever')}
          </Button>
        </>
      ),
    },
  }[mode]

  return (
    <Dialog
      open={isOpen}
      onClose={handleClose}
      title={step.title}
      describedBy={descriptionId}
      size="lg"
      footer={step.footer}
    >
      <div ref={bodyRef} className="space-y-4">
        <p id={descriptionId} className="text-sm text-garage-text-muted">{step.description}</p>

        {/* Mode Selection */}
        {mode === 'select' && (
          <>
            {/* Vehicle Info */}
            <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
              <p className="text-sm text-garage-text">
                <strong>{t('modal.remove.nickname')}:</strong> {vehicle.nickname}
              </p>
              <p className="text-sm text-garage-text">
                <strong>{t('modal.vehicle')}:</strong> {vehicle.year} {vehicle.make} {vehicle.model}
              </p>
              <p className="text-sm text-garage-text-muted font-mono text-xs mt-1">
                <strong>{identifierLabel(vehicle, t)}:</strong> {identifierValue(vehicle) ?? '-'}
              </p>
            </div>

            {/* Options */}
            <div className="space-y-3">
              {/* Archive Option (Recommended) */}
              <button
                onClick={() => setMode('archive')}
                className="w-full p-4 bg-success/10 border-2 border-success/30 rounded-lg hover:border-success hover:bg-success/20 transition-all text-left"
              >
                <div className="flex items-start gap-3">
                  <Archive className="w-6 h-6 text-success mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-garage-text">{t('modal.archiveRecommended')}</span>
                      <span className="px-2 py-0.5 text-xs bg-success/20 text-success rounded">{t('modal.safe')}</span>
                    </div>
                    <p className="text-sm text-garage-text-muted mt-1">
                      {t('modal.archiveDescription')}
                    </p>
                  </div>
                </div>
              </button>

              {/* Delete Option */}
              <button
                onClick={() => setMode('delete')}
                className="w-full p-4 bg-danger/10 border-2 border-danger/30 rounded-lg hover:border-danger hover:bg-danger/20 transition-all text-left"
              >
                <div className="flex items-start gap-3">
                  <Trash2 className="w-6 h-6 text-danger mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-garage-text">{t('modal.deletePermanently')}</span>
                      <span className="px-2 py-0.5 text-xs bg-danger/20 text-danger rounded">⚠️ {t('modal.remove.irreversible')}</span>
                    </div>
                    <p className="text-sm text-garage-text-muted mt-1">
                      {t('modal.deleteDescription')}
                    </p>
                  </div>
                </div>
              </button>
            </div>
          </>
        )}

        {/* Archive Form */}
        {mode === 'archive' && (
          <>
            {/* Reason Dropdown */}
            <div>
              <label className="block text-sm font-medium text-garage-text mb-2">
                {t('modal.reason')} <span className="text-danger">*</span>
              </label>
              <Select
                value={archiveReason}
                onChange={(e) => setArchiveReason(e.target.value as ArchiveReason)}
                options={[
                  { value: 'Sold', label: t('modal.remove.reasonSold') },
                  { value: 'Totaled', label: t('modal.remove.reasonTotaled') },
                  { value: 'Gifted', label: t('modal.remove.reasonGifted') },
                  { value: 'Trade-in', label: t('modal.remove.reasonTradeIn') },
                  { value: 'Other', label: t('modal.remove.reasonOther') },
                ]}
              />
            </div>

            {/* Sale Price (conditional) */}
            {showFinancialFields && (
              <div>
                <label htmlFor="archive-sale-price" className="block text-sm font-medium text-garage-text mb-2">
                  {archiveReason === 'Sold' ? t('modal.salePrice') : t('modal.tradeInValue')} ({t('common:optional')})
                </label>
                <NumberInput
                  id="archive-sale-price"
                  value={salePrice}
                  onChange={(e) => {
                    setSalePrice(e.target.value)
                    setSalePriceError(undefined)
                  }}
                  placeholder="25000"
                  invalid={!!salePriceError}
                  aria-describedby={salePriceError ? 'archive-sale-price-error' : undefined}
                />
                {salePriceError && (
                  <p id="archive-sale-price-error" role="alert" className="mt-1 text-xs text-danger">
                    {salePriceError}
                  </p>
                )}
              </div>
            )}

            {/* Sale Date (conditional) */}
            {showFinancialFields && (
              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  {archiveReason === 'Sold' ? t('modal.saleDate') : t('modal.tradeInDate')} ({t('common:optional')})
                </label>
                <input
                  type="date"
                  value={saleDate}
                  onChange={(e) => setSaleDate(e.target.value)}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
            )}

            {/* Notes */}
            <div>
              <label className="block text-sm font-medium text-garage-text mb-2">
                {t('common:notes')} ({t('common:optional')})
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t('modal.archiveNotesPlaceholder')}
                rows={3}
                maxLength={1000}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              />
              <p className="text-xs text-garage-text-muted mt-1">
                {notes.length}/1000 {t('common:characters')}
              </p>
            </div>

            {/* Visibility Toggle */}
            <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={visible}
                  onChange={(e) => setVisible(e.target.checked)}
                  className="w-4 h-4 accent-(--accent-solid) bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                />
                <div className="flex items-center gap-2">
                  {visible ? (
                    <Eye className="w-4 h-4 text-(--accent-fg)" />
                  ) : (
                    <EyeOff className="w-4 h-4 text-garage-text-muted" />
                  )}
                  <span className="text-sm font-medium text-garage-text">
                    {t('modal.showInMainList')}
                  </span>
                </div>
              </label>
              <p className="text-xs text-garage-text-muted mt-2 ml-7">
                {visible
                  ? t('modal.remove.visibleHint')
                  : t('modal.remove.hiddenHint')
                }
              </p>
            </div>
          </>
        )}

        {/* Delete Confirmation */}
        {mode === 'delete' && (
          <>
            {/* Impact Warning */}
            <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg">
              <p className="text-sm text-danger font-semibold mb-2">⚠️ {t('modal.dataImpact')}:</p>
              <ul className="text-sm text-garage-text space-y-1">
                <li>• {t('modal.remove.impactVehicle')}</li>
                <li>• {t('modal.remove.impactFuel')}</li>
                <li>• {t('modal.remove.impactService')}</li>
                <li>• {t('modal.remove.impactOdometer')}</li>
                <li>• {t('modal.remove.impactPhotos')}</li>
                <li>• {t('modal.remove.impactAnalytics')}</li>
                <li>• {t('modal.deleteImpact.irreversible')}</li>
              </ul>
            </div>

            {/* Recommendation */}
            <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
              <p className="text-sm text-garage-text">
                <strong>💡 {t('modal.remove.recommendationLabel')}:</strong> {t('modal.remove.recommendationDesc')}
              </p>
            </div>

            {/* Confirmation Input */}
            <div>
              <label className="block text-sm font-medium text-garage-text mb-2">
                {t('modal.remove.confirmPrefix')} <code className="px-1.5 py-0.5 bg-garage-bg border border-danger rounded text-danger font-mono">DELETE</code> {t('modal.remove.confirmSuffix')}
              </label>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="DELETE"
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-danger"
                autoComplete="off"
              />
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
