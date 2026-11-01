import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Radio, RefreshCw, Trash2 } from 'lucide-react'

import { Button, Drawer, Field, Input, Select } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type { DeviceReadingsResponse, IntegrationTab, LiveLinkDevice } from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { STATUS_KEY } from '../integrationStatus'
import DeviceReadingsList from './DeviceReadingsList'
import TopicMapEditor from './TopicMapEditor'

/**
 * One MQTT device's settings: a preset device such as Mopeka, or one mapped by
 * hand. Replaces MqttSourcesCard, which showed every topic mapping as the
 * first thing; here the readings come first, each with its dashboard switch,
 * and the mappings sit under "Advanced".
 *
 * The vehicle picker is not decoration. generic_mqtt devices need a vehicle:
 * ingest drops everything an unlinked one publishes, so an unlinked device
 * says so in words, not just with an empty field.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  onChanged: () => void
}

const TAB_PREFIX = 'device:'

export default function MqttDeviceDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const idBase = useId()
  const deviceId = tab?.id.startsWith(TAB_PREFIX) ? tab.id.slice(TAB_PREFIX.length) : null

  const [device, setDevice] = useState<LiveLinkDevice | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [readings, setReadings] = useState<DeviceReadingsResponse | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [readingsFailed, setReadingsFailed] = useState(false)
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)

  // The tab as it is NOW. The prop is the object captured when Settings was
  // clicked, so after a link change it would go on stating the old status.
  // Reset from the prop when a different tab opens; refreshed after changes.
  const [liveTab, setLiveTab] = useState(tab)
  const [seenTab, setSeenTab] = useState(tab)
  if (tab !== seenTab) {
    setSeenTab(tab)
    setLiveTab(tab)
  }

  const refreshTab = useCallback(async (): Promise<void> => {
    if (!tab) return
    try {
      const { tabs } = await livelinkService.getIntegrations()
      const found = tabs.find((candidate) => candidate.id === tab.id)
      if (found) setLiveTab(found)
    } catch {
      // Keep the last known status; the card behind shows its own error.
    }
  }, [tab])

  const loadDevice = useCallback(async (): Promise<LiveLinkDevice | null> => {
    const list = await livelinkService.getDevices()
    const found = list.devices.find((d) => d.device_id === deviceId) ?? null
    setDevice(found)
    return found
  }, [deviceId])

  const loadReadings = useCallback(async (): Promise<void> => {
    if (!deviceId) return
    setReadingsFailed(false)
    try {
      setReadings(await livelinkService.getDeviceReadings(deviceId))
    } catch {
      setReadingsFailed(true)
    }
  }, [deviceId])

  const load = useCallback(async (): Promise<void> => {
    if (!deviceId) return
    setLoadFailed(false)
    try {
      const [found, loadedVehicles] = await Promise.all([loadDevice(), vehicleService.list()])
      setVehicles(loadedVehicles.vehicles)
      setLabel(found?.label ?? '')
    } catch {
      setLoadFailed(true)
      return
    }
    // Separate, so a readings failure leaves the header usable: linking the
    // device is often exactly what fixes it.
    await loadReadings()
  }, [deviceId, loadDevice, loadReadings])

  useEffect(() => {
    if (!open) return
    setDevice(null)
    setReadings(null)
    void load()
  }, [open, load])

  const update = async (change: { vin?: string; label?: string }): Promise<void> => {
    if (!deviceId) return
    setBusy(true)
    try {
      await livelinkService.updateDevice(deviceId, change)
      const found = await loadDevice()
      if (change.label !== undefined) setLabel(found?.label ?? '')
      await Promise.all([loadReadings(), refreshTab()])
      onChanged()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('integrations.saveSettingsAction')))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (): Promise<void> => {
    if (!deviceId || !confirm(t('forms:modal.livelink.confirmDeleteDevice'))) return
    setBusy(true)
    try {
      await livelinkService.deleteDevice(deviceId)
      onChanged()
      onClose()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('integrations.deleteSourceAction')))
    } finally {
      setBusy(false)
    }
  }

  // A handmade device's tab is named from its label, so a rename renames the
  // open drawer too. A preset device's tab keeps the preset's name.
  const title = device && !device.preset_key ? device.label || device.device_id : (liveTab?.label ?? '')
  const labelId = `${idBase}-label`
  const vehicleId = `${idBase}-vehicle`

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={title}
      icon={Radio}
      width="lg"
      closeLabel={t('common:close')}
      footer={
        device ? (
          <Button variant="danger" size="sm" icon={Trash2} disabled={busy} onClick={() => void remove()}>
            {t('integrations.deleteSource')}
          </Button>
        ) : undefined
      }
    >
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !device ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-6">
          <section className="space-y-2">
            {liveTab?.description ? <p className="text-sm text-text">{liveTab.description}</p> : null}
            {liveTab ? (
              <p className="text-sm text-text-mute">
                {t(STATUS_KEY[liveTab.reason] ?? 'integrations.statusNotConfigured')}
              </p>
            ) : null}
          </section>

          <section>
            <Field
              id={vehicleId}
              label={t('integrations.sourceVehicle')}
              error={device.vin ? undefined : t('integrations.deviceNotLinked')}
            >
              {/* The empty option UNLINKS: the API reads vin "" as "clear". */}
              <Select
                id={vehicleId}
                value={device.vin ?? ''}
                disabled={busy}
                onChange={(e) => void update({ vin: e.target.value })}
                placeholder={t('forms:modal.livelink.unlinked')}
                options={vehicles.map((v) => ({
                  value: v.vin,
                  label: v.nickname || `${v.year} ${v.make} ${v.model}`,
                }))}
              />
            </Field>
            <Field
              id={labelId}
              label={t('integrations.deviceLabel')}
              hint={device.preset_key ? t('integrations.labelPresetHint') : undefined}
            >
              <Input id={labelId} value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} />
            </Field>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || label === (device.label ?? '')}
              onClick={() => void update({ label })}
            >
              {t('forms:modal.livelink.save')}
            </Button>
          </section>

          {readingsFailed ? (
            <div className="space-y-2">
              <p className="text-sm text-text-mute">{t('integrations.readingsLoadError')}</p>
              <Button size="sm" variant="secondary" onClick={() => void loadReadings()}>
                {t('common:retry')}
              </Button>
            </div>
          ) : readings ? (
            <DeviceReadingsList readings={readings.readings} onChanged={() => void loadReadings()} />
          ) : null}

          {/* Keyed on the device, so reopening on another device starts closed
              or open by that device's own rule. */}
          <details key={device.device_id} open={!device.preset_key} className="rounded-control border border-border p-3">
            <summary className="cursor-pointer text-sm font-semibold text-text">
              {t('integrations.advancedMappings')}
            </summary>
            <div className="mt-3">
              <TopicMapEditor deviceId={device.device_id} onMappingsChanged={() => void loadReadings()} />
            </div>
          </details>
        </div>
      )}
    </Drawer>
  )
}
