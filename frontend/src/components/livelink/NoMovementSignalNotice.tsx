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
 * The backend logs the same thing once per process with the parameter keys
 * attached. This is the half that survives a log rotation and reaches someone
 * who is not reading logs.
 *
 * A device that has simply never been driven since the upgrade also has no
 * movement on record, so this waits for it to have been HEARD FROM recently:
 * a device checking in and still reporting nothing readable is the actionable
 * case, and a dongle sitting in a drawer is not.
 *
 * "Recently" is measured against the NEWEST check-in among the devices shown,
 * not against the wall clock. `Date.now()` in render is impure -- it makes the
 * component non-idempotent, and eslint refuses it -- and the relative form is
 * the better question anyway: it asks whether this device is keeping up with
 * the others, so an instance whose whole fleet has been offline for a month
 * raises nothing rather than raising everything.
 */

interface Props {
  devices: LiveLinkDevice[]
}

/** How far behind the newest check-in a device may be and still be flagged. */
const RECENTLY_SEEN_DAYS = 7

export default function NoMovementSignalNotice({ devices }: Props): React.ReactElement | null {
  const { t } = useTranslation('forms')

  const seenAt = (device: LiveLinkDevice): number =>
    device.last_seen == null ? Number.NEGATIVE_INFINITY : new Date(device.last_seen).getTime()

  const newestCheckIn = devices.reduce(
    (newest, device) => Math.max(newest, seenAt(device)),
    Number.NEGATIVE_INFINITY
  )
  const cutoff = newestCheckIn - RECENTLY_SEEN_DAYS * 24 * 60 * 60 * 1000

  const affected = devices.filter(
    (device) =>
      device.enabled &&
      device.vin != null &&
      device.last_movement_at == null &&
      device.last_seen != null &&
      seenAt(device) >= cutoff
  )

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
