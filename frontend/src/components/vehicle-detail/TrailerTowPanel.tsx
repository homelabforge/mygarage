import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Link2, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, Button, Field, Select, Input } from '../ui'
import vehicleService from '../../services/vehicleService'
import { NON_MOTORIZED_TYPES } from '../../schemas/vehicle'
import type { TrailerDetails, Vehicle } from '../../types/vehicle'

interface TrailerTowPanelProps {
  vehicle: Vehicle
}

const HITCH_OPTIONS = ['Ball', 'Pintle', 'Fifth Wheel', 'Gooseneck']
const BRAKE_OPTIONS = ['None', 'Electric', 'Hydraulic']

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
        const list = await vehicleService.listTowedTrailers(vehicle.vin)
        setTowed(Array.isArray(list) ? list : [])
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
      const payload = {
        hitch_type: form.hitch_type || null,
        brake_type: form.brake_type || null,
        axle_count: form.axle_count ? Number(form.axle_count) : null,
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
      toast.success(t('detail.tow.saved', { defaultValue: 'Trailer details saved' }))
      await load()
    } catch (err) {
      toast.error(t('detail.tow.saveError', { defaultValue: 'Failed to save trailer details' }))
      console.error(err)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card breakInside>
        <CardHeader title={t('detail.tow.title', { defaultValue: 'Tow pairing' })} />
        <p className="text-sm text-text-mute">{t('common:loading', { defaultValue: 'Loading…' })}</p>
      </Card>
    )
  }

  if (!isTrailerLike) {
    if (towed.length === 0) return null
    return (
      <Card breakInside>
        <CardHeader
          title={t('detail.tow.linkedTrailers', { defaultValue: 'Linked trailers' })}
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
      <CardHeader title={t('detail.tow.title', { defaultValue: 'Trailer & tow vehicle' })} icon={Link2} />
      <div className="space-y-3">
        <Field id="tow_vehicle_vin" label={t('detail.tow.towVehicle', { defaultValue: 'Tow vehicle' })}>
          <Select
            id="tow_vehicle_vin"
            value={form.tow_vehicle_vin}
            onChange={(e) => setForm((f) => ({ ...f, tow_vehicle_vin: e.target.value }))}
            options={[
              { value: '', label: t('detail.tow.none', { defaultValue: 'None' }) },
              ...towCandidates.map((v) => ({
                value: v.vin,
                label: `${v.nickname} (${v.vin})`,
              })),
            ]}
          />
        </Field>
        <Field id="hitch_type" label={t('detail.tow.hitch', { defaultValue: 'Hitch type' })}>
          <Select
            id="hitch_type"
            value={form.hitch_type}
            onChange={(e) => setForm((f) => ({ ...f, hitch_type: e.target.value }))}
            options={[
              { value: '', label: '—' },
              ...HITCH_OPTIONS.map((h) => ({ value: h, label: h })),
            ]}
          />
        </Field>
        <Field id="brake_type" label={t('detail.tow.brakes', { defaultValue: 'Brake type' })}>
          <Select
            id="brake_type"
            value={form.brake_type}
            onChange={(e) => setForm((f) => ({ ...f, brake_type: e.target.value }))}
            options={[
              { value: '', label: '—' },
              ...BRAKE_OPTIONS.map((h) => ({ value: h, label: h })),
            ]}
          />
        </Field>
        <Field id="axle_count" label={t('detail.tow.axles', { defaultValue: 'Axles' })}>
          <Input
            id="axle_count"
            type="number"
            min={1}
            max={10}
            value={form.axle_count}
            onChange={(e) => setForm((f) => ({ ...f, axle_count: e.target.value }))}
          />
        </Field>
        <Button variant="primary" icon={Save} loading={saving} onClick={() => void save()}>
          {t('common:save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  )
}
