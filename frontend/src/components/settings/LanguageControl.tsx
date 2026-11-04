/**
 * The display language, for this person. It switches at once, then saves.
 * Lives in Quick Settings.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { SUPPORTED_LANGUAGES } from '@/constants/i18n'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { Select } from '../ui'

const OPTIONS = SUPPORTED_LANGUAGES.map((lang) => ({
  value: lang.code,
  label: `${lang.nativeName} (${lang.name})`,
}))

export default function LanguageControl(): React.ReactElement {
  const { t, i18n } = useTranslation('settings')
  const save = useSavePersonalPreference()
  // i18n holds the language in effect (`useLanguageSync` keeps it on the
  // account's); this shows a choice before the save lands.
  const [pending, setPending] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const selected = pending ?? i18n.resolvedLanguage ?? i18n.language

  const change = async (lang: string): Promise<void> => {
    const previous = selected
    setSaving(true)
    setPending(lang)
    try {
      // Switch first, so the drawer itself answers in the new language.
      await i18n.changeLanguage(lang)
      await save('language', lang, 'i18nextLng')
      toast.success(t('language.saved'))
    } catch {
      toast.error(t('language.error'))
      await i18n.changeLanguage(previous)
    } finally {
      // Once the save settles the stored value wins, so a later change elsewhere shows.
      setPending(null)
      setSaving(false)
    }
  }

  return (
    <div>
      <label htmlFor="quick-settings-language" className="ui-eyebrow mb-2 block">
        {t('language.label')}
      </label>
      <Select
        id="quick-settings-language"
        value={selected}
        onChange={(e) => void change(e.target.value)}
        disabled={saving}
        options={OPTIONS}
      />
    </div>
  )
}
