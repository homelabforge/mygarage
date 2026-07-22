import { Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppVersion } from '../hooks/useAppVersion'
import OfflineBanner from './OfflineBanner'
import TopNav from './shell/TopNav'
import MobileTabBar from './shell/MobileTabBar'

export default function Layout() {
  const { t: tc } = useTranslation('common')
  const version = useAppVersion()

  return (
    <div className="min-h-screen flex flex-col pb-16 md:pb-0">
      <TopNav />

      <OfflineBanner />

      {/* Main content */}
      <main className="flex-1">
        <Outlet />
      </main>

      <MobileTabBar />

      {/* Footer - hidden on mobile */}
      <footer className="hidden md:block bg-garage-surface border-t border-garage-border py-4">
        <div className="container mx-auto px-4 text-center text-garage-text-muted text-sm">
          <p>{tc('footer', { version })}</p>
        </div>
      </footer>
    </div>
  )
}
