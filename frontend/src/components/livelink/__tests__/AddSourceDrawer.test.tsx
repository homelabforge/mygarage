import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'

const listPresets = vi.fn()
const createDevice = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    listPresets: () => listPresets(),
    createDevice: (body: unknown) => createDevice(body),
  },
}))
const listVehicles = vi.fn()
vi.mock('@/services/vehicleService', () => ({
  default: { list: () => listVehicles() },
}))
// The form has its own suite. Here: which preset it is given, and what the
// drawer does once it reports a sensor created.
vi.mock('../settings/SensorForm', () => ({
  default: ({
    preset,
    vehicles,
    onCreated,
    onCancel,
  }: {
    preset: { name: string }
    vehicles: unknown[]
    onCreated: (device: unknown) => void
    onCancel: () => void
  }) => (
    <div>
      <p>
        sensor form for {preset.name} with {vehicles.length} vehicle(s)
      </p>
      <button onClick={() => onCreated({ device_id: 'mopeka-t1' })}>form-submit</button>
      <button onClick={onCancel}>form-cancel</button>
    </div>
  ),
}))

import AddSourceDrawer from '../AddSourceDrawer'

const VEHICLE = { vin: '1HGBH41JXMN109186', nickname: 'Durango', year: 2023, make: 'KZ', model: 'RV' }
const PRESET = {
  name: 'mopeka',
  title: 'Mopeka',
  description: 'Mopeka Pro Check propane tank sensors.',
  kind: 'generic_mqtt',
  readings: [],
}

/** What axios rejects with, as far as getActionErrorMessage reads it. */
const httpError = (status: number, detail: string): Error =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })

const renderDrawer = (props: Partial<Parameters<typeof AddSourceDrawer>[0]> = {}) => {
  const onClose = vi.fn()
  const onCreated = vi.fn()
  const utils = render(<AddSourceDrawer open onClose={onClose} onCreated={onCreated} {...props} />)
  return { ...utils, onClose, onCreated }
}

const typeDeviceId = (value: string): void => {
  fireEvent.change(screen.getByLabelText('integrations.mqttDeviceId'), { target: { value } })
}

beforeEach(() => {
  vi.clearAllMocks()
  listPresets.mockResolvedValue([PRESET])
  listVehicles.mockResolvedValue({ vehicles: [VEHICLE], total: 1 })
  createDevice.mockResolvedValue({ device_id: 'hand1' })
})

