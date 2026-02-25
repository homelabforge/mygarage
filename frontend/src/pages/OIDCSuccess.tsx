import { useEffect } from 'react'
import { Car, Loader, CheckCircle } from 'lucide-react'
import api, { setCSRFToken } from '../services/api'
import { resolvePostLoginRoute } from '../utils/postLoginRedirect'

export default function OIDCSuccess() {
  useEffect(() => {
    const redirect = async () => {
      // Extract CSRF token from URL parameter (Security Enhancement v2.10.0)
      const params = new URLSearchParams(window.location.search)
      const csrfToken = params.get('csrf_token')

      if (csrfToken) {
        setCSRFToken(csrfToken)
      }

      // Cookie is already set by backend — fetch user to determine redirect target.
      // Retry once if cookie hasn't propagated yet (same pattern as AuthContext login).
      let user: { mobile_quick_entry_enabled?: boolean } = {}
      try {
        const response = await api.get('/auth/me')
        user = response.data
      } catch {
        await new Promise(resolve => setTimeout(resolve, 50))
        try {
          const response = await api.get('/auth/me')
          user = response.data
        } catch {
          // If still failing, fall back to dashboard
        }
      }

      // Full-page navigate (not React Router) to ensure the JWT cookie is
      // processed before the destination page loads.
      window.location.href = resolvePostLoginRoute(user)
    }

    // Brief delay lets the browser process the Set-Cookie before we fetch /auth/me
    setTimeout(() => void redirect(), 300)
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
            Redirecting...
          </p>

          {/* Loading spinner */}
          <Loader className="w-6 h-6 animate-spin text-primary mx-auto" />
        </div>
      </div>
    </div>
  )
}
