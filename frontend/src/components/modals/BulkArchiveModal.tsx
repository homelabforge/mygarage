/**
 * Bulk archive modal — archive multiple vehicles with shared metadata.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Archive, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { Select } from '@/components/ui'

type ArchiveReason = 'Sold' | 'Totaled' | 'Gifted' | 'Trade-in' | 'Other'

interface BulkArchiveModalProps {
  isOpen: boolean
  vins: string[]
  onClose: () => void
  onConfirm: () => void
}

export default function BulkArchiveModal({ isOpen, vins, onClose, onConfirm }: BulkArchiveModalProps) {
  const { t } = useTranslation('forms')
  const [loading, setLoading] = useState(false)
  const [archiveReason, setArchiveReason] = useState<ArchiveReason>('Sold')
  const [salePrice, setSalePrice] = useState('')
  const [saleDate, setSaleDate] = useState('')
  const [notes, setNotes] = useState('')
  const [visible, setVisible] = useState(false)

  const resetForm = () => {
    setArchiveReason('Sold')
    setSalePrice('')
    setSaleDate('')
    setNotes('')
    setVisible(false)
  }

  const handleClose = () => {
    if (!loading) {
      onClose()
      resetForm()
    }
  }

  const handleArchive = async () => {
    if (vins.length === 0) return
    setLoading(true)
    try {
      const response = await api.post('/vehicles/archive/bulk', {
        vins,
        reason: archiveReason,
        sale_price: salePrice ? parseFloat(salePrice) : null,
        sale_date: saleDate || null,
        notes: notes || null,
        visible,
      })
      const count = response.data?.total ?? vins.length
      toast.success(t('modal.bulkArchiveSuccess', { count }))
      onConfirm()
      handleClose()
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : t('modal.failedToArchive'))
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen || vins.length === 0) return null

  const showFinancialFields = archiveReason === 'Sold' || archiveReason === 'Trade-in'

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-lg w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-primary/10 p-2">
              <Archive className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-garage-text">{t('modal.bulkArchiveTitle')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('modal.bulkArchiveDescription', { count: vins.length })}
              </p>
            </div>
          </div>

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

          {showFinancialFields && (
            <>
              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  {archiveReason === 'Sold' ? t('modal.salePrice') : t('modal.tradeInValue')} ({t('common:optional')})
                </label>
                <input
                  type="number"
                  value={salePrice}
                  onChange={(e) => setSalePrice(e.target.value)}
                  placeholder="25000"
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>
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
            </>
          )}

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
          </div>

          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={visible}
                onChange={(e) => setVisible(e.target.checked)}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <div className="flex items-center gap-2">
                {visible ? (
                  <Eye className="w-4 h-4 text-primary" />
                ) : (
                  <EyeOff className="w-4 h-4 text-garage-text-muted" />
                )}
                <span className="text-sm font-medium text-garage-text">
                  {t('modal.showInMainList')}
                </span>
              </div>
            </label>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={loading}
              className="rounded-lg border border-garage-border px-4 py-2 text-sm text-garage-text"
            >
              {t('common:cancel')}
            </button>
            <button
              type="button"
              onClick={handleArchive}
              disabled={loading}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-(--accent-on-solid) disabled:opacity-50"
            >
              {loading ? t('modal.archiving') : t('modal.bulkArchiveAction', { count: vins.length })}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
