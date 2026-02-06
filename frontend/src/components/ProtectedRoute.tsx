import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Loader } from 'lucide-react'

export default function ProtectedRoute() {
  const { isAuthenticated, loading, authMode } = useAuth()

  // Show loading spinner while checking auth status
  if (loading) {
    return (
      <div className="min-h-screen bg-garage-bg flex items-center justify-center" role="status" aria-label="Loading">
        <div className="text-center">
          <Loader className="w-8 h-8 text-primary animate-spin mx-auto mb-4" />
          <p className="text-garage-text-muted">Loading...</p>
        </div>
      </div>
    )
  }

  // If auth mode is 'none', allow access without authentication
  if (authMode === 'none') {
    return <Outlet />
  }

  // If auth is required and user is not authenticated, redirect to login
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  // User is authenticated or auth is disabled
  return <Outlet />
}
