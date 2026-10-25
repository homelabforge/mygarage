import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Check, Pencil, SlidersHorizontal, Trash2 } from 'lucide-react'

import { Button, IconButton, Input, Select } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import type { DeviceReadingsResponse, LiveLinkDevice } from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import DeviceReadingsList from './DeviceReadingsList'
import SensorAlerts from './SensorAlerts'
import TopicMapEditor from './TopicMapEditor'

/**
 * One sensor made from a preset: a compact block under the preset's drawer,
 * the way each WiCAN dongle is one row under WiCAN's.
 *
 * The header holds what belongs to the sensor itself (its name, whether it is
 * reporting, which vehicle it feeds); the body is its readings, two to a row,
 * then its alert lines. Topic mappings and delete are one click away but not
 * in the way.
 */

interface Props {
  device: LiveLinkDevice
  vehicles: Vehicle[]
  /** The sensor list or a status changed: the drawer reloads and the card
   *  behind it refetches its strip. */
  onChanged: () => void
}

export default function SensorBlock({ device, vehicles, onChanged }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const idBase = useId()
  const [readings, setReadings] = useState<DeviceReadingsResponse | null>(null)
  const [readingsFailed, setReadingsFailed] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [label, setLabel] = useState(device.label ?? '')
  const [showMappings, setShowMappings] = useState(false)
  const [busy, setBusy] = useState(false)

  const loadReadings = useCallback(async (): Promise<void> => {
    setReadingsFailed(false)
    try {
      setReadings(await livelinkService.getDeviceReadings(device.device_id))
    } catch {
      setReadingsFailed(true)
    }
  }, [device.device_id])

  useEffect(() => {
    void loadReadings()
  }, [loadReadings])

  const update = async (change: { vin?: string; label?: string }): Promise<void> => {
    setBusy(true)
    try {
      await livelinkService.updateDevice(device.device_id, change)
      setRenaming(false)
      onChanged()
      // A rename renames the readings too (server side), and a link change
      // changes which rows count as this sensor's.
      await loadReadings()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('integrations.saveSettingsAction')))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (): Promise<void> => {
    // ||, not ??: a name cleared before blanks were stored as null is still ''.
    if (!confirm(t('integrations.confirmDeleteSensor', { name: device.label || device.device_id }))) return
    setBusy(true)
    try {
      await livelinkService.deleteDevice(device.device_id)
      onChanged()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('integrations.deleteSourceAction')))
      setBusy(false)
    }
  }

  // Short: the line under the header says what not being linked costs. Until
  // the readings arrive nothing is known, and a failed load isn't a quiet
  // sensor, so neither may read "no recent readings".
  const [status, tone] = !device.vin
    ? [t('integrations.sourceVehicleUnset'), 'text-warning']
    : readingsFailed
      ? [t('integrations.sensorStatusFailed'), 'text-warning']
      : !readings
        ? [t('integrations.sensorStatusLoading'), 'text-text-mute']
        : readings.online
          ? [t('integrations.statusReceiving'), 'text-success']
          : [t('integrations.sensorNoData'), 'text-warning']
  const name = device.label || device.device_id

  return (
    <section
      aria-labelledby={`${idBase}-name`}
      className="rounded-control border border-border p-3 space-y-2"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {renaming ? (
          <div className="flex items-center gap-1">
            <Input
              aria-label={t('integrations.sensorName')}
              size="sm"
              value={label}
              maxLength={60}
              onChange={(e) => setLabel(e.target.value)}
            />
            {/* Every reading is named after the sensor, so a blank name
                would leave them all nameless. */}
            <IconButton
              icon={Check}
              label={t('forms:modal.livelink.save')}
              variant="ghost"
              size="sm"
              disabled={busy || label.trim() === ''}
              onClick={() => void update({ label: label.trim() })}
            />
          </div>
        ) : (
          <h4 id={`${idBase}-name`} className="flex items-center gap-1 text-sm font-semibold text-text">
            {name}
            <IconButton
              icon={Pencil}
              label={t('integrations.renameSensor', { name })}
              variant="ghost"
              size="sm"
              onClick={() => setRenaming(true)}
            />
          </h4>
        )}
        <span className={`text-xs ${tone}`}>{status}</span>
        <div className="ml-auto flex items-center gap-1">
          <Select
            aria-label={t('integrations.sourceVehicle')}
            size="sm"
            value={device.vin ?? ''}
            disabled={busy}
            onChange={(e) => void update({ vin: e.target.value })}
            placeholder={t('integrations.sourceVehicleUnset')}
            options={vehicles.map((v) => ({
              value: v.vin,
              label: v.nickname || `${v.year} ${v.make} ${v.model}`,
            }))}
          />
          <IconButton
            icon={SlidersHorizontal}
            label={t('integrations.advancedMappings')}
            variant="ghost"
            size="sm"
            onClick={() => setShowMappings((shown) => !shown)}
          />
          <IconButton
            icon={Trash2}
            label={t('integrations.deleteSensor', { name })}
            variant="danger"
            size="sm"
            onClick={() => void remove()}
          />
        </div>
      </header>

      {!device.vin ? <p className="text-xs text-warning">{t('integrations.deviceNotLinked')}</p> : null}

      {readingsFailed ? (
        <div className="flex items-center gap-2">
          <p className="text-xs text-text-mute">{t('integrations.readingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void loadReadings()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : readings ? (
        <>
          <DeviceReadingsList
            compact
            sensorLabel={device.label ?? undefined}
            readings={readings.readings}
            onChanged={() => void loadReadings()}
          />
          <SensorAlerts
            readings={readings.readings}
            sensorLabel={device.label ?? undefined}
            onSaved={() => void loadReadings()}
          />
        </>
      ) : null}

      {showMappings ? (
        <div className="border-t border-border pt-2">
          <TopicMapEditor deviceId={device.device_id} onMappingsChanged={() => void loadReadings()} />
        </div>
      ) : null}
    </section>
  )
}
