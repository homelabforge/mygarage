/**
 * Family Dashboard Page - Admin view of family vehicles and reminders
 */

import { useState, useEffect, useCallback } from 'react'
import { Users, Car, AlertTriangle, Bell, Settings, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { familyService } from '@/services/familyService'
import type { FamilyDashboardResponse } from '@/types/family'
import FamilyMemberCard from '@/components/FamilyMemberCard'
import FamilyDashboardManageModal from '@/components/modals/FamilyDashboardManageModal'
import { useAuth } from '@/contexts/AuthContext'
import { Navigate } from 'react-router-dom'

export default function FamilyDashboard() {
  const { isAdmin } = useAuth()
  const [loading, setLoading] = useState(true)
  const [dashboard, setDashboard] = useState<FamilyDashboardResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showManageModal, setShowManageModal] = useState(false)

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await familyService.getFamilyDashboard()
      setDashboard(data)
    } catch (err) {
      console.error('Failed to load family dashboard:', err)
      setError('Failed to load family dashboard')
      toast.error('Failed to load family dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  // Redirect non-admins
  if (!isAdmin) {
    return <Navigate to="/" replace />
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-danger/10 border border-danger/30 rounded-lg p-6 text-center">
          <AlertTriangle className="w-12 h-12 text-danger mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-garage-text mb-2">Error</h2>
          <p className="text-garage-text-muted">{error}</p>
        </div>
      </div>
    )
  }

  if (!dashboard) {
    return null
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Users className="w-8 h-8 text-primary" />
          <div>
            <h1 className="text-2xl font-bold text-garage-text">Family Dashboard</h1>
            <p className="text-garage-text-muted">Overview of family vehicles and maintenance</p>
          </div>
        </div>
        <button
          onClick={() => setShowManageModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
        >
          <Settings className="w-4 h-4" />
          <span className="hidden sm:inline">Manage Members</span>
        </button>
      </div>

      {/* Manage Members Modal */}
      <FamilyDashboardManageModal
        isOpen={showManageModal}
        onClose={() => setShowManageModal(false)}
        onUpdate={loadDashboard}
      />

      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary/20 rounded-lg">
              <Users className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-2xl font-bold text-garage-text">{dashboard.total_members}</p>
              <p className="text-sm text-garage-text-muted">Members</p>
            </div>
          </div>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-info/20 rounded-lg">
              <Car className="w-5 h-5 text-info" />
            </div>
            <div>
              <p className="text-2xl font-bold text-garage-text">{dashboard.total_vehicles}</p>
              <p className="text-sm text-garage-text-muted">Vehicles</p>
            </div>
          </div>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-warning/20 rounded-lg">
              <Bell className="w-5 h-5 text-warning" />
            </div>
            <div>
              <p className="text-2xl font-bold text-garage-text">{dashboard.total_upcoming_reminders}</p>
              <p className="text-sm text-garage-text-muted">Upcoming</p>
            </div>
          </div>
        </div>

        <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-danger/20 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-danger" />
            </div>
            <div>
              <p className="text-2xl font-bold text-garage-text">{dashboard.total_overdue_reminders}</p>
              <p className="text-sm text-garage-text-muted">Overdue</p>
            </div>
          </div>
        </div>
      </div>

      {/* Member Cards */}
      {dashboard.members.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-12 text-center">
          <Users className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
          <h2 className="text-xl font-semibold text-garage-text mb-2">No Family Members</h2>
          <p className="text-garage-text-muted max-w-md mx-auto">
            Add users to the family dashboard from the User Management settings to see their vehicles here.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {dashboard.members.map((member, index) => (
            <FamilyMemberCard
              key={member.id}
              member={member}
              defaultExpanded={index === 0}
            />
          ))}
        </div>
      )}
    </div>
  )
}
