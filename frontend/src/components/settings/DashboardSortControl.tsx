/**
 * The order the dashboard opens in, for this person. Lives in Quick Settings.
 *
 * A saved default also drops this tab's sort-menu pick, so the dashboard opens
 * on the new default rather than on a pick made over the old one.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { useDashboardSort, DASHBOARD_SORT_STORAGE_KEY } from '@/hooks/useDashboardSort'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { DASHBOARD_SORT_OPTIONS, type DashboardSort } from '@/constants/dashboardSort'
import { forgetSortPick } from '@/utils/dashboardSort'
import { Select } from '../ui'

export default function DashboardSortControl(): React.ReactElement {
  const { t } = useTranslation('settings')
  const { user } = useAuth()
  const { dashboardSort: stored } = useDashboardSort()
  const save = useSavePersonalPreference()
  // Shows the choice until the save settles.
  const [pending, setPending] = useState<DashboardSort | null>(null)
  const [saving, setSaving] = useState(false)
  const selected = pending ?? stored

  const change = async (sort: DashboardSort): Promise<void> => {
    setSaving(true)
    setPending(sort)
    try {
      await save('dashboard_sort', sort, DASHBOARD_SORT_STORAGE_KEY)
      forgetSortPick(user?.id)
      toast.success(t('dashboardSort.saved'))
    } catch {
      toast.error(t('dashboardSort.error'))
    } finally {
      // Once the save settles the stored value wins, so a later change elsewhere shows.
      setPending(null)
      setSaving(false)
    }
  }

  return (
    <div>
      <label htmlFor="quick-settings-dashboard-sort" className="ui-eyebrow mb-2 block">
        {t('dashboardSort.label')}
      </label>
      <Select
        id="quick-settings-dashboard-sort"
        value={selected}
        onChange={(e) => void change(e.target.value as DashboardSort)}
        disabled={saving}
        options={DASHBOARD_SORT_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
      />
    </div>
  )
}
