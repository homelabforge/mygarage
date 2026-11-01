import { useState } from 'react'
import { Gauge } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { useUpdateMountPeriod } from '../../hooks/queries/useTires'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { useRefuseUnreadableNumbers } from '../../hooks/useRefuseUnreadableNumbers'
import type { MountedPosition, Tire, TireMountPeriod, TirePosition } from '../../types/tire'
import { hoursFromField } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { canonicalFromTypedUnitField, seedUnitField } from '../../utils/unitFormat'
import { num } from '../../utils/wireNumber'
import { Button, Drawer, Field, Input } from '../ui'
import MountEventFields, { type OdometerFieldValue } from './MountEventFields'
import { withUnitSession } from '../../contexts/UnitSession'

interface MountPeriodEditorProps {
  vin: string
  tire: Tire
  period: TireMountPeriod
  open: boolean
  onClose: () => void
  labelFor: (position: TirePosition) => string
  /** Whether the vehicle takes an odometer. Defaults to true. */
  tracksDistance?: boolean
  /** Whether the vehicle takes an hour meter. Defaults to false. */
  tracksHours?: boolean
}

interface EditorState {
  mounted_on: string
  mounted_odometer_km: OdometerFieldValue
  mounted_hours: string
  dismounted_on: string
  dismounted_odometer_km: OdometerFieldValue
  dismounted_hours: string
  notes: string
}

/**
 * Correct one mount period. A nested drawer, because it opens from the
 * history drawer and a modal opened from a drawer is inert in this app.
 *
 * Every rendered field is seeded from the period and every rendered field
 * is sent, so clearing one is a deliberate act and an unrendered field can
 * never submit as null. The dismount pair renders only for a closed period:
 * the server refuses a dismount key on an open one, even as null, because
 * closing a period is what Dismount is. Render this with `key={period.id}`
 * so the state seeds once per period rather than through an effect.
 */
function MountPeriodEditor({
  vin,
  tire,
  period,
  open,
  onClose,
  labelFor,
  tracksDistance = true,
  tracksHours = false,
}: MountPeriodEditorProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const update = useUpdateMountPeriod(vin)
  const refuseUnreadable = useRefuseUnreadableNumbers()
  const closed = period.dismounted_on != null

  const [form, setForm] = useState<EditorState>(() => {
    const mount = seedUnitField(num(period.mounted_odometer_km), u.distance)
    const dismount = seedUnitField(num(period.dismounted_odometer_km), u.distance)
    return {
      mounted_on: period.mounted_on ?? '',
      mounted_odometer_km: { typed: mount.display, origin: mount },
      mounted_hours: period.mounted_hours != null ? Number(period.mounted_hours).toFixed(1) : '',
      dismounted_on: period.dismounted_on ?? '',
      dismounted_odometer_km: { typed: dismount.display, origin: dismount },
      dismounted_hours: period.dismounted_hours != null ? Number(period.dismounted_hours).toFixed(1) : '',
      notes: period.notes ?? '',
    }
  })

  const odometerLabel = t('tireList.odometerWithUnit', { unit: u.distance.label })
  // The two halves have the same boxes, so a refusal says which half.
  const mountLabel = (field: string): string => t('tireList.periodField', { group: t('tireList.periodMount'), field })
  const dismountLabel = (field: string): string =>
    t('tireList.periodField', { group: t('tireList.periodDismount'), field })

  const save = () => {
    if (closed && form.dismounted_on === '') {
      toast.error(t('tireList.periodDismountDateRequired'))
      return
    }
    if (
      refuseUnreadable([
        [mountLabel(odometerLabel), tracksDistance && form.mounted_odometer_km.typed],
        [mountLabel(t('common:engineHours')), tracksHours && form.mounted_hours],
        [dismountLabel(odometerLabel), closed && tracksDistance && form.dismounted_odometer_km.typed],
        [dismountLabel(t('common:engineHours')), closed && tracksHours && form.dismounted_hours],
      ])
    )
      return
    const payload = {
      tireId: tire.id,
      periodId: period.id,
      mounted_on: form.mounted_on || null,
      ...(tracksDistance
        ? {
            mounted_odometer_km: canonicalFromTypedUnitField(
              form.mounted_odometer_km.typed,
              form.mounted_odometer_km.origin,
              u.distance
            ),
          }
        : {}),
      ...(tracksHours ? { mounted_hours: hoursFromField(form.mounted_hours) } : {}),
      notes: form.notes.trim() || null,
      ...(closed
        ? {
            dismounted_on: form.dismounted_on,
            ...(tracksDistance
              ? {
                  dismounted_odometer_km: canonicalFromTypedUnitField(
                    form.dismounted_odometer_km.typed,
                    form.dismounted_odometer_km.origin,
                    u.distance
                  ),
                }
              : {}),
            ...(tracksHours ? { dismounted_hours: hoursFromField(form.dismounted_hours) } : {}),
          }
        : {}),
    }
    update.mutate(payload, {
      onSuccess: () => {
        toast.success(t('tireList.periodSaved'))
        onClose()
      },
      onError: (err: unknown) =>
        toast.error(getActionErrorMessage(err, t('tireList.periodSaveAction'))),
    })
  }

  return (
    <Drawer
      nested
      open={open}
      onClose={onClose}
      /* `MountPeriodResponse.position` is generated as plain `string` (the
         backend schema has no Literal there), but a period is always mounted
         at one of the five corners. Same pre-approved cast as the history
         drawer. */
      title={t('tireList.editPeriodTitle', { position: labelFor(period.position as MountedPosition) })}
      icon={Gauge}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={update.isPending} onClick={save}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <MountEventFields
          vin={vin}
          idPrefix="period-mount"
          groupLabel={t('tireList.periodMount')}
          dateLabel={t('tireList.periodMount')}
          date={form.mounted_on}
          onDateChange={(next) => setForm({ ...form, mounted_on: next })}
          odometerLabel={odometerLabel}
          odometer={form.mounted_odometer_km}
          onOdometerChange={(next) => setForm({ ...form, mounted_odometer_km: next })}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
          hours={form.mounted_hours}
          onHoursChange={(next) => setForm({ ...form, mounted_hours: next })}
        />
        {closed && (
          <MountEventFields
            vin={vin}
            idPrefix="period-dismount"
            groupLabel={t('tireList.periodDismount')}
            dateLabel={t('tireList.periodDismount')}
            date={form.dismounted_on}
            onDateChange={(next) => setForm({ ...form, dismounted_on: next })}
            odometerLabel={odometerLabel}
            odometer={form.dismounted_odometer_km}
            onOdometerChange={(next) => setForm({ ...form, dismounted_odometer_km: next })}
            tracksDistance={tracksDistance}
            tracksHours={tracksHours}
            hours={form.dismounted_hours}
            onHoursChange={(next) => setForm({ ...form, dismounted_hours: next })}
          />
        )}
        <Field id="period-notes" label={t('tireList.notes')}>
          <Input
            id="period-notes"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </Field>
      </div>
    </Drawer>
  )
}

// Pins its units for as long as it is open (R4).
export default withUnitSession(MountPeriodEditor)
