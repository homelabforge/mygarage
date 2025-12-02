import { useEffect } from 'react'
import { Car, Loader, CheckCircle } from 'lucide-react'
import { setCSRFToken } from '../services/api'

export default function OIDCSuccess() {
  useEffect(() => {
    // Extract CSRF token from URL parameter (Security Enhancement v2.10.0)
    const params = new URLSearchParams(window.location.search)
    const csrfToken = params.get('csrf_token')

    if (csrfToken) {
      setCSRFToken(csrfToken)
    }

    // Cookie is already set by backend
    // Just redirect to home page after brief delay
    setTimeout(() => {
      window.location.href = '/'
    }, 1500)
  }, [])

  return (
    <div className="min-h-screen bg-garage-bg flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
          {/* Logo */}
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-primary/10 rounded-full">
              <Car className="w-12 h-12 text-primary" />
            </div>
          </div>

          {/* Success message */}
          <div className="flex justify-center mb-4">
            <div className="p-3 bg-success-500/10 rounded-full">
              <CheckCircle className="w-10 h-10 text-success-500" />
            </div>
          </div>

          <h2 className="text-2xl font-bold text-garage-text mb-2">
            Authentication Successful!
          </h2>
          <p className="text-garage-text-muted mb-4">
            Redirecting to your dashboard...
          </p>

          {/* Loading spinner */}
          <Loader className="w-6 h-6 animate-spin text-primary mx-auto" />
        </div>
      </div>
    </div>
  )
}
