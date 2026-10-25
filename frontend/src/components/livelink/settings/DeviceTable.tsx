import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Copy } from 'lucide-react'

import { livelinkService } from '@/services/livelinkService'
import type {
  BackfillResultResponse,
  DeviceFirmwareStatus,
  LiveLinkDevice,
  LiveLinkDeviceUpdate,
  SdConfigUpdate,
} from '@/types/livelink'
import type { SourceInfo } from '@/types/livelinkTopicMap'
import type { Vehicle } from '@/types/vehicle'
import { getErrorMessage, parseApiError } from '@/utils/httpErrorHandler'
import DeviceRow from './DeviceRow'

/**
 * A settings drawer's device list, and the per-device actions behind it.
 *
 * Moved out of `LiveLinkSettingsModal`, which owned the handlers and reloaded
 * its own device list after each one. Here the CALLER owns the data: every
 * successful mutation calls `onChanged`, and the drawer reloads what it
 * shows and bumps the card's tab strip. A drawer that also shows firmware
 * must reload that too, or a skip leaves the row's badge stale.
 */

/**
 * The server's reason for refusing an SD action, else the fallback. The SD
 * routes answer 422 for a kind with no SD card, 409 with LiveLink off and
 * 403/404 for the device, each saying which; `getErrorMessage` would swap a
 * 422's reason for a generic "could not be processed".
 */
function sdRefusal(error: unknown, fallback: string): string {
  const { status, detail } = parseApiError(error)
  return status >= 400 && status < 500 && detail ? detail : fallback
}

interface Props {
  /** Already filtered to the drawer's source. */
  devices: LiveLinkDevice[]
  vehicles: Vehicle[]
  deviceFirmware?: DeviceFirmwareStatus[]
  mqttConnected?: boolean
  onChanged: () => void
}

