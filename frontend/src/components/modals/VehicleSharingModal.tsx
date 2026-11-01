/**
 * Vehicle Sharing Modal - Manage vehicle sharing with other users
 * Features:
 * - List current shares with permission dropdown and revoke button
 * - Add new share with user dropdown and permission select
 * - Only editable by owner/admin
 */

import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { UserPlus, Trash2, Loader2, Share2, User } from 'lucide-react'
import { toast } from 'sonner'
import { Drawer, Select } from '@/components/ui'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
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
  const { t } = useTranslation('forms')
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
        toast.error(t('modal.failedToLoadSharingData'))
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [isOpen, vin, t])

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
      toast.success(t('modal.vehicleShared'))
      onSharesUpdated?.()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('modal.shareVehicleAction')))
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
      toast.success(t('modal.permissionUpdated'))
      onSharesUpdated?.()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('modal.updatePermissionAction')))
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
      toast.success(t('modal.shareRevoked'))
      onSharesUpdated?.()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('modal.revokeShareAction')))
    } finally {
      setRevokingShareId(null)
    }
  }

  if (!isOpen) return null

  return (
    <Drawer
      open
      onClose={onClose}
      title={t('modal.shareVehicle')}
      icon={Share2}
      width="md"
      closeLabel={t('common:close')}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="btn btn-secondary rounded-lg cursor-pointer"
        >
          {t('vehicleSharingModal.done')}
        </button>
      }
    >
      <p className="text-sm text-garage-text-muted -mt-1 mb-4">{vehicleNickname}</p>
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Current Shares */}
          <div>
            <h3 className="text-sm font-medium text-garage-text mb-3">{t('modal.sharedWith')}</h3>
            {shares.length === 0 ? (
              <div className="text-center py-6 text-garage-text-muted border border-dashed border-garage-border rounded-lg">
                <Share2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p>{t('modal.notSharedYet')}</p>
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
                            {formatRelationship(share.user.relationship, null, t)}
                          </span>
                        )}
                      </div>
                    </div>
                    <Select
                      value={share.permission}
                      onChange={(e) =>
                        handleUpdatePermission(share.id, e.target.value as PermissionType)
                      }
                      disabled={updatingShareId === share.id}
                      options={[
                        { value: 'read', label: t('modal.read') },
                        { value: 'write', label: t('modal.write') },
                      ]}
                    />
                    <button
                      onClick={() => handleRevokeShare(share.id)}
                      disabled={revokingShareId === share.id}
                      className="p-2 text-danger hover:bg-danger/20 rounded transition-colors disabled:opacity-50"
                      title={t('vehicleSharingModal.revokeShare')}
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
              <h3 className="text-sm font-medium text-garage-text mb-3">{t('modal.addShare')}</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-garage-text-muted mb-1">{t('common:user')}</label>
                  <Select
                    value={selectedUserId}
                    onChange={(e) =>
                      setSelectedUserId(e.target.value === '' ? '' : parseInt(e.target.value))
                    }
                    placeholder={t('modal.selectUser')}
                    options={availableUsers.map((user) => ({
                      value: String(user.id),
                      label: `${user.display_name}${user.relationship ? ` (${formatRelationship(user.relationship, null, t)})` : ''}`,
                    }))}
                  />
                </div>
                <div>
                  <label className="block text-sm text-garage-text-muted mb-1">{t('modal.permission')}</label>
                  <Select
                    value={selectedPermission}
                    onChange={(e) => setSelectedPermission(e.target.value as PermissionType)}
                    options={[
                      { value: 'read', label: t('modal.readDescription') },
                      { value: 'write', label: t('modal.writeDescription') },
                    ]}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowAddForm(false)}
                    className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
                  >
                    {t('vehicleSharingModal.cancel')}
                  </button>
                  <button
                    onClick={handleAddShare}
                    disabled={selectedUserId === '' || addingShare}
                    className="flex-1 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {addingShare ? (
                      <span className="flex items-center justify-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        {t('modal.sharing')}
                      </span>
                    ) : (
                      t('modal.share')
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
              {t('modal.shareWithAnother')}
            </button>
          ) : (
            <div className="text-center py-4 text-garage-text-muted text-sm">
              {t('modal.allUsersHaveAccess')}
            </div>
          )}

          {/* Permission Legend */}
          <div className="pt-4 border-t border-garage-border">
            <h4 className="text-xs font-medium text-garage-text-muted uppercase mb-2">
              {t('modal.permissionLevels')}
            </h4>
            <div className="space-y-1 text-sm">
              <div className="flex items-start gap-2">
                <span className="font-medium text-garage-text">{t('modal.read')}:</span>
                <span className="text-garage-text-muted">
                  {t('modal.readPermDescription')}
                </span>
              </div>
              <div className="flex items-start gap-2">
                <span className="font-medium text-garage-text">{t('modal.write')}:</span>
                <span className="text-garage-text-muted">
                  {t('modal.writePermDescription')}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </Drawer>
  )
}
