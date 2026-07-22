import { useTranslation } from 'react-i18next'
import { DESKTOP_NAV_ITEMS } from './navItems'
import NavSearch from './NavSearch'
import TopNavLink from './TopNavLink'

interface HamburgerPanelProps {
  onNavigate: () => void
}

/**
 * The 768-899px collapse panel (prototype dc.html:112-123). Not a side drawer —
 * an inline panel pushed below the sticky bar, full nav-width, with the search
 * field re-shown at the top and the six desktop-label links stacked. Rendered
 * only when menuOpen (TopNav), so the closed DOM stays clean and
 * Layout.supplies.test.tsx keeps counting 2 supplies links, not 3.
 *
 * I1 — CSS band guard `hidden md:max-nav:block`: there is no width observer to
 * auto-close menuOpen, so opening the panel at 800px and resizing past 900 (or
 * below 768) would otherwise show two nav affordances. The guard keeps the
 * panel display:none outside 768-899 even while menuOpen is true. `md:max-nav:`
 * (768 AND <900), NOT `nav:hidden` alone — the latter leaves the <768 hole open.
 */
export default function HamburgerPanel({ onNavigate }: HamburgerPanelProps) {
  const { t } = useTranslation('nav')
  return (
    <div className="hidden border-t border-hair bg-(--color-nav) px-[clamp(16px,3vw,30px)] pb-3.5 pt-2 md:max-nav:block">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-0.5">
        <NavSearch placeholder={t('searchPlaceholder')} className="my-1.5 w-full" />
        {DESKTOP_NAV_ITEMS.map((item) => (
          <TopNavLink
            key={item.to}
            to={item.to}
            label={t(item.labelKey)}
            variant="stacked"
            onNavigate={onNavigate}
          />
        ))}
      </div>
    </div>
  )
}
