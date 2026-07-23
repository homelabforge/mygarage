/**
 * Torque Source Modal - owner-reachable, per-vehicle Torque Pro upload
 * source registration (Task 13, R1-H6).
 *
 * Distinct from LiveLinkSettingsModal (admin-gated, global WiCAN device
 * management): this modal is scoped to a single vehicle's `vin` and is
 * launched from a button any vehicle OWNER can reach on VehicleDetail --
 * no admin rights required, and reachable before any device is linked
 * (the LiveLink primary tab stays hidden until then).
 *
 * Lists this vehicle's existing torque-kind sources, lets the owner create
 * a new one (revealing the Torque "Upload URL" + a one-time device token
 * using the copy/eye/"save now" pattern from LiveLinkSettingsModal), and
 * revoke existing sources.
 */

import { useTranslation } from 'react-i18next'
import { useState, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { Radio, Plus, Copy, Eye, EyeOff, Trash2, Loader2, AlertTriangle } from 'lucide-react'
import { Drawer } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import type { TorqueSourceResponse, TorqueSourceCreateResponse } from '@/types/livelink'
import { getActiveLocale } from '@/constants/i18n'

interface TorqueSourceModalProps {
  vin: string
  isOpen: boolean
  onClose: () => void
}

export default function TorqueSourceModal({ vin, isOpen, onClose }: TorqueSourceModalProps) {
  const { t } = useTranslation('forms')
  const [loading, setLoading] = useState(true)
  const [sources, setSources] = useState<TorqueSourceResponse[]>([])

  // Add-source form
  const [showAddForm, setShowAddForm] = useState(false)
  const [label, setLabel] = useState('')
  const [creating, setCreating] = useState(false)

  // One-time reveal of the just-created source
  const [revealed, setRevealed] = useState<TorqueSourceCreateResponse | null>(null)
  const [showToken, setShowToken] = useState(false)

  const [revokingDeviceId, setRevokingDeviceId] = useState<string | null>(null)

  const loadSources = useCallback(async (): Promise<void> => {
    setLoading(true)
    try {
      const data = await livelinkService.getTorqueSources(vin)
      setSources(data.sources ?? [])
    } catch (error) {
      console.error('Failed to load Torque sources:', error)
      toast.error(t('modal.torque.failedToLoad'))
    } finally {
      setLoading(false)
    }
  }, [vin, t])

  useEffect(() => {
    if (isOpen) {
      loadSources()
    }
  }, [isOpen, loadSources])

  // Reset transient state when the modal closes
  useEffect(() => {
    if (!isOpen) {
      setShowAddForm(false)
      setLabel('')
      setRevealed(null)
      setShowToken(false)
    }
  }, [isOpen])

  const copyToClipboard = async (text: string, fieldLabel: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${fieldLabel} copied to clipboard`)
    } catch {
      toast.error(t('modal.failedToCopy'))
    }
  }

  const handleCreate = async (): Promise<void> => {
    setCreating(true)
    try {
      const created = await livelinkService.createTorqueSource(vin, label.trim() || undefined)
      setRevealed(created)
      setShowToken(false)
      setShowAddForm(false)
      setLabel('')
      toast.success(t('modal.torque.sourceCreated'))
      await loadSources()
    } catch (error) {
      console.error('Failed to create Torque source:', error)
      toast.error(t('modal.torque.failedToCreate'))
    } finally {
      setCreating(false)
    }
  }

  const handleRevoke = async (deviceId: string): Promise<void> => {
    if (!confirm(t('modal.torque.revokeConfirm'))) {
      return
    }

    setRevokingDeviceId(deviceId)
    try {
      await livelinkService.deleteTorqueSource(vin, deviceId)
      setSources((prev) => prev.filter((s) => s.device_id !== deviceId))
      toast.success(t('modal.torque.sourceRevoked'))
    } catch (error) {
      console.error('Failed to revoke Torque source:', error)
      toast.error(t('modal.torque.failedToRevoke'))
    } finally {
      setRevokingDeviceId(null)
    }
  }

  if (!isOpen) return null

  return (
    <Drawer
      open
      onClose={onClose}
      title={t('modal.torque.title')}
      icon={Radio}
      width="md"
      closeLabel={t('common:close')}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="btn btn-secondary rounded-lg cursor-pointer"
        >
          {t('modal.torque.done')}
        </button>
      }
    >
      <p className="text-sm text-garage-text-muted -mt-1 mb-4">{t('modal.torque.description')}</p>
      <div className="space-y-6">
        {/* Metric units warning - always visible */}
        <div className="flex items-start gap-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3">
          <AlertTriangle className="w-5 h-5 flex-shrink-0 text-yellow-500 mt-0.5" />
          <p className="text-sm text-yellow-500 font-medium">{t('modal.torque.metricWarning')}</p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-primary animate-spin" />
          </div>
        ) : (
          <>
            {/* One-time reveal of the just-created source */}
            {revealed && (
              <div className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-1">
                    {t('modal.torque.urlLabel')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      readOnly
                      value={revealed.upload_url}
                      className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                    />
                    <button
                      onClick={() => copyToClipboard(revealed.upload_url, 'URL')}
                      className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-1">
                    {t('modal.torque.tokenLabel')}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type={showToken ? 'text' : 'password'}
                      readOnly
                      value={revealed.token}
                      className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                    />
                    <button
                      onClick={() => setShowToken(!showToken)}
                      className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                    >
                      {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      onClick={() => copyToClipboard(revealed.token, 'Token')}
                      className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="p-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <p className="text-xs text-yellow-500">
                    <strong>{t('modal.torque.saveTokenNow')}</strong>
                  </p>
                </div>

                <button
                  onClick={() => setRevealed(null)}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text text-sm transition-colors"
                >
                  {t('modal.torque.done')}
                </button>
              </div>
            )}

            {/* Existing sources */}
            <div>
              {sources.length === 0 ? (
                <div className="text-center py-6 text-garage-text-muted border border-dashed border-garage-border rounded-lg">
                  <Radio className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>{t('modal.torque.noSources')}</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {sources.map((source) => (
                    <div
                      key={source.device_id}
                      className="flex items-center gap-3 p-3 rounded-lg border border-garage-border bg-garage-bg"
                    >
                      <div className="w-10 h-10 rounded-full bg-garage-border flex items-center justify-center flex-shrink-0">
                        <Radio className="w-5 h-5 text-garage-text-muted" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-garage-text truncate">
                          {source.label || source.device_id}
                        </p>
                        <p className="text-xs text-garage-text-muted">
                          {source.last_seen
                            ? `${t('modal.torque.lastSeen')}: ${new Date(source.last_seen).toLocaleString(getActiveLocale())}`
                            : t('modal.torque.neverSeen')}
                        </p>
                      </div>
                      <button
                        onClick={() => handleRevoke(source.device_id)}
                        disabled={revokingDeviceId === source.device_id}
                        className="p-2 text-danger hover:bg-danger/20 rounded transition-colors disabled:opacity-50"
                        title={t('modal.torque.revoke')}
                      >
                        {revokingDeviceId === source.device_id ? (
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

            {/* Add source form */}
            {showAddForm ? (
              <div className="border border-primary/30 rounded-lg p-4 bg-primary/5">
                <h3 className="text-sm font-medium text-garage-text mb-3">{t('modal.torque.add')}</h3>
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm text-garage-text-muted mb-1">
                      {t('modal.torque.addLabel')}
                    </label>
                    <input
                      type="text"
                      value={label}
                      onChange={(e) => setLabel(e.target.value)}
                      maxLength={100}
                      placeholder={t('modal.torque.addLabelPlaceholder')}
                      className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        setShowAddForm(false)
                        setLabel('')
                      }}
                      className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
                    >
                      {t('modal.torque.cancel')}
                    </button>
                    <button
                      onClick={handleCreate}
                      disabled={creating}
                      className="flex-1 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {creating ? (
                        <span className="flex items-center justify-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          {t('modal.torque.creating')}
                        </span>
                      ) : (
                        t('modal.torque.create')
                      )}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowAddForm(true)}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 border-2 border-dashed border-garage-border rounded-lg text-garage-text-muted hover:text-garage-text hover:border-primary transition-colors"
              >
                <Plus className="w-5 h-5" />
                {t('modal.torque.add')}
              </button>
            )}
          </>
        )}
      </div>
    </Drawer>
  )
}
