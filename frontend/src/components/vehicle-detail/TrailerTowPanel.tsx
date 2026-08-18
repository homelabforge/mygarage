import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Link2, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, Button, Field, Select, NumberInput } from '../ui'
import vehicleService from '../../services/vehicleService'
import { NON_MOTORIZED_TYPES } from '../../schemas/vehicle'
import type { TrailerDetails, Vehicle } from '../../types/vehicle'
import { parseDecimalInput } from '../../utils/decimalInput'
import { getActiveLocale } from '@/constants/i18n'

interface TrailerTowPanelProps {
  vehicle: Vehicle
}

const HITCH_OPTIONS = [
  { value: 'Ball', labelKey: 'detail.tow.hitchBall' },
  { value: 'Pintle', labelKey: 'detail.tow.hitchPintle' },
  { value: 'Fifth Wheel', labelKey: 'detail.tow.hitchFifthWheel' },
  { value: 'Gooseneck', labelKey: 'detail.tow.hitchGooseneck' },
] as const
const BRAKE_OPTIONS = [
  { value: 'None', labelKey: 'detail.tow.brakeNone' },
  { value: 'Electric', labelKey: 'detail.tow.brakeElectric' },
  { value: 'Hydraulic', labelKey: 'detail.tow.brakeHydraulic' },
] as const

/**
 * Trailer details + tow-vehicle pairing for trailer-like vehicles,
 * or a list of linked trailers when viewing a tow vehicle.
 */
export default function TrailerTowPanel({ vehicle }: TrailerTowPanelProps) {
  const { t } = useTranslation('vehicles')
  const isTrailerLike = (NON_MOTORIZED_TYPES as readonly string[]).includes(vehicle.vehicle_type)
  const [details, setDetails] = useState<TrailerDetails | null>(null)
  const [towed, setTowed] = useState<Vehicle[]>([])
  const [garageVehicles, setGarageVehicles] = useState<Vehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    hitch_type: '',
    brake_type: '',
    axle_count: '',
    tow_vehicle_vin: '',
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      if (isTrailerLike) {
        try {
          const list = await vehicleService.list(0, 200)
          setGarageVehicles(list.vehicles ?? [])
        } catch {
          setGarageVehicles([])
        }
        try {
          const d = await vehicleService.getTrailerDetails(vehicle.vin)
          setDetails(d)
          setForm({
            hitch_type: d.hitch_type || '',
            brake_type: d.brake_type || '',
            axle_count: d.axle_count != null ? String(d.axle_count) : '',
            tow_vehicle_vin: d.tow_vehicle_vin || '',
          })
        } catch {
          setDetails(null)
          setForm({ hitch_type: '', brake_type: '', axle_count: '', tow_vehicle_vin: '' })
        }
      } else {
        // Guarded like the two calls above. Without this the rejection escapes
        // the effect entirely, so a failed lookup surfaces as an unhandled
        // error rather than an empty list.
        try {
          const list = await vehicleService.listTowedTrailers(vehicle.vin)
          setTowed(Array.isArray(list) ? list : [])
        } catch {
          setTowed([])
        }
      }
    } finally {
      setLoading(false)
    }
  }, [isTrailerLike, vehicle.vin])

  useEffect(() => {
    void load()
  }, [load])

  const towCandidates = garageVehicles.filter(
    (v) =>
      v.vin !== vehicle.vin &&
      !(NON_MOTORIZED_TYPES as readonly string[]).includes(v.vehicle_type),
  )

  const save = async () => {
    setSaving(true)
    try {
      let axle_count: number | null = null
      if (form.axle_count.trim()) {
        const parsed = parseDecimalInput(form.axle_count, getActiveLocale())
        if (parsed.kind !== 'value' || !Number.isInteger(parsed.value) || parsed.value < 1 || parsed.value > 10) {
          toast.error(t('detail.tow.axlesInvalid'))
          setSaving(false)
          return
        }
        axle_count = parsed.value
      }
      const payload = {
        hitch_type: form.hitch_type || null,
        brake_type: form.brake_type || null,
        axle_count,
        tow_vehicle_vin: form.tow_vehicle_vin || null,
      }
      if (details) {
        await vehicleService.updateTrailerDetails(vehicle.vin, payload)
      } else {
        await vehicleService.createTrailerDetails(vehicle.vin, {
          vin: vehicle.vin,
          ...payload,
        })
      }
      toast.success(t('detail.tow.saved'))
      await load()
    } catch (err) {
      toast.error(t('detail.tow.saveError'))
      console.error(err)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card breakInside>
        <CardHeader title={t('detail.tow.loadingTitle')} />
        <p className="text-sm text-text-mute">{t('common:loading')}</p>
      </Card>
    )
  }

  if (!isTrailerLike) {
    if (towed.length === 0) return null
    return (
      <Card breakInside>
        <CardHeader
          title={t('detail.tow.linkedTrailers')}
          icon={Link2}
        />
        <ul className="space-y-2">
          {towed.map((tr) => (
            <li key={tr.vin}>
              <Link className="text-primary hover:underline font-medium" to={`/vehicles/${tr.vin}`}>
                {tr.nickname}
              </Link>
              <span className="text-xs text-text-mute ml-2 font-mono">{tr.vin}</span>
            </li>
          ))}
        </ul>
      </Card>
    )
  }

  return (
    <Card breakInside>
      <CardHeader title={t('detail.tow.title')} icon={Link2} />
      <div className="space-y-3">
        <Field id="tow_vehicle_vin" label={t('detail.tow.towVehicle')}>
          <Select
            id="tow_vehicle_vin"
            value={form.tow_vehicle_vin}
            onChange={(e) => setForm((f) => ({ ...f, tow_vehicle_vin: e.target.value }))}
            options={[
              { value: '', label: t('detail.tow.none') },
              ...towCandidates.map((v) => ({
                value: v.vin,
                label: `${v.nickname} (${v.vin})`,
              })),
            ]}
          />
        </Field>
        <Field id="hitch_type" label={t('detail.tow.hitch')}>
          <Select
            id="hitch_type"
            value={form.hitch_type}
            onChange={(e) => setForm((f) => ({ ...f, hitch_type: e.target.value }))}
            options={[
              { value: '', label: '—' },
              ...HITCH_OPTIONS.map((h) => ({ value: h.value, label: t(h.labelKey) })),
            ]}
          />
        </Field>
        <Field id="brake_type" label={t('detail.tow.brakes')}>
          <Select
            id="brake_type"
            value={form.brake_type}
            onChange={(e) => setForm((f) => ({ ...f, brake_type: e.target.value }))}
            options={[
              { value: '', label: '—' },
              ...BRAKE_OPTIONS.map((h) => ({ value: h.value, label: t(h.labelKey) })),
            ]}
          />
        </Field>
        <Field id="axle_count" label={t('detail.tow.axles')}>
          <NumberInput
            id="axle_count"
            value={form.axle_count}
            onChange={(e) => setForm((f) => ({ ...f, axle_count: e.target.value }))}
            placeholder="2"
          />
        </Field>
        <Button variant="primary" icon={Save} loading={saving} onClick={() => void save()}>
          {t('common:save')}
        </Button>
      </div>
    </Card>
  )
}
