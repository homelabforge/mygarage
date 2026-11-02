/**
 * This person's country, in Quick Settings. It is the second rung of the
 * country precedence (a vehicle's own registration country wins, the
 * instance default loses) and drives national defaults: the technical
 * inspection cadence, the fuel pump names, the tax types. It never hides a
 * feature. "Not set" clears it.
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { countryOptions } from '@/constants/countries'
import { useDateLocale } from '@/hooks/useDateLocale'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { COUNTRY_STORAGE_KEY, useCountryPreference } from '@/hooks/useResolvedCountry'
import { Select } from '../ui'

export default function CountryControl(): React.ReactElement {
  const { t } = useTranslation('settings')
  const locale = useDateLocale()
  const stored = useCountryPreference()
  const save = useSavePersonalPreference()
  // The chosen code shows at once; a failed save puts the stored one back.
  const [saved, setSaved] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const selected = saved ?? stored ?? ''

  const options = useMemo(
    () => [{ value: '', label: t('country.none') }, ...countryOptions(locale)],
    [locale, t]
  )

  const choose = async (code: string): Promise<void> => {
    setSaving(true)
    setSaved(code)
    try {
      await save('country', code, COUNTRY_STORAGE_KEY)
      toast.success(t('country.saved'))
    } catch {
      toast.error(t('country.error'))
      setSaved(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <label htmlFor="quick-settings-country" className="ui-eyebrow mb-2 block">
        {t('country.label')}
      </label>
      <Select
        id="quick-settings-country"
        value={selected}
        onChange={(e) => void choose(e.target.value)}
        disabled={saving}
        options={options}
      />
      <p className="mt-1 text-xs text-garage-text-muted">{t('country.description')}</p>
    </div>
  )
}
