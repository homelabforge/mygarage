import { useState } from 'react'
import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Ellipsis } from 'lucide-react'
import { Drawer } from '../ui'
import { MOBILE_MORE_ITEMS, MOBILE_NAV_ITEMS } from './navItems'

// Every slot gets an equal share of the row and can shrink past its label,
// which truncates. The DOM text stays whole, so the accessible name does too.
const SLOT = 'flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center rounded-row px-0.5 py-2 transition-colors'
const ACTIVE = 'text-(--accent-fg) bg-(--accent-soft)'
const IDLE = 'text-text-mute hover:text-text'
const LABEL = 'mt-1 w-full truncate text-center text-xs'

const ROW =
  'ui-focus-ring ui-motion flex cursor-pointer items-center gap-2 rounded-row border border-border px-4 py-3 text-sm'

/**
 * The phone bottom bar (`md:hidden`): four tabs plus More, which opens a
 * drawer with the rest (D1). Pads for the home indicator; Layout and
 * --toast-lift add the same inset. QuickEntry redirect lives in App.tsx.
 */
export default function MobileTabBar() {
  const { t } = useTranslation('nav')
  const { pathname } = useLocation()
  const [moreOpen, setMoreOpen] = useState(false)
  const onMoreRoute = MOBILE_MORE_ITEMS.some((item) => matchPath({ path: item.to, end: false }, pathname))

  return (
    <>
      <nav data-tab-bar className="fixed bottom-0 left-0 right-0 z-nav border-t border-hair bg-(--color-nav) pb-safe-bottom backdrop-blur-[12px] md:hidden">
        <div className="flex h-16 items-center gap-1 px-2">
          {MOBILE_NAV_ITEMS.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) => `${SLOT} ${isActive ? ACTIVE : IDLE}`}
              >
                <Icon aria-hidden="true" className="h-5 w-5 shrink-0" />
                <span className={LABEL}>{t(item.labelKey)}</span>
              </NavLink>
            )
          })}
          <button
            type="button"
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen(true)}
            className={`${SLOT} ${onMoreRoute ? ACTIVE : IDLE}`}
          >
            <Ellipsis aria-hidden="true" className="h-5 w-5 shrink-0" />
            <span className={LABEL}>{t('more')}</span>
          </button>
        </div>
      </nav>
      <Drawer
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title={t('more')}
        icon={Ellipsis}
        width="2xs"
        closeLabel={t('common:close')}
      >
        <div className="flex flex-col gap-2">
          {MOBILE_MORE_ITEMS.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMoreOpen(false)}
                className={({ isActive }) => `${ROW} ${isActive ? `${ACTIVE} border-transparent` : 'bg-surface-2 text-text hover:bg-surface-3'}`}
              >
                <Icon aria-hidden="true" className="h-4 w-4" />
                {t(item.labelKey)}
              </NavLink>
            )
          })}
        </div>
      </Drawer>
    </>
  )
}