export default function DeviceTable({
  devices,
  vehicles,
  deviceFirmware = [],
  mqttConnected,
  onChanged,
}: Props): ReactElement {
  const { t } = useTranslation('forms')
  const [sources, setSources] = useState<Record<string, SourceInfo>>({})
  const [deviceTokenModal, setDeviceTokenModal] = useState<{
    deviceId: string
    token: string | null
  } | null>(null)

  useEffect(() => {
    // Once per table, not once per row: every row needs its kind's entry.
    // A failure leaves rows showing only the controls that need no
    // capability, which is the safe direction.
    void livelinkService
      .listSources()
      .then((list) => setSources(Object.fromEntries(list.map((s) => [s.kind, s]))))
      .catch(() => setSources({}))
  }, [])

  // Firmware is a WiCAN column. The drawers list one kind each, so a table is
  // either all WiCAN or none.
  const showFirmware = devices.some((d) => d.kind === 'wican')

  const copyToClipboard = async (text: string, label: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('modal.livelink.copiedToClipboard', { label }))
    } catch {
      toast.error(t('modal.failedToCopy'))
    }
  }

  /** False when the server refused it, so the row can put its value back. */
  const handleUpdateDevice = async (deviceId: string, update: LiveLinkDeviceUpdate): Promise<boolean> => {
    try {
      await livelinkService.updateDevice(deviceId, update)
      toast.success(t('modal.deviceUpdated'))
      onChanged()
      return true
    } catch (error) {
      console.error('Failed to update device:', error)
      // The server refuses an odometer-unit change once readings depend on it,
      // and says why and what to run. A generic failure toast would throw that
      // away and leave the setting looking merely broken.
      toast.error(getErrorMessage(error, t('modal.failedToUpdateDevice')))
      return false
    }
  }

  const handleDeleteDevice = async (deviceId: string): Promise<void> => {
    if (!confirm(t('modal.livelink.confirmDeleteDevice'))) {
      return
    }
    try {
      await livelinkService.deleteDevice(deviceId)
      toast.success(t('modal.deviceDeleted'))
      onChanged()
    } catch (error) {
      console.error('Failed to delete device:', error)
      toast.error(t('modal.failedToDeleteDevice'))
    }
  }

  const handleGenerateDeviceToken = async (deviceId: string): Promise<void> => {
    try {
      const response = await livelinkService.generateDeviceToken(deviceId)
      setDeviceTokenModal({ deviceId, token: response.token })
      onChanged()
    } catch (error) {
      console.error('Failed to generate device token:', error)
      toast.error(t('modal.failedToGenerateDeviceToken'))
    }
  }

  const handleRevokeDeviceToken = async (deviceId: string): Promise<void> => {
    if (!confirm(t('modal.livelink.confirmRevokeDeviceToken'))) {
      return
    }
    try {
      await livelinkService.revokeDeviceToken(deviceId)
      toast.success(t('modal.deviceTokenRevoked'))
      onChanged()
    } catch (error) {
      console.error('Failed to revoke device token:', error)
      toast.error(t('modal.failedToRevokeDeviceToken'))
    }
  }

  const handleSendCommand = async (deviceId: string, command: string): Promise<void> => {
    try {
      const result = await livelinkService.sendDeviceCommand(deviceId, command)
      toast.success(result.message)
    } catch (error) {
      console.error('Failed to send command:', error)
      toast.error(t('modal.failedToSendCommand'))
    }
  }

  const handleSkipFirmware = async (deviceId: string, version: string): Promise<void> => {
    try {
      await livelinkService.skipFirmwareVersion(deviceId, version)
      // The row's pill is derived from the server's skipped_version, not local
      // state, so the caller must re-read firmware status.
      onChanged()
    } catch (error) {
      console.error('Failed to skip firmware version:', error)
      toast.error(t('modal.livelink.skipFailed'))
    }
  }

  const handleUnskipFirmware = async (deviceId: string): Promise<void> => {
    try {
      await livelinkService.unskipFirmwareVersion(deviceId)
      onChanged()
    } catch (error) {
      console.error('Failed to unskip firmware version:', error)
      toast.error(t('modal.livelink.skipFailed'))
    }
  }

  const handleSetSdConfig = async (deviceId: string, config: SdConfigUpdate): Promise<void> => {
    try {
      await livelinkService.setSdConfig(deviceId, config)
      toast.success(t('modal.livelink.sdConfigSaved'))
      onChanged()
    } catch (error) {
      console.error('Failed to save SD config:', error)
      toast.error(sdRefusal(error, t('modal.livelink.failedToSaveSdConfig')))
    }
  }

  const handleSdBackfill = async (deviceId: string): Promise<BackfillResultResponse | null> => {
    try {
      const result = await livelinkService.triggerSdBackfill(deviceId)
      const summary = t('modal.livelink.backfillSummary', {
        ingested: result.rows_ingested,
        skipped: result.rows_skipped,
      })
      if (result.errors && result.errors.length > 0) {
        toast.warning(`${summary} — ${result.errors[0]}`)
      } else {
        toast.success(summary)
      }
      return result
    } catch (error) {
      console.error('Failed to trigger SD backfill:', error)
      toast.error(sdRefusal(error, t('modal.livelink.sdBackfillFailed')))
      return null
    }
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-garage-border">
              <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.device')}</th>
              <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.status')}</th>
              <th className="text-left py-2 px-3 text-garage-text">{t('modal.vehicle')}</th>
              {showFirmware && (
                <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.firmware')}</th>
              )}
              <th className="text-right py-2 px-3 text-garage-text">{t('modal.livelink.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((device) => (
              <DeviceRow
                key={device.device_id}
                device={device}
                vehicles={vehicles}
                source={sources[device.kind]}
                showFirmware={showFirmware}
                deviceFirmware={deviceFirmware.find((d) => d.device_id === device.device_id)}
                mqttConnected={mqttConnected}
                onUpdate={handleUpdateDevice}
                onDelete={(id) => void handleDeleteDevice(id)}
                onGenerateToken={(id) => void handleGenerateDeviceToken(id)}
                onRevokeToken={(id) => void handleRevokeDeviceToken(id)}
                onSendCommand={(id, command) => void handleSendCommand(id, command)}
                onSetSdConfig={handleSetSdConfig}
                onSdBackfill={handleSdBackfill}
                onSkipFirmware={(id, version) => void handleSkipFirmware(id, version)}
                onUnskipFirmware={(id) => void handleUnskipFirmware(id)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Device Token dialog, portalled to <body> so it escapes the drawer's
          root-level inert and the panel's transform, staying a centred modal
          on top of the drawer. */}
      {deviceTokenModal &&
        createPortal(
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-drawer-nested">
            <div className="bg-garage-surface rounded-lg border border-garage-border p-6 max-w-lg w-full mx-4">
              <h3 className="text-lg font-semibold text-garage-text mb-4">
                {t('modal.livelink.deviceTokenGenerated')}
              </h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-garage-text-muted mb-2">
                    {t('modal.livelink.tokenForDevice', { deviceId: deviceTokenModal.deviceId })}
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      readOnly
                      value={deviceTokenModal.token ?? ''}
                      className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-sm"
                    />
                    <button
                      onClick={() => void copyToClipboard(deviceTokenModal.token ?? '', t('modal.livelink.tokenLabel'))}
                      className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <p className="text-sm text-yellow-500">
                    <strong>{t('modal.livelink.saveTokenNowLabel')}</strong>{' '}
                    {t('modal.livelink.saveTokenNowDesc')}
                  </p>
                </div>
                <div className="flex justify-end">
                  <button onClick={() => setDeviceTokenModal(null)} className="btn btn-primary rounded-lg">
                    {t('modal.livelink.done')}
                  </button>
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
