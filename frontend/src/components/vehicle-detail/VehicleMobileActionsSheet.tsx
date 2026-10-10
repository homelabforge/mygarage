import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { X, Upload, Download, BarChart3, Share2, Edit, ArrowRightLeft, Trash2 } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'

interface VehicleMobileActionsSheetProps {
  vin: string
  isAdmin: boolean
  importing: boolean
  exporting: boolean
  isOnline: boolean
  onImportClick: () => void
  onExport: () => void
  onOpenModal: (modal: 'remove' | 'transfer' | 'sharing') => void
  onClose: () => void
  onEdit: () => void
}

/**
 * Vehicle Detail mobile actions sheet. Mechanically extracted from
 * VehicleDetail.tsx (P5 Task 1, verbatim — no restyle). Retokenize-only in
 * Task 8 (stays a bespoke bottom-sheet, not a right Drawer — D2).
 */
export default function VehicleMobileActionsSheet({
  vin, isAdmin, importing, exporting, isOnline,
  onImportClick, onExport, onOpenModal, onClose, onEdit,
}: VehicleMobileActionsSheetProps) {
  const { t } = useTranslation('vehicles')
  const navigate = useNavigate()
  // Same as the desktop toolbar: no Share with sign-in off (A-12).
  const { authMode } = useAuth()
  const canShare = authMode !== 'none'
  return (
    <div className="fixed inset-0 bg-black/50 flex items-end justify-center z-50 md:hidden" onClick={onClose}>
      <div className="bg-surface rounded-t-2xl w-full max-w-lg max-h-[70vh] overflow-y-auto pb-safe" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="text-lg font-semibold text-text">{t('detail.actions')}</h3>
          <button
            onClick={onClose}
            className="p-2 text-text-mute hover:text-text rounded-lg ui-motion cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-2">
          <button
            onClick={() => { onImportClick(); onClose() }}
            disabled={importing || !isOnline}
            className="w-full flex items-center space-x-3 px-4 py-3 text-left text-text hover:bg-surface-2 rounded-lg ui-motion cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Upload className="w-5 h-5" />
            <span>{importing ? t('detail.importing') : t('detail.importData')}</span>
          </button>
          <button
            onClick={() => { onExport(); onClose() }}
            disabled={exporting || !isOnline}
            className="w-full flex items-center space-x-3 px-4 py-3 text-left text-text hover:bg-surface-2 rounded-lg ui-motion cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Download className="w-5 h-5" />
            <span>{exporting ? t('detail.exporting') : t('detail.exportData')}</span>
          </button>
          <button
            onClick={() => { navigate(`/vehicles/${vin}/analytics`); onClose() }}
            className="w-full flex items-center space-x-3 px-4 py-3 text-left text-text hover:bg-surface-2 rounded-lg ui-motion cursor-pointer"
          >
            <BarChart3 className="w-5 h-5" />
            <span>{t('detail.viewAnalytics')}</span>
          </button>
          {canShare && (
            <button
              onClick={() => { onClose(); onOpenModal('sharing') }}
              className="w-full flex items-center space-x-3 px-4 py-3 text-left text-text hover:bg-surface-2 rounded-lg ui-motion cursor-pointer"
            >
              <Share2 className="w-5 h-5" />
              <span>{t('detail.shareVehicle')}</span>
            </button>
          )}
          <button
            onClick={() => { onClose(); onEdit() }}
            className="w-full flex items-center space-x-3 px-4 py-3 text-left text-text hover:bg-surface-2 rounded-lg ui-motion cursor-pointer"
          >
            <Edit className="w-5 h-5" />
            <span>{t('detail.editVehicle')}</span>
          </button>
          {isAdmin && (
            <button
              onClick={() => { onClose(); onOpenModal('transfer') }}
              className="w-full flex items-center space-x-3 px-4 py-3 text-left text-warning hover:bg-warning/10 rounded-lg ui-motion cursor-pointer"
            >
              <ArrowRightLeft className="w-5 h-5" />
              <span>{t('detail.transferVehicle')}</span>
            </button>
          )}
          <button
            onClick={() => { onClose(); onOpenModal('remove') }}
            className="w-full flex items-center space-x-3 px-4 py-3 text-left text-danger hover:bg-danger/10 rounded-lg ui-motion cursor-pointer"
          >
            <Trash2 className="w-5 h-5" />
            <span>{t('detail.removeVehicle')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
