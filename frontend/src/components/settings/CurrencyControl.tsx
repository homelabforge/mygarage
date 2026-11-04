/**
 * The currency costs are shown in, for this person. A change is confirmed in
 * place first, then saved. Lives in Quick Settings.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { SUPPORTED_CURRENCIES } from '@/constants/i18n'
import { useCurrencyPreference } from '@/hooks/useCurrencyPreference'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { formatCurrency } from '@/utils/formatUtils'
import { Select } from '../ui'
import InlineConfirm from './InlineConfirm'

const OPTIONS = SUPPORTED_CURRENCIES.map((curr) => ({
  value: curr.code,
  label: `${curr.code} — ${curr.name}`,
}))

export default function CurrencyControl(): React.ReactElement {
  const { t } = useTranslation('settings')
  const { currencyCode: stored, locale } = useCurrencyPreference()
  const save = useSavePersonalPreference()
  // `saved` shows a confirmed choice until the save settles; `asking` is a
  // choice awaiting confirmation.
  const [saved, setSaved] = useState<string | null>(null)
  const [asking, setAsking] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const selected = saved ?? stored

  const confirm = async (): Promise<void> => {
    if (asking === null) return
    const code = asking
    setAsking(null)
    setSaving(true)
    setSaved(code)
    try {
      await save('currency_code', code, 'currency_code')
      toast.success(t('currency.saved'))
    } catch {
      toast.error(t('currency.error'))
    } finally {
      // Once the save settles the stored value wins, so a later change elsewhere shows.
      setSaved(null)
      setSaving(false)
    }
  }

  return (
    <div>
      <label htmlFor="quick-settings-currency" className="ui-eyebrow mb-2 block">
        {t('currency.label')}
      </label>
      <Select
        id="quick-settings-currency"
        value={selected}
        onChange={(e) => setAsking(e.target.value)}
        disabled={saving}
        options={OPTIONS}
      />
      <p className="mt-1 text-xs text-garage-text-muted">
        {t('currency.preview', {
          amount: formatCurrency(1234.56, { currencyCode: selected, locale }),
        })}
      </p>
      {asking !== null && (
        <InlineConfirm
          id="quick-settings-currency-confirm"
          title={t('currency.confirmTitle')}
          confirmLabel={t('currency.confirmAction')}
          onConfirm={() => void confirm()}
          onCancel={() => setAsking(null)}
        >
          <p className="text-sm text-garage-text-muted">{t('currency.confirmMessage')}</p>
        </InlineConfirm>
      )}
    </div>
  )
}
