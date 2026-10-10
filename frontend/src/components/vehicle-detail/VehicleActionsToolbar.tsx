import { useTranslation } from 'react-i18next'
import {
  Wrench, Fuel, Bell, List, Plus, Edit, Upload, Download, BarChart3, Share2,
  ArrowRightLeft, Trash2, MoreVertical,
} from 'lucide-react'
import { Button } from '../ui'
import { useAuth } from '../../contexts/AuthContext'

interface VehicleActionsToolbarProps {
  isAdmin: boolean
  importing: boolean
  exporting: boolean
  isOnline: boolean
  showFuelAction: boolean
  hasStandardEquipment: boolean
  hasOptionalEquipment: boolean
  onLogService: () => void
  onAddFuel: () => void
  onReminder: () => void
  onEditEquipment: (which: 'standard' | 'optional') => void
  onEdit: () => void
  onAnalytics: () => void
  onImport: () => void
  onExport: () => void
  onOpenModal: (modal: 'remove' | 'transfer' | 'sharing') => void
  onOpenMobileMenu: () => void
}

/**
 * Vehicle Detail actions (P5 Task 4). Two rows per the prototype: primary
 * actions (Log Service / Add Fuel / Reminder switch tabs — SDQ-1; an Equipment
 * pill expands the Overview lists — SDQ-2, each button rendered only when its
 * target list exists; Edit) and a secondary toolbar (Import / Export /
 * Analytics / Share / Transfer / Remove). Every control keeps its title attr
 * and Transfer/Remove stay real, clickable, literal text (G6). No `vin` prop —
 * Edit/Analytics navigate via the page's callbacks.
 */
export default function VehicleActionsToolbar({
  isAdmin, importing, exporting, isOnline, showFuelAction,
  hasStandardEquipment, hasOptionalEquipment,
  onLogService, onAddFuel, onReminder, onEditEquipment, onEdit, onAnalytics,
  onImport, onExport, onOpenModal, onOpenMobileMenu,
}: VehicleActionsToolbarProps) {
  const { t } = useTranslation('vehicles')
  // Sharing needs a signed-in user, so it's gone with sign-in off (A-12).
  const { authMode } = useAuth()
  const canShare = authMode !== 'none'
  return (
    <>
      {/* Mobile overflow trigger (phones) */}
      <button
        onClick={onOpenMobileMenu}
        className="md:hidden mt-4 inline-flex items-center gap-2 rounded-control border border-border bg-surface px-4 py-2.5 text-sm font-semibold text-text-dim cursor-pointer"
        title={t('detail.misc.moreActions')}
      >
        <MoreVertical className="h-5 w-5" />
        <span>{t('detail.actions')}</span>
      </button>

      {/* Primary actions row (desktop) */}
      <div className="mt-4 hidden md:flex flex-wrap items-center gap-2.5">
        <Button variant="primary" icon={Wrench} onClick={onLogService}>{t('detail.hero.logService')}</Button>
        {showFuelAction && (
          <Button variant="primary" icon={Fuel} onClick={onAddFuel}>{t('detail.hero.addFuel')}</Button>
        )}
        <Button variant="primary" icon={Bell} onClick={onReminder}>{t('detail.hero.reminder')}</Button>

        {/* Equipment pill group (SDQ-2, B7) — the whole group is hidden when
            neither decoded list exists; each button is hidden when its own
            <details> target is absent (no live no-op controls). */}
        {(hasStandardEquipment || hasOptionalEquipment) && (
          <div className="ml-auto flex items-center gap-2 rounded-control border border-border py-1 pl-3 pr-2">
            <span className="text-[11px] font-bold uppercase tracking-[.05em] text-text-mute">{t('detail.hero.equipment')}</span>
            {hasStandardEquipment && (
              <Button variant="secondary" size="sm" icon={List} onClick={() => onEditEquipment('standard')}>
                {t('detail.hero.standard')}
              </Button>
            )}
            {hasOptionalEquipment && (
              <Button variant="secondary" size="sm" icon={Plus} onClick={() => onEditEquipment('optional')}>
                {t('detail.hero.optional')}
              </Button>
            )}
          </div>
        )}

        <Button
          variant="secondary"
          icon={Edit}
          onClick={onEdit}
          title={t('detail.editVehicle')}
          className={hasStandardEquipment || hasOptionalEquipment ? '' : 'ml-auto'}
        >
          {t('common:edit')}
        </Button>
      </div>

      {/* Secondary toolbar (desktop) */}
      <div className="mt-3 hidden md:flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" icon={Upload} disabled={importing || !isOnline} onClick={onImport} title={t('detail.misc.importTooltip')}>
          {importing ? t('detail.importing') : t('detail.import')}
        </Button>
        <Button variant="secondary" size="sm" icon={Download} disabled={exporting || !isOnline} onClick={onExport} title={t('detail.exportTooltip')}>
          {exporting ? t('detail.exporting') : t('detail.export')}
        </Button>
        <Button variant="accentTint" size="sm" icon={BarChart3} onClick={onAnalytics} title={t('detail.analyticsTooltip')}>
          {t('detail.analytics')}
        </Button>
        {canShare && (
          <Button variant="secondary" size="sm" icon={Share2} onClick={() => onOpenModal('sharing')} title={t('detail.shareTooltip')}>
            {t('detail.share')}
          </Button>
        )}
        {isAdmin && (
          <button
            onClick={() => onOpenModal('transfer')}
            title={t('detail.misc.transferTooltip')}
            className="ml-auto inline-flex h-btn-sm items-center gap-1.5 rounded-control border border-warning/40 bg-warning/10 px-3 text-xs font-semibold text-warning hover:bg-warning/20 transition-colors cursor-pointer"
          >
            <ArrowRightLeft className="h-4 w-4" />
            <span>{t('detail.transfer')}</span>
          </button>
        )}
        <button
          onClick={() => onOpenModal('remove')}
          title={t('detail.removeVehicle')}
          className={`${isAdmin ? '' : 'ml-auto'} inline-flex h-btn-sm items-center gap-1.5 rounded-control border border-danger/40 bg-danger/10 px-3 text-xs font-semibold text-danger hover:bg-danger/20 transition-colors cursor-pointer`}
        >
          <Trash2 className="h-4 w-4" />
          <span>{t('detail.remove')}</span>
        </button>
      </div>
    </>
  )
}
