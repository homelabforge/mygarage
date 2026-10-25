/**
 * How an integrations tab's status reads, shared by the card's tab strip and
 * the per-source settings drawers.
 *
 * Moved out of LiveLinkIntegrationsCard so a drawer states a tab's status in
 * the same words the card does, from the same table.
 */

/** Green, yellow, red, and nothing else: the operator ruled out a grey
 *  "unconfigured" state, so not-set-up reads as red. An unknown status also
 *  reads as red, never green, matching `derive_broker_status`. */
export const DOT_TONE: Record<string, 'success' | 'warning' | 'danger'> = {
  ok: 'success',
  attention: 'warning',
  off: 'danger',
}

/** Written as literal keys so `validate-i18n-usage` can see them. A computed
 *  key would be invisible to the scanner and could ship as a raw string. */
export const STATUS_KEY: Record<string, string> = {
  receiving: 'integrations.statusReceiving',
  firmware_update: 'integrations.statusFirmwareUpdate',
  not_linked: 'integrations.statusNotLinked',
  no_data: 'integrations.statusNoData',
  broker_down: 'integrations.statusBrokerDown',
  disabled: 'integrations.statusDisabled',
  not_configured: 'integrations.statusNotConfigured',
}

/** One status in words. `labelKey` is a field name `validate-i18n-usage`
 *  checks, so a key missing from English fails the gate instead of shipping
 *  raw. Namespace-qualified, since each table is read from more than one. */
interface StatusLabel {
  readonly labelKey: string
}

/** A device's status line: online, offline, or never heard from. */
export type DeviceStatusWord = 'online' | 'offline' | 'unknown'

export const DEVICE_STATUS_LABEL: Readonly<Record<DeviceStatusWord, StatusLabel>> = {
  online: { labelKey: 'forms:modal.livelink.deviceStatus.online' },
  offline: { labelKey: 'forms:modal.livelink.deviceStatus.offline' },
  unknown: { labelKey: 'forms:modal.livelink.deviceStatus.unknown' },
}

/** The ECU line under a WiCAN's status. */
export const ECU_STATUS_LABEL: Readonly<Record<DeviceStatusWord, StatusLabel>> = {
  online: { labelKey: 'forms:modal.livelink.ecuStatus.online' },
  offline: { labelKey: 'forms:modal.livelink.ecuStatus.offline' },
  unknown: { labelKey: 'forms:modal.livelink.ecuStatus.unknown' },
}

/**
 * Which word a device's status line reads.
 *
 * `online` is the server's call (the same rule the card's dots use), so a
 * Torque phone that never reports a status still reads online while it
 * uploads. Not online and never seen is "no status yet": calling a device
 * that hasn't sent anything offline would say it stopped.
 */
export function deviceStatusWord(device: {
  online: boolean
  device_status: string
  last_seen: string | null
}): DeviceStatusWord {
  if (device.online) return 'online'
  if (device.device_status === 'unknown' && !device.last_seen) return 'unknown'
  return 'offline'
}

/** The ECU status as a word this table has, anything else reading unknown. */
export function ecuStatusWord(ecuStatus: string): DeviceStatusWord {
  return ecuStatus === 'online' || ecuStatus === 'offline' ? ecuStatus : 'unknown'
}

/** The broker's connection state in the Mosquitto drawer. `disconnected` is
 *  what the subscriber reports before its first connect and after a stop. */
export const BROKER_STATUS_LABEL: Readonly<Record<string, StatusLabel>> = {
  connected: { labelKey: 'settings:integrations.brokerStatus.connected' },
  connecting: { labelKey: 'settings:integrations.brokerStatus.connecting' },
  disabled: { labelKey: 'settings:integrations.brokerStatus.disabled' },
  disconnected: { labelKey: 'settings:integrations.brokerStatus.disconnected' },
  error: { labelKey: 'settings:integrations.brokerStatus.error' },
  stopped: { labelKey: 'settings:integrations.brokerStatus.stopped' },
}

/** For a state the table above doesn't know yet. */
export const BROKER_STATUS_FALLBACK: StatusLabel = {
  labelKey: 'settings:integrations.brokerStatus.unknown',
}
