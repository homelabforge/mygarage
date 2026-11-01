import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Disc } from 'lucide-react'
import { toast } from 'sonner'

import { useLogBrakeMeasurements } from '../../hooks/queries/useBrakes'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { useRefuseUnreadableNumbers } from '../../hooks/useRefuseUnreadableNumbers'
import { AXLE_OF, BRAKE_POSITIONS, type BrakeMeasurementCorner, type BrakeOverview, type BrakePosition } from '../../types/brake'
import { formatDateForInput } from '../../utils/dateUtils'
import { hoursFromField } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { canonicalFromTypedUnitField } from '../../utils/unitFormat'
import { numberFromField } from '../../utils/decimalInput'
import MountEventFields, { EMPTY_ODOMETER, type OdometerFieldValue } from '../tires/MountEventFields'
import { Button, Drawer, Field, NumberInput } from '../ui'
import { useBrakeText } from './useBrakeText'
import { withUnitSession } from '../../contexts/UnitSession'

/** The figures one corner's fieldset holds, as typed, in mm. */
interface CornerFields {
  inner_pad_mm: string
  outer_pad_mm: string
  rotor_mm: string
  shoe_mm: string
  drum_mm: string
}

const EMPTY_CORNER: CornerFields = {
  inner_pad_mm: '',
  outer_pad_mm: '',
  rotor_mm: '',
  shoe_mm: '',
  drum_mm: '',
}

const DISC_FIELDS = ['inner_pad_mm', 'outer_pad_mm', 'rotor_mm'] as const
const DRUM_FIELDS = ['shoe_mm', 'drum_mm'] as const

interface LogBrakeMeasurementsDrawerProps {
  vin: string
  overview: BrakeOverview
  open: boolean
  onClose: () => void
}

/**
 * One form for all four corners, because the wheels usually come off
 * together. A corner left blank is skipped. Remount it (with a `key`) to start
 * the form over.
 */
function LogBrakeMeasurementsDrawer({
  vin,
  overview,
  open,
  onClose,
}: LogBrakeMeasurementsDrawerProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const text = useBrakeText()
  const log = useLogBrakeMeasurements(vin)
  const refuseUnreadable = useRefuseUnreadableNumbers()
  const [date, setDate] = useState(() => formatDateForInput())
  const [odometer, setOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [hours, setHours] = useState('')
  const [corners, setCorners] = useState<Record<BrakePosition, CornerFields>>({
    FL: EMPTY_CORNER,
    FR: EMPTY_CORNER,
    RL: EMPTY_CORNER,
    RR: EMPTY_CORNER,
  })

  const typeOf = (position: BrakePosition) =>
    overview.axles.find((axle) => axle.axle === AXLE_OF[position])?.brake_type ?? 'disc'

  const setField = (position: BrakePosition, name: keyof CornerFields, value: string): void =>
    setCorners((prev) => ({ ...prev, [position]: { ...prev[position], [name]: value } }))

  const fieldLabels: Record<keyof CornerFields, string> = {
    inner_pad_mm: t('brakes.innerPad'),
    outer_pad_mm: t('brakes.outerPad'),
    rotor_mm: t('brakes.rotor'),
    shoe_mm: t('brakes.shoe'),
    drum_mm: t('brakes.drumDiameter'),
  }

  const handleSave = (): void => {
    if (!date) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    const odometerLabel = t('brakes.odometerWithUnit', { unit: u.distance.label })
    if (
      refuseUnreadable([
        [odometerLabel, overview.tracks_distance && odometer.typed],
        [t('common:engineHours'), overview.tracks_hours && hours],
        ...BRAKE_POSITIONS.flatMap((position) =>
          (typeOf(position) === 'drum' ? DRUM_FIELDS : DISC_FIELDS).map(
            (name) => [`${text.labelFor(position)} · ${fieldLabels[name]}`, corners[position][name]] as const
          )
        ),
      ])
    )
      return
    const measured: BrakeMeasurementCorner[] = []
    for (const position of BRAKE_POSITIONS) {
      const names = typeOf(position) === 'drum' ? DRUM_FIELDS : DISC_FIELDS
      const figures: Partial<Record<keyof CornerFields, number>> = {}
      for (const name of names) {
        // A blank figure is left out, so the corner's other figures are kept; 0 stays 0.
        const value = numberFromField(corners[position][name])
        if (value !== null) figures[name] = value
      }
      if (Object.keys(figures).length > 0) measured.push({ position, ...figures })
    }
    if (measured.length === 0) {
      toast.error(t('brakes.nothingToLog'))
      return
    }
    log.mutate(
      {
        recorded_at: date,
        corners: measured,
        ...(overview.tracks_distance
          ? { odometer_km: canonicalFromTypedUnitField(odometer.typed, odometer.origin, u.distance) }
          : {}),
        ...(overview.tracks_hours ? { engine_hours: hoursFromField(hours) } : {}),
      },
      {
        onSuccess: () => {
          toast.success(t('brakes.logged'))
          onClose()
        },
        onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.logAction'))),
      }
    )
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('brakes.logTitle')}
      icon={Disc}
      width="md"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={log.isPending} onClick={handleSave}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <MountEventFields
          vin={vin}
          idPrefix="brake-log"
          dateLabel={t('common:date')}
          date={date}
          onDateChange={setDate}
          odometerLabel={t('brakes.odometerWithUnit', { unit: u.distance.label })}
          odometer={odometer}
          onOdometerChange={setOdometer}
          tracksDistance={overview.tracks_distance}
          tracksHours={overview.tracks_hours}
          hours={hours}
          onHoursChange={setHours}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          {BRAKE_POSITIONS.map((position) => {
            const type = typeOf(position)
            const names = type === 'drum' ? DRUM_FIELDS : DISC_FIELDS
            return (
              <fieldset key={position} className="space-y-2 rounded-card border border-border p-3">
                <legend className="px-1 text-sm font-semibold">
                  {text.labelFor(position)} · {text.typeLabel(type)}
                </legend>
                {names.map((name) => {
                  const id = `brake-log-${position}-${name}`
                  return (
                    <Field key={name} id={id} label={fieldLabels[name]} unit="mm">
                      <NumberInput
                        id={id}
                        value={corners[position][name]}
                        onChange={(e) => setField(position, name, e.target.value)}
                      />
                    </Field>
                  )
                })}
              </fieldset>
            )
          })}
        </div>
        <p className="text-sm text-text-mute">{t('brakes.logHint')}</p>
      </div>
    </Drawer>
  )
}

// Pins its units for as long as it is open (R4).
export default withUnitSession(LogBrakeMeasurementsDrawer)
