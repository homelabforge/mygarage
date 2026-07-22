import { Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppVersion } from '../hooks/useAppVersion'
import OfflineBanner from './OfflineBanner'
import TopNav from './shell/TopNav'
import MobileTabBar from './shell/MobileTabBar'

/**
 * App chrome. The header/nav/bottom-bar JSX moved into src/components/shell/
 * (P2). Root keeps `pb-16 md:pb-0` so the fixed MobileTabBar never overlaps
 * content on phone. OfflineBanner sits between the sticky bar and main, exactly
 * as before (digest §A4).
 */
export default function Layout() {
  const { t: tc } = useTranslation('common')
  const version = useAppVersion()

  return (
    <div className="flex min-h-screen flex-col pb-16 md:pb-0">
      <TopNav />
      <OfflineBanner />
      <main className="flex-1">
        <Outlet />
      </main>
      <MobileTabBar />
      <footer className="hidden border-t border-border bg-surface py-4 md:block">
        <div className="container mx-auto px-4 text-center text-sm text-text-mute">
          <p>{tc('footer', { version })}</p>
        </div>
      </footer>
    </div>
  )
}
