import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { IntegrationTab } from '@/types/livelink'

const getMQTTSettings = vi.fn()
const getMQTTStatus = vi.fn()
const updateMQTTSettings = vi.fn()
const restartMQTTSubscriber = vi.fn()
const testMQTTConnection = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getMQTTSettings: () => getMQTTSettings(),
    getMQTTStatus: () => getMQTTStatus(),
    updateMQTTSettings: (u: unknown) => updateMQTTSettings(u),
    restartMQTTSubscriber: () => restartMQTTSubscriber(),
    testMQTTConnection: () => testMQTTConnection(),
    discoverTopics: () => Promise.resolve([]),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import MosquittoSettingsDrawer from '../MosquittoSettingsDrawer'

const SETTINGS = {
  enabled: true,
  broker_host: '10.10.1.11',
  broker_port: 1883,
  username: 'garage',
  has_password: true,
  topic_prefix: 'wican',
  use_tls: false,
}
const STATUS = { running: true, connection_status: 'connected', messages_processed: 12, last_message_at: null }
const TAB = { id: 'broker', label: 'Mosquitto', kind: null } as unknown as IntegrationTab

const renderDrawer = () => {
  const onChanged = vi.fn()
  render(<MosquittoSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={onChanged} />)
  return { onChanged }
}

beforeEach(() => {
  vi.clearAllMocks()
  getMQTTSettings.mockResolvedValue(SETTINGS)
  getMQTTStatus.mockResolvedValue(STATUS)
  updateMQTTSettings.mockImplementation((u: object) => Promise.resolve({ ...SETTINGS, ...u }))
  restartMQTTSubscriber.mockResolvedValue({ ...STATUS, connection_status: 'connecting' })
})

describe('MosquittoSettingsDrawer', () => {
  it('saves the host on Save, not per keystroke, and sends only what changed', async () => {
    renderDrawer()
    const host = await screen.findByLabelText('modal.brokerHost')

    fireEvent.change(host, { target: { value: '10.10.1.1' } })
    fireEvent.change(host, { target: { value: '10.10.1.12' } })
    expect(updateMQTTSettings).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.save' }))

    await waitFor(() => expect(updateMQTTSettings).toHaveBeenCalledTimes(1))
    expect(updateMQTTSettings).toHaveBeenCalledWith({ broker_host: '10.10.1.12' })
  })

  it('sends a typed password and clears it, and never sends an untouched one', async () => {
    renderDrawer()
    const password = await screen.findByLabelText('modal.password')

    fireEvent.change(screen.getByLabelText('modal.username'), { target: { value: 'rv' } })
    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.save' }))
    await waitFor(() => expect(updateMQTTSettings).toHaveBeenCalledWith({ username: 'rv' }))

    fireEvent.change(password, { target: { value: 's3cret' } })
    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.save' }))
    await waitFor(() => expect(updateMQTTSettings).toHaveBeenLastCalledWith({ password: 's3cret' }))
    await waitFor(() => expect(password).toHaveValue(''))
  })

  it('holds Test and Restart until the draft is saved', async () => {
    // Both act on the SAVED settings: testing an unsaved host tests the old one.
    renderDrawer()
    fireEvent.change(await screen.findByLabelText('modal.brokerHost'), {
      target: { value: 'broker.lan' },
    })

    expect(screen.getByRole('button', { name: 'modal.test' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'modal.livelink.restart' })).toBeDisabled()
    expect(screen.getByText('settings:integrations.brokerSaveFirst')).toBeInTheDocument()
  })

  it('restarting shows the new status and refreshes the card', async () => {
    const { onChanged } = renderDrawer()

    fireEvent.click(await screen.findByRole('button', { name: 'modal.livelink.restart' }))

    expect(await screen.findByText('settings:integrations.brokerStatus.connecting')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it('rejects a port outside 1 to 65535 without saving', async () => {
    renderDrawer()
    fireEvent.change(await screen.findByLabelText('modal.port'), { target: { value: '70000' } })

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('settings:integrations.numberOutOfRange')
    expect(updateMQTTSettings).not.toHaveBeenCalled()
  })

  it('leaves the WiCAN topic prefix to the WiCAN drawer', async () => {
    // It is the prefix WiCAN devices publish under, not a broker setting.
    renderDrawer()
    await screen.findByLabelText('modal.brokerHost')

    // By value, so it holds whatever the field would be labelled: the saved
    // prefix is 'wican', and no field here shows it.
    expect(screen.queryByDisplayValue('wican')).not.toBeInTheDocument()
  })

  it.each([
    ['connected', 'settings:integrations.brokerStatus.connected'],
    ['connecting', 'settings:integrations.brokerStatus.connecting'],
    ['disabled', 'settings:integrations.brokerStatus.disabled'],
    ['error', 'settings:integrations.brokerStatus.error'],
    ['disconnected', 'settings:integrations.brokerStatus.disconnected'],
    // A state this table doesn't know yet still reads as words, not a raw value.
    ['reticulating', 'settings:integrations.brokerStatus.unknown'],
  ])('says %s in words', async (connection, key) => {
    getMQTTStatus.mockResolvedValue({ ...STATUS, connection_status: connection })
    renderDrawer()

    expect(await screen.findByText(key)).toBeInTheDocument()
    expect(screen.queryByText(connection)).not.toBeInTheDocument()
  })
})
