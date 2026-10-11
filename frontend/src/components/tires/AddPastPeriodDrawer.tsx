import { useState } from 'react'
import { Gauge } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { useCreateMountPeriod } from '../../hooks/queries/useTires'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { POSITIONS } from '../../types/tire'
import type { MountedPosition, Tire, TirePosition } from '../../types/tire'
import { hoursFromField } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { canonicalFromUnitField } from '../../utils/unitFormat'
import { Button, Chip, Drawer, Field, Input } from '../ui'
import MountEventFields, { EMPTY_ODOMETER, type OdometerFieldValue } from './MountEventFields'

interface AddPastPeriodDrawerProps {
  vin: string
  tire: Tire
  open: boolean
  onClose: () => void
  labelFor: (position: TirePosition) => string
  /** Whether the vehicle takes an odometer. Defaults to true. */
  tracksDistance?: boolean
  /** Whether the vehicle takes an hour meter. Defaults to false. */
  tracksHours?: boolean
}

/**
 * Record a closed period the tire spent on a corner in the past.
 *
 * A sibling of `MountPeriodEditor`, not a mode of it: the editor seeds every
 * field from an existing period and sends only what that period's own state
 * allows to be sent (an open period has no dismount pair at all), while a
 * create form has neither an existing period to seed from nor a partial
 * shape to respect -- every field starts empty and the corner and both
 * dates are required before Save can submit. A nested drawer, because it
 * opens from the history drawer and a modal opened from a drawer is inert
 * in this app.
 */
export default function AddPastPeriodDrawer({
  vin,
  tire,
  open,
  onClose,
  labelFor,
  tracksDistance = true,
  tracksHours = false,
}: AddPastPeriodDrawerProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const create = useCreateMountPeriod(vin)

  const [position, setPosition] = useState<MountedPosition | null>(null)
  const [mountedOn, setMountedOn] = useState('')
  const [mountedOdometer, setMountedOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [mountedHours, setMountedHours] = useState('')
  const [dismountedOn, setDismountedOn] = useState('')
  const [dismountedOdometer, setDismountedOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [dismountedHours, setDismountedHours] = useState('')
  const [notes, setNotes] = useState('')

  const odometerLabel = t('tireList.odometerWithUnit', { unit: u.distance.label })

  const save = (): void => {
    if (position === null) {
      toast.error(t('tireList.pastPeriodCornerRequired'))
      return
    }
    if (mountedOn === '' || dismountedOn === '') {
      toast.error(t('tireList.pastPeriodDatesRequired'))
      return
    }
    create.mutate(
      {
        tireId: tire.id,
        position,
        mounted_on: mountedOn,
        dismounted_on: dismountedOn,
        ...(tracksDistance
          ? {
              mounted_odometer_km: canonicalFromUnitField(
                mountedOdometer.typed,
                mountedOdometer.origin,
                u.distance
              ),
              dismounted_odometer_km: canonicalFromUnitField(
                dismountedOdometer.typed,
                dismountedOdometer.origin,
                u.distance
              ),
            }
          : {}),
        ...(tracksHours
          ? {
              mounted_hours: hoursFromField(mountedHours),
              dismounted_hours: hoursFromField(dismountedHours),
            }
          : {}),
        notes: notes.trim() || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.pastPeriodSaved'))
          onClose()
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.pastPeriodSaveAction'))),
      }
    )
  }

  return (
    <Drawer
      nested
      open={open}
      onClose={onClose}
      title={t('tireList.addPastPeriodTitle')}
      icon={Gauge}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={create.isPending} onClick={save}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field id="past-position" label={t('tireList.pastPeriodCorner')}>
          <div className="flex flex-wrap gap-2">
            {POSITIONS.map((p) => (
              <Chip key={p} selected={position === p} onClick={() => setPosition(p)}>
                {labelFor(p)}
              </Chip>
            ))}
          </div>
        </Field>
        <MountEventFields
          vin={vin}
          idPrefix="past-mount"
          dateLabel={t('tireList.periodMount')}
          date={mountedOn}
          onDateChange={setMountedOn}
          odometerLabel={odometerLabel}
          odometer={mountedOdometer}
          onOdometerChange={setMountedOdometer}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
          hours={mountedHours}
          onHoursChange={setMountedHours}
        />
        <MountEventFields
          vin={vin}
          idPrefix="past-dismount"
          dateLabel={t('tireList.periodDismount')}
          date={dismountedOn}
          onDateChange={setDismountedOn}
          odometerLabel={odometerLabel}
          odometer={dismountedOdometer}
          onOdometerChange={setDismountedOdometer}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
          hours={dismountedHours}
          onHoursChange={setDismountedHours}
        />
        <Field id="past-notes" label={t('tireList.notes')}>
          <Input id="past-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Drawer>
  )
}
