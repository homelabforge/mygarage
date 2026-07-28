import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Info, Settings } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Drawer, IconButton } from '../ui'
import { useAccent } from '../../contexts/AccentContext'
import { useAuth } from '../../contexts/AuthContext'
import { ACCENTS, ACCENT_KEYS, type AccentKey } from '../../constants/accents'
import api from '../../services/api'

interface QuickSettingsDrawerProps {
  className?: string
}

const ROW =
  'ui-focus-ring ui-motion flex cursor-pointer items-center gap-2 rounded-row border border-border bg-surface-2 px-4 py-3 text-sm text-text hover:bg-surface-3'

/**
 * Quick-settings drawer. The trigger IS the right-cluster gear (a Settings
 * icon), so there is exactly one gear (I2). e2e-safe: nav.settings in
 * selectors.ts:14 is defined but never called, and every spec reaches Settings
 * via page.goto('/settings'), so the gear being a button breaks nothing.
 *
 * Content: the Appearance accent picker (per-account; see below) + an About row
 * (Jamey's decision — About lives here) + a one-tap "All settings" link. The
 * dark/light theme is a standalone toggle in RightCluster, not duplicated here.
 */
export default function QuickSettingsDrawer({ className = '' }: QuickSettingsDrawerProps) {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  const { accent, setAccent } = useAccent()
  const { isAuthenticated, refreshUser } = useAuth()

  // Apply the accent immediately (CSS custom props + localStorage), then persist
  // it to the account so the choice follows the user across devices. Logged-out
  // / auth-none users keep the localStorage-only behavior. A failed save keeps
  // the local apply and surfaces an error — the accent still works on this device.
  const selectAccent = async (key: AccentKey): Promise<void> => {
    setAccent(key)
    if (!isAuthenticated) return
    try {
      await api.put('/auth/me', { accent_color: key })
      await refreshUser()
    } catch {
      toast.error(t('accentError'))
    }
  }

  return (
    <>
      <IconButton
        icon={Settings}
        label={t('quickSettings')}
        variant="surface"
        className={className}
        onClick={() => setOpen(true)}
      />
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('quickSettings')}
        icon={Settings}
        width="2xs"
        closeLabel={t('common:close')}
      >
        <div className="flex flex-col gap-4">
          {/* Appearance — per-account accent picker */}
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[.06em] text-text-faint">
              {t('appearance')}
            </div>
            <div className="flex flex-wrap gap-2" role="group" aria-label={t('accent')}>
              {ACCENT_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={accent === key}
                  aria-label={t(`accents.${key}`)}
                  title={t(`accents.${key}`)}
                  onClick={() => selectAccent(key)}
                  className={`ui-focus-ring ui-motion h-8 w-8 rounded-full border-2 ${
                    accent === key ? 'border-text' : 'border-border'
                  }`}
                  style={{ backgroundColor: ACCENTS[key].solid }}
                />
              ))}
            </div>
          </div>

          <Link to="/about" onClick={() => setOpen(false)} className={ROW}>
            <Info aria-hidden="true" className="h-4 w-4" />
            {t('about')}
          </Link>
          <Link to="/settings" onClick={() => setOpen(false)} className={ROW}>
            <Settings aria-hidden="true" className="h-4 w-4" />
            {t('allSettings')}
          </Link>
        </div>
      </Drawer>
    </>
  )
}
