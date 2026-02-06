/**
 * Shared layout for authentication pages (Login, Register).
 * Provides centered card with logo header and version footer.
 */

import { Car } from 'lucide-react'
import { useAppVersion } from '../hooks/useAppVersion'

interface AuthPageLayoutProps {
  subtitle: string
  headerExtra?: React.ReactNode
  footerExtra?: React.ReactNode
  children: React.ReactNode
  className?: string
}

export default function AuthPageLayout({
  subtitle,
  headerExtra,
  footerExtra,
  children,
  className = '',
}: AuthPageLayoutProps) {
  const version = useAppVersion()

  return (
    <div className={`min-h-screen bg-garage-bg flex items-center justify-center px-4 ${className}`}>
      <div className="w-full max-w-md">
        {/* Logo and Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-primary/10 rounded-full">
              <Car className="w-12 h-12 text-primary" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-garage-text mb-2">
            My<span className="text-primary">Garage</span>
          </h1>
          <p className="text-garage-text-muted">{subtitle}</p>
          {headerExtra}
        </div>

        {/* Form Card */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-4 sm:p-6 md:p-8">
          {children}
        </div>

        {/* Footer Links */}
        {footerExtra}

        {/* Version Footer */}
        <div className="mt-8 text-center text-xs text-garage-text-muted">
          MyGarage v{version} &bull; Self-hosted vehicle maintenance tracking
        </div>
      </div>
    </div>
  )
}