describe('AddSourceDrawer', () => {
  it('lists the preset catalog, its description in the reader\'s language', async () => {
    renderDrawer()

    expect(await screen.findByText('Mopeka')).toBeInTheDocument()
    expect(screen.getByText('settings:integrations.presets.mopeka.description')).toBeInTheDocument()
    expect(screen.queryByText(PRESET.description)).not.toBeInTheDocument()
  })

  it("falls back to the server's description for a preset it has no words for", async () => {
    // Regression guard: every preset read this way before the table existed.
    listPresets.mockResolvedValue([{ ...PRESET, name: 'victron', title: 'Victron', description: 'Victron shunts.' }])
    renderDrawer()

    expect(await screen.findByText('Victron shunts.')).toBeInTheDocument()
  })

  it("opens a preset's sensor form with the vehicles, and takes no device id for it", async () => {
    // The server picks a sensor's id; only the blank device is typed.
    renderDrawer()
    await screen.findByRole('option', { name: 'Durango' })

    fireEvent.click(screen.getByRole('button', { name: 'integrations.addSensor' }))

    expect(screen.getByText('sensor form for mopeka with 1 vehicle(s)')).toBeInTheDocument()
    expect(screen.getAllByLabelText('integrations.mqttDeviceId')).toHaveLength(1)
  })

  it('notifies and closes once the form has added a sensor', async () => {
    // Without onCreated the operator adds a sensor and no tab appears until
    // they reload the page.
    const { onCreated, onClose } = renderDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'integrations.addSensor' }))

    fireEvent.click(screen.getByRole('button', { name: 'form-submit' }))

    expect(onCreated).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('puts the button back when the form is cancelled', async () => {
    renderDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'integrations.addSensor' }))

    fireEvent.click(screen.getByRole('button', { name: 'form-cancel' }))

    expect(screen.queryByText(/sensor form for/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.addSensor' })).toBeInTheDocument()
  })

  it('creates a blank device with its label and vehicle, then notifies', async () => {
    const { onCreated } = renderDrawer()
    await screen.findByText('Mopeka')
    await screen.findByRole('option', { name: 'Durango' })

    typeDeviceId('hand1')
    fireEvent.change(screen.getByLabelText('integrations.sourceVehicle'), {
      target: { value: VEHICLE.vin },
    })
    fireEvent.change(screen.getByLabelText('integrations.mqttDeviceLabel'), {
      target: { value: 'Shed sensors' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' }))

    await waitFor(() =>
      expect(createDevice).toHaveBeenCalledWith({
        device_id: 'hand1',
        kind: 'generic_mqtt',
        label: 'Shed sensors',
        vin: VEHICLE.vin,
      }),
    )
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
  })

  it('sends no vehicle, not an empty string, when left unlinked', async () => {
    renderDrawer()
    await screen.findByText('Mopeka')

    typeDeviceId('hand1')
    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' }))

    await waitFor(() =>
      expect(createDevice).toHaveBeenCalledWith({ device_id: 'hand1', kind: 'generic_mqtt', label: null, vin: null }),
    )
  })

  it('holds the blank device until a device id is entered', async () => {
    renderDrawer()
    await screen.findByText('Mopeka')

    expect(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' })).toBeDisabled()
  })

  it('rejects an id that cannot be a URL path segment, before sending it', async () => {
    // The backend enforces the same pattern. Catching it here names the rule
    // at the field instead of after a round trip.
    renderDrawer()
    await screen.findByText('Mopeka')

    typeDeviceId('rv/gw')

    expect(await screen.findByRole('alert')).toHaveTextContent('integrations.deviceIdBadChar')
    expect(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' })).toBeDisabled()
  })

  it('says what is wrong rather than repeating the rule', async () => {
    // The hint above the field already states the rule. The error names the
    // actual problem: a bad first character, or the first character that
    // is not allowed.
    renderDrawer()
    await screen.findByText('Mopeka')

    typeDeviceId('-gw')
    expect(await screen.findByRole('alert')).toHaveTextContent('integrations.deviceIdStart')

    typeDeviceId('gw#1')
    expect(await screen.findByRole('alert')).toHaveTextContent('integrations.deviceIdBadChar')
  })

  it('accepts the id shapes the backend accepts', async () => {
    renderDrawer()
    await screen.findByText('Mopeka')

    typeDeviceId('rv-gateway.2_b')

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' })).toBeEnabled()
  })

  it("shows the server's reason and stays open when creation fails", async () => {
    createDevice.mockRejectedValue(httpError(409, 'Device hand1 already exists'))
    const { onCreated, onClose } = renderDrawer()
    await screen.findByText('Mopeka')

    typeDeviceId('hand1')
    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' }))

    expect(await screen.findByText(/Device hand1 already exists/)).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('starts empty when reopened', async () => {
    const { rerender } = renderDrawer()
    await screen.findByText('Mopeka')
    typeDeviceId('hand1')
    fireEvent.click(screen.getByRole('button', { name: 'integrations.addSensor' }))

    rerender(<AddSourceDrawer open={false} onClose={() => {}} onCreated={() => {}} />)
    rerender(<AddSourceDrawer open onClose={() => {}} onCreated={() => {}} />)

    expect(await screen.findByLabelText('integrations.mqttDeviceId')).toHaveValue('')
    expect(screen.queryByText(/sensor form for/)).not.toBeInTheDocument()
  })
})
