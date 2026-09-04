import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'
import type { LiveLinkDevice } from '@/types/livelink'

/**
 * Names devices that report telemetry but nothing recognisable as movement.
 *
 * Drive sessions are decided by speed, an odometer increase, or RPM. A device
 * whose speed arrives under a name this codebase does not know records **no
 * drives at all** -- and "no drives" is indistinguishable from "the vehicle was
 * parked" unless something says otherwise. A silent zero is precisely the
 * failure the boundary rework exists to remove, so reintroducing one for this
 * cohort would be absurd.
 *
 * The backend picks the cohort, because the answer needs the devices' parameter
 * keys; see `LiveLinkService.movement_unreadable_device_ids` for why the browser
 * cannot and what an earlier version of this file got wrong by trying.
 *
 * The backend logs the same conclusion once per process with the keys attached.
 * This is the half that survives a log rotation and reaches someone who is not
 * reading logs.
 */

interface Props {
  devices: LiveLinkDevice[]
}

export default function NoMovementSignalNotice({ devices }: Props): React.ReactElement | null {
  const { t } = useTranslation('forms')

  const affected = devices.filter((device) => device.movement_unreadable)

  if (affected.length === 0) return null

  return (
    <div
      role="status"
      className="flex gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3"
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
      <div className="text-sm">
        <p className="font-medium text-garage-text">{t('modal.livelink.noMovementSignal')}</p>
        <p className="mt-1 text-garage-text-muted">
          {t('modal.livelink.noMovementSignalDesc', {
            devices: affected.map((device) => device.label || device.device_id).join(', '),
          })}
        </p>
      </div>
    </div>
  )
}
