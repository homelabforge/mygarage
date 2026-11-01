import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { AlertTriangle, Copy, Eye, EyeOff, Plus, Radio, RefreshCw } from 'lucide-react'

import NoMovementSignalNotice from '@/components/livelink/NoMovementSignalNotice'
import { Button, Drawer, Field, Input, Select } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type { IntegrationTab, LiveLinkDevice, TorqueSourceCreateResponse } from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import DeviceTable from './DeviceTable'

/**
 * Torque's settings: its sources (one per phone and vehicle), and a way to add
 * one. A Torque source is not hardware: it is an upload URL with a token in it,
 * pasted into the Torque Pro app.
 *
 * The admin counterpart of TorqueSourceModal, which stays on VehicleDetail
 * because any vehicle OWNER can reach it without admin rights; this drawer is
 * admin-only, so the two are not substitutes. TorqueSourceModal needs a vin
 * because it serves one vehicle. Here each source row carries its own vehicle
 * (DeviceTable's vehicle column), and creating one asks which vehicle it is for.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  onChanged: () => void
}

export default function TorqueSettingsDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('forms')
  const idBase = useId()
  const [devices, setDevices] = useState<LiveLinkDevice[] | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [loadFailed, setLoadFailed] = useState(false)

  const [vin, setVin] = useState('')
  const [label, setLabel] = useState('')
  const [creating, setCreating] = useState(false)
  const [revealed, setRevealed] = useState<TorqueSourceCreateResponse | null>(null)
  const [showToken, setShowToken] = useState(false)

  const reloadDevices = useCallback(async (): Promise<void> => {
    const loaded = await livelinkService.getDevices()
    setDevices(loaded.devices.filter((d) => d.kind === 'torque'))
  }, [])

  const load = useCallback(async (): Promise<void> => {
    setLoadFailed(false)
    try {
      const [loaded, loadedVehicles] = await Promise.all([livelinkService.getDevices(), vehicleService.list()])
      setDevices(loaded.devices.filter((d) => d.kind === 'torque'))
      setVehicles(loadedVehicles.vehicles)
    } catch {
      setLoadFailed(true)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    // The token is shown once. Reopening must not show the last one again.
    setRevealed(null)
    setShowToken(false)
    setVin('')
    setLabel('')
    void load()
  }, [open, load])

  const copyToClipboard = async (text: string, fieldLabel: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('modal.livelink.copiedToClipboard', { label: fieldLabel }))
    } catch {
      toast.error(t('modal.failedToCopy'))
    }
  }

  const create = async (): Promise<void> => {
    if (!vin) return
    setCreating(true)
    try {
      const created = await livelinkService.createTorqueSource(vin, label.trim() || undefined)
      setRevealed(created)
      setShowToken(false)
      setLabel('')
      toast.success(t('modal.torque.sourceCreated'))
      await reloadDevices()
      onChanged()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('settings:integrations.addSourceAction')))
    } finally {
      setCreating(false)
    }
  }

  const deviceChanged = (): void => {
    void reloadDevices()
    onChanged()
  }

  const vehicleId = `${idBase}-vehicle`
  const labelId = `${idBase}-label`

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('settings:integrations.sourceSettings', { source: tab?.label ?? '' })}
      icon={Radio}
      width="xl"
      closeLabel={t('common:close')}
    >
      <p className="text-sm text-garage-text-muted -mt-1 mb-4">{t('settings:integrations.torqueDrawerDescription')}</p>
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('settings:integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !devices ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="flex items-start gap-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3">
            <AlertTriangle aria-hidden="true" className="w-5 h-5 flex-shrink-0 text-yellow-500 mt-0.5" />
            <p className="text-sm text-yellow-500 font-medium">{t('modal.torque.metricWarning')}</p>
          </div>

          {revealed ? (
            <div className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.torque.urlLabel')}</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    aria-label={t('modal.torque.urlLabel')}
                    value={revealed.upload_url}
                    className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                  />
                  <button
                    onClick={() => void copyToClipboard(revealed.upload_url, t('modal.torque.urlLabel'))}
                    className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.torque.tokenLabel')}</label>
                <div className="flex gap-2">
                  <input
                    type={showToken ? 'text' : 'password'}
                    readOnly
                    aria-label={t('modal.torque.tokenLabel')}
                    value={revealed.token}
                    className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                  />
                  <button
                    onClick={() => setShowToken(!showToken)}
                    className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                  >
                    {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => void copyToClipboard(revealed.token, t('modal.torque.tokenLabel'))}
                    className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div className="p-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                <p className="text-xs text-yellow-500">
                  <strong>{t('modal.torque.saveTokenNow')}</strong>
                </p>
              </div>
              <Button size="sm" variant="secondary" onClick={() => setRevealed(null)}>
                {t('modal.torque.done')}
              </Button>
            </div>
          ) : null}

          <section>
            <NoMovementSignalNotice devices={devices} />
            {devices.length > 0 ? (
              <DeviceTable devices={devices} vehicles={vehicles} onChanged={deviceChanged} />
            ) : (
              <div className="text-center py-6 text-garage-text-muted border border-dashed border-garage-border rounded-lg">
                <Radio aria-hidden="true" className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p>{t('modal.torque.noSources')}</p>
              </div>
            )}
          </section>

          <section className="border-t border-border pt-4">
            <h3 className="text-sm font-semibold text-text mb-3">{t('modal.torque.add')}</h3>
            <div className="grid gap-x-4 sm:grid-cols-2">
              <Field id={vehicleId} label={t('settings:integrations.sourceVehicle')}>
                <Select
                  id={vehicleId}
                  value={vin}
                  onChange={(e) => setVin(e.target.value)}
                  placeholder={t('settings:integrations.chooseVehicle')}
                  placeholderDisabled
                  options={vehicles.map((v) => ({
                    value: v.vin,
                    label: v.nickname || `${v.year} ${v.make} ${v.model}`,
                  }))}
                />
              </Field>
              <Field id={labelId} label={t('modal.torque.addLabel')}>
                <Input
                  id={labelId}
                  value={label}
                  maxLength={100}
                  placeholder={t('modal.torque.addLabelPlaceholder')}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </Field>
            </div>
            <Button size="sm" icon={Plus} loading={creating} disabled={!vin || creating} onClick={() => void create()}>
              {t('modal.torque.create')}
            </Button>
          </section>
        </div>
      )}
    </Drawer>
  )
}
