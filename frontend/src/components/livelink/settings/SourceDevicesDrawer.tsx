import { useCallback, useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Cpu, RefreshCw } from 'lucide-react'

import NoMovementSignalNotice from '@/components/livelink/NoMovementSignalNotice'
import { Button, Drawer } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type { IntegrationTab, LiveLinkDevice } from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import DeviceTable from './DeviceTable'

/**
 * The settings drawer for a source kind nobody has written a drawer for.
 *
 * A newly registered source module gets a tab with no frontend change (spec
 * G2), and this is what its Settings button opens: its devices, with the
 * controls its capabilities allow, and nothing bespoke. The module contract
 * carries no presentation metadata, so a richer drawer needs code.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  onChanged: () => void
}

export default function SourceDevicesDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const kind = tab?.kind ?? null
  const [devices, setDevices] = useState<LiveLinkDevice[] | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [loadFailed, setLoadFailed] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    setLoadFailed(false)
    try {
      const [loaded, loadedVehicles] = await Promise.all([livelinkService.getDevices(), vehicleService.list()])
      setDevices(loaded.devices.filter((d) => d.kind === kind))
      setVehicles(loadedVehicles.vehicles)
    } catch {
      setLoadFailed(true)
    }
  }, [kind])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const deviceChanged = (): void => {
    void load()
    onChanged()
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('integrations.sourceSettings', { source: tab?.label ?? '' })}
      icon={Cpu}
      width="xl"
      closeLabel={t('common:close')}
    >
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !devices ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : devices.length > 0 ? (
        <div className="space-y-4">
          <NoMovementSignalNotice devices={devices} />
          <DeviceTable devices={devices} vehicles={vehicles} onChanged={deviceChanged} />
        </div>
      ) : (
        <p className="text-sm text-text-mute">{t('integrations.noSourceDevices')}</p>
      )}
    </Drawer>
  )
}
