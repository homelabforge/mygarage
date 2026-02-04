/**
 * Vehicle Sharing Modal - Manage vehicle sharing with other users
 * Features:
 * - List current shares with permission dropdown and revoke button
 * - Add new share with user dropdown and permission select
 * - Only editable by owner/admin
 */

import { useState, useEffect } from 'react'
import { X, UserPlus, Trash2, Loader2, Share2, User } from 'lucide-react'
import { toast } from 'sonner'
import { familyService } from '@/services/familyService'
import type { ShareableUser, VehicleShareResponse, PermissionType } from '@/types/family'
import { formatRelationship } from '@/types/family'

interface VehicleSharingModalProps {
  isOpen: boolean
  onClose: () => void
  vin: string
  vehicleNickname: string
  onSharesUpdated?: () => void
}

export default function VehicleSharingModal({
  isOpen,
  onClose,
  vin,
  vehicleNickname,
  onSharesUpdated,
}: VehicleSharingModalProps) {
  const [loading, setLoading] = useState(true)
  const [shares, setShares] = useState<VehicleShareResponse[]>([])
  const [shareableUsers, setShareableUsers] = useState<ShareableUser[]>([])

  // Add share form
  const [showAddForm, setShowAddForm] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState<number | ''>('')
  const [selectedPermission, setSelectedPermission] = useState<PermissionType>('read')
  const [addingShare, setAddingShare] = useState(false)

  // Updating/revoking
  const [updatingShareId, setUpdatingShareId] = useState<number | null>(null)
  const [revokingShareId, setRevokingShareId] = useState<number | null>(null)

  // Load shares and shareable users
  useEffect(() => {
    if (!isOpen) return

    const loadData = async () => {
      setLoading(true)
      try {
        const [sharesData, usersData] = await Promise.all([
          familyService.getVehicleShares(vin),
          familyService.getShareableUsers(),
        ])
        setShares(sharesData.shares)
        setShareableUsers(usersData)
      } catch (err) {
        console.error('Failed to load sharing data:', err)
        toast.error('Failed to load sharing data')
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [isOpen, vin])

  // Reset form when modal closes
  useEffect(() => {
    if (!isOpen) {
      setShowAddForm(false)
      setSelectedUserId('')
      setSelectedPermission('read')
    }
  }, [isOpen])

  // Filter out users who already have a share
  const availableUsers = shareableUsers.filter(
    (user) => !shares.some((share) => share.user.id === user.id)
  )

  // Handle adding a new share
  const handleAddShare = async () => {
    if (selectedUserId === '') return

    setAddingShare(true)
    try {
      const newShare = await familyService.shareVehicle(vin, {
        user_id: selectedUserId as number,
        permission: selectedPermission,
      })
      setShares([...shares, newShare])
      setShowAddForm(false)
      setSelectedUserId('')
      setSelectedPermission('read')
      toast.success('Vehicle shared successfully')
      onSharesUpdated?.()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to share vehicle')
    } finally {
      setAddingShare(false)
    }
  }

  // Handle updating a share's permission
  const handleUpdatePermission = async (shareId: number, newPermission: PermissionType) => {
    setUpdatingShareId(shareId)
    try {
      const updated = await familyService.updateShare(shareId, { permission: newPermission })
      setShares(shares.map((s) => (s.id === shareId ? updated : s)))
      toast.success('Permission updated')
      onSharesUpdated?.()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to update permission')
    } finally {
      setUpdatingShareId(null)
    }
  }

  // Handle revoking a share
  const handleRevokeShare = async (shareId: number) => {
    setRevokingShareId(shareId)
    try {
      await familyService.revokeShare(shareId)
      setShares(shares.filter((s) => s.id !== shareId))
      toast.success('Share revoked')
      onSharesUpdated?.()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Failed to revoke share')
    } finally {
      setRevokingShareId(null)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-lg w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Share2 className="w-6 h-6 text-primary" />
            <div>
              <h2 className="text-xl font-bold text-garage-text">Share Vehicle</h2>
              <p className="text-sm text-garage-text-muted">{vehicleNickname}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
            </div>
          ) : (
            <div className="space-y-6">
              {/* Current Shares */}
              <div>
                <h3 className="text-sm font-medium text-garage-text mb-3">Shared With</h3>
                {shares.length === 0 ? (
                  <div className="text-center py-6 text-garage-text-muted border border-dashed border-garage-border rounded-lg">
                    <Share2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p>Not shared with anyone yet</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {shares.map((share) => (
                      <div
                        key={share.id}
                        className="flex items-center gap-3 p-3 rounded-lg border border-garage-border bg-garage-bg"
                      >
                        <div className="w-10 h-10 rounded-full bg-garage-border flex items-center justify-center flex-shrink-0">
                          <User className="w-5 h-5 text-garage-text-muted" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-garage-text truncate">
                            {share.user.full_name || share.user.username}
                          </p>
                          <div className="flex items-center gap-2">
                            <span className="text-sm text-garage-text-muted">
                              @{share.user.username}
                            </span>
                            {share.user.relationship && (
                              <span className="px-1.5 py-0.5 text-xs bg-info/20 text-info rounded">
                                {formatRelationship(share.user.relationship, null)}
                              </span>
                            )}
                          </div>
                        </div>
                        <select
                          value={share.permission}
                          onChange={(e) =>
                            handleUpdatePermission(share.id, e.target.value as PermissionType)
                          }
                          disabled={updatingShareId === share.id}
                          className="px-2 py-1 bg-garage-surface border border-garage-border rounded text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                        >
                          <option value="read">Read</option>
                          <option value="write">Write</option>
                        </select>
                        <button
                          onClick={() => handleRevokeShare(share.id)}
                          disabled={revokingShareId === share.id}
                          className="p-2 text-danger hover:bg-danger/20 rounded transition-colors disabled:opacity-50"
                          title="Revoke share"
                        >
                          {revokingShareId === share.id ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Trash2 className="w-4 h-4" />
                          )}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Add Share Form */}
              {showAddForm ? (
                <div className="border border-primary/30 rounded-lg p-4 bg-primary/5">
                  <h3 className="text-sm font-medium text-garage-text mb-3">Add Share</h3>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-sm text-garage-text-muted mb-1">User</label>
                      <select
                        value={selectedUserId}
                        onChange={(e) =>
                          setSelectedUserId(e.target.value === '' ? '' : parseInt(e.target.value))
                        }
                        className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                      >
                        <option value="">Select a user...</option>
                        {availableUsers.map((user) => (
                          <option key={user.id} value={user.id}>
                            {user.display_name}
                            {user.relationship ? ` (${formatRelationship(user.relationship, null)})` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-garage-text-muted mb-1">Permission</label>
                      <select
                        value={selectedPermission}
                        onChange={(e) => setSelectedPermission(e.target.value as PermissionType)}
                        className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                      >
                        <option value="read">Read - Can view vehicle and records</option>
                        <option value="write">Write - Can add records and photos</option>
                      </select>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowAddForm(false)}
                        className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleAddShare}
                        disabled={selectedUserId === '' || addingShare}
                        className="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {addingShare ? (
                          <span className="flex items-center justify-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Sharing...
                          </span>
                        ) : (
                          'Share'
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ) : availableUsers.length > 0 ? (
                <button
                  onClick={() => setShowAddForm(true)}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 border-2 border-dashed border-garage-border rounded-lg text-garage-text-muted hover:text-garage-text hover:border-primary transition-colors"
                >
                  <UserPlus className="w-5 h-5" />
                  Share with another user
                </button>
              ) : (
                <div className="text-center py-4 text-garage-text-muted text-sm">
                  All available users already have access to this vehicle.
                </div>
              )}

              {/* Permission Legend */}
              <div className="pt-4 border-t border-garage-border">
                <h4 className="text-xs font-medium text-garage-text-muted uppercase mb-2">
                  Permission Levels
                </h4>
                <div className="space-y-1 text-sm">
                  <div className="flex items-start gap-2">
                    <span className="font-medium text-garage-text">Read:</span>
                    <span className="text-garage-text-muted">
                      View vehicle details, service history, and reminders
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="font-medium text-garage-text">Write:</span>
                    <span className="text-garage-text-muted">
                      All read permissions, plus add service records, fuel logs, and photos
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
