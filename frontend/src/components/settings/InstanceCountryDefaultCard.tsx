/**
 * The instance-wide default country, as an admin control on the System tab.
 *
 * Last rung of the country precedence (`useResolvedCountry`): a vehicle's own
 * registration country, then each person's country, then this. It drives
 * national defaults only (inspection cadence, fuel pump names, tax types) and
 * never hides a feature. "Not set" clears the row.
 *
 * Same mechanics as `InstanceUnitDefaultsCard`: gated on `useCanManageInstance`
 * (not `isAdmin`, which is empty in auth_mode=none), hidden until
 * `/settings/public` has answered once, written through `POST /settings/batch`
 * (which upserts a deleted row), and followed by `refreshUser` so every mounted
 * consumer repaints from the republished payload.
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { countryOptions } from '@/constants/countries'
import { useAuth } from '@/contexts/AuthContext'
import { useCanManageInstance } from '@/hooks/useCanManageInstance'
import { useDateLocale } from '@/hooks/useDateLocale'
import api from '@/services/api'
import { DEFAULT_COUNTRY_KEY } from '@/utils/publicCountryDefault'
import { Select } from '../ui'

export default function InstanceCountryDefaultCard(): React.ReactElement | null {
  const { t } = useTranslation('settings')
  const locale = useDateLocale()
  const { defaultCountry, publicSettingsLoaded, refreshUser } = useAuth()
  const canManageInstance = useCanManageInstance()
  const [pending, setPending] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const options = useMemo(
    () => [{ value: '', label: t('country.none') }, ...countryOptions(locale)],
    [locale, t]
  )

  if (!canManageInstance) return null
  if (!publicSettingsLoaded) return null

  const selected = pending ?? defaultCountry ?? ''

  const apply = async (code: string): Promise<void> => {
    setSaving(true)
    setPending(code)
    try {
      await api.post('/settings/batch', { settings: { [DEFAULT_COUNTRY_KEY]: code } })
      await refreshUser()
      toast.success(t('systemConfig.defaultCountrySaved'))
    } catch {
      toast.error(t('systemConfig.defaultCountryError'))
    } finally {
      setPending(null)
      setSaving(false)
    }
  }

  return (
    <section aria-label={t('systemConfig.defaultCountry')}>
      <label
        htmlFor="instance-default-country"
        className="block text-sm font-medium text-garage-text mb-3"
      >
        {t('systemConfig.defaultCountry')}
      </label>
      <Select
        id="instance-default-country"
        value={selected}
        onChange={(e) => void apply(e.target.value)}
        disabled={saving}
        options={options}
      />
      <p className="mt-1 text-xs text-garage-text-muted">{t('systemConfig.defaultCountryDesc')}</p>
    </section>
  )
}
