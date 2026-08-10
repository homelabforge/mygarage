import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Gauge, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { Tire, TirePosition } from '../types/tire'
import {
  useTires,
  useUpsertTire,
  useAddTireReading,
  useDeleteTire,
} from '../hooks/queries/useTires'
import { Button, IconButton, Card, EmptyState, Input, Field, Select } from './ui'

const POSITIONS: TirePosition[] = ['FL', 'FR', 'RL', 'RR', 'SPARE']

interface TireListProps {
  vin: string
}

export default function TireList({ vin }: TireListProps) {
  const { t } = useTranslation('vehicles')
  const { data, isLoading, error } = useTires(vin)
  const upsert = useUpsertTire(vin)
  const addReading = useAddTireReading(vin)
  const remove = useDeleteTire(vin)

  const [showForm, setShowForm] = useState(false)
  const [readingTireId, setReadingTireId] = useState<number | null>(null)
  const [form, setForm] = useState({
    position: 'FL' as TirePosition,
    brand: '',
    model_name: '',
    size: '',
    dot_code: '',
    tread_depth_mm: '',
    pressure_kpa: '',
    min_tread_mm: '2.0',
    notes: '',
  })
  const [readingForm, setReadingForm] = useState({
    recorded_at: new Date().toISOString().slice(0, 10),
    odometer_km: '',
    tread_depth_mm: '',
    pressure_kpa: '',
    notes: '',
  })

  const tires = data?.tires ?? []

  const handleSave = () => {
    upsert.mutate(
      {
        vin,
        position: form.position,
        brand: form.brand || null,
        model_name: form.model_name || null,
        size: form.size || null,
        dot_code: form.dot_code || null,
        tread_depth_mm: form.tread_depth_mm ? Number(form.tread_depth_mm) : null,
        pressure_kpa: form.pressure_kpa ? Number(form.pressure_kpa) : null,
        min_tread_mm: form.min_tread_mm ? Number(form.min_tread_mm) : 2.0,
        notes: form.notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.saved', { defaultValue: 'Tire saved' }))
          setShowForm(false)
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : 'Failed to save tire')
        },
      }
    )
  }

  const handleReading = (tireId: number) => {
    if (!readingForm.tread_depth_mm) {
      toast.error(t('tireList.treadRequired', { defaultValue: 'Tread depth is required' }))
      return
    }
    addReading.mutate(
      {
        tireId,
        recorded_at: readingForm.recorded_at,
        odometer_km: readingForm.odometer_km ? Number(readingForm.odometer_km) : null,
        tread_depth_mm: Number(readingForm.tread_depth_mm),
        pressure_kpa: readingForm.pressure_kpa ? Number(readingForm.pressure_kpa) : null,
        notes: readingForm.notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.readingSaved', { defaultValue: 'Reading saved' }))
          setReadingTireId(null)
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : 'Failed to save reading')
        },
      }
    )
  }

  if (isLoading) {
    return <div className="text-text-mute">{t('common:loading', { defaultValue: 'Loading…' })}</div>
  }
  if (error) {
    return (
      <div className="rounded-panel border border-danger bg-danger/10 p-4 text-danger">
        {error instanceof Error ? error.message : 'Failed to load tires'}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Gauge className="h-5 w-5" />
          {t('tireList.title', { defaultValue: 'Tires' })}
        </h2>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowForm(true)}
          icon={Plus}
        >
          {t('tireList.add', { defaultValue: 'Add / update tire' })}
        </Button>
      </div>

      {tires.length === 0 && !showForm && (
        <EmptyState
          icon={Gauge}
          title={t('tireList.empty', { defaultValue: 'No tires tracked yet' })}
          description={t('tireList.emptyHint', {
            defaultValue: 'Add FL/FR/RL/RR (and spare) with tread depth and DOT code.',
          })}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {tires.map((tire: Tire) => (
          <Card key={tire.id} padding="sm" className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  {tire.position}
                  {tire.below_threshold && (
                    <span className="inline-flex items-center gap-1 text-xs text-danger">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {t('tireList.lowTread', { defaultValue: 'Low tread' })}
                    </span>
                  )}
                </div>
                <div className="text-sm text-text-mute">
                  {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                </div>
              </div>
              <IconButton
                icon={Trash2}
                label={t('common:delete')}
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (confirm(t('tireList.confirmDelete', { defaultValue: 'Delete this tire?' }))) {
                    remove.mutate(tire.id)
                  }
                }}
              />
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-text-mute">DOT</dt>
              <dd className="font-mono">{tire.dot_code || '—'}</dd>
              <dt className="text-text-mute">{t('tireList.tread', { defaultValue: 'Tread' })}</dt>
              <dd className="font-mono">
                {tire.tread_depth_mm != null ? `${tire.tread_depth_mm} mm` : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.pressure', { defaultValue: 'Pressure' })}</dt>
              <dd className="font-mono">
                {tire.pressure_kpa != null ? `${tire.pressure_kpa} kPa` : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.projection', { defaultValue: 'Wear estimate' })}</dt>
              <dd className="font-mono text-xs">
                {tire.projected_km_remaining != null
                  ? `~${tire.projected_km_remaining} km`
                  : '—'}
                {tire.projected_wear_date
                  ? ` · ${formatDateForDisplay(tire.projected_wear_date)}`
                  : ''}
              </dd>
            </dl>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setReadingTireId(tire.id)
                setReadingForm((f) => ({
                  ...f,
                  tread_depth_mm: tire.tread_depth_mm != null ? String(tire.tread_depth_mm) : '',
                }))
              }}
            >
              {t('tireList.addReading', { defaultValue: 'Log reading' })}
            </Button>

            {readingTireId === tire.id && (
              <div className="mt-2 space-y-2 rounded-control border border-border p-3">
                <Field id={`reading-date-${tire.id}`} label={t('common:date', { defaultValue: 'Date' })}>
                  <Input
                    type="date"
                    value={readingForm.recorded_at}
                    onChange={(e) => setReadingForm({ ...readingForm, recorded_at: e.target.value })}
                  />
                </Field>
                <Field id={`reading-tread-${tire.id}`} label="Tread (mm)">
                  <Input
                    type="number"
                    step="0.1"
                    value={readingForm.tread_depth_mm}
                    onChange={(e) =>
                      setReadingForm({ ...readingForm, tread_depth_mm: e.target.value })
                    }
                  />
                </Field>
                <Field id={`reading-odo-${tire.id}`} label="Odometer (km)">
                  <Input
                    type="number"
                    step="0.1"
                    value={readingForm.odometer_km}
                    onChange={(e) =>
                      setReadingForm({ ...readingForm, odometer_km: e.target.value })
                    }
                  />
                </Field>
                <div className="flex gap-2">
                  <Button size="sm" variant="primary" onClick={() => handleReading(tire.id)}>
                    {t('common:save', { defaultValue: 'Save' })}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setReadingTireId(null)}>
                    {t('common:cancel', { defaultValue: 'Cancel' })}
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>

      {showForm && (
        <Card padding="sm" className="space-y-3">
          <h3 className="font-semibold">{t('tireList.formTitle', { defaultValue: 'Tire details' })}</h3>
          <Field id="tire-position" label="Position">
            <Select
              value={form.position}
              onChange={(e) =>
                setForm({ ...form, position: e.target.value as TirePosition })
              }
              options={POSITIONS.map((p) => ({ value: p, label: p }))}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="tire-brand" label="Brand">
              <Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} />
            </Field>
            <Field id="tire-model" label="Model">
              <Input
                value={form.model_name}
                onChange={(e) => setForm({ ...form, model_name: e.target.value })}
              />
            </Field>
            <Field id="tire-size" label="Size">
              <Input value={form.size} onChange={(e) => setForm({ ...form, size: e.target.value })} />
            </Field>
            <Field id="tire-dot" label="DOT">
              <Input
                value={form.dot_code}
                onChange={(e) => setForm({ ...form, dot_code: e.target.value })}
              />
            </Field>
            <Field id="tire-tread" label="Tread (mm)">
              <Input
                type="number"
                step="0.1"
                value={form.tread_depth_mm}
                onChange={(e) => setForm({ ...form, tread_depth_mm: e.target.value })}
              />
            </Field>
            <Field id="tire-min" label="Min tread (mm)">
              <Input
                type="number"
                step="0.1"
                value={form.min_tread_mm}
                onChange={(e) => setForm({ ...form, min_tread_mm: e.target.value })}
              />
            </Field>
          </div>
          <div className="flex gap-2">
            <Button variant="primary" onClick={handleSave} disabled={upsert.isPending}>
              {t('common:save', { defaultValue: 'Save' })}
            </Button>
            <Button variant="ghost" onClick={() => setShowForm(false)}>
              {t('common:cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}
