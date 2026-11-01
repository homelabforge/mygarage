import { useCallback, useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Radio, RefreshCw } from 'lucide-react'

import { Button, Drawer } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type { IntegrationTab, LiveLinkDevice } from '@/types/livelink'
import type { PresetInfo } from '@/types/livelinkTopicMap'
import type { Vehicle } from '@/types/vehicle'
import { presetDescription } from '../presetText'
import SensorBlock from './SensorBlock'
import SensorForm from './SensorForm'

/**
 * A preset's drawer: every sensor made from it, one compact block each, and a
 * way to add another. Opened from the preset's tab ("Mopeka"), which groups
 * all of them the way the WiCAN tab groups every dongle.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  onChanged: () => void
}

export const PRESET_TAB_PREFIX = 'preset:'

export default function PresetDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const presetName = tab?.id.startsWith(PRESET_TAB_PREFIX) ? tab.id.slice(PRESET_TAB_PREFIX.length) : null

  const [preset, setPreset] = useState<PresetInfo | null>(null)
  const [sensors, setSensors] = useState<LiveLinkDevice[] | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [loadFailed, setLoadFailed] = useState(false)
  const [adding, setAdding] = useState(false)

  const loadSensors = useCallback(async (): Promise<void> => {
    const list = await livelinkService.getDevices()
    // In the order they were added (mopeka-t1, t2, ... t10), not the list's
    // own order, which moves whichever reported last to the top.
    setSensors(
      list.devices
        .filter((d) => d.preset_key === presetName)
        .sort((a, b) => a.device_id.localeCompare(b.device_id, undefined, { numeric: true })),
    )
  }, [presetName])

  const load = useCallback(async (): Promise<void> => {
    if (!presetName) return
    setLoadFailed(false)
    try {
      const [presets, loadedVehicles] = await Promise.all([livelinkService.listPresets(), vehicleService.list()])
      setPreset(presets.find((p) => p.name === presetName) ?? null)
      setVehicles(loadedVehicles.vehicles)
      await loadSensors()
    } catch {
      setLoadFailed(true)
    }
  }, [presetName, loadSensors])

  useEffect(() => {
    if (!open) return
    setAdding(false)
    void load()
  }, [open, load])

  const changed = (): void => {
    void loadSensors()
    onChanged()
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('integrations.sourceSettings', { source: tab?.label ?? '' })}
      icon={Radio}
      width="lg"
      closeLabel={t('common:close')}
    >
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !sensors || !preset ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-text">{presetDescription(preset, t)}</p>

          {sensors.length === 0 ? (
            <p className="text-sm text-text-mute">{t('integrations.noSensors')}</p>
          ) : (
            sensors.map((sensor) => (
              <SensorBlock key={sensor.device_id} device={sensor} vehicles={vehicles} onChanged={changed} />
            ))
          )}

          {adding ? (
            <section className="rounded-control border border-border p-3 space-y-2">
              <h4 className="text-sm font-semibold text-text">{t('integrations.addSensor')}</h4>
              <SensorForm
                preset={preset}
                vehicles={vehicles}
                onCreated={() => {
                  setAdding(false)
                  changed()
                }}
                onCancel={() => setAdding(false)}
              />
            </section>
          ) : (
            <Button size="sm" variant="secondary" icon={Plus} onClick={() => setAdding(true)}>
              {t('integrations.addSensor')}
            </Button>
          )}
        </div>
      )}
    </Drawer>
  )
}
