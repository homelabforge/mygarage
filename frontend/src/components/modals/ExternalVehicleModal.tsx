import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Drawer, Button, Field, Input, NumberInput, Textarea } from '@/components/ui'
import VINInput from '@/components/VINInput'
import MakeSelect from '@/components/MakeSelect'
import ModelSelect from '@/components/ModelSelect'
import { getActiveLocale } from '@/constants/i18n'
import type { ExternalVehicle, ExternalVehicleInput } from '@/types/externalVehicle'
import type { VINDecodeResponse } from '@/types/vin'
import { parseDecimalInput } from '@/utils/decimalInput'
import {
  createExternalVehicle,
  updateExternalVehicle,
  deleteExternalVehicle,
} from '@/services/externalVehicleService'

interface ExternalVehicleModalProps {
  isOpen: boolean
  onClose: () => void
  vehicle?: ExternalVehicle | null
  onSaved: () => void
}

const emptyForm = (): ExternalVehicleInput => ({
  nickname: '',
  vin: '',
  year: null,
  make: '',
  model: '',
  vehicle_type: '',
  contact_name: '',
  contact_phone: '',
  notes: '',
})

export default function ExternalVehicleModal({
  isOpen,
  onClose,
  vehicle,
  onSaved,
}: ExternalVehicleModalProps) {
  const { t } = useTranslation('vehicles')
  const [form, setForm] = useState<ExternalVehicleInput>(emptyForm())
  const [yearText, setYearText] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // Did the person name it? A decode rewrites a nickname it wrote itself (a
  // picked AutoRef version after the make-only agreement), never a typed one.
  const nicknameTyped = useRef(false)

  useEffect(() => {
    if (!isOpen) return
    nicknameTyped.current = Boolean(vehicle)
    if (vehicle) {
      setForm({
        nickname: vehicle.nickname,
        vin: vehicle.vin ?? '',
        year: vehicle.year,
        make: vehicle.make ?? '',
        model: vehicle.model ?? '',
        vehicle_type: vehicle.vehicle_type ?? '',
        contact_name: vehicle.contact_name ?? '',
        contact_phone: vehicle.contact_phone ?? '',
        notes: vehicle.notes ?? '',
      })
      setYearText(vehicle.year != null ? String(vehicle.year) : '')
    } else {
      setForm(emptyForm())
      setYearText('')
    }
  }, [isOpen, vehicle])

  const title = vehicle
    ? t('externalVehicles.editTitle')
    : t('externalVehicles.addReferenceTitle')

  const setField = <K extends keyof ExternalVehicleInput>(key: K, value: ExternalVehicleInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  // Built from prev: the decode can land after the person kept typing.
  const handleVinDecode = (data: VINDecodeResponse) => {
    setForm((prev) => {
      const year = data.year ?? prev.year ?? null
      const make = data.make || prev.make || ''
      const model = data.model || prev.model || ''
      const nickname = nicknameTyped.current && prev.nickname?.trim()
        ? prev.nickname
        : `${year || ''} ${make} ${model}`.trim()
      return { ...prev, year, make, model, nickname }
    })
    if (data.year != null) setYearText(String(data.year))
  }

  const parseYear = (): number | null | 'invalid' => {
    const result = parseDecimalInput(yearText, getActiveLocale())
    if (result.kind === 'empty') return null
    if (result.kind === 'invalid') return 'invalid'
    if (!Number.isInteger(result.value)) return 'invalid'
    if (result.value < 1900 || result.value > 2100) return 'invalid'
    return result.value
  }

  const handleSave = async () => {
    if (!form.nickname.trim()) {
      toast.error(t('externalVehicles.nicknameRequired'))
      return
    }
    const year = parseYear()
    if (year === 'invalid') {
      toast.error(t('common:validation.vehicle.yearInvalid'))
      return
    }
    setSaving(true)
    try {
      const vinRaw = (form.vin ?? '').trim().toUpperCase()
      const payload: ExternalVehicleInput = {
        ...form,
        nickname: form.nickname.trim(),
        vin: vinRaw || null,
        make: form.make?.trim() || null,
        model: form.model?.trim() || null,
        vehicle_type: form.vehicle_type?.trim() || null,
        contact_name: form.contact_name?.trim() || null,
        contact_phone: form.contact_phone?.trim() || null,
        notes: form.notes?.trim() || null,
        year,
      }
      if (vehicle) {
        await updateExternalVehicle(vehicle.id, payload)
        toast.success(t('externalVehicles.updated'))
      } else {
        await createExternalVehicle(payload)
        toast.success(t('externalVehicles.created'))
      }
      onSaved()
      onClose()
    } catch {
      toast.error(t('externalVehicles.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!vehicle) return
    if (!window.confirm(t('externalVehicles.confirmDelete'))) return
    setDeleting(true)
    try {
      await deleteExternalVehicle(vehicle.id)
      toast.success(t('externalVehicles.deleted'))
      onSaved()
      onClose()
    } catch {
      toast.error(t('externalVehicles.deleteError'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Drawer open={isOpen} onClose={onClose} title={title} width="md">
      <div className="space-y-4 p-4">
        <Field id="ext-nickname" label={t('externalVehicles.nickname')} required>
          <Input
            id="ext-nickname"
            value={form.nickname}
            onChange={(e) => {
              nicknameTyped.current = true
              setField('nickname', e.target.value)
            }}
            placeholder={t('externalVehicles.nicknamePlaceholder')}
          />
        </Field>
        <Field id="ext-vin" label={t('externalVehicles.vin')}>
          <VINInput
            value={form.vin ?? ''}
            onChange={(vin) => setField('vin', vin)}
            onDecode={handleVinDecode}
            checkDuplicate={false}
          />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field id="ext-year" label={t('externalVehicles.year')}>
            <NumberInput
              id="ext-year"
              value={yearText}
              onChange={(e) => setYearText(e.target.value)}
            />
          </Field>
          <Field id="ext-make" label={t('externalVehicles.make')}>
            <MakeSelect
              id="ext-make"
              value={form.make ?? ''}
              onChange={(next) => setField('make', next)}
            />
          </Field>
          <Field id="ext-model" label={t('externalVehicles.model')}>
            <ModelSelect
              id="ext-model"
              make={form.make}
              value={form.model ?? ''}
              onChange={(next) => setField('model', next)}
            />
          </Field>
        </div>
        <Field id="ext-contact-name" label={t('externalVehicles.contactName')}>
          <Input
            id="ext-contact-name"
            value={form.contact_name ?? ''}
            onChange={(e) => setField('contact_name', e.target.value)}
          />
        </Field>
        <Field id="ext-contact-phone" label={t('externalVehicles.contactPhone')}>
          <Input
            id="ext-contact-phone"
            value={form.contact_phone ?? ''}
            onChange={(e) => setField('contact_phone', e.target.value)}
          />
        </Field>
        <Field id="ext-notes" label={t('externalVehicles.notes')}>
          <Textarea
            id="ext-notes"
            value={form.notes ?? ''}
            onChange={(e) => setField('notes', e.target.value)}
            rows={4}
          />
        </Field>

        <div className="flex flex-wrap justify-between gap-2 pt-2">
          {vehicle ? (
            <Button variant="danger" onClick={handleDelete} disabled={deleting || saving}>
              {t('externalVehicles.delete')}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t('common:cancel')}
            </Button>
            <Button variant="primary" onClick={handleSave} disabled={saving}>
              {saving ? t('externalVehicles.saving') : t('externalVehicles.save')}
            </Button>
          </div>
        </div>
      </div>
    </Drawer>
  )
}
