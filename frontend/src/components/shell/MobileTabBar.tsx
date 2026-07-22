import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { MOBILE_NAV_ITEMS } from './navItems'

/**
 * The mobile bottom tab bar, extracted from Layout.tsx (digest §A2) and
 * retokenized (D2): active moves from `text-primary-500 bg-primary-500/10` to
 * the accent tokens `text-(--accent-fg) bg-(--accent-soft)`; surfaces move to
 * the nav token + hairline. Seven links, mobile labels, `md:hidden`, unchanged
 * routes. QuickEntry redirect is unaffected (it lives in App.tsx, digest §A2).
 */
export default function MobileTabBar() {
  const { t } = useTranslation('nav')
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-nav border-t border-hair bg-(--color-nav) backdrop-blur-[12px] md:hidden">
      <div className="flex h-16 items-center justify-around px-2">
        {MOBILE_NAV_ITEMS.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex min-w-[56px] cursor-pointer flex-col items-center justify-center rounded-row px-3 py-3 transition-colors ${
                  isActive
                    ? 'text-(--accent-fg) bg-(--accent-soft)'
                    : 'text-text-mute hover:text-text'
                }`
              }
            >
              <Icon aria-hidden="true" className="h-5 w-5" />
              <span className="mt-1 text-xs">{t(item.labelKey)}</span>
            </NavLink>
          )
        })}
      </div>
    </nav>
  )
}
