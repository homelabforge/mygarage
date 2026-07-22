import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Info, Settings } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Drawer, IconButton } from '../ui'

interface QuickSettingsDrawerProps {
  className?: string
}

const ROW =
  'ui-focus-ring ui-motion flex cursor-pointer items-center gap-2 rounded-row border border-border bg-surface-2 px-4 py-3 text-sm text-text hover:bg-surface-3'

/**
 * Shelled quick-settings drawer (§8 deferred #1 — "ship in P2 against an empty
 * inbox"). Its real content is P10. The trigger IS the right-cluster gear (a
 * Settings icon), so there is exactly one gear (I2). e2e-safe: nav.settings in
 * selectors.ts:14 is defined but never called, and every spec reaches Settings
 * via page.goto('/settings'), so the gear being a button breaks nothing.
 * Content: an About row (Jamey's decision — About lives here) + a one-tap "All
 * settings" link. Theme is a standalone toggle in RightCluster, not duplicated.
 */
export default function QuickSettingsDrawer({ className = '' }: QuickSettingsDrawerProps) {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)

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
