import { useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Battery,
  Bell,
  BellOff,
  CheckCircle,
  Download,
  ExternalLink,
  Key,
  Link2,
  Link2Off,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react'

import { IconButton, Select, Toggle } from '@/components/ui'
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
import {
  DEVICE_STATUS_LABEL,
  ECU_STATUS_LABEL,
  deviceStatusWord,
  ecuStatusWord,
} from '../integrationStatus'
import type { DeviceStatusWord } from '../integrationStatus'

/**
 * One device in a settings drawer's device table.
 *
 * Moved out of `LiveLinkSettingsModal` so every per-source drawer can list its
 * own devices. It used to show every control to every device, which was right
 * only while WiCAN was the only source. Controls are now gated by what the
 * device's source module declares (`source.capabilities`), and three WiCAN
 * wire features by kind (see `wicanWire`).
 */

const STATUS_COLOR: Readonly<Record<DeviceStatusWord, string>> = {
  online: 'text-green-500',
  offline: 'text-red-500',
  unknown: 'text-gray-500',
}

interface Props {
  device: LiveLinkDevice
  vehicles: Vehicle[]
  /** From listSources(). Undefined while loading, which shows only the
   *  controls that need no capability: the safe direction. */
  source?: SourceInfo
  showFirmware: boolean
  deviceFirmware?: DeviceFirmwareStatus
  mqttConnected?: boolean
  /** Resolves false when the server refused the change, so a control that
   *  shows its own copy of the value can put the device's back. */
  onUpdate: (deviceId: string, update: LiveLinkDeviceUpdate) => Promise<boolean>
  onDelete: (deviceId: string) => void
  onGenerateToken: (deviceId: string) => void
  onRevokeToken: (deviceId: string) => void
  onSendCommand: (deviceId: string, command: string) => void
  onSetSdConfig: (deviceId: string, config: SdConfigUpdate) => Promise<void>
  onSdBackfill: (deviceId: string) => Promise<BackfillResultResponse | null>
  onSkipFirmware: (deviceId: string, version: string) => void
  onUnskipFirmware: (deviceId: string) => void
}

export default function DeviceRow({
  device,
  vehicles,
  source,
  showFirmware,
  deviceFirmware,
  mqttConnected,
  onUpdate,
  onDelete,
  onGenerateToken,
  onRevokeToken,
  onSendCommand,
  onSetSdConfig,
  onSdBackfill,
  onSkipFirmware,
  onUnskipFirmware,
}: Props): ReactElement {
  const { t } = useTranslation('forms')
  const idBase = useId()
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(device.label ?? '')
  const [showSdConfig, setShowSdConfig] = useState(false)
  const [sdAddress, setSdAddress] = useState(device.device_address ?? '')
  const [sdEnabled, setSdEnabled] = useState(device.sd_backfill_enabled ?? false)
  const savedOdometerUnit = (device.odometer_unit as 'km' | 'mi' | null) ?? 'auto'
  const [odometerUnit, setOdometerUnit] = useState<'km' | 'mi' | 'auto'>(savedOdometerUnit)
  const [odometerParamKey, setOdometerParamKey] = useState<string>(
    device.odometer_param_key ?? '',
  )
  const [paramKeys, setParamKeys] = useState<string[]>([])
  const [savingSd, setSavingSd] = useState(false)
  const [backfilling, setBackfilling] = useState(false)

  const capabilities = new Set(source?.capabilities ?? [])
  // A declaration on a kind whose module already syncs odometer inside
  // store_telemetry is threaded nowhere and would be silently ignored. WiCAN
  // is the case today.
  const syncsOdometer = source?.syncs_odometer ?? false
  const hasOdometer = capabilities.has('odometer')
  const hasSd = capabilities.has('sd_backfill')
  const choosesOdometerParam = hasOdometer && !syncsOdometer
  // Firmware tracks, ECU status and the per-device HTTPS token are WiCAN's
  // wire protocol; no Capability names them. A Torque source's token IS its
  // upload URL, so offering to regenerate it here would break the phone.
  const wicanWire = device.kind === 'wican'
  // Torque sends TORQUE_ODOMETER in km, always; read as miles every reading
  // lands 1.609x high. The server refuses that pair both ways, so the unit is
  // locked while it's the saved key.
  const torqueKmOdometer = device.kind === 'torque' && device.odometer_param_key === 'TORQUE_ODOMETER'

  useEffect(() => {
    if (!choosesOdometerParam) return
    // Per-DEVICE keys. vehicle_telemetry_latest has no device_id column, so a
    // per-vehicle list would offer a Torque phone the co-located WiCAN's
    // A6-ODOMETER, which it never emits.
    void livelinkService
      .getDeviceParamKeys(device.device_id)
      .then(setParamKeys)
      .catch(() => setParamKeys([]))
  }, [device.device_id, choosesOdometerParam])

  const handleSaveLabel = (): void => {
    // null clears; undefined would be dropped from the JSON and keep the old label.
    void onUpdate(device.device_id, { label: label || null })
    setEditing(false)
  }

  // The select moves first so it feels instant. A refusal (409 once readings
  // depend on the unit) puts the device's own value back rather than leaving
  // the refused one on screen.
  const changeOdometerUnit = async (next: 'km' | 'mi' | 'auto'): Promise<void> => {
    setOdometerUnit(next)
    if (!(await onUpdate(device.device_id, { odometer_unit: next }))) setOdometerUnit(savedOdometerUnit)
  }

  const changeOdometerParamKey = async (next: string): Promise<void> => {
    setOdometerParamKey(next)
    if (!(await onUpdate(device.device_id, { odometer_param_key: next }))) {
      setOdometerParamKey(device.odometer_param_key ?? '')
    }
  }

  const handleSaveSdConfig = async (): Promise<void> => {
    setSavingSd(true)
    await onSetSdConfig(device.device_id, {
      device_address: sdAddress.trim() || null,
      sd_backfill_enabled: sdEnabled,
    })
    setSavingSd(false)
  }

  const handleBackfill = async (): Promise<void> => {
    setBackfilling(true)
    await onSdBackfill(device.device_id)
    setBackfilling(false)
  }

  const firmwareSkipped =
    deviceFirmware?.skipped_version != null &&
    deviceFirmware.skipped_version === deviceFirmware.latest_version

  // `online` is the server's rule, not `device_status`: a Torque phone never
  // reports a status, and a disabled device freezes at its last one.
  const status = deviceStatusWord(device)
  const ecu = ecuStatusWord(device.ecu_status)
  // Every row has the same buttons, so each name says which device it's for.
  // The tooltip keeps the short action.
  const name = device.label || device.device_id
  const forDevice = (actionKey: string): string => t('modal.livelink.actionFor', { action: t(actionKey), name })

  return (
    <>
    <tr className="border-b border-garage-border hover:bg-garage-surface/50">
      <td className="py-2 px-3">
        <div>
          {editing ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                aria-label={t('modal.livelink.labelPlaceholder')}
                placeholder={t('modal.livelink.labelPlaceholder')}
                className="px-2 py-1 bg-garage-surface border border-garage-border rounded text-xs text-garage-text w-24"
              />
              <IconButton
                icon={CheckCircle}
                label={t('modal.livelink.save')}
                size="sm"
                className="text-green-500! hover:text-green-400!"
                onClick={handleSaveLabel}
              />
            </div>
          ) : (
            <button onClick={() => setEditing(true)} className="text-garage-text hover:text-(--accent-fg) text-sm">
              {device.label || device.device_id.substring(0, 8) + '...'}
            </button>
          )}
          <p className="text-xs text-garage-text-muted font-mono">{device.device_id}</p>
        </div>
      </td>
      <td className="py-2 px-3">
        <div className="flex flex-col gap-0.5">
          <span className={`flex items-center gap-1 text-xs ${STATUS_COLOR[status]}`}>
            {status === 'online' ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {t(DEVICE_STATUS_LABEL[status].labelKey)}
          </span>
          {wicanWire && (
            <span className={`flex items-center gap-1 text-xs ${STATUS_COLOR[ecu]}`}>
              {ecu === 'online' ? <Link2 className="w-3 h-3" /> : <Link2Off className="w-3 h-3" />}
              {t('modal.livelink.ecuLabel')} {t(ECU_STATUS_LABEL[ecu].labelKey)}
            </span>
          )}
        </div>
      </td>
      <td className="py-2 px-3">
        {/* The empty option UNLINKS: the API reads vin "" as "clear the link",
            where null would mean "leave it" and never unlinked anything. */}
        <Select
          aria-label={forDevice('modal.vehicle')}
          value={device.vin ?? ''}
          onChange={(e) => void onUpdate(device.device_id, { vin: e.target.value })}
          placeholder={t('modal.livelink.unlinked')}
          options={vehicles.map((v) => ({
            value: v.vin,
            label: v.nickname || `${v.year} ${v.make} ${v.model}`,
          }))}
        />
      </td>
      {showFirmware && (
        <td className="py-2 px-3">
          <span className="text-xs text-garage-text">{device.fw_version ?? t('modal.livelink.unknown')}</span>
          {/* A skip silences exactly the release it named: a newer latest no
              longer matches skipped_version and the badge returns. */}
          {deviceFirmware?.update_available && firmwareSkipped && (
            <>
              <span className="ml-1 px-1 py-0.5 bg-garage-border/50 text-garage-text-muted text-xs rounded">
                {t('modal.livelink.skippedBadge', { version: deviceFirmware.latest_version })}
              </span>
              <IconButton
                icon={Bell}
                label={forDevice('modal.livelink.unskip')}
                title={t('modal.livelink.unskip')}
                size="sm"
                className="ml-1 hover:text-yellow-500!"
                onClick={() => onUnskipFirmware(device.device_id)}
              />
            </>
          )}
          {deviceFirmware?.update_available && !firmwareSkipped && (
            <>
              <span className="ml-1 px-1 py-0.5 bg-yellow-500/20 text-yellow-500 text-xs rounded">
                {t('modal.livelink.updateBadge')}
              </span>
              <IconButton
                icon={BellOff}
                label={forDevice('modal.livelink.skipVersion')}
                title={t('modal.livelink.skipVersion')}
                size="sm"
                className="ml-1 hover:text-yellow-500!"
                onClick={() =>
                  deviceFirmware.latest_version &&
                  onSkipFirmware(device.device_id, deviceFirmware.latest_version)
                }
              />
            </>
          )}
        </td>
      )}
      <td className="py-2 px-3 text-right">
        <div className="flex items-center justify-end gap-1">
          {capabilities.has('commands') && mqttConnected && device.online && (
            <IconButton
              icon={Battery}
              label={forDevice('modal.livelink.checkBatteryVoltage')}
              title={t('modal.livelink.checkBatteryVoltage')}
              size="sm"
              className="hover:text-green-500!"
              onClick={() => onSendCommand(device.device_id, 'get_vbatt')}
            />
          )}
          {device.sta_ip && (
            <a
              href={`http://${device.sta_ip}`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1 text-garage-text-muted hover:text-(--accent-fg)"
              title={t('modal.livelink.openDeviceUi')}
              aria-label={forDevice('modal.livelink.openDeviceUi')}
            >
              <ExternalLink aria-hidden="true" className="w-4 h-4" />
            </a>
          )}
          {wicanWire &&
            (device.has_device_token ? (
              // Yellow says the device has its own token. The ! beats the ghost
              // variant's own colour, which would otherwise win or lose by CSS order.
              <IconButton
                icon={Key}
                label={forDevice('modal.livelink.revokeDeviceToken')}
                title={t('modal.livelink.revokeDeviceToken')}
                size="sm"
                className="text-yellow-500! hover:text-yellow-400!"
                onClick={() => onRevokeToken(device.device_id)}
              />
            ) : (
              <IconButton
                icon={Key}
                label={forDevice('modal.livelink.generateDeviceToken')}
                title={t('modal.livelink.generateDeviceToken')}
                size="sm"
                className="hover:text-(--accent-fg)!"
                onClick={() => onGenerateToken(device.device_id)}
              />
            ))}
          {(hasSd || hasOdometer) && (
            <IconButton
              icon={SlidersHorizontal}
              label={forDevice('modal.livelink.deviceSettings')}
              title={t('modal.livelink.deviceSettings')}
              size="sm"
              className={showSdConfig ? 'text-(--accent-fg)!' : 'hover:text-(--accent-fg)!'}
              aria-expanded={showSdConfig}
              onClick={() => setShowSdConfig(!showSdConfig)}
            />
          )}
          <IconButton
            icon={Trash2}
            label={forDevice('modal.livelink.deleteDevice')}
            title={t('modal.livelink.deleteDevice')}
            variant="danger"
            size="sm"
            onClick={() => onDelete(device.device_id)}
          />
        </div>
      </td>
    </tr>
    {showSdConfig && (
      <tr className="bg-garage-surface/30 border-b border-garage-border">
        <td colSpan={showFirmware ? 5 : 4} className="px-4 py-3">
          <div className="flex flex-wrap items-end gap-4">
            {hasSd && (
              <>
                <div>
                  <label htmlFor={`${idBase}-address`} className="block text-xs font-medium text-garage-text mb-1">
                    {t('modal.livelink.deviceAddress')}
                  </label>
                  <input
                    id={`${idBase}-address`}
                    type="text"
                    value={sdAddress}
                    onChange={(e) => setSdAddress(e.target.value)}
                    placeholder="192.168.1.x"
                    className="px-2 py-1 bg-garage-bg border border-garage-border rounded text-xs text-garage-text w-40 focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div className="mb-1">
                  <Toggle
                    label={t('modal.livelink.autoSdBackfill')}
                    checked={sdEnabled}
                    onChange={setSdEnabled}
                  />
                </div>
              </>
            )}
            {hasOdometer && (
              <div>
                <label htmlFor={`${idBase}-odometer-unit`} className="block text-xs font-medium text-garage-text mb-1">
                  {t('modal.livelink.odometerUnit')}
                </label>
                <Select
                  id={`${idBase}-odometer-unit`}
                  value={odometerUnit}
                  onChange={(e) => void changeOdometerUnit(e.target.value as 'km' | 'mi' | 'auto')}
                  disabled={torqueKmOdometer}
                  options={[
                    { value: 'auto', label: t('modal.livelink.odometerUnitAuto') },
                    { value: 'km', label: t('modal.livelink.odometerUnitKm') },
                    { value: 'mi', label: t('modal.livelink.odometerUnitMi') },
                  ]}
                />
                {torqueKmOdometer ? (
                  <>
                    <p className="mt-1 text-[11px] text-garage-text-muted max-w-56">
                      {t('modal.livelink.odometerUnitTorqueKm')}
                    </p>
                    {savedOdometerUnit === 'mi' && (
                      <p className="mt-1 text-[11px] text-yellow-500 max-w-56 break-words">
                        {t('modal.livelink.odometerUnitTorqueMiRepair', { deviceId: device.device_id })}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="mt-1 text-[11px] text-garage-text-muted max-w-56">
                    {t('modal.livelink.odometerUnitHelp')}
                  </p>
                )}
              </div>
            )}
            {choosesOdometerParam && (
              <div>
                <label htmlFor={`${idBase}-odometer-param`} className="block text-xs font-medium text-garage-text mb-1">
                  {t('modal.livelink.odometerParam')}
                </label>
                <Select
                  id={`${idBase}-odometer-param`}
                  value={odometerParamKey}
                  onChange={(e) => void changeOdometerParamKey(e.target.value)}
                  options={[
                    { value: '', label: t('modal.livelink.odometerParamNone') },
                    ...paramKeys.map((k) => ({ value: k, label: k })),
                  ]}
                />
                <p className="mt-1 text-[11px] text-garage-text-muted max-w-56">
                  {t('modal.livelink.odometerParamHelp')}
                </p>
              </div>
            )}
            {hasSd && (
              <>
                <button
                  onClick={handleSaveSdConfig}
                  disabled={savingSd || sdAddress.trim() === ''}
                  className="flex items-center gap-1 px-3 py-1 bg-garage-surface border border-garage-border rounded text-xs text-garage-text hover:bg-garage-bg disabled:opacity-50"
                >
                  {savingSd ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                  {t('modal.livelink.save')}
                </button>
                <button
                  onClick={handleBackfill}
                  disabled={backfilling}
                  className="flex items-center gap-1 px-3 py-1 btn btn-primary rounded text-xs disabled:opacity-50"
                >
                  {backfilling ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                  {t('modal.livelink.pullSdLogsNow')}
                </button>
              </>
            )}
          </div>
        </td>
      </tr>
    )}
    </>
  )
}
